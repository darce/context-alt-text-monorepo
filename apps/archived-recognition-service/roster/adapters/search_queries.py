"""pgvector search helpers for PostgreSQL roster storage."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from roster.domain.entities import RosterEntry

from .database_base_utils import coerce_metadata

logger = logging.getLogger(__name__)


def hydrate_entry_with_mv_stats(
    row: Any,
    reference_images: List[Dict[str, Any]],
    augmented_embeddings: List[Dict[str, Any]],
    *,
    mv_aggregate_embedding: Optional[list] = None,
    mv_reference_count: Optional[int] = None,
    mv_augmented_count: Optional[int] = None,
    mv_last_updated: Optional[Any] = None,
    embedding_source: Optional[str] = None,
) -> RosterEntry:
    """Hydrate roster entry payload with MV metadata for monitoring."""
    metadata = coerce_metadata(row.meta)
    metadata.setdefault("model", getattr(row, "model", None))
    metadata["augmented_embeddings"] = augmented_embeddings

    aggregate_embedding = mv_aggregate_embedding or row.aggregate_embedding

    if mv_reference_count is not None:
        metadata["_mv_stats"] = {
            "reference_count": mv_reference_count,
            "augmented_count": mv_augmented_count or 0,
            "source": embedding_source or "materialized_view",
            "mv_last_updated": mv_last_updated.isoformat() if hasattr(mv_last_updated, "isoformat") else None,
            "hydrated_at": datetime.utcnow().isoformat(),
        }
        logger.debug(
            "Hydrating %s with MV aggregate: %s ref + %s aug",
            row.label,
            mv_reference_count,
            mv_augmented_count or 0,
        )
    else:
        metadata["_mv_stats"] = {
            "source": embedding_source or "roster_entries_column",
            "reference_count": len(reference_images),
            "augmented_count": len(augmented_embeddings),
            "reason": "mv_join_failed_or_null",
            "hydrated_at": datetime.utcnow().isoformat(),
        }
        logger.warning(
            "Hydrating %s without MV data - using roster_entries.aggregate_embedding",
            row.label,
        )

    payload: Dict[str, Any] = {
        "name": metadata.get("name", row.display_name or row.label),
        "display_name": row.display_name or row.label,
        "unique_id": row.label,
        "reference_images": reference_images,
        "aggregate_embedding": aggregate_embedding,
        "metadata": metadata,
        "created_timestamp": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else None,
        "updated_timestamp": row.updated_at.isoformat() if hasattr(row.updated_at, "isoformat") else None,
    }
    return RosterEntry.from_dict(payload)


def similarity_search(
    adapter,
    roster_entry_model,
    query_embedding: List[float],
    model: str,
    top_k: int,
    threshold: float,
) -> List[Tuple[RosterEntry, float]]:
    """Execute pgvector similarity search using MV aggregates where possible."""
    try:
        with adapter._session() as session:  # noqa: SLF001
            adapter._ensure_tenant(session)  # noqa: SLF001

            query_vec = "[" + ",".join(map(str, query_embedding)) + "]"
            rows = session.execute(
                text(
                    """
                    SELECT
                        re.id,
                        (
                            CASE
                                WHEN mv.last_updated IS NOT NULL
                                     AND mv.aggregate_embedding IS NOT NULL
                                     AND mv.last_updated >= re.updated_at
                                THEN mv.aggregate_embedding
                                ELSE re.aggregate_embedding
                            END <=> CAST(:query_vec AS vector)
                        ) AS distance,
                        CASE
                            WHEN mv.last_updated IS NOT NULL
                                 AND mv.aggregate_embedding IS NOT NULL
                                 AND mv.last_updated >= re.updated_at
                            THEN mv.aggregate_embedding
                            ELSE re.aggregate_embedding
                        END AS selected_embedding,
                        mv.reference_count,
                        mv.augmented_count,
                        mv.last_updated AS mv_last_updated,
                        re.updated_at AS roster_updated_at,
                        CASE
                            WHEN mv.last_updated IS NOT NULL
                                 AND mv.aggregate_embedding IS NOT NULL
                                 AND mv.last_updated >= re.updated_at
                            THEN 'materialized_view'
                            ELSE 'roster_entries'
                        END AS embedding_source
                    FROM roster_entries re
                    LEFT JOIN roster_aggregate_embeddings mv
                           ON mv.roster_entry_id = re.id
                          AND mv.tenant_id = re.tenant_id
                    WHERE re.tenant_id = :tenant_id
                      AND (:model_filter = 'all' OR :model_filter IS NULL OR re.model = :model_filter)
                      AND (
                            (mv.aggregate_embedding IS NOT NULL
                             AND mv.last_updated IS NOT NULL
                             AND mv.last_updated >= re.updated_at)
                            OR re.aggregate_embedding IS NOT NULL
                          )
                    ORDER BY distance
                    LIMIT :top_k
                    """
                ),
                {
                    "query_vec": query_vec,
                    "tenant_id": adapter._tenant_uuid,  # noqa: SLF001
                    "model_filter": model if model is not None else "all",
                    "top_k": top_k,
                },
            ).all()

            if not rows:
                return []

            entry_ids = [row.id for row in rows]
            db_entries = (
                session.execute(
                    select(roster_entry_model).where(roster_entry_model.id.in_(entry_ids))
                )
                .scalars()
                .all()
            )
            entry_map = {entry.id: entry for entry in db_entries}

            reference_map = adapter._load_reference_embeddings(session, entry_ids)  # noqa: SLF001
            augmented_map = adapter._load_augmented_embeddings(session, entry_ids)  # noqa: SLF001

            matches: List[Tuple[RosterEntry, float]] = []
            for row in rows:
                similarity = 1.0 - float(row.distance)
                if similarity < threshold or similarity != similarity:  # NaN guard
                    continue

                db_row = entry_map.get(row.id)
                if db_row is None:
                    continue

                if model not in ("all", None) and getattr(db_row, "model", None) != model:
                    continue

                entry = hydrate_entry_with_mv_stats(
                    db_row,
                    reference_map.get(db_row.id, []),
                    augmented_map.get(db_row.id, []),
                    mv_aggregate_embedding=row.selected_embedding,
                    mv_reference_count=row.reference_count,
                    mv_augmented_count=row.augmented_count,
                    mv_last_updated=row.mv_last_updated,
                    embedding_source=row.embedding_source,
                )

                matches.append((entry, similarity))

            return matches

    except SQLAlchemyError:
        logger.exception("pgvector similarity search failed")
        return []
