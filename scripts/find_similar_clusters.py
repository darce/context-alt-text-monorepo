#!/usr/bin/env python
"""
List pairs of clusters with high centroid cosine similarity to diagnose missed merges.

Examples:
    python scripts/find_similar_clusters.py --tenant-id <uuid> --threshold 0.7 --limit 50
    python scripts/find_similar_clusters.py --max-clusters 500
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT / "apps" / "prototype-description-service"))

from db.models import ClusterCentroid, IdentityCluster  # noqa: E402
from db.settings import get_database_settings  # noqa: E402


@dataclass(frozen=True)
class ClusterRow:
    cluster_id: str
    label: str | None
    centroid: np.ndarray


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find similar clusters by centroid cosine similarity.")
    parser.add_argument("--tenant-id", help="Tenant UUID to scope results. If omitted, scans all tenants.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="Cosine similarity threshold for reporting pairs (default: 0.6).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of pairs to display (default: 100).",
    )
    parser.add_argument(
        "--max-clusters",
        type=int,
        default=1000,
        help="Maximum clusters to load for analysis to avoid huge cross-products (default: 1000).",
    )
    return parser.parse_args()


def build_engine() -> Engine:
    settings = get_database_settings()
    from sqlalchemy import create_engine

    return create_engine(settings.postgres_sync_dsn, future=True)


def load_centroids(session: Session, tenant_id: str | None, max_clusters: int) -> list[ClusterRow]:
    stmt = (
        select(
            ClusterCentroid.cluster_id,
            ClusterCentroid.centroid,
            IdentityCluster.label,
        )
        .join(IdentityCluster, IdentityCluster.id == ClusterCentroid.cluster_id)
        .where(ClusterCentroid.centroid.isnot(None))
    )
    if tenant_id:
        from sqlalchemy import bindparam

        stmt = stmt.where(ClusterCentroid.tenant_id == bindparam("tenant_id"))

    stmt = stmt.limit(max_clusters)

    params = {"tenant_id": tenant_id} if tenant_id else {}
    session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
    rows = session.execute(stmt, params).all()
    session.execute(text("RESET app.bypass_rls"))

    clusters: list[ClusterRow] = []
    for cluster_id, centroid, label in rows:
        clusters.append(
            ClusterRow(
                cluster_id=str(cluster_id),
                label=label,
                centroid=np.array(centroid, dtype=np.float32),
            )
        )
    return clusters


def compute_pairs(clusters: list[ClusterRow], threshold: float, limit: int) -> list[tuple[ClusterRow, ClusterRow, float]]:
    pairs: list[tuple[ClusterRow, ClusterRow, float]] = []
    n = len(clusters)
    for i in range(n):
        for j in range(i + 1, n):
            a = clusters[i]
            b = clusters[j]
            sim = float(np.dot(a.centroid, b.centroid))
            if sim >= threshold:
                pairs.append((a, b, sim))
    pairs.sort(key=lambda t: t[2], reverse=True)
    return pairs[:limit]


def print_pairs(pairs: Iterable[tuple[ClusterRow, ClusterRow, float]]) -> None:
    pairs = list(pairs)
    if not pairs:
        print("No similar clusters found.")
        return

    print(f"Found {len(pairs)} similar cluster pairs:\n")
    for a, b, sim in pairs:
        print(
            f"- similarity={sim:.4f} | A={a.cluster_id} ({a.label}) | "
            f"B={b.cluster_id} ({b.label})"
        )


def main() -> None:
    args = parse_args()
    engine = build_engine()

    with Session(engine) as session:
        clusters = load_centroids(session, args.tenant_id, args.max_clusters)
        pairs = compute_pairs(clusters, args.threshold, args.limit)
    print_pairs(pairs)


if __name__ == "__main__":
    main()
