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

    def record_error(self, operation: str, error: BaseException, context: Dict[str, Any]) -> None:
        entry = {
            "operation": operation,
            "error": str(error),
            "timestamp": datetime.utcnow().isoformat(),
            **context,
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

        logger.info(
            "PostgreSQL roster storage adapter initialised (tenant=%s, pool=%s)",
            self.tenant_id,
            pool_size,
        )

    # ------------------------------------------------------------------
    # Engine configuration
    # ------------------------------------------------------------------
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
                    rows = session.execute(
                        text(
                            """
                            SELECT id, (aggregate_embedding <=> CAST(:query_vec AS vector)) AS distance
                            FROM roster_entries
                            WHERE tenant_id = :tenant_id AND aggregate_embedding IS NOT NULL
                            ORDER BY aggregate_embedding <=> CAST(:query_vec AS vector)
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
