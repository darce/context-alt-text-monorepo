#!/usr/bin/env python3
"""Evaluate a clustering run against a canonical report.

Usage:
    python -m scripts.evaluate_run --canonical <path> --tenant-id <UUID>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from db.session import async_session_factory
from db.tenant_context import set_tenant_context
from recognition.application.regression_harness.db_export import fetch_predicted_clusters
from recognition.application.regression_harness.metrics import compute_curation_cost, compute_pairwise_metrics
from recognition.application.regression_harness.serialization import load_canonical_labels, write_json

logger = logging.getLogger(__name__)


def _parse_uuid(value: str, *, field_name: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc


def _load_media_ids_from_report(path: Path) -> list[int] | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    dataset = payload.get("dataset")
    if not isinstance(dataset, dict):
        return None
    media_ids = dataset.get("media_ids")
    if not isinstance(media_ids, list) or not all(isinstance(mid, int) for mid in media_ids):
        return None
    return media_ids


async def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Evaluate clustering output against canonical report")
    parser.add_argument("--canonical", required=True, help="Path to canonical_report.json")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID for the run to evaluate")
    parser.add_argument("--output", required=False, help="Optional output path for metrics JSON")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    canonical_path = Path(args.canonical)
    tenant_uuid = _parse_uuid(args.tenant_id, field_name="tenant-id")

    canonical_labels = load_canonical_labels(canonical_path)
    media_ids = _load_media_ids_from_report(canonical_path)

    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_uuid)
        predicted_clusters = await fetch_predicted_clusters(session, tenant_id=args.tenant_id, media_ids=media_ids)

    pairwise = compute_pairwise_metrics(canonical_labels=canonical_labels, predicted_clusters=predicted_clusters)
    curation_cost = compute_curation_cost(canonical_labels=canonical_labels, predicted_clusters=predicted_clusters)

    intersection = canonical_labels.keys() & predicted_clusters.keys()
    metrics_payload: dict[str, object] = {
        "schema_version": 1,
        "evaluated_at": datetime.now(tz=UTC).isoformat(),
        "tenant_id": args.tenant_id,
        "inputs": {
            "canonical_path": str(canonical_path),
            "media_ids": media_ids,
        },
        "identity_counts": {
            "canonical": len(canonical_labels),
            "predicted": len(predicted_clusters),
            "intersection": len(intersection),
            "missing_in_predicted": len(canonical_labels) - len(intersection),
        },
        "pairwise": asdict(pairwise),
        "curation_cost": asdict(curation_cost),
    }

    if args.output:
        output_path = Path(args.output)
        write_json(output_path, metrics_payload)
        logger.info("Metrics written to %s", output_path)

    print(json.dumps(metrics_payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
