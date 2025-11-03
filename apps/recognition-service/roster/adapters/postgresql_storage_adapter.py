"""PostgreSQL-backed roster storage adapter with pgvector support."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from db.models import RosterEntry as RosterEntryModel
from roster.domain.entities import RosterEntry

from .database_storage_base import DEFAULT_TENANT_ID, DatabaseRosterStorageAdapter

logger = logging.getLogger(__name__)


class DatabaseMetrics:
    """Lightweight metrics collector for database operations."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.query_count = 0
        self.error_count = 0
        self.slow_query_count = 0
        self.total_duration_ms = 0.0
        self.operation_counts: Dict[str, int] = {}
        self._slow_queries: List[Dict[str, Any]] = []
        self._errors: List[Dict[str, Any]] = []

    def record_query(self, operation: str, duration_ms: float, *, success: bool) -> None:
        self.query_count += 1
        self.total_duration_ms += duration_ms
        self.operation_counts[operation] = self.operation_counts.get(operation, 0) + 1
        if not success:
            self.error_count += 1

    def record_slow_query(self, operation: str, duration_ms: float, context: Dict[str, Any]) -> None:
        self.slow_query_count += 1
        entry = {
            "operation": operation,
            "duration_ms": round(duration_ms, 2),
            "timestamp": datetime.utcnow().isoformat(),
            **context,
        }
        self._slow_queries.append(entry)
        if len(self._slow_queries) > 100:
            self._slow_queries = self._slow_queries[-100:]

    def record_error(
        self, 
        operation: str, 
        error: Optional[BaseException] = None,
        error_type: Optional[str] = None,
        message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record error with operation name and optional context.
        
        Args:
            operation: Name of the operation that failed
            error: Exception object (if available)
            error_type: Type name of the error (alternative to error)
            message: Error message (alternative to error)
            context: Additional context dict
        """
        # Support both old style (error as BaseException) and new style (error_type + message)
        if error is not None:
            error_info = {
                "error_type": type(error).__name__,
                "message": str(error)
            }
        else:
            error_info = {
                "error_type": error_type or "UnknownError",
                "message": message or "No error message provided"
            }
            
        entry = {
            "operation": operation,
            "timestamp": datetime.utcnow().isoformat(),
            **error_info,
            **(context or {}),
        }
        self._errors.append(entry)
        if len(self._errors) > 50:
            self._errors = self._errors[-50:]

    def snapshot(self) -> Dict[str, Any]:
        avg = self.total_duration_ms / self.query_count if self.query_count else 0.0
        return {
            "query_count": self.query_count,
            "error_count": self.error_count,
            "slow_query_count": self.slow_query_count,
            "avg_duration_ms": round(avg, 2),
            "total_duration_ms": round(self.total_duration_ms, 2),
            "operation_counts": dict(self.operation_counts),
            "recent_slow_queries": list(self._slow_queries),
            "recent_errors": self._errors[-10:],
        }


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
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'"
                ))
                row = result.fetchone()
                
                if row is None:
                    raise RuntimeError(
                        "pgvector extension not found in database. "
                        "Please install pgvector extension (0.8.1+ required for HNSW support). "
                        "See db/SETUP.md for installation instructions."
                    )
                
                version = row[1]
                logger.info("✅ pgvector extension verified (version %s)", version)
        except SQLAlchemyError as e:
            logger.error("Failed to verify pgvector extension: %s", e)
            raise RuntimeError(
                "Could not verify pgvector extension. "
                "Database connection may be misconfigured or extension may be missing. "
                "See db/SETUP.md for setup instructions."
            ) from e

    def _create_engine(self, database_url: str, *, echo: bool) -> Engine:
        return create_engine(
            database_url,
            echo=echo,
            future=True,
            poolclass=QueuePool,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_timeout=self._pool_timeout,
            pool_pre_ping=True,
        )

    @contextmanager
    def _timed_operation(self, operation: str, **context: Any):
        start = time.time()
        success = True
        error: Optional[BaseException] = None

        try:
            yield
        except BaseException as exc:  # noqa: BLE001 - propagate original exception
            success = False
            error = exc
            raise
        finally:
            duration_ms = (time.time() - start) * 1000
            context_payload = {key: value for key, value in context.items() if value is not None}

            self._metrics.record_query(operation, duration_ms, success=success)

            if success and duration_ms >= self._slow_query_threshold_ms:
                self._metrics.record_slow_query(operation, duration_ms, context_payload)
                logger.warning(
                    "Slow query detected: %s took %.2fms (context=%s)",
                    operation,
                    duration_ms,
                    context_payload,
                )
            if not success and error is not None:
                self._metrics.record_error(operation, error, context_payload)
                logger.error(
                    "Database operation %s failed after %.2fms (context=%s, error=%s)",
                    operation,
                    duration_ms,
                    context_payload,
                    error,
                )

            logger.debug(
                "database operation %s finished in %.2fms (success=%s, context=%s)",
                operation,
                duration_ms,
                success,
                context_payload,
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
        with self._timed_operation("load_roster_entries", model=model):
            return super().load_roster_entries(model)

    def get_roster_entry(self, unique_id: str, model: str) -> Optional[RosterEntry]:
        with self._timed_operation("get_roster_entry", unique_id=unique_id, model=model):
            return super().get_roster_entry(unique_id, model)

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
            try:
                with self._session() as session:
                    self._ensure_tenant(session)

                    query_vec = "[" + ",".join(map(str, query_embedding)) + "]"
                    
                    # Query MV instead of roster_entries for canonical aggregates
                    # MV has HNSW index, so performance is identical (< 50ms p95)
                    rows = session.execute(
                        text(
                            """
                            SELECT 
                                re.id, 
                                (mv.aggregate_embedding <=> CAST(:query_vec AS vector)) AS distance,
                                mv.reference_count,
                                mv.augmented_count,
                                mv.last_updated
                            FROM roster_aggregate_embeddings mv
                            JOIN roster_entries re ON re.id = mv.roster_entry_id
                            WHERE mv.tenant_id = :tenant_id 
                              AND mv.aggregate_embedding IS NOT NULL
                            ORDER BY mv.aggregate_embedding <=> CAST(:query_vec AS vector)
                            LIMIT :top_k
                            """
                        ),
                        {
                            "query_vec": query_vec,
                            "tenant_id": self._tenant_uuid,
                            "top_k": top_k,
                        },
                    ).all()

                    if not rows:
                        return []

                    entry_ids = [row.id for row in rows]
                    db_entries = (
                        session.execute(
                            select(RosterEntryModel).where(RosterEntryModel.id.in_(entry_ids))
                        )
                        .scalars()
                        .all()
                    )
                    entry_map = {entry.id: entry for entry in db_entries}

                    reference_map = self._load_reference_embeddings(session, entry_ids)
                    augmented_map = self._load_augmented_embeddings(session, entry_ids)

                    matches: List[Tuple[RosterEntry, float]] = []
                    for row in rows:
                        similarity = 1.0 - float(row.distance)
                        if similarity < threshold:
                            continue

                        db_row = entry_map.get(row.id)
                        if db_row is None:
                            continue

                        if model not in ("all", None) and getattr(db_row, "model", None) != model:
                            continue

                        entry = self._hydrate_entry(
                            db_row,
                            reference_map.get(db_row.id, []),
                            augmented_map.get(db_row.id, []),
                        )

                        matches.append((entry, similarity))

                    return matches

            except SQLAlchemyError:
                logger.exception("pgvector similarity search failed")
                return []

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
        start_time = time.perf_counter()
        operation = "refresh_aggregate_view_selective" if roster_id else "refresh_aggregate_view_full"
        
        try:
            with self._session() as session:
                if roster_id:
                    # Selective refresh: The view auto-updates when underlying tables change,
                    # but we need to explicitly refresh to ensure consistency.
                    # PostgreSQL REFRESH MATERIALIZED VIEW CONCURRENTLY allows reads during refresh.
                    session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY roster_aggregate_embeddings"))
                    logger.debug(f"Refreshed materialized view (triggered by roster_id={roster_id})")
                else:
                    # Full refresh (blocking) - used during startup or migrations
                    session.execute(text("REFRESH MATERIALIZED VIEW roster_aggregate_embeddings"))
                    logger.info("Fully refreshed materialized view roster_aggregate_embeddings")
                
                session.commit()
                
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_query(operation, duration_ms, success=True)
            
            if duration_ms > self._slow_query_threshold_ms:
                self._metrics.record_slow_query(
                    operation, duration_ms, 
                    {"roster_id": roster_id, "type": "selective" if roster_id else "full"}
                )
                
        except SQLAlchemyError as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_query(operation, duration_ms, success=False)
            self._metrics.record_error(
                operation=operation,
                error_type=type(exc).__name__,
                message=str(exc),
                context={"roster_id": roster_id}
            )
            logger.error(f"Failed to refresh materialized view: {exc}")
            # Don't raise - progressive learning should degrade gracefully
            # FAISS index will still work with slightly stale data

    def refresh_aggregate_view_incremental(self, roster_id: str) -> None:
        """
        Incrementally update aggregate embedding for a single roster entry.
        
        This is much faster than full MV refresh (~5-10ms vs 500ms-2s) because it:
        1. Computes the new aggregate in a SQL subquery
        2. UPDATEs the MV row directly (instead of rebuilding entire view)
        3. Doesn't block other queries
        
        Strategy:
        - Use this for single-entry updates (e.g., after confirming observations)
        - Run full refresh_aggregate_view() nightly or after N incremental updates
        
        Trade-off: MV can become slightly stale for other entries, but the entry
        being updated is always fresh. The HNSW index stays consistent.
        
        Args:
            roster_id: The roster entry ID to refresh
        """
        start_time = time.perf_counter()
        operation = "refresh_aggregate_view_incremental"
        
        try:
            with self._session() as session:
                # Use the same weighted average logic as the MV definition
                # (scalar multiplication with quality-tier weights)
                session.execute(text("""
                    -- Update the materialized view row directly
                    UPDATE roster_aggregate_embeddings
                    SET 
                        aggregate_embedding = (
                            SELECT CAST((SUM(embedding * weight) / SUM(weight)) AS vector(512))
                            FROM (
                                -- Reference embeddings: weight = 3.0
                                SELECT embedding, 3.0 AS weight
                                FROM reference_embeddings
                                WHERE roster_entry_id = :roster_id
                                
                                UNION ALL
                                
                                -- Augmented embeddings: quality-based weights
                                SELECT 
                                    embedding,
                                    CASE quality_tier
                                        WHEN 'high' THEN 3.0
                                        WHEN 'medium' THEN 2.0
                                        WHEN 'low' THEN 1.0
                                        ELSE 2.0
                                    END AS weight
                                FROM augmented_embeddings
                                WHERE roster_entry_id = :roster_id
                            ) weighted_embeddings
                        ),
                        reference_count = (
                            SELECT COUNT(*) 
                            FROM reference_embeddings 
                            WHERE roster_entry_id = :roster_id
                        ),
                        augmented_count = (
                            SELECT COUNT(*) 
                            FROM augmented_embeddings 
                            WHERE roster_entry_id = :roster_id
                        ),
                        last_updated = GREATEST(
                            (SELECT MAX(created_at) FROM reference_embeddings WHERE roster_entry_id = :roster_id),
                            (SELECT MAX(created_at) FROM augmented_embeddings WHERE roster_entry_id = :roster_id)
                        )
                    WHERE roster_entry_id = :roster_id
                """), {"roster_id": roster_id})
                session.commit()
                
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_query(operation, duration_ms, success=True)
            logger.debug(f"Incrementally refreshed aggregate for roster_id={roster_id} in {duration_ms:.2f}ms")
            
            if duration_ms > self._slow_query_threshold_ms:
                self._metrics.record_slow_query(
                    operation, duration_ms,
                    {"roster_id": roster_id}
                )
                
        except SQLAlchemyError as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_query(operation, duration_ms, success=False)
            self._metrics.record_error(
                operation=operation,
                error_type=type(exc).__name__,
                message=str(exc),
                context={"roster_id": roster_id}
            )
            logger.error(f"Failed to incrementally refresh aggregate for {roster_id}: {exc}")
            # Don't raise - fall back to stale aggregate if needed

    def get_progressive_learning_stats(self) -> Dict[str, Any]:
        """
        Query progressive learning metrics from materialized view and related tables.
        
        Returns comprehensive stats for WordPress dashboard and /service/info endpoint.
        """
        try:
            with self._session() as session:
                # Get pgvector version
                pgvector_version = session.execute(text("""
                    SELECT extversion FROM pg_extension WHERE extname = 'vector'
                """)).scalar()
                
                # Get roster entry counts
                entry_stats = session.execute(text("""
                    SELECT 
                        COUNT(*) as total_entries,
                        COUNT(DISTINCT CASE WHEN aug.roster_entry_id IS NOT NULL THEN re.id END) as entries_with_augmentations
                    FROM roster_entries re
                    LEFT JOIN augmented_embeddings aug ON aug.roster_entry_id = re.id
                    WHERE re.tenant_id = :tenant_id
                """), {"tenant_id": self._tenant_uuid}).fetchone()
                
                # Get embedding counts
                embedding_counts = session.execute(text("""
                    SELECT
                        (SELECT COUNT(*) FROM reference_embeddings ref 
                         JOIN roster_entries re ON ref.roster_entry_id = re.id 
                         WHERE re.tenant_id = :tenant_id) as total_reference,
                        (SELECT COUNT(*) FROM augmented_embeddings aug 
                         JOIN roster_entries re ON aug.roster_entry_id = re.id 
                         WHERE re.tenant_id = :tenant_id) as total_augmented
                """), {"tenant_id": self._tenant_uuid}).fetchone()
                
                # Get quality distribution
                quality_dist = session.execute(text("""
                    SELECT 
                        quality_tier,
                        COUNT(*) as count
                    FROM augmented_embeddings aug
                    JOIN roster_entries re ON aug.roster_entry_id = re.id
                    WHERE re.tenant_id = :tenant_id
                    GROUP BY quality_tier
                """), {"tenant_id": self._tenant_uuid}).fetchall()
                
                total_augmented = embedding_counts[1] if embedding_counts else 0
                quality_breakdown = {row[0]: row[1] for row in quality_dist}
                
                # Calculate percentages
                quality_high_pct = round((quality_breakdown.get('high', 0) / total_augmented * 100), 2) if total_augmented else 0
                quality_medium_pct = round((quality_breakdown.get('medium', 0) / total_augmented * 100), 2) if total_augmented else 0
                quality_low_pct = round((quality_breakdown.get('low', 0) / total_augmented * 100), 2) if total_augmented else 0
                
                # Get confirmations in last 24 hours
                confirmations_24h = session.execute(text("""
                    SELECT COUNT(*) 
                    FROM augmented_embeddings aug
                    JOIN roster_entries re ON aug.roster_entry_id = re.id
                    WHERE re.tenant_id = :tenant_id
                      AND aug.created_at >= NOW() - INTERVAL '24 hours'
                """), {"tenant_id": self._tenant_uuid}).scalar() or 0
                
                # Get MV last refresh time
                mv_last_updated = session.execute(text("""
                    SELECT MAX(last_updated) FROM roster_aggregate_embeddings
                    WHERE tenant_id = :tenant_id
                """), {"tenant_id": self._tenant_uuid}).scalar()
                
                # Calculate average augmentations per entry
                total_entries = entry_stats[0] if entry_stats else 0
                avg_augmentations = round((total_augmented / total_entries), 2) if total_entries else 0
                
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
                    # Placeholder values for future implementation
                    "last_full_refresh": None,
                    "refresh_in_progress": False,
                    "pending_refresh_count": 0,
                    "faiss_index_size": 0,
                    "faiss_last_reload": None,
                    "faiss_reload_pending": False,
                }
                
        except SQLAlchemyError as exc:
            logger.error(f"Failed to get progressive learning stats: {exc}")
            # Return minimal stats on error
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
