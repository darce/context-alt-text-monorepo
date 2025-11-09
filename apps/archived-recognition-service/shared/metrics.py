"""Prometheus metrics for observability.

This module defines Prometheus metrics for tracking augmented embedding operations,
roster operations, and FAISS index reloads. Metrics are exposed via FastAPI middleware
for scraping by Prometheus.

If prometheus_client is not installed, metrics are no-ops to allow the service
to run without metrics collection in development environments.
"""

import logging
import time
from typing import Callable, Optional
from functools import wraps

logger = logging.getLogger(__name__)

# Try to import prometheus_client; fall back to no-op if not available
try:
    from prometheus_client import Counter, Histogram, Gauge, Info
    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover
    logger.warning("prometheus_client not installed - metrics will be no-ops")
    PROMETHEUS_AVAILABLE = False
    
    # Define no-op classes
    class Counter:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass
        def inc(self, amount=1):
            pass
        def labels(self, **kwargs):
            return self
    
    class Histogram:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass
        def observe(self, amount):
            pass
        def time(self):
            return _NoOpContextManager()
        def labels(self, **kwargs):
            return self
    
    class Gauge:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass
        def set(self, value):
            pass
        def inc(self, amount=1):
            pass
        def dec(self, amount=1):
            pass
        def labels(self, **kwargs):
            return self
    
    class Info:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass
        def info(self, data):
            pass
    
    class _NoOpContextManager:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass


# Augmented embedding metrics
augmented_embedding_requests_total = Counter(
    "augmented_embedding_requests_total",
    "Total number of augmented embedding requests",
    ["status", "quality_tier"]
)

augmented_embedding_duration_seconds = Histogram(
    "augmented_embedding_duration_seconds",
    "Time spent processing augmented embedding requests",
    ["operation"],
    buckets=[0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

aggregate_recomputation_duration_seconds = Histogram(
    "aggregate_recomputation_duration_seconds",
    "Time spent recomputing aggregate embeddings",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

# Roster metrics
roster_entries_total = Gauge(
    "roster_entries_total",
    "Total number of roster entries",
    ["model"]
)

roster_embeddings_total = Gauge(
    "roster_embeddings_total",
    "Total number of embeddings by type",
    ["type", "model"]
)

# FAISS index metrics
faiss_reload_duration_seconds = Histogram(
    "faiss_reload_duration_seconds",
    "Time spent reloading FAISS index",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0]
)

faiss_index_vectors_total = Gauge(
    "faiss_index_vectors_total",
    "Total number of vectors in FAISS index"
)

faiss_index_last_reload_timestamp = Gauge(
    "faiss_index_last_reload_timestamp",
    "Unix timestamp of last FAISS index reload"
)


def track_augment_request(quality_tier: str = "unknown"):
    """
    Decorator to track augmented embedding requests.
    
    Args:
        quality_tier: Quality tier of the embedding (low/medium/high)
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            status = "success"
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as exc:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start_time
                augmented_embedding_requests_total.labels(
                    status=status,
                    quality_tier=quality_tier
                ).inc()
                augmented_embedding_duration_seconds.labels(
                    operation="augment_request"
                ).observe(duration)
        
        return wrapper
    return decorator


def track_aggregate_recomputation():
    """
    Context manager to track aggregate embedding recomputation time.
    
    Usage:
        with track_aggregate_recomputation():
            # recompute aggregate embedding
            pass
    """
    if PROMETHEUS_AVAILABLE:
        return aggregate_recomputation_duration_seconds.time()
    else:
        return _NoOpContextManager()


def update_roster_metrics(roster_stats: dict, model: str = "insightface_w600k"):
    """
    Update roster metrics from storage info.
    
    Args:
        roster_stats: Dictionary with entry_count, reference_embeddings, augmented_embeddings
        model: Model identifier
    """
    if not roster_stats:
        return
    
    entry_count = roster_stats.get("entry_count", 0)
    reference_count = roster_stats.get("reference_embeddings", 0)
    augmented_count = roster_stats.get("augmented_embeddings", 0)
    
    roster_entries_total.labels(model=model).set(entry_count)
    roster_embeddings_total.labels(type="reference", model=model).set(reference_count)
    roster_embeddings_total.labels(type="augmented", model=model).set(augmented_count)


def update_faiss_metrics(faiss_stats: dict):
    """
    Update FAISS index metrics.
    
    Args:
        faiss_stats: Dictionary with total_vectors, last_reload, etc.
    """
    if not faiss_stats:
        return
    
    total_vectors = faiss_stats.get("total_vectors", 0)
    faiss_index_vectors_total.set(total_vectors)
    
    # Update reload timestamp if available
    last_reload = faiss_stats.get("last_reload")
    if last_reload:
        # Convert ISO timestamp to unix timestamp if needed
        # For now, just log it
        logger.debug(f"FAISS last reload: {last_reload}")


def record_faiss_reload_duration(duration_seconds: float):
    """
    Record FAISS index reload duration.
    
    Args:
        duration_seconds: Duration of reload operation in seconds
    """
    faiss_reload_duration_seconds.observe(duration_seconds)
    faiss_index_last_reload_timestamp.set(time.time())


# Metrics endpoint for Prometheus scraping
def get_metrics_handler():
    """
    Get the metrics HTTP handler for FastAPI.
    
    Returns:
        Callable that can be used as a FastAPI endpoint
    """
    if not PROMETHEUS_AVAILABLE:
        logger.warning("prometheus_client not available - /metrics endpoint will return 501")
        
        def not_implemented():
            from fastapi import HTTPException
            raise HTTPException(
                status_code=501,
                detail="Metrics not available (prometheus_client not installed)"
            )
        
        return not_implemented
    
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi import Response
    
    def metrics():
        """Prometheus metrics endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    
    return metrics
