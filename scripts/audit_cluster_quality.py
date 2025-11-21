#!/usr/bin/env python
"""
Identify cluster members whose stored similarity falls below the cluster threshold.

Examples:
    python scripts/audit_cluster_quality.py --tenant-id <uuid>
    python scripts/audit_cluster_quality.py --threshold-override 0.65 --limit 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT / "apps" / "prototype-description-service"))

from db.settings import get_database_settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit cluster member similarities against thresholds.")
    parser.add_argument(
        "--tenant-id",
        help="Optional tenant UUID to scope results.",
    )
    parser.add_argument(
        "--threshold-override",
        type=float,
        help="Override per-cluster threshold. If unset, uses cluster.similarity_threshold.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Limit number of rows returned (default: 200).",
    )
    return parser.parse_args()


def build_engine() -> Engine:
    settings = get_database_settings()
    from sqlalchemy import create_engine

    return create_engine(settings.postgres_sync_dsn, future=True)


def run_audit(session: Session, tenant_id: str | None, threshold_override: float | None, limit: int):
    stmt = text(
        """
        SELECT
            im.id::text AS member_id,
            im.cluster_id::text AS cluster_id,
            ic.label AS cluster_label,
            ic.similarity_threshold AS cluster_threshold,
            im.similarity,
            mi.media_id,
            mi.id::text AS identity_id
        FROM identity_members im
        JOIN identity_clusters ic ON ic.id = im.cluster_id
        JOIN media_identities mi ON mi.id = im.identity_id
        WHERE (:tenant_id IS NULL OR im.tenant_id = :tenant_id::uuid)
          AND im.similarity < COALESCE(:threshold_override, ic.similarity_threshold, 1.0)
        ORDER BY im.similarity ASC
        LIMIT :limit
        """
    )
    params = {
        "tenant_id": tenant_id,
        "threshold_override": threshold_override,
        "limit": limit,
    }

    session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
    result = session.execute(stmt, params).mappings().all()
    session.execute(text("RESET app.bypass_rls"))
    return result


def print_rows(rows: Iterable[dict]) -> None:
    if not rows:
        print("No members below threshold found.")
        return

    print(f"Found {len(rows)} members below threshold:\n")
    for row in rows:
        effective_threshold = row["cluster_threshold"]
        print(
            f"- member={row['member_id']} cluster={row['cluster_id']} ({row['cluster_label']}) "
            f"identity={row['identity_id']} media_id={row['media_id']} "
            f"similarity={row['similarity']:.4f} threshold={effective_threshold}"
        )


def main() -> None:
    args = parse_args()
    engine = build_engine()

    with Session(engine) as session:
        rows = run_audit(session, args.tenant_id, args.threshold_override, args.limit)
    print_rows(rows)


if __name__ == "__main__":
    main()
