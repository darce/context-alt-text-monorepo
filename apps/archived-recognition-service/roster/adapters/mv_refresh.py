"""Materialized view refresh helpers for PostgreSQL roster storage."""

from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .database_base_utils import normalize_entry_id


def refresh_materialized_view(adapter, logger, roster_id: Optional[str]) -> None:
    start_time = time.perf_counter()
    operation = "refresh_aggregate_view_selective" if roster_id else "refresh_aggregate_view_full"

    try:
        with adapter._session() as session:  # noqa: SLF001
            if roster_id:
                session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY roster_aggregate_embeddings"))
                logger.debug("Refreshed materialized view (triggered by roster_id=%s)", roster_id)
            else:
                session.execute(text("REFRESH MATERIALIZED VIEW roster_aggregate_embeddings"))
                logger.info("Fully refreshed materialized view roster_aggregate_embeddings")

            session.commit()

        duration_ms = (time.perf_counter() - start_time) * 1000
        adapter._metrics.record_query(operation, duration_ms, success=True)  # noqa: SLF001

        if duration_ms > adapter._slow_query_threshold_ms:  # noqa: SLF001
            adapter._metrics.record_slow_query(  # noqa: SLF001
                operation,
                duration_ms,
                {"roster_id": roster_id, "type": "selective" if roster_id else "full"},
            )

    except SQLAlchemyError as exc:  # pragma: no cover - defensive path
        duration_ms = (time.perf_counter() - start_time) * 1000
        adapter._metrics.record_query(operation, duration_ms, success=False)  # noqa: SLF001
        adapter._metrics.record_error(  # noqa: SLF001
            operation=operation,
            error_type=type(exc).__name__,
            message=str(exc),
            context={"roster_id": roster_id},
        )
        logger.error("Failed to refresh materialized view: %s", exc)


def refresh_aggregate_view_incremental(adapter, logger, roster_id: str) -> None:
    start_time = time.perf_counter()
    operation = "refresh_aggregate_view_incremental"

    try:
        normalized_roster_id = normalize_entry_id(roster_id)

        with adapter._session() as session:  # noqa: SLF001
            update_result = session.execute(
                text(
                    """
                    WITH combined AS (
                        SELECT embedding
                        FROM reference_embeddings
                        WHERE roster_entry_id = :roster_id

                        UNION ALL
                        SELECT embedding
                        FROM reference_embeddings
                        WHERE roster_entry_id = :roster_id

                        UNION ALL
                        SELECT embedding
                        FROM reference_embeddings
                        WHERE roster_entry_id = :roster_id

                        UNION ALL
                        SELECT embedding
                        FROM augmented_embeddings
                        WHERE roster_entry_id = :roster_id
                          AND quality_tier = 'high'

                        UNION ALL
                        SELECT embedding
                        FROM augmented_embeddings
                        WHERE roster_entry_id = :roster_id
                          AND quality_tier = 'high'

                        UNION ALL
                        SELECT embedding
                        FROM augmented_embeddings
                        WHERE roster_entry_id = :roster_id
                          AND quality_tier = 'high'

                        UNION ALL
                        SELECT embedding
                        FROM augmented_embeddings
                        WHERE roster_entry_id = :roster_id
                          AND quality_tier = 'medium'

                        UNION ALL
                        SELECT embedding
                        FROM augmented_embeddings
                        WHERE roster_entry_id = :roster_id
                          AND quality_tier = 'medium'

                        UNION ALL
                        SELECT embedding
                        FROM augmented_embeddings
                        WHERE roster_entry_id = :roster_id
                          AND quality_tier IS NULL

                        UNION ALL
                        SELECT embedding
                        FROM augmented_embeddings
                        WHERE roster_entry_id = :roster_id
                          AND quality_tier = 'low'
                    ),
                    aggregate AS (
                        SELECT
                            CASE
                                WHEN COUNT(*) = 0
                                    THEN NULL
                                ELSE CAST(AVG(embedding) AS vector(512))
                            END AS aggregate_embedding
                        FROM combined
                    )
                    UPDATE roster_entries re
                    SET
                        aggregate_embedding = aggregate.aggregate_embedding,
                        updated_at = NOW()
                    FROM aggregate
                    WHERE re.id = :roster_entry_uuid
                      AND re.tenant_id = :tenant_id
                    RETURNING aggregate.aggregate_embedding
                    """
                ),
                {
                    "roster_id": normalized_roster_id,
                    "roster_entry_uuid": normalized_roster_id,
                    "tenant_id": adapter._tenant_uuid,  # noqa: SLF001
                },
            )

            session.commit()

            aggregate_row = update_result.first()
            if aggregate_row is None:
                logger.warning(
                    "Incremental refresh could not update roster entry %s (missing entry or embeddings)",
                    roster_id,
                )

            mv_exists = session.execute(
                text(
                    """
                    SELECT 1
                    FROM roster_aggregate_embeddings
                    WHERE roster_entry_id = :roster_id
                    LIMIT 1
                    """
                ),
                {"roster_id": normalized_roster_id},
            ).scalar()

        if not mv_exists:
            logger.info("Materialized view missing row for %s; triggering full refresh", roster_id)
            adapter.refresh_aggregate_view()

        duration_ms = (time.perf_counter() - start_time) * 1000
        adapter._metrics.record_query(operation, duration_ms, success=True)  # noqa: SLF001
        logger.debug(
            "Incrementally refreshed aggregate for roster_id=%s in %.2fms",
            roster_id,
            duration_ms,
        )

        if duration_ms > adapter._slow_query_threshold_ms:  # noqa: SLF001
            adapter._metrics.record_slow_query(  # noqa: SLF001
                operation,
                duration_ms,
                {"roster_id": roster_id},
            )

    except SQLAlchemyError as exc:  # pragma: no cover - defensive path
        duration_ms = (time.perf_counter() - start_time) * 1000
        adapter._metrics.record_query(operation, duration_ms, success=False)  # noqa: SLF001
        adapter._metrics.record_error(  # noqa: SLF001
            operation=operation,
            error_type=type(exc).__name__,
            message=str(exc),
            context={"roster_id": roster_id},
        )
        logger.error("Failed to incrementally refresh aggregate for %s: %s", roster_id, exc)
