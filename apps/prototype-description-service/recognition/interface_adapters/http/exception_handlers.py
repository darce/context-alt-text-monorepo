"""Exception handlers for recognition HTTP API."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from db.session import get_pool_stats
from recognition.domain.cluster import ReservedClusterLabelError
from recognition.domain.repositories import ClusterNotFoundError
from recognition.interface_adapters.http.middleware.correlation import (
    CORRELATION_ID_HEADER,
    generate_correlation_id,
    get_correlation_id,
)

logger = logging.getLogger(__name__)


def _correlation_id_for(request: Request) -> str:
    """Return the active correlation id, falling back to request header or a new id.

    The CorrelationIdMiddleware is registered app-wide, so ``get_correlation_id``
    almost always returns the value already echoed in the response header. The
    remaining fallbacks exist for handlers that run before the middleware has
    had a chance to bind the contextvar (e.g. routing failures in tests).
    """
    return get_correlation_id() or request.headers.get(CORRELATION_ID_HEADER) or generate_correlation_id()


def _opaque_error_response(
    *,
    request: Request,
    status_code: int,
    error: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": error,
            "path": str(request.url),
            "correlation_id": _correlation_id_for(request),
        },
        headers=headers,
    )


class RecognitionError(Exception):
    """Base exception for recognition service errors."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TenantIsolationError(RecognitionError):
    def __init__(self, message: str = "Access denied") -> None:
        super().__init__(message, status_code=403)


class ValidationError(RecognitionError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)


async def recognition_exception_handler(request: Request, exc: RecognitionError) -> JSONResponse:
    """Handle known recognition errors with a structured payload."""
    correlation_id = _correlation_id_for(request)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "path": str(request.url),
            "correlation_id": correlation_id,
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected errors with a 500 response."""
    correlation_id = _correlation_id_for(request)
    logger.exception("Unhandled exception", extra={"correlation_id": correlation_id, "path": str(request.url)})
    return _opaque_error_response(request=request, status_code=500, error="internal_server_error")


async def pool_exhaustion_handler(request: Request, exc: PoolTimeoutError) -> JSONResponse:
    """Map SQLAlchemy pool checkout failures to a retryable 503."""
    correlation_id = _correlation_id_for(request)
    logger.exception(
        "Database pool exhausted",
        extra={
            "correlation_id": correlation_id,
            "path": str(request.url),
            "pool_stats": get_pool_stats(),
        },
    )
    return _opaque_error_response(
        request=request,
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        error="database_unavailable",
        headers={"Retry-After": "5"},
    )


async def cluster_not_found_exception_handler(request: Request, exc: ClusterNotFoundError) -> JSONResponse:
    """Translate domain cluster-not-found errors to HTTP 404."""
    correlation_id = _correlation_id_for(request)
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "ClusterNotFoundError",
            "message": str(exc),
            "path": str(request.url),
            "correlation_id": correlation_id,
        },
    )


async def reserved_cluster_label_exception_handler(request: Request, exc: ReservedClusterLabelError) -> JSONResponse:
    """Translate reserved operator labels to HTTP 400."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "ReservedClusterLabelError",
            "message": str(exc),
            "path": str(request.url),
            "correlation_id": _correlation_id_for(request),
        },
    )


def _is_duplicate_cluster_label(exc: IntegrityError) -> bool:
    """Return True when IntegrityError is caused by duplicate (tenant_id, label)."""
    message = str(exc).lower()
    if "unique_tenant_identity_label" in message:
        return True
    # SQLite-style message: "UNIQUE constraint failed: identity_clusters.tenant_id, identity_clusters.label"
    return "unique constraint failed" in message and "identity_clusters" in message and ".label" in message


async def integrity_exception_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Translate common DB constraint violations into friendlier HTTP errors."""
    correlation_id = _correlation_id_for(request)

    if _is_duplicate_cluster_label(exc):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "DuplicateClusterLabel",
                "message": "Cluster label already exists for this tenant.",
                "path": str(request.url),
                "correlation_id": correlation_id,
            },
        )

    logger.exception("Unhandled integrity error", extra={"correlation_id": correlation_id, "path": str(request.url)})
    return _opaque_error_response(
        request=request, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, error="integrity_error"
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach exception handlers to the FastAPI app."""
    app.add_exception_handler(ClusterNotFoundError, cluster_not_found_exception_handler)
    app.add_exception_handler(ReservedClusterLabelError, reserved_cluster_label_exception_handler)
    app.add_exception_handler(RecognitionError, recognition_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_exception_handler)
    app.add_exception_handler(PoolTimeoutError, pool_exhaustion_handler)
    app.add_exception_handler(Exception, generic_exception_handler)


__all__ = [
    "RecognitionError",
    "TenantIsolationError",
    "ValidationError",
    "recognition_exception_handler",
    "generic_exception_handler",
    "pool_exhaustion_handler",
    "cluster_not_found_exception_handler",
    "register_exception_handlers",
]
