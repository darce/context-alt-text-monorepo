"""VLM-6 S2: plan and optionally run Hugging Face weight pre-pulls.

Reuses ``bakeoff_runner.build_plans`` so ordering, ``--only`` filtering,
VRAM-budget errors, and stack skips stay identical to the planner. This
module never calls the network itself: ``execute=False`` (default) is a
dry-run; ``execute=True`` shells out through an injected runner.

A local size>0 check is not an integrity check. Revision pins and
``verify_revisions`` remain the integrity surface.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

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


class DownloadStatus(StrEnum):
    """Outcome of one planned download (sr-007)."""

    PLANNED = "planned"
    SKIPPED_PRESENT = "skipped_present"
    DOWNLOADED = "downloaded"
    FAILED = "failed"


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
    return [_job_from_plan(plan, models_dir=models_dir) for plan in plans]


def list_skips(
    registry: BakeoffCandidateRegistry,
    jobs: Sequence[DownloadJob],
) -> list[tuple[str, str]]:
    """Name every unplanned registry row (AGT-06). ``--only`` filters are omitted."""
    planned = {job.candidate_id for job in jobs}
    budget_gb = float(registry.hardware_target.usable_vram_budget_gb)
    skips: list[tuple[str, str]] = []
    for entry in registry.entries:
        if entry.id in planned:
            continue
        try:
            reason = _skip_reason(entry, planned, budget_gb)
        except SkipNotesInconsistentError:
            continue
        if reason is not None:
            skips.append((entry.id, reason))
    return skips


def already_present(job: DownloadJob) -> bool:
    """True when every expected file exists under ``local_dir`` with size > 0.

    This is not an integrity check — only a local presence probe so
    idempotent re-runs skip work. Pins live on the registry revision.
    """
    for name in job.files:
        path = Path(job.local_dir) / name
        if not path.is_file() or path.stat().st_size <= 0:
            return False
    return True


def check_disk_budget(
    jobs: Sequence[DownloadJob],
    models_dir: str,
    *,
    margin_gb: float = DEFAULT_MARGIN_GB,
    disk_usage: Callable[[str], Any] | None = None,
) -> DiskBudget:
    """Return budget; raise ``DiskBudgetError`` naming both numbers when not ok."""
    usage_fn = disk_usage if disk_usage is not None else shutil.disk_usage
    missing = [job for job in jobs if not already_present(job)]
    required_gb = sum(job.size_gb for job in missing) + float(margin_gb)
    free_gb = float(usage_fn(_existing_path(models_dir)).free) / float(1024**3)
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
        if already_present(job):
            results.append(
                DownloadResult(
                    candidate_id=job.candidate_id,
                    status=DownloadStatus.SKIPPED_PRESENT,
                    returncode=None,
                    argv=job.argv,
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
    parser.add_argument("--margin-gb", type=float, default=DEFAULT_MARGIN_GB)
    args = parser.parse_args(argv)

    try:
        registry = load_bakeoff_candidates()
        only = _parse_only(args.only)
        jobs = plan_downloads(registry, models_dir=args.models_dir, only=only)
        skips = list_skips(registry, jobs)
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


def _job_from_plan(plan: Any, *, models_dir: str) -> DownloadJob:
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
    return DownloadJob(
        candidate_id=plan.candidate_id,
        repo=plan.repo,
        revision=plan.revision,
        files=files,
        local_dir=local_dir,
        size_gb=plan.total_gb,
        argv=argv,
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
        completed = runner(list(job.argv), check=False)
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


def _missing_files(job: DownloadJob) -> list[str]:
    missing: list[str] = []
    for name in job.files:
        path = Path(job.local_dir) / name
        if not path.is_file() or path.stat().st_size <= 0:
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
        print(f"PLAN {job.candidate_id} {job.repo}@{job.revision} {job.size_gb}GB -> {job.local_dir}")
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
        job_rows.append(row)
    return {
        "jobs": job_rows,
        "budget": asdict(budget),
        "skips": [{"candidate_id": candidate_id, "reason": reason} for candidate_id, reason in skips],
    }


if __name__ == "__main__":
    raise SystemExit(main())
