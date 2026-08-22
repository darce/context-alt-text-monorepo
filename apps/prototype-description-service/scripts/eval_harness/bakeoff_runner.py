"""VLM-6 S2a-2: registry-driven bake-off plan driver.

Turns the sealed candidate registry into per-candidate serve+run argv.
This module PLANS only: it never starts a server, never downloads weights,
never calls an endpoint, and never touches the network.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from scripts.eval_harness.bakeoff_candidates import (
    BakeoffCandidateRegistry,
    CandidateEntry,
    CandidateRole,
    ServingStack,
    load_bakeoff_candidates,
)

if TYPE_CHECKING:
    from scripts.eval_harness.prepull_weights import SkipReason

DEFAULT_ENDPOINT = "http://localhost:8000"
DEFAULT_MANIFEST = "scripts/eval_harness/corpus646-interleave-manifest-20260716.json"
DEFAULT_OUT_DIR = "out"
DEFAULT_MODELS_DIR = "/opt/models"
MMPROJ_ESTIMATE_GB = 1.0
REPORT_LIMIT = 646
READY_TIMEOUT_S = 600
READY_SLEEP_S = 1
# Wall-clock ceiling (rg-007). Attempt-count is not a bound: each failed
# poll also spends curl --max-time.
_CLIENT_ONLY_FLAGS = frozenset({"--no-think"})
_REPORT_MODULE = "scripts.eval_harness.build_bakeoff_report"
_BAKEOFF_MODULE = "scripts.eval_harness.bakeoff"
# Shell is planned on the laptop/VM but executed on the GPU host; sys.executable
# is the local interpreter path and is meaningless there (Ubuntu ships python3).
PYTHON_EXE = "python3"
WARMUP_REQUESTS = 1
"""Discarded first-image requests before scored items, PERF-03."""

# Value-identical to SkipReason members. Kept as strings so this module
# can load without importing prepull_weights (circular). _skip_reason
# returns the enum; list_skips still prints these exact strings.
SKIP_REASON_STACK = "stack not supported"
SKIP_REASON_VRAM = "vram budget"
SKIP_REASON_NOT_COMPETING = "not competing"


class UnsupportedStackError(Exception):
    """Candidate recipe uses a serving stack this planner does not emit."""


class VramBudgetError(Exception):
    """Candidate artifacts exceed the registry usable VRAM budget."""


class UnknownCandidateError(Exception):
    """``--only`` named an id that is not in the registry."""


class NotCompetingError(Exception):
    """``--only`` named a known id that is not a competing candidate."""


class UnknownIncumbentError(Exception):
    """``--incumbent-run`` named an id that is not a registry incumbent."""


class SkipNotesInconsistentError(Exception):
    """An unplanned entry has no skip reason; planner and notes disagree."""


@dataclass(frozen=True)
class CandidatePlan:
    """One competing candidate's serve + run plan."""

    candidate_id: str
    model_id: str
    serve_argv: tuple[str, ...]
    run_argv: tuple[str, ...]
    out_path: str
    total_gb: float
    repo: str
    revision: str
    models_dir: str
    min_runtime_build: str | None = None
    min_runtime_build_is_lower_bound: bool = False


def build_plans(
    registry: BakeoffCandidateRegistry,
    *,
    endpoint: str,
    manifest: str,
    out_dir: str,
    models_dir: str,
    only: Sequence[str] | None = None,
) -> list[CandidatePlan]:
    """Build serve+run plans for competing candidates, in registry order.

    Args:
        registry: Validated bake-off roster.
        endpoint: OpenAI-compatible base URL passed to the bake-off runner.
        manifest: Corpus manifest path passed to the bake-off runner.
        out_dir: Directory for ``run-bakeoff-<id>.json`` records.
        models_dir: Root directory that holds ``<id>/<gguf|mmproj>`` artifacts.
        only: Optional id filter. Unknown and non-competing ids are rejected.
            Order stays registry order, not the order of ``only``.

    Returns:
        One ``CandidatePlan`` per selected competing ``llama_cpp`` candidate.
        Other stacks are skipped unless named in ``only``.

    Raises:
        UnknownCandidateError: An ``only`` id is not in the registry.
        NotCompetingError: An ``only`` id exists but is not competing.
        UnsupportedStackError: An explicitly selected candidate is not
            ``llama_cpp``.
        VramBudgetError: A selected candidate exceeds the usable VRAM budget.
    """
    selected = _select_competing(registry, only)
    requested = set(only) if only is not None else None
    plans: list[CandidatePlan] = []
    for entry in selected:
        if entry.recipe.stack is not ServingStack.LLAMA_CPP and (requested is None or entry.id not in requested):
            continue
        plans.append(
            _plan_candidate(
                entry,
                endpoint=endpoint,
                manifest=manifest,
                out_dir=out_dir,
                models_dir=models_dir,
                budget_gb=float(registry.hardware_target.usable_vram_budget_gb),
            )
        )
    return plans


def _emit_ready_poll_lines(models_url: str) -> list[str]:
    """Bounded /v1/models poll; stamp ``_cold`` on first success (rg-015)."""
    return [
        '_cold=""',
        "_ready=0",
        "SECONDS=0",
        "while true; do",
        f"  if curl -sf --max-time 6 {shlex.quote(models_url)} >/dev/null; then",
        "    _ready=1",
        "    # cold-load resolution: ±1s poll interval; first /v1/models success, rounded to 0.1s (rg-015)",
        '    _cold=$(python3 -c "import time;print(round(time.time()-$_t0,1))") || _cold=""',
        "    break",
        "  fi",
        '  kill -0 "$_serve_pid" 2>/dev/null || break',
        '  if [ "${SECONDS}" -ge "${READY_TIMEOUT_S}" ]; then',
        "    break",
        "  fi",
        f"  sleep {READY_SLEEP_S}",
        "done",
    ]


def _emit_ready_run_lines(plan: CandidatePlan) -> list[str]:
    """Lines for a ready candidate: bakeoff fetch, caption score, VRAM sanity."""
    run_base = shlex.join(plan.run_argv)
    score_base = shlex.join(_score_argv(plan))
    return [
        "  # warm-up: bakeoff --warmup runs inside the run argv; this shell does not send extra requests",
        "  _cold_flag=()",
        '  if [ -n "${_cold}" ]; then',
        '    _cold_flag=(--cold-load-s "${_cold}")',
        "  fi",
        f'  if ! {run_base} "${{_cold_flag[@]}}"; then',
        f'    echo "candidate {plan.candidate_id} fetch FAILED" >&2',
        "    _fail=$((_fail + 1))",
        f"  elif ! {score_base}; then",
        f'    echo "candidate {plan.candidate_id} score FAILED" >&2',
        "    _fail=$((_fail + 1))",
        "  fi",
        "  if command -v nvidia-smi >/dev/null 2>&1; then",
        '    echo "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)" >&2',
        "  fi",
    ]


def emit_shell(
    plans: Sequence[CandidatePlan],
    *,
    incumbent_runs: Mapping[str, str],
    ready_timeout_s: int = READY_TIMEOUT_S,
) -> str:
    """Return a ``set -euo pipefail`` bash script for the planned bake-off.

    Per candidate: download-hint comment, serve, bounded wait for
    ``/v1/models``, run (continue on fetch failure), stop. Then one
    ``build_bakeoff_report`` invocation covering existing candidate and
    incumbent run-record paths.
    """
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'trap \'if [ -n "${_serve_pid:-}" ]; then '
        'kill "${_serve_pid}" 2>/dev/null || true; '
        'wait "${_serve_pid}" 2>/dev/null || true; fi\' EXIT',
        "",
        f"READY_TIMEOUT_S={ready_timeout_s}",
        "_fail=0",
        "_total=0",
        "",
    ]
    for plan in plans:
        local_dir = f"{plan.models_dir.rstrip('/')}/{plan.candidate_id}"
        gguf = _argv_flag(plan.serve_argv, "--model").rsplit("/", 1)[-1]
        mmproj = _argv_flag(plan.serve_argv, "--mmproj").rsplit("/", 1)[-1]
        hint = (
            f"huggingface-cli download {plan.repo} --revision {plan.revision} "
            f"--include {gguf} --include {mmproj} --local-dir {local_dir}"
        )
        endpoint = _argv_flag(plan.run_argv, "--endpoint")
        models_url = f"{endpoint.rstrip('/')}/v1/models"
        lines.append(f"# candidate: {plan.candidate_id}")
        lines.append(f"# download: {hint}")
        lines.append("_total=$((_total + 1))")
        lines.append("for _candidate_once in 1; do")
        lines.extend(_emit_runtime_build_preflight(plan))
        lines.append("_t0=$(date +%s.%N)")
        lines.append(f"{shlex.join(plan.serve_argv)} &")
        lines.append("_serve_pid=$!")
        lines.extend(_emit_ready_poll_lines(models_url))
        lines.append('if [ "${_ready}" -ne 1 ]; then')
        lines.append(f'  echo "candidate {plan.candidate_id} never became ready" >&2')
        lines.append("  _fail=$((_fail + 1))")
        lines.append("else")
        lines.extend(_emit_ready_run_lines(plan))
        lines.append("fi")
        lines.append('kill "${_serve_pid}" 2>/dev/null || true')
        lines.append('wait "${_serve_pid}" 2>/dev/null || true')
        lines.append("_serve_pid=")
        lines.append("done")
        lines.append("")

    lines.extend(_emit_report_lines(plans, incumbent_runs))
    lines.append('if [ "${_total}" -gt 0 ] && [ "${_fail}" -eq "${_total}" ]; then')
    lines.append('  echo "all ${_total} candidates failed" >&2')
    lines.append("  exit 1")
    lines.append('elif [ "${_fail}" -gt 0 ]; then')
    lines.append('  echo "${_fail} of ${_total} candidate legs failed" >&2')
    lines.append("  exit 1")
    lines.append("fi")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Plan competing candidates. Returns process status."""
    parser = argparse.ArgumentParser(
        description="Plan VLM-6 bake-off serve+run argv from the sealed registry (no I/O)."
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--models-dir", default=DEFAULT_MODELS_DIR)
    parser.add_argument(
        "--only",
        default=None,
        metavar="ID[,ID...]",
        help="restrict the plan to these competing candidate ids",
    )
    parser.add_argument("--emit-shell", default=None, metavar="PATH")
    parser.add_argument(
        "--incumbent-run",
        action="append",
        default=None,
        metavar="ID=PATH",
        help="repeatable; incumbent registry id = existing run-record path",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        registry = load_bakeoff_candidates()
        only = _parse_only(args.only)
        incumbent_runs = _parse_incumbent_runs(registry, args.incumbent_run)
        plans = build_plans(
            registry,
            endpoint=args.endpoint,
            manifest=args.manifest,
            out_dir=args.out_dir,
            models_dir=args.models_dir,
            only=only,
        )
    except (
        UnsupportedStackError,
        VramBudgetError,
        UnknownCandidateError,
        NotCompetingError,
        UnknownIncumbentError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if only is None:
        _emit_skip_notes(registry, plans)

    if args.emit_shell:
        with open(args.emit_shell, "w", encoding="utf-8") as handle:
            handle.write(emit_shell(plans, incumbent_runs=incumbent_runs))

    if args.json:
        print(json.dumps([_plan_json(plan) for plan in plans], indent=2))
    else:
        _print_table(plans)
    return 0


def _select_competing(
    registry: BakeoffCandidateRegistry,
    only: Sequence[str] | None,
) -> list[CandidateEntry]:
    known = [entry.id for entry in registry.entries]
    known_set = set(known)
    competing_ids = {entry.id for entry in registry.entries if entry.competing}
    if only is not None:
        unknown = [candidate_id for candidate_id in only if candidate_id not in known_set]
        if unknown:
            raise UnknownCandidateError(
                f"unknown candidate id {unknown[0]!r}; "
                f"known ids: {', '.join(known)}. "
                "Pass an id from bakeoff_candidates.yaml."
            )
        not_competing = [candidate_id for candidate_id in only if candidate_id not in competing_ids]
        if not_competing:
            raise NotCompetingError(
                f"candidate id {not_competing[0]!r} is not competing; "
                "incumbent and reference rows are measured, not planned. "
                "Pass a competing id from bakeoff_candidates.yaml."
            )
        wanted = set(only)
        return [entry for entry in registry.entries if entry.competing and entry.id in wanted]
    return [entry for entry in registry.entries if entry.competing]


def _plan_candidate(
    entry: CandidateEntry,
    *,
    endpoint: str,
    manifest: str,
    out_dir: str,
    models_dir: str,
    budget_gb: float,
) -> CandidatePlan:
    if entry.recipe.stack is not ServingStack.LLAMA_CPP:
        raise UnsupportedStackError(
            f"candidate {entry.id!r} uses stack {entry.recipe.stack.value!r}; "
            "bakeoff_runner only emits llama-server argv. "
            "Filter with --only to a llama_cpp candidate, or add an explicit "
            "planner for this stack (never invent a vLLM command line)."
        )
    if not entry.recipe.gguf or not entry.recipe.mmproj:
        raise UnsupportedStackError(
            f"candidate {entry.id!r} is llama_cpp but missing gguf/mmproj; pin both filenames in the registry recipe."
        )

    total_gb = _entry_total_gb(entry)
    if total_gb > budget_gb:
        raise VramBudgetError(
            f"candidate {entry.id!r} total_gb={total_gb} exceeds "
            f"usable_vram_budget_gb={budget_gb}. Reduce artifact_gb or raise "
            "the budget; never downgrade the quant silently."
        )

    gguf_path = _artifact_path(models_dir, entry.id, entry.recipe.gguf)
    mmproj_path = _artifact_path(models_dir, entry.id, entry.recipe.mmproj)
    host, port = _endpoint_bind(endpoint)
    serve_flags = [flag for flag in entry.recipe.extra_flags if flag not in _CLIENT_ONLY_FLAGS]
    serve_argv = (
        "llama-server",
        "--host",
        host,
        "--port",
        port,
        "--model",
        gguf_path,
        "--mmproj",
        mmproj_path,
        "-c",
        str(entry.recipe.ctx_size),
        "--image-max-tokens",
        str(entry.recipe.image_max_tokens),
        "-np",
        str(entry.recipe.parallel),
        *serve_flags,
    )
    out_path = _run_out_path(out_dir, entry.id)
    run_argv_list = [
        PYTHON_EXE,
        "-m",
        _BAKEOFF_MODULE,
        "--endpoint",
        endpoint,
        "--model-id",
        entry.model_id,
        "--model-version",
        entry.quant,
        "--manifest",
        manifest,
        "--prompt-variant",
        entry.prompt_template,
        "--two-pass",
        "--out",
        out_path,
        "--warmup",
        str(WARMUP_REQUESTS),
    ]
    if entry.reasoning_tuned or "--no-think" in entry.recipe.extra_flags:
        run_argv_list.append("--no-think")
    return CandidatePlan(
        candidate_id=entry.id,
        model_id=entry.model_id,
        serve_argv=serve_argv,
        run_argv=tuple(run_argv_list),
        out_path=out_path,
        total_gb=total_gb,
        repo=entry.repo,
        revision=entry.revision,
        models_dir=models_dir,
        min_runtime_build=entry.recipe.min_runtime_build,
        min_runtime_build_is_lower_bound=entry.recipe.min_runtime_build_is_lower_bound,
    )


def _emit_runtime_build_preflight(plan: CandidatePlan) -> list[str]:
    """Emit a per-candidate llama.cpp build check before ``llama-server`` starts."""
    required = plan.min_runtime_build
    if not required:
        return []
    req_digits = required[1:] if required.startswith("b") else required
    cid = plan.candidate_id
    lines = [
        f"# preflight: {cid} requires llama.cpp {required}",
        "_build=$(llama-server --version 2>&1 | grep -oE 'b[0-9]+' | head -1) || _build=\"\"",
        'if [ -z "${_build}" ]; then',
        f'  echo "candidate {cid}: cannot parse llama-server runtime build (required {required}, observed empty)" >&2',
        "  _fail=$((_fail + 1))",
        "  continue",
        "fi",
        "_obs=${_build#b}",
        f"_req={req_digits}",
        'if [ "${_obs}" -lt "${_req}" ]; then',
        f'  echo "candidate {cid}: runtime build ${{_build}} is older than required '
        f'{required} (observed ${{_build}})" >&2',
        "  _fail=$((_fail + 1))",
        "  continue",
        "fi",
    ]
    if plan.min_runtime_build_is_lower_bound:
        lines.extend(
            [
                'if ! [ "${_obs}" -gt "${_req}" ]; then',
                f'  echo "candidate {cid}: runtime build ${{_build}} equals pinned bound '
                f"{required}; exact requirement is unknown and strictly greater than "
                f'{required} (observed ${{_build}})" >&2',
                "  _fail=$((_fail + 1))",
                "  continue",
                "fi",
            ]
        )
    return lines


def _artifact_path(models_dir: str, candidate_id: str, filename: str) -> str:
    return f"{models_dir.rstrip('/')}/{candidate_id}/{filename}"


def _run_out_path(out_dir: str, candidate_id: str) -> str:
    return f"{out_dir.rstrip('/')}/run-bakeoff-{candidate_id}.json"


def _score_argv(plan: CandidatePlan) -> tuple[str, ...]:
    manifest = _argv_flag(plan.run_argv, "--manifest")
    return (
        PYTHON_EXE,
        "-m",
        "scripts.eval_harness.cli",
        "score",
        "--manifest",
        manifest,
        "--run-record",
        plan.out_path,
        "--rubric-gate",
        "enforce",
        "--allow-refused",
        "detection",
        "--allow-refused",
        "identification",
    )


def _parse_only(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def _argv_flag(argv: Sequence[str], flag: str) -> str:
    try:
        return argv[list(argv).index(flag) + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError(f"plan argv missing {flag}") from exc


def _endpoint_bind(endpoint: str) -> tuple[str, str]:
    parsed = urlparse(endpoint)
    host = parsed.hostname
    if not host:
        raise ValueError(f"endpoint {endpoint!r} has no hostname")
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return host, str(port)


def _report_base_argv(plans: Sequence[CandidatePlan]) -> list[str]:
    manifest = DEFAULT_MANIFEST
    out_dir = DEFAULT_OUT_DIR
    if plans:
        manifest = _argv_flag(plans[0].run_argv, "--manifest")
        out_dir = plans[0].out_path.rsplit("/", 1)[0] or DEFAULT_OUT_DIR
    return [
        PYTHON_EXE,
        "-m",
        _REPORT_MODULE,
        "--manifest",
        manifest,
        "--out",
        f"{out_dir.rstrip('/')}/bakeoff-report.html",
        "--limit",
        str(REPORT_LIMIT),
    ]


def _report_argv(
    plans: Sequence[CandidatePlan],
    incumbent_runs: Mapping[str, str],
) -> list[str]:
    argv = _report_base_argv(plans)
    for plan in plans:
        argv.extend(["--run", f"{plan.candidate_id}={plan.out_path}"])
    for incumbent_id, run_path in sorted(incumbent_runs.items()):
        argv.extend(["--run", f"{incumbent_id}={run_path}"])
    return argv


def _emit_report_lines(
    plans: Sequence[CandidatePlan],
    incumbent_runs: Mapping[str, str],
) -> list[str]:
    lines = ["_runs=()"]
    for plan in plans:
        quoted = shlex.quote(plan.out_path)
        run_spec = shlex.quote(f"{plan.candidate_id}={plan.out_path}")
        lines.append(f"if [ -f {quoted} ]; then")
        lines.append(f"  _runs+=(--run {run_spec})")
        lines.append("fi")
    for incumbent_id, run_path in sorted(incumbent_runs.items()):
        quoted = shlex.quote(run_path)
        run_spec = shlex.quote(f"{incumbent_id}={run_path}")
        lines.append(f"if [ -f {quoted} ]; then")
        lines.append(f"  _runs+=(--run {run_spec})")
        lines.append("else")
        lines.append(f'  echo "WARN: missing incumbent run-record ({run_path})" >&2')
        lines.append("fi")
    base = shlex.join(_report_base_argv(plans))
    lines.append('if [ "${#_runs[@]}" -gt 0 ]; then')
    lines.append(f'  {base} "${{_runs[@]}}"')
    lines.append("else")
    lines.append('  echo "WARN: no run-records to report" >&2')
    lines.append("fi")
    return lines


def _plan_json(plan: CandidatePlan) -> dict[str, Any]:
    payload = asdict(plan)
    payload["serve_argv"] = list(plan.serve_argv)
    payload["run_argv"] = list(plan.run_argv)
    return payload


def _parse_incumbent_runs(
    registry: BakeoffCandidateRegistry,
    specs: Sequence[str] | None,
) -> dict[str, str]:
    if not specs:
        return {}
    incumbents = {entry.id: entry for entry in registry.entries if entry.role is CandidateRole.INCUMBENT}
    parsed: dict[str, str] = {}
    for spec in specs:
        if "=" not in spec:
            raise UnknownIncumbentError(f"--incumbent-run must be ID=PATH, got {spec!r}")
        incumbent_id, run_path = spec.split("=", 1)
        if incumbent_id not in incumbents:
            known = ", ".join(sorted(incumbents))
            raise UnknownIncumbentError(
                f"--incumbent-run id {incumbent_id!r} is not a registry incumbent; incumbent ids: {known}"
            )
        parsed[incumbent_id] = run_path
    return parsed


def _mmproj_gb(entry: CandidateEntry) -> float:
    if not entry.recipe.mmproj:
        return 0.0
    if entry.recipe.mmproj_gb is not None:
        return float(entry.recipe.mmproj_gb)
    return MMPROJ_ESTIMATE_GB


def _entry_total_gb(entry: CandidateEntry) -> float:
    return float(entry.artifact_gb) + _mmproj_gb(entry)


def _skip_reason(
    entry: CandidateEntry,
    planned: set[str],
    budget_gb: float,
) -> SkipReason | None:
    """Return why ``entry`` is absent from the plan, or None if planned."""
    from scripts.eval_harness.prepull_weights import SkipReason

    if entry.id in planned:
        return None
    if not entry.competing:
        return SkipReason.NOT_COMPETING
    if entry.recipe.stack is not ServingStack.LLAMA_CPP:
        return SkipReason.STACK_NOT_SUPPORTED
    if _entry_total_gb(entry) > budget_gb:
        return SkipReason.VRAM_BUDGET
    raise SkipNotesInconsistentError(
        f"candidate {entry.id!r} is not planned but has no skip reason; planner and skip notes disagree"
    )


def _emit_skip_notes(
    registry: BakeoffCandidateRegistry,
    plans: Sequence[CandidatePlan],
) -> None:
    planned = {plan.candidate_id for plan in plans}
    budget_gb = float(registry.hardware_target.usable_vram_budget_gb)
    roster = list(registry.entries)
    skipped = [(entry, reason) for entry in roster if (reason := _skip_reason(entry, planned, budget_gb)) is not None]
    for entry, reason in skipped:
        print(f"skip {entry.id} ({reason})", file=sys.stderr)
    print(
        f"skipped {len(skipped)} of {len(roster)} registry entries",
        file=sys.stderr,
    )


def _print_table(plans: Sequence[CandidatePlan]) -> None:
    if not plans:
        print("no competing candidates selected")
        return
    headers = ("candidate_id", "model_id", "total_gb", "out_path")
    rows = [(plan.candidate_id, plan.model_id, f"{plan.total_gb:.1f}", plan.out_path) for plan in plans]
    widths = [max(len(header), max(len(row[idx]) for row in rows)) for idx, header in enumerate(headers)]
    print("  ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    for row in rows:
        print("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


if __name__ == "__main__":
    raise SystemExit(main())
