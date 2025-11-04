"""Progressive learning statistics helpers for PostgreSQL adapters."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def fetch_progressive_learning_stats(adapter, logger) -> Dict[str, Any]:
    """Return progressive learning metrics for `/service/info` responses."""
    try:
        with adapter._session() as session:  # noqa: SLF001
            pgvector_version = session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar()

            entry_stats = session.execute(
                text(
                    """
                    SELECT
                        COUNT(*) as total_entries,
                        COUNT(DISTINCT CASE WHEN aug.roster_entry_id IS NOT NULL THEN re.id END) as entries_with_augmentations
                    FROM roster_entries re
                    LEFT JOIN augmented_embeddings aug ON aug.roster_entry_id = re.id
                    WHERE re.tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": adapter._tenant_uuid},  # noqa: SLF001
            ).fetchone()

            embedding_counts = session.execute(
                text(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM reference_embeddings ref
                         JOIN roster_entries re ON ref.roster_entry_id = re.id
                         WHERE re.tenant_id = :tenant_id) as total_reference,
                        (SELECT COUNT(*) FROM augmented_embeddings aug
                         JOIN roster_entries re ON aug.roster_entry_id = re.id
                         WHERE re.tenant_id = :tenant_id) as total_augmented
                    """
                ),
                {"tenant_id": adapter._tenant_uuid},  # noqa: SLF001
            ).fetchone()

            quality_dist = session.execute(
                text(
                    """
                    SELECT
                        quality_tier,
                        COUNT(*) as count
                    FROM augmented_embeddings aug
                    JOIN roster_entries re ON aug.roster_entry_id = re.id
                    WHERE re.tenant_id = :tenant_id
                    GROUP BY quality_tier
                    """
                ),
                {"tenant_id": adapter._tenant_uuid},  # noqa: SLF001
            ).fetchall()

            total_augmented = embedding_counts[1] if embedding_counts else 0
            quality_breakdown = {row[0]: row[1] for row in quality_dist}

            quality_high_pct = (
                round((quality_breakdown.get("high", 0) / total_augmented * 100), 2)
                if total_augmented
                else 0
            )
            quality_medium_pct = (
                round((quality_breakdown.get("medium", 0) / total_augmented * 100), 2)
                if total_augmented
                else 0
            )
            quality_low_pct = (
                round((quality_breakdown.get("low", 0) / total_augmented * 100), 2)
                if total_augmented
                else 0
            )

            confirmations_24h = (
                session.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM augmented_embeddings aug
                        JOIN roster_entries re ON aug.roster_entry_id = re.id
                        WHERE re.tenant_id = :tenant_id
                          AND aug.created_at >= NOW() - INTERVAL '24 hours'
                        """
                    ),
                    {"tenant_id": adapter._tenant_uuid},  # noqa: SLF001
                ).scalar()
                or 0
            )

            mv_last_updated = session.execute(
                text(
                    """
                    SELECT MAX(last_updated) FROM roster_aggregate_embeddings
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": adapter._tenant_uuid},  # noqa: SLF001
            ).scalar()

            total_entries = entry_stats[0] if entry_stats else 0
            avg_augmentations = (
                round((total_augmented / total_entries), 2) if total_entries else 0
            )

            return {
                "pgvector_version": pgvector_version or "unknown",
                "total_entries": total_entries,
                "augmented_entries": entry_stats[1] if entry_stats else 0,
                "total_reference": embedding_counts[0] if embedding_counts else 0,
                "total_augmented": total_augmented,
                "confirmations_24h": confirmations_24h,
                "avg_augmentations": avg_augmentations,
                "quality_high_pct": quality_high_pct,
                "quality_medium_pct": quality_medium_pct,
                "quality_low_pct": quality_low_pct,
                "last_mv_refresh": mv_last_updated.isoformat() if mv_last_updated else None,
                "last_full_refresh": None,
                "refresh_in_progress": False,
                "pending_refresh_count": 0,
                "faiss_index_size": 0,
                "faiss_last_reload": None,
                "faiss_reload_pending": False,
            }

    except SQLAlchemyError as exc:  # pragma: no cover - defensive path
        logger.error("Failed to get progressive learning stats: %s", exc)
        return {
            "pgvector_version": "unknown",
            "total_entries": 0,
            "augmented_entries": 0,
            "total_reference": 0,
            "total_augmented": 0,
            "confirmations_24h": 0,
            "avg_augmentations": 0.0,
            "quality_high_pct": 0.0,
            "quality_medium_pct": 0.0,
            "quality_low_pct": 0.0,
            "last_mv_refresh": None,
            "last_full_refresh": None,
            "refresh_in_progress": False,
            "pending_refresh_count": 0,
            "faiss_index_size": 0,
            "faiss_last_reload": None,
            "faiss_reload_pending": False,
        }
