#!/usr/bin/env python3
"""Generate a canonical recognition report for regression testing.

Usage:
    python -m scripts.generate_canonical_report [--tenant-id <UUID>] [--run-id <UUID>] [--media-id-file <path>]

    # Generate baseline with all runs aggregated (for large datasets with multiple batches):
    python -m scripts.generate_canonical_report --all-runs --dataset-name "golden-baseline"

    # Compare new clustering against saved baseline (after DB reset):
    python -m scripts.generate_canonical_report --all-runs --compare-baseline data/canonical_reports/.../golden.json

If --tenant-id and --run-id are not provided, the script will auto-detect
the most recent recognition run from the database.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select

from db.models import RecognitionRun
from db.session import async_session_factory
from db.tenant_context import set_tenant_context
from recognition.application.regression_harness.report_builder import generate_canonical_report
from recognition.application.regression_harness.serialization import write_json

logger = logging.getLogger(__name__)

LOG_FILE = Path("logs/recognition.log")


def _parse_uuid(value: str, *, field_name: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc


def _extract_tenant_from_log(log_path: Path) -> str | None:
    """Extract the most recent tenant_id from the log file."""
    if not log_path.exists():
        return None
    pattern = re.compile(r"tenant_id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
    last_tenant = None
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.search(line)
        if match:
            last_tenant = match.group(1)
    return last_tenant


async def _get_latest_run(tenant_id: str | None = None) -> tuple[str, str] | None:
    """Query DB for the most recent recognition run.

    Returns (tenant_id, run_id) tuple or None if no runs found.
    """
    async with async_session_factory() as session:
        stmt = select(RecognitionRun).order_by(RecognitionRun.created_at.desc()).limit(1)
        if tenant_id:
            stmt = stmt.where(RecognitionRun.tenant_id == UUID(tenant_id))
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        if run:
            return str(run.tenant_id), str(run.id)
    return None


def _read_media_ids(path: Path) -> list[int]:
    media_ids: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        media_ids.append(int(cleaned))
    return media_ids


def _default_output_path(*, tenant_id: str, run_id: str | None) -> Path:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    name = run_id or stamp
    return Path("data") / "canonical_reports" / tenant_id / f"{name}.json"


async def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Generate canonical recognition report (regression harness)")
    parser.add_argument("--tenant-id", required=False, help="Tenant UUID (auto-detected if not provided)")
    parser.add_argument("--run-id", required=False, help="Recognition run UUID (auto-detected if not provided)")
    parser.add_argument(
        "--all-runs",
        action="store_true",
        help="Aggregate events from ALL recognition runs for the tenant (for multi-batch datasets)",
    )
    parser.add_argument(
        "--compare-baseline",
        required=False,
        metavar="PATH",
        help="Path to a saved baseline JSON file to use as ground truth (enables post-reset comparison)",
    )
    parser.add_argument(
        "--baseline-source",
        required=False,
        default="curated",
        choices=["curated", "predicted"],
        help=(
            "Source of ground truth labels from baseline file: "
            "'curated' uses canonical_clusters (user-curated labels, default), "
            "'predicted' uses pre_curation_state.predicted_clusters (original algorithm output). "
            "Use 'predicted' to measure clustering reproducibility after code changes."
        ),
    )
    parser.add_argument("--media-id-file", required=False, help="Optional file containing media IDs (one per line)")
    parser.add_argument("--dataset-name", required=False, help="Optional human-friendly dataset name")
    parser.add_argument("--dataset-notes", required=False, help="Optional dataset notes")
    parser.add_argument(
        "--output", required=False, help="Optional output path (defaults to data/canonical_reports/...)"
    )
    parser.add_argument(
        "--log-file", required=False, help="Log file to extract tenant from (default: logs/recognition.log)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    tenant_id = args.tenant_id
    run_id = args.run_id
    all_runs = args.all_runs
    compare_baseline = args.compare_baseline

    # Validate mutually exclusive options
    if run_id and all_runs:
        parser.error("Cannot use --run-id and --all-runs together. Choose one.")

    # Auto-detect tenant_id and run_id if not provided
    if not tenant_id or (not run_id and not all_runs):
        # First try to get from DB (most reliable)
        latest = await _get_latest_run(tenant_id)
        if latest:
            if not tenant_id:
                tenant_id = latest[0]
                logger.info("Auto-detected tenant_id from DB: %s", tenant_id)
            if not run_id and not all_runs:
                run_id = latest[1]
                logger.info("Auto-detected run_id from DB: %s", run_id)
        elif not tenant_id:
            # Fall back to log file
            log_path = Path(args.log_file) if args.log_file else LOG_FILE
            tenant_id = _extract_tenant_from_log(log_path)
            if tenant_id:
                logger.info("Auto-detected tenant_id from log: %s", tenant_id)
            else:
                parser.error("Could not auto-detect tenant_id. Please provide --tenant-id")

    tenant_uuid = _parse_uuid(tenant_id, field_name="tenant-id")
    _ = _parse_uuid(run_id, field_name="run-id") if run_id else None

    media_ids: list[int] | None = None
    if args.media_id_file:
        media_ids = _read_media_ids(Path(args.media_id_file))

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    elif all_runs:
        stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        output_path = Path("data") / "canonical_reports" / tenant_id / f"all_runs_{stamp}.json"
    else:
        output_path = _default_output_path(tenant_id=tenant_id, run_id=run_id)

    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        report = await generate_canonical_report(
            session,
            tenant_id=tenant_id,
            run_id=run_id,
            all_runs=all_runs,
            compare_baseline_path=compare_baseline,
            baseline_source_type=args.baseline_source,
            media_ids=media_ids,
            dataset_name=args.dataset_name,
            dataset_notes=args.dataset_notes,
        )

    write_json(output_path, report)
    logger.info("Canonical report written to %s", output_path)

    # Print metrics summary if available
    report_dict = cast("dict[str, Any]", report)
    metrics = cast("dict[str, Any]", report_dict.get("metrics", {}))
    if metrics:
        pairwise = cast("dict[str, Any]", metrics.get("pairwise", {}))
        if pairwise:
            logger.info(
                "Metrics: precision=%.3f, recall=%.3f, F1=%.3f (TP=%d, GT=%d, Pred=%d)",
                pairwise.get("precision", 0),
                pairwise.get("recall", 0),
                pairwise.get("f1", 0),
                pairwise.get("true_positive_pairs", 0),
                pairwise.get("ground_truth_pairs", 0),
                pairwise.get("predicted_pairs", 0),
            )
        baseline_source = metrics.get("baseline_source")
        if baseline_source:
            logger.info("Ground truth loaded from: %s", baseline_source)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
