"""VLM-6 S2: plan and optionally run Hugging Face weight pre-pulls.

Reuses ``bakeoff_runner.build_plans`` so ordering, ``--only`` filtering,
VRAM-budget errors, and stack skips stay identical to the planner. This
module never calls the network itself: ``execute=False`` (default) is a
dry-run; ``execute=True`` shells out through an injected runner.

``already_present`` is a local size probe against pinned ``artifact_gb`` /
``mmproj_gb`` (present iff ``size_bytes >= 0.90 * expected_gb * 1e9``).
When the registry has no size for an artifact, presence requires size > 0
and a size-unverified note is recorded — never silently. This is not an
integrity check. ``verify_revisions`` checks REMOTE revision listings
only; it never stats local files.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from scripts.eval_harness._pathtext import _printable_path
from scripts.eval_harness.bakeoff_candidates import (
    BakeoffCandidateRegistry,
    RegistryError,
    load_bakeoff_candidates,
)
from scripts.eval_harness.bakeoff_runner import (
    DEFAULT_ENDPOINT,
    DEFAULT_MANIFEST,
    DEFAULT_MODELS_DIR,
    DEFAULT_OUT_DIR,
    NotCompetingError,
    SkipNotesInconsistentError,
    UnknownCandidateError,
    UnsupportedStackError,
    VramBudgetError,
    _argv_flag,
    _parse_only,
    _skip_reason,
    build_plans,
)

DEFAULT_MARGIN_GB = 5.0
PRESENT_SIZE_RATIO = 0.90
BYTES_PER_GB = 1e9
DOWNLOAD_TIMEOUT_S = 3600  # per huggingface-cli job; hung download → failed (rg-007)


class DownloadStatus(StrEnum):
    """Outcome of one planned download (sr-007)."""

    PLANNED = "planned"
    SKIPPED_PRESENT = "skipped_present"
    DOWNLOADED = "downloaded"
    FAILED = "failed"


class SkipReason(StrEnum):
    """Why a sealed roster row is not a download job (sr-007, AGT-06)."""

    EXCLUDED_BY_ONLY = "excluded by --only"
    STACK_NOT_SUPPORTED = "stack not supported"
    VRAM_BUDGET = "vram budget"
    NOT_COMPETING = "not competing"


SIZE_UNVERIFIED_NOTE = "size unverified: registry has no pinned size for this artifact"


class DiskBudgetError(Exception):
    """Required download footprint exceeds measured free space."""

    def __init__(self, required_gb: float, free_gb: float) -> None:
        self.required_gb = required_gb
        self.free_gb = free_gb
        super().__init__(f"disk budget exceeded: required_gb={required_gb} free_gb={free_gb}")


@dataclass(frozen=True)
class DownloadJob:
    """One candidate's huggingface-cli download argv."""

    candidate_id: str
    repo: str
    revision: str
    files: tuple[str, ...]
    local_dir: str
    size_gb: float
    argv: tuple[str, ...]
    file_expected_gb: tuple[float | None, ...] = ()


@dataclass(frozen=True)
class DiskBudget:
    """Measured free space vs required download footprint + margin."""

    required_gb: float
    free_gb: float
    ok: bool


@dataclass(frozen=True)
class DownloadResult:
    """Per-job outcome. ``returncode`` is None when no process ran."""

    candidate_id: str
    status: DownloadStatus
    returncode: int | None
    argv: tuple[str, ...]
    note: str | None = None


def plan_downloads(
    registry: BakeoffCandidateRegistry | None,
    *,
    models_dir: str,
    only: Sequence[str] | None = None,
) -> list[DownloadJob]:
    """Build download jobs in the same order ``build_plans`` would emit."""
    roster = registry if registry is not None else load_bakeoff_candidates()
    plans = build_plans(
        roster,
        endpoint=DEFAULT_ENDPOINT,
        manifest=DEFAULT_MANIFEST,
        out_dir=DEFAULT_OUT_DIR,
        models_dir=models_dir,
        only=only,
    )
    by_id = {entry.id: entry for entry in roster.entries}
    return [_job_from_plan(plan, models_dir=models_dir, entry=by_id[plan.candidate_id]) for plan in plans]


def list_skips(
    registry: BakeoffCandidateRegistry,
    jobs: Sequence[DownloadJob],
    *,
    only: Sequence[str] | None = None,
) -> list[tuple[str, str]]:
    """Name every unplanned registry row (AGT-06).

    Every sealed id is a job or a named skip. Rows dropped by ``--only``
    carry ``SkipReason.EXCLUDED_BY_ONLY``; never ``continue`` past an
    unplanned competing llama_cpp row without naming it.
    """
    planned = {job.candidate_id for job in jobs}
    wanted = set(only) if only is not None else None
    budget_gb = float(registry.hardware_target.usable_vram_budget_gb)
    skips: list[tuple[str, str]] = []
    for entry in registry.entries:
        if entry.id in planned:
            continue
        try:
            reason = _skip_reason(entry, planned, budget_gb)
        except SkipNotesInconsistentError:
            if wanted is not None and entry.id not in wanted:
                reason = SkipReason.EXCLUDED_BY_ONLY
            else:
                raise
        if reason is not None:
            skips.append((entry.id, str(reason)))
    return skips


def already_present(job: DownloadJob, *, notes: list[str] | None = None) -> bool:
    """True when every expected file meets the pinned-size presence probe.

    Present iff ``size_bytes >= 0.90 * expected_gb * 1e9``. When the
    registry has no size for an artifact, present requires size > 0 and a
    size-unverified note is recorded. Not an integrity check — pins live
    on the registry revision; ``verify_revisions`` lists REMOTE files only.
    """
    expecteds = job.file_expected_gb
    for idx, name in enumerate(job.files):
        path = Path(job.local_dir) / name
        expected = expecteds[idx] if idx < len(expecteds) else None
        present, note = _file_is_present(path, expected)
        if not present:
            return False
        if note is not None and notes is not None:
            notes.append(f"{job.candidate_id}: {name} {note}")
    return True


def check_disk_budget(
    jobs: Sequence[DownloadJob],
    models_dir: str,
    *,
    margin_gb: float = DEFAULT_MARGIN_GB,
    disk_usage: Callable[[str], Any] | None = None,
) -> DiskBudget:
    """Return budget; raise ``DiskBudgetError`` naming both numbers when not ok."""
    margin = float(margin_gb)
    if margin < 0 or not math.isfinite(margin):
        raise ValueError(f"margin_gb must be a finite number >= 0, got {margin_gb!r}")
    usage_fn = disk_usage if disk_usage is not None else shutil.disk_usage
    missing = [job for job in jobs if not already_present(job)]
    required_gb = sum(job.size_gb for job in missing) + margin
    free_gb = float(usage_fn(_existing_path(models_dir)).free) / BYTES_PER_GB
    budget = DiskBudget(required_gb=required_gb, free_gb=free_gb, ok=required_gb <= free_gb)
    if not budget.ok:
        raise DiskBudgetError(budget.required_gb, budget.free_gb)
    return budget


def run_downloads(
    jobs: Sequence[DownloadJob],
    *,
    execute: bool,
    runner: Callable[..., Any] | None = None,
    log: Callable[[str], None] = print,
) -> list[DownloadResult]:
    """Dry-run (default) or run each argv sequentially.

    Failures are isolated (rg-007): one job's failure does not stop the rest.
    """
    run = runner if runner is not None else subprocess.run
    results: list[DownloadResult] = []
    for job in jobs:
        presence_notes: list[str] = []
        if already_present(job, notes=presence_notes):
            results.append(
                DownloadResult(
                    candidate_id=job.candidate_id,
                    status=DownloadStatus.SKIPPED_PRESENT,
                    returncode=None,
                    argv=job.argv,
                    note="; ".join(presence_notes) if presence_notes else None,
                )
            )
            continue
        if not execute:
            results.append(
                DownloadResult(
                    candidate_id=job.candidate_id,
                    status=DownloadStatus.PLANNED,
                    returncode=None,
                    argv=job.argv,
                )
            )
            continue
        results.append(_execute_one(job, runner=run, log=log))
    return results


def main(argv: list[str] | None = None) -> int:
    """Plan (default) or execute weight pre-pulls. Returns process status."""
    parser = argparse.ArgumentParser(description="Plan or run VLM-6 bake-off weight pre-pulls.")
    parser.add_argument("--models-dir", default=DEFAULT_MODELS_DIR)
    parser.add_argument(
        "--only",
        default=None,
        metavar="ID[,ID...]",
        help="restrict downloads to these competing candidate ids",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="opt-in: run huggingface-cli for jobs that are not already present",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--margin-gb", type=_parse_margin_gb, default=DEFAULT_MARGIN_GB)
    args = parser.parse_args(argv)

    try:
        registry = load_bakeoff_candidates()
        only = _parse_only(args.only)
        jobs = plan_downloads(registry, models_dir=args.models_dir, only=only)
        skips = list_skips(registry, jobs, only=only)
    except (
        RegistryError,
        UnsupportedStackError,
        VramBudgetError,
        UnknownCandidateError,
        NotCompetingError,
        SkipNotesInconsistentError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 3

    try:
        budget = check_disk_budget(
            jobs,
            args.models_dir,
            margin_gb=args.margin_gb,
        )
    except DiskBudgetError as exc:
        budget = DiskBudget(required_gb=exc.required_gb, free_gb=exc.free_gb, ok=False)
        _emit_output(jobs, skips, budget, as_json=args.json)
        sys.stdout.flush()
        if not args.json:
            print(str(exc), file=sys.stderr)
        return 2

    _emit_output(jobs, skips, budget, as_json=args.json)
    sys.stdout.flush()

    if not args.execute:
        return 0

    results = run_downloads(jobs, execute=True)
    if any(result.status is DownloadStatus.FAILED for result in results):
        return 1
    return 0


def _parse_margin_gb(value: str) -> float:
    """Reject negative and non-finite ``--margin-gb`` at parse time (rg-008)."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid --margin-gb {value!r}") from exc
    if parsed < 0 or not math.isfinite(parsed):
        raise argparse.ArgumentTypeError(f"--margin-gb must be a finite number >= 0, got {value!r}")
    return parsed


def _job_from_plan(plan: Any, *, models_dir: str, entry: Any) -> DownloadJob:
    gguf = _argv_flag(plan.serve_argv, "--model").rsplit("/", 1)[-1]
    mmproj = _argv_flag(plan.serve_argv, "--mmproj").rsplit("/", 1)[-1]
    files = (gguf, mmproj)
    local_dir = f"{models_dir.rstrip('/')}/{plan.candidate_id}"
    argv = (
        "huggingface-cli",
        "download",
        plan.repo,
        "--revision",
        plan.revision,
        "--include",
        gguf,
        "--include",
        mmproj,
        "--local-dir",
        local_dir,
    )
    mmproj_gb = entry.recipe.mmproj_gb
    return DownloadJob(
        candidate_id=plan.candidate_id,
        repo=plan.repo,
        revision=plan.revision,
        files=files,
        local_dir=local_dir,
        size_gb=plan.total_gb,
        argv=argv,
        file_expected_gb=(
            float(entry.artifact_gb),
            float(mmproj_gb) if mmproj_gb is not None else None,
        ),
    )


def _existing_path(path: str) -> str:
    candidate = Path(path)
    for node in (candidate, *candidate.parents):
        if node.exists():
            return str(node)
    return str(Path(path).anchor or "/")


def _execute_one(
    job: DownloadJob,
    *,
    runner: Callable[..., Any],
    log: Callable[[str], None],
) -> DownloadResult:
    try:
        completed = runner(list(job.argv), check=False, timeout=DOWNLOAD_TIMEOUT_S)
        returncode = getattr(completed, "returncode", None)
    except Exception as exc:
        log(f"FAIL {job.candidate_id}: {exc}")
        return DownloadResult(
            candidate_id=job.candidate_id,
            status=DownloadStatus.FAILED,
            returncode=None,
            argv=job.argv,
        )
    if returncode != 0:
        log(f"FAIL {job.candidate_id}: huggingface-cli exit {returncode}")
        return DownloadResult(
            candidate_id=job.candidate_id,
            status=DownloadStatus.FAILED,
            returncode=returncode if isinstance(returncode, int) else None,
            argv=job.argv,
        )
    missing = _missing_files(job)
    if missing:
        log(f"downloaded but expected file missing: {missing[0]}")
        return DownloadResult(
            candidate_id=job.candidate_id,
            status=DownloadStatus.FAILED,
            returncode=returncode if isinstance(returncode, int) else None,
            argv=job.argv,
        )
    return DownloadResult(
        candidate_id=job.candidate_id,
        status=DownloadStatus.DOWNLOADED,
        returncode=returncode if isinstance(returncode, int) else None,
        argv=job.argv,
    )


def _file_is_present(path: Path, expected_gb: float | None) -> tuple[bool, str | None]:
    if not path.is_file():
        return False, None
    size = path.stat().st_size
    if expected_gb is None:
        if size <= 0:
            return False, None
        return True, SIZE_UNVERIFIED_NOTE
    threshold = PRESENT_SIZE_RATIO * float(expected_gb) * BYTES_PER_GB
    return size >= threshold, None


def _missing_files(job: DownloadJob) -> list[str]:
    missing: list[str] = []
    expecteds = job.file_expected_gb
    for idx, name in enumerate(job.files):
        path = Path(job.local_dir) / name
        expected = expecteds[idx] if idx < len(expecteds) else None
        present, _note = _file_is_present(path, expected)
        if not present:
            missing.append(name)
    return missing


def _emit_output(
    jobs: Sequence[DownloadJob],
    skips: Sequence[tuple[str, str]],
    budget: DiskBudget,
    *,
    as_json: bool,
) -> None:
    if as_json:
        print(json.dumps(_payload_json(jobs, skips, budget), indent=2))
        return
    for job in jobs:
        print(
            f"PLAN {job.candidate_id} {job.repo}@{job.revision} "
            f"{job.size_gb}GB -> {_printable_path(job.local_dir)}"
        )
    for candidate_id, reason in skips:
        print(f"SKIP {candidate_id}: {reason}")
    print(f"BUDGET required_gb={budget.required_gb} free_gb={budget.free_gb} ok={budget.ok}")


def _payload_json(
    jobs: Sequence[DownloadJob],
    skips: Sequence[tuple[str, str]],
    budget: DiskBudget,
) -> dict[str, Any]:
    job_rows = []
    for job in jobs:
        row = asdict(job)
        row["files"] = list(job.files)
        row["argv"] = list(job.argv)
        row["file_expected_gb"] = list(job.file_expected_gb)
        job_rows.append(row)
    return {
        "jobs": job_rows,
        "budget": asdict(budget),
        "skips": [{"candidate_id": candidate_id, "reason": reason} for candidate_id, reason in skips],
    }


if __name__ == "__main__":
    raise SystemExit(main())
