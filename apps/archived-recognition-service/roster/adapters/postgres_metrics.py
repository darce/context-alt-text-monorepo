"""Shared metrics and timing helpers for PostgreSQL adapters."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional


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
        self._slow_queries: list[Dict[str, Any]] = []
        self._errors: list[Dict[str, Any]] = []

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
        *,
        error_type: Optional[str] = None,
        message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record error with operation name and optional context."""
        if error is not None:
            error_info = {
                "error_type": type(error).__name__,
                "message": str(error),
            }
        else:
            error_info = {
                "error_type": error_type or "UnknownError",
                "message": message or "No error message provided",
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


@contextmanager
def timed_operation(
    metrics: DatabaseMetrics,
    logger: logging.Logger,
    slow_query_threshold_ms: float,
    operation: str,
    **context: Any,
):
    """Context manager that records metrics for a database operation."""
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

        metrics.record_query(operation, duration_ms, success=success)

        if success and duration_ms >= slow_query_threshold_ms:
            metrics.record_slow_query(operation, duration_ms, context_payload)
            logger.warning(
                "Slow query detected: %s took %.2fms (context=%s)",
                operation,
                duration_ms,
                context_payload,
            )
        if not success and error is not None:
            metrics.record_error(operation, error, context=context_payload)
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
