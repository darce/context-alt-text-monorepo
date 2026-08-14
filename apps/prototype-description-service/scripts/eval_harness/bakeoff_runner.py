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
from typing import Any
from urllib.parse import urlparse

from scripts.eval_harness.bakeoff_candidates import (
    BakeoffCandidateRegistry,
    CandidateEntry,
    CandidateRole,
    ServingStack,
    load_bakeoff_candidates,
)

DEFAULT_ENDPOINT = "http://localhost:8000"
DEFAULT_MANIFEST = "scripts/eval_harness/corpus646-interleave-manifest-20260716.json"
DEFAULT_OUT_DIR = "out"
DEFAULT_MODELS_DIR = "/opt/models"
MMPROJ_ESTIMATE_GB = 1.0
READY_ATTEMPTS = 40
READY_SLEEP_S = 15
_CLIENT_ONLY_FLAGS = frozenset({"--no-think"})
_REPORT_MODULE = "scripts.eval_harness.build_bakeoff_report"
_BAKEOFF_MODULE = "scripts.eval_harness.bakeoff"


class UnsupportedStackError(Exception):
    """Candidate recipe uses a serving stack this planner does not emit."""


class VramBudgetError(Exception):
    """Candidate artifacts exceed the registry usable VRAM budget."""


class UnknownCandidateError(Exception):
    """``--only`` named an id that is not in the registry."""


class NotCompetingError(Exception):
    """``--only`` named a known id that is not a competing candidate."""


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
        if (
            entry.recipe.stack is not ServingStack.LLAMA_CPP
            and (requested is None or entry.id not in requested)
        ):
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


def emit_shell(plans: Sequence[CandidatePlan], *, incumbent_runs: Mapping[str, str]) -> str:
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
    ]
    for plan in plans:
        local_dir = f"{plan.models_dir.rstrip('/')}/{plan.candidate_id}"
        hint = (
            f"huggingface-cli download {plan.repo} --revision {plan.revision} "
            f"--local-dir {local_dir}"
        )
        endpoint = _argv_flag(plan.run_argv, "--endpoint")
        models_url = f"{endpoint.rstrip('/')}/v1/models"
        lines.append(f"# candidate: {plan.candidate_id}")
        lines.append(f"# download: {hint}")
        lines.append(f"{shlex.join(plan.serve_argv)} &")
        lines.append("_serve_pid=$!")
        lines.append("_ready=0")
        lines.append(f"for _i in $(seq 1 {READY_ATTEMPTS}); do")
        lines.append(f"  if curl -sf --max-time 6 {shlex.quote(models_url)} >/dev/null; then")
        lines.append("    _ready=1")
        lines.append("    break")
        lines.append("  fi")
        lines.append(f"  sleep {READY_SLEEP_S}")
        lines.append("done")
        lines.append('if [ "${_ready}" -ne 1 ]; then')
        lines.append(f'  echo "candidate {plan.candidate_id} never became ready" >&2')
        lines.append("else")
        lines.append(
            f"  {shlex.join(plan.run_argv)} || "
            f'echo "candidate {plan.candidate_id} fetch FAILED" >&2'
        )
        lines.append("fi")
        lines.append('kill "${_serve_pid}" 2>/dev/null || true')
        lines.append('wait "${_serve_pid}" 2>/dev/null || true')
        lines.append("_serve_pid=")
        lines.append("")

    lines.extend(_emit_report_lines(plans, incumbent_runs))
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
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        registry = load_bakeoff_candidates()
        only = _parse_only(args.only)
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
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.emit_shell:
        incumbent_runs = {
            entry.id: _run_out_path(args.out_dir, entry.id)
            for entry in registry.entries
            if entry.role is CandidateRole.INCUMBENT
        }
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
        not_competing = [
            candidate_id for candidate_id in only if candidate_id not in competing_ids
        ]
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
            f"candidate {entry.id!r} is llama_cpp but missing gguf/mmproj; "
            "pin both filenames in the registry recipe."
        )

    mmproj_gb = MMPROJ_ESTIMATE_GB if entry.recipe.mmproj else 0.0
    total_gb = float(entry.artifact_gb) + mmproj_gb
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
        "python",
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
    )


def _artifact_path(models_dir: str, candidate_id: str, filename: str) -> str:
    return f"{models_dir.rstrip('/')}/{candidate_id}/{filename}"


def _run_out_path(out_dir: str, candidate_id: str) -> str:
    return f"{out_dir.rstrip('/')}/run-bakeoff-{candidate_id}.json"


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
        "python",
        "-m",
        _REPORT_MODULE,
        "--manifest",
        manifest,
        "--out",
        f"{out_dir.rstrip('/')}/bakeoff-report.html",
    ]


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


def _print_table(plans: Sequence[CandidatePlan]) -> None:
    if not plans:
        print("no competing candidates selected")
        return
    headers = ("candidate_id", "model_id", "total_gb", "out_path")
    rows = [
        (plan.candidate_id, plan.model_id, f"{plan.total_gb:.1f}", plan.out_path)
        for plan in plans
    ]
    widths = [
        max(len(header), max(len(row[idx]) for row in rows))
        for idx, header in enumerate(headers)
    ]
    print("  ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    for row in rows:
        print("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


if __name__ == "__main__":
    raise SystemExit(main())
