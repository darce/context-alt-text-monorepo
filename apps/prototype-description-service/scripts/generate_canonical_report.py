#!/usr/bin/env python3
"""Generate a canonical recognition report for regression testing.

Usage:
    python -m scripts.generate_canonical_report --tenant-id <UUID> [--run-id <UUID>] [--media-id-file <path>]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from db.session import async_session_factory
from db.tenant_context import set_tenant_context
from recognition.application.regression_harness.report_builder import generate_canonical_report
from recognition.application.regression_harness.serialization import write_json

logger = logging.getLogger(__name__)


def _parse_uuid(value: str, *, field_name: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc


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
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID")
    parser.add_argument("--run-id", required=False, help="Optional recognition_runs UUID")
    parser.add_argument("--media-id-file", required=False, help="Optional file containing media IDs (one per line)")
    parser.add_argument("--dataset-name", required=False, help="Optional human-friendly dataset name")
    parser.add_argument("--dataset-notes", required=False, help="Optional dataset notes")
    parser.add_argument(
        "--output", required=False, help="Optional output path (defaults to data/canonical_reports/...)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    tenant_uuid = _parse_uuid(args.tenant_id, field_name="tenant-id")
    _ = _parse_uuid(args.run_id, field_name="run-id") if args.run_id else None

    media_ids: list[int] | None = None
    if args.media_id_file:
        media_ids = _read_media_ids(Path(args.media_id_file))

    output_path = (
        Path(args.output) if args.output else _default_output_path(tenant_id=args.tenant_id, run_id=args.run_id)
    )

    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        report = await generate_canonical_report(
            session,
            tenant_id=args.tenant_id,
            run_id=args.run_id,
            media_ids=media_ids,
            dataset_name=args.dataset_name,
            dataset_notes=args.dataset_notes,
        )

    write_json(output_path, report)
    logger.info("Canonical report written to %s", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
