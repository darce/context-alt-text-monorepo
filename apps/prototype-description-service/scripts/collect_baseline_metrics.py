#!/usr/bin/env python3
"""Collect baseline clustering metrics for A/B comparison.

Usage:
    python -m scripts.collect_baseline_metrics --tenant-id <UUID> [--label <label>]

This script collects current clustering metrics and saves them as a baseline
snapshot for comparison after implementing changes.

See: docs/tasks/4.0/4.2.3/clustering-improvements-dev-plan.md (Section 1.4)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def collect_metrics(tenant_id: UUID) -> dict:
    """Collect clustering metrics for a tenant."""
    from db.models import IdentityCluster, MediaIdentity
    from db.session import async_session_factory
    from db.tenant_context import set_tenant_context

    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_id)

        # Total identities
        identity_count_stmt = select(func.count(MediaIdentity.id)).where(MediaIdentity.tenant_id == tenant_id)
        identity_result = await session.execute(identity_count_stmt)
        total_identities = identity_result.scalar() or 0

        # Total clusters
        cluster_count_stmt = select(func.count(IdentityCluster.id)).where(IdentityCluster.tenant_id == tenant_id)
        cluster_result = await session.execute(cluster_count_stmt)
        total_clusters = cluster_result.scalar() or 0

        # Singleton count (clusters with exactly 1 member)
        singleton_stmt = select(func.count(IdentityCluster.id)).where(
            IdentityCluster.tenant_id == tenant_id,
            IdentityCluster.identity_count == 1,
        )
        singleton_result = await session.execute(singleton_stmt)
        singleton_count = singleton_result.scalar() or 0

        # Cluster sizes
        size_stats_stmt = select(
            func.avg(IdentityCluster.identity_count).label("avg_size"),
            func.max(IdentityCluster.identity_count).label("max_size"),
        ).where(IdentityCluster.tenant_id == tenant_id)
        size_result = await session.execute(size_stats_stmt)
        size_row = size_result.one_or_none()

        avg_cluster_size = float(size_row.avg_size) if size_row and size_row.avg_size else 0.0
        max_cluster_size = int(size_row.max_size) if size_row and size_row.max_size else 0

        # Unclustered identities
        unclustered_stmt = (
            select(func.count(MediaIdentity.id))
            .where(MediaIdentity.tenant_id == tenant_id)
            .where(~MediaIdentity.cluster_memberships.any())
        )
        try:
            unclustered_result = await session.execute(unclustered_stmt)
            unclustered_count = unclustered_result.scalar() or 0
        except Exception:
            # Fallback if relationship query fails
            unclustered_count = -1

        # Compute singleton ratio
        singleton_ratio = singleton_count / total_clusters if total_clusters > 0 else 0.0

        # Cluster size distribution
        size_dist_stmt = (
            select(IdentityCluster.identity_count, func.count(IdentityCluster.id))
            .where(IdentityCluster.tenant_id == tenant_id)
            .group_by(IdentityCluster.identity_count)
            .order_by(IdentityCluster.identity_count)
        )
        size_dist_result = await session.execute(size_dist_stmt)
        size_distribution = {str(size): count for size, count in size_dist_result.all()}

        return {
            "tenant_id": str(tenant_id),
            "collected_at": datetime.utcnow().isoformat(),
            "total_identities": total_identities,
            "total_clusters": total_clusters,
            "singleton_count": singleton_count,
            "singleton_ratio": round(singleton_ratio, 4),
            "avg_cluster_size": round(avg_cluster_size, 2),
            "max_cluster_size": max_cluster_size,
            "unclustered_count": unclustered_count,
            "size_distribution": size_distribution,
        }


def save_baseline(metrics: dict, label: str, output_dir: Path) -> Path:
    """Save metrics as a labeled baseline file."""
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"baseline_{label}_{timestamp}.json"
    filepath = output_dir / filename

    metrics["label"] = label

    with open(filepath, "w") as f:
        json.dump(metrics, f, indent=2)

    return filepath


async def main():
    parser = argparse.ArgumentParser(description="Collect baseline clustering metrics")
    parser.add_argument(
        "--tenant-id",
        type=str,
        required=True,
        help="Tenant UUID to collect metrics for",
    )
    parser.add_argument(
        "--label",
        type=str,
        default="baseline",
        help="Label for this baseline (e.g., 'before_confidence_weighting')",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/baselines",
        help="Directory to save baseline files",
    )

    args = parser.parse_args()

    try:
        tenant_id = UUID(args.tenant_id)
    except ValueError:
        logger.error("Invalid tenant ID format: %s", args.tenant_id)
        return 1

    logger.info("Collecting metrics for tenant %s...", tenant_id)

    try:
        metrics = await collect_metrics(tenant_id)
    except Exception as e:
        logger.error("Failed to collect metrics: %s", e)
        return 1

    output_dir = Path(args.output_dir)
    filepath = save_baseline(metrics, args.label, output_dir)

    logger.info("Baseline saved to: %s", filepath)
    logger.info("Metrics summary:")
    logger.info("  Total identities: %d", metrics["total_identities"])
    logger.info("  Total clusters: %d", metrics["total_clusters"])
    logger.info("  Singleton count: %d", metrics["singleton_count"])
    logger.info("  Singleton ratio: %.2f%%", metrics["singleton_ratio"] * 100)
    logger.info("  Avg cluster size: %.2f", metrics["avg_cluster_size"])
    logger.info("  Max cluster size: %d", metrics["max_cluster_size"])

    # Print JSON for easy copy-paste
    print("\n--- JSON Output ---")
    print(json.dumps(metrics, indent=2))

    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
