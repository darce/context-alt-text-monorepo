"""PostgreSQL-backed roster storage adapter with pgvector support."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from db.models import RosterEntry as RosterEntryModel
from roster.domain.entities import RosterEntry

from .database_storage_base import DEFAULT_TENANT_ID, DatabaseRosterStorageAdapter
from .mv_refresh import (
    refresh_aggregate_view_incremental as run_incremental_mv_refresh,
    refresh_materialized_view as run_mv_refresh,
)
from .postgres_metrics import DatabaseMetrics, timed_operation
from .progressive_learning_stats import fetch_progressive_learning_stats
from .search_queries import (
    hydrate_entry_with_mv_stats as hydrate_entry_with_mv_stats_helper,
    similarity_search,
)
from .session_utils import create_engine_with_pool, verify_pgvector_extension

logger = logging.getLogger(__name__)


class PostgreSQLStorageAdapter(DatabaseRosterStorageAdapter):
    """PostgreSQL implementation of the roster storage port."""

    def __init__(
        self,
        database_url: Optional[str] = None,
        tenant_id: Optional[Any] = None,
        *,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        slow_query_threshold_ms: float = 100.0,
        echo: bool = False,
    ) -> None:
        url = database_url or os.getenv("DATABASE_URL")
        if not url:
            raise ValueError("DATABASE_URL must be provided for PostgreSQL storage")

        tenant = tenant_id or os.getenv("DEFAULT_TENANT_ID") or DEFAULT_TENANT_ID

        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._pool_timeout = pool_timeout
        self._slow_query_threshold_ms = slow_query_threshold_ms
        self._metrics = DatabaseMetrics()

        super().__init__(
            database_url=url,
            tenant_id=tenant,
            echo=echo,
            create_schema=False,
        )

        # Verify pgvector extension is installed
        self._verify_pgvector_extension()

        logger.info(
            "PostgreSQL roster storage adapter initialised (tenant=%s, pool=%s)",
            self.tenant_id,
            pool_size,
        )

    # ------------------------------------------------------------------
    # Engine configuration
    # ------------------------------------------------------------------
    def _verify_pgvector_extension(self) -> None:
        """
        Verify pgvector extension is installed in the database.
        
        Raises:
            RuntimeError: If pgvector extension is not found.
        """
        verify_pgvector_extension(self.engine, logger, minimum_version="0.8.1")

    def _create_engine(self, database_url: str, *, echo: bool) -> Engine:
        return create_engine_with_pool(
            database_url,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_timeout=self._pool_timeout,
            echo=echo,
        )

    def _timed_operation(self, operation: str, **context: Any):
        return timed_operation(
            self._metrics,
            logger,
            self._slow_query_threshold_ms,
            operation,
            **context,
        )

    # ------------------------------------------------------------------
    # Port overrides (metrics wrappers)
    # ------------------------------------------------------------------
    def save_roster_entry(self, entry: RosterEntry, model: str) -> bool:
        with self._timed_operation(
            "save_roster_entry",
            unique_id=entry.unique_id,
            model=model,
            reference_count=len(entry.reference_images),
        ):
            return super().save_roster_entry(entry, model)

    def load_roster_entries(self, model: str) -> List[RosterEntry]:
        """
        Load all roster entries for model with MV aggregates.
        
        Joins roster_aggregate_embeddings MV to get weighted aggregates for all entries.
        """
        from db.models import RosterEntry as RosterEntryModel, RosterAggregateEmbedding
        from sqlalchemy import func as sa_func
        
        with self._timed_operation("load_roster_entries", model=model):
            try:
                with self._session() as session:
                    self._ensure_tenant(session)
                    
                    # Build query with LEFT JOIN to MV
                    stmt = (
                        select(
                            RosterEntryModel,
                            # Use COALESCE to prefer MV aggregate, fallback to column
                            sa_func.coalesce(
                                RosterAggregateEmbedding.aggregate_embedding,
                                RosterEntryModel.aggregate_embedding
                            ).label("aggregate_embedding"),
                            RosterAggregateEmbedding.reference_count,
                            RosterAggregateEmbedding.augmented_count,
                            RosterAggregateEmbedding.last_updated.label("mv_last_updated"),
                        )
                        .outerjoin(
                            RosterAggregateEmbedding,
                            RosterAggregateEmbedding.roster_entry_id == RosterEntryModel.id
                        )
                        .where(
                            RosterEntryModel.model == model,
                            RosterEntryModel.tenant_id == self._tenant_uuid,
                        )
                        .order_by(RosterEntryModel.created_at.desc())
                    )
                    
                    results = session.execute(stmt).all()
                    
                    if not results:
                        return []
                    
                    # Batch load sub-entities for all entries
                    entry_ids = [row[0].id for row in results]  # row[0] is RosterEntryModel
                    reference_map = self._load_reference_embeddings(session, entry_ids)
                    augmented_map = self._load_augmented_embeddings(session, entry_ids)
                    
                    # Hydrate all entries with MV stats tracking
                    entries = []
                    for row in results:
                        roster_updated_at = getattr(row[0], "updated_at", None)
                        mv_last_updated = row.mv_last_updated
                        embedding_source = (
                            "materialized_view"
                            if (
                                mv_last_updated is not None
                                and roster_updated_at is not None
                                and mv_last_updated >= roster_updated_at
                            )
                            else "roster_entries"
                        )
                        entry = self._hydrate_entry_with_mv_stats(
                            row[0],  # RosterEntryModel
                            reference_map.get(row[0].id, []),
                            augmented_map.get(row[0].id, []),
                            mv_aggregate_embedding=row.aggregate_embedding,  # COALESCE result
                            mv_reference_count=row.reference_count,
                            mv_augmented_count=row.augmented_count,
                            mv_last_updated=mv_last_updated,
                            embedding_source=embedding_source,
                        )
                        entries.append(entry)
                    
                    return entries
                    
            except SQLAlchemyError:
                logger.exception("Failed to load roster entries for model '%s' with MV", model)
                return []

    def get_roster_entry(self, unique_id: str, model: str) -> Optional[RosterEntry]:
        """
        Fetch roster entry with aggregate from materialized view.
        
        Joins roster_aggregate_embeddings MV to get weighted aggregate (canonical source).
        Falls back to roster_entries.aggregate_embedding if MV not available.
        """
        from db.models import RosterEntry as RosterEntryModel, RosterAggregateEmbedding
        from sqlalchemy import func as sa_func
        
        with self._timed_operation("get_roster_entry", unique_id=unique_id, model=model):
            try:
                with self._session() as session:
                    self._ensure_tenant(session)
                    
                    # Build query with LEFT JOIN to MV
                    stmt = (
                        select(
                            RosterEntryModel,
                            # Use COALESCE to prefer MV aggregate, fallback to column
                            sa_func.coalesce(
                                RosterAggregateEmbedding.aggregate_embedding,
                                RosterEntryModel.aggregate_embedding
                            ).label("aggregate_embedding"),
                            RosterAggregateEmbedding.reference_count,
                            RosterAggregateEmbedding.augmented_count,
                            RosterAggregateEmbedding.last_updated.label("mv_last_updated"),
                        )
                        .outerjoin(
                            RosterAggregateEmbedding,
                            RosterAggregateEmbedding.roster_entry_id == RosterEntryModel.id
                        )
                        .where(
                            RosterEntryModel.label == unique_id,
                            RosterEntryModel.tenant_id == self._tenant_uuid,
                        )
                    )
                    
                    if model not in ("all", None):
                        stmt = stmt.where(RosterEntryModel.model == model)
                    
                    result = session.execute(stmt).first()
                    
                    if not result:
                        return None
                    
                    # Load sub-entities
                    reference_map = self._load_reference_embeddings(session, [result[0].id])
                    augmented_map = self._load_augmented_embeddings(session, [result[0].id])
                    
                    # Hydrate with MV stats tracking
                    roster_updated_at = getattr(result[0], "updated_at", None)
                    mv_last_updated = result.mv_last_updated
                    embedding_source = (
                        "materialized_view"
                        if (
                            mv_last_updated is not None
                            and roster_updated_at is not None
                            and mv_last_updated >= roster_updated_at
                        )
                        else "roster_entries"
                    )
                    return self._hydrate_entry_with_mv_stats(
                        result[0],  # RosterEntryModel
                        reference_map.get(result[0].id, []),
                        augmented_map.get(result[0].id, []),
                        mv_aggregate_embedding=result.aggregate_embedding,  # COALESCE result
                        mv_reference_count=result.reference_count,
                        mv_augmented_count=result.augmented_count,
                        mv_last_updated=mv_last_updated,
                        embedding_source=embedding_source,
                    )
                    
            except SQLAlchemyError:
                logger.exception("Failed to fetch roster entry '%s' with MV", unique_id)
                return None

    def delete_roster_entry(self, unique_id: str, model: str) -> bool:
        with self._timed_operation("delete_roster_entry", unique_id=unique_id, model=model):
            return super().delete_roster_entry(unique_id, model)

    def roster_exists(self, model: str) -> bool:
        with self._timed_operation("roster_exists", model=model):
            return super().roster_exists(model)

    def clear_roster(self, model: str) -> bool:
        with self._timed_operation("clear_roster", model=model):
            return super().clear_roster(model)

    def _augment_storage_info(self, info: Dict[str, Any]) -> None:
        super()._augment_storage_info(info)
        info["backend"] = "postgresql"
        details = info.setdefault("backend_details", {})
        details.update(
            {
                "pgvector_enabled": True,
                "connection_pool": self._pool_stats(),
                "slow_query_threshold_ms": self._slow_query_threshold_ms,
                "query_metrics": self._metrics.snapshot(),
            }
        )

    # ------------------------------------------------------------------
    # PostgreSQL-specific operations
    # ------------------------------------------------------------------
    def search_similar(
        self,
        query_embedding: List[float],
        model: str,
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> List[Tuple[RosterEntry, float]]:
        with self._timed_operation(
            "search_similar",
            model=model,
            top_k=top_k,
            threshold=threshold,
            embedding_dim=len(query_embedding),
        ):
            return similarity_search(
                self,
                RosterEntryModel,
                query_embedding,
                model,
                top_k,
                threshold,
            )

    # ------------------------------------------------------------------
    # Progressive Learning: Materialized View Refresh
    # ------------------------------------------------------------------
    def refresh_aggregate_view(self, roster_id: Optional[str] = None) -> None:
        """
        Refresh materialized view for roster aggregate embeddings.
        
        This is called after adding augmented embeddings to update the weighted
        aggregate that includes reference embeddings (weight=1.0) and augmented
        embeddings (weight based on quality_tier: high=1.0, medium=0.8, low=0.5).
        
        Args:
            roster_id: If provided, only refreshes this specific entry (selective refresh).
                      If None, refreshes the entire view (used during startup/migrations).
        
        Note: The materialized view handles weighting by duplicating embeddings:
        - Reference embeddings: 3 copies (weight = 3/3 = 1.0 effective)
        - High quality: 3 copies (weight = 3/3 = 1.0 effective) 
        - Medium quality: 2 copies (weight = 2/3 ≈ 0.67 effective)
        - Low quality: 1 copy (weight = 1/3 ≈ 0.33 effective)
        
        The view is then queried by vector search operations instead of
        the roster_entries.aggregate_embedding column.
        """
        run_mv_refresh(self, logger, roster_id)

    def refresh_aggregate_view_incremental(self, roster_id: str) -> None:
        """
        Incrementally update aggregate embedding for a single roster entry.
        
        This path recomputes the weighted aggregate directly into the base
        `roster_entries` table using scalar-weighted sums so it completes in a few
        milliseconds. Nightly jobs should still run `refresh_aggregate_view()` to
        hydrate the materialized view for pgvector search, but the hot path no
        longer issues a blocking REFRESH operation.
        
        Strategy:
        - Use this for single-entry updates (e.g., after confirming observations)
        - Run full refresh_aggregate_view() nightly or after N incremental updates
        
        Trade-off: MV can become slightly stale until the next full refresh, but
        read paths fall back to the fresh aggregate stored on roster_entries to
        maintain correctness.
        
        Args:
            roster_id: The roster entry ID to refresh
        """
        run_incremental_mv_refresh(self, logger, roster_id)

    def get_progressive_learning_stats(self) -> Dict[str, Any]:
        """
        Query progressive learning metrics from materialized view and related tables.
        
        Returns comprehensive stats for WordPress dashboard and /service/info endpoint.
        """
        return fetch_progressive_learning_stats(self, logger)

    # ------------------------------------------------------------------
    # Helper methods for MV-aware hydration
    # ------------------------------------------------------------------
    def _hydrate_entry_with_mv_stats(
        self,
        row: Any,  # RosterEntryModel ORM object
        reference_images: List[Dict[str, Any]],
        augmented_embeddings: List[Dict[str, Any]],
        mv_aggregate_embedding: Optional[list] = None,
        mv_reference_count: Optional[int] = None,
        mv_augmented_count: Optional[int] = None,
        mv_last_updated: Optional[Any] = None,
        embedding_source: Optional[str] = None,
    ) -> RosterEntry:
        return hydrate_entry_with_mv_stats_helper(
            row,
            reference_images,
            augmented_embeddings,
            mv_aggregate_embedding=mv_aggregate_embedding,
            mv_reference_count=mv_reference_count,
            mv_augmented_count=mv_augmented_count,
            mv_last_updated=mv_last_updated,
            embedding_source=embedding_source,
        )

    # ------------------------------------------------------------------
    # Metrics utilities
    # ------------------------------------------------------------------
    def get_metrics(self) -> Dict[str, Any]:
        return {
            **self._metrics.snapshot(),
            "connection_pool": self._pool_stats(),
            "slow_query_threshold_ms": self._slow_query_threshold_ms,
        }

    def reset_metrics(self) -> None:
        self._metrics.reset()

    def _pool_stats(self) -> Dict[str, Any]:
        pool = getattr(self._engine, "pool", None)
        if pool is None:
            return {}

        try:
            size = pool.size()
            checked_in = pool.checkedin()
            checked_out = pool.checkedout()
            overflow = pool.overflow()
        except Exception:  # pragma: no cover - defensive
            return {}

        utilisation = 0.0
        try:
            utilisation = round((checked_out / size) * 100, 2) if size else 0.0
        except ZeroDivisionError:  # pragma: no cover - defensive
            utilisation = 0.0

        return {
            "size": size,
            "checked_in": checked_in,
            "checked_out": checked_out,
            "overflow": overflow,
            "utilisation_percent": utilisation,
        }

    @property
    def slow_query_threshold_ms(self) -> float:
        return self._slow_query_threshold_ms

    @property
    def engine(self) -> Engine:
        return self._engine
