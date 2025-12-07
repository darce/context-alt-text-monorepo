"""Exception handlers for recognition HTTP API."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class RecognitionError(Exception):
    """Base exception for recognition service errors."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ClusterNotFoundError(RecognitionError):
    def __init__(self, message: str = "Cluster not found") -> None:
        super().__init__(message, status_code=404)


class TenantIsolationError(RecognitionError):
    def __init__(self, message: str = "Access denied") -> None:
        super().__init__(message, status_code=403)


class ValidationError(RecognitionError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)


async def recognition_exception_handler(request: Request, exc: RecognitionError) -> JSONResponse:
    """Handle known recognition errors with a structured payload."""
    trace_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4()}"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "path": str(request.url),
            "trace_id": trace_id,
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected errors with a 500 response."""
    trace_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4()}"
    logger.exception("Unhandled exception", extra={"trace_id": trace_id, "path": str(request.url)})
    return JSONResponse(
        status_code=500,
        content={
            "error": exc.__class__.__name__,
            "message": str(exc),
            "path": str(request.url),
            "trace_id": trace_id,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach exception handlers to the FastAPI app."""
    app.add_exception_handler(RecognitionError, recognition_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)


__all__ = [
    "RecognitionError",
    "ClusterNotFoundError",
    "TenantIsolationError",
    "ValidationError",
    "recognition_exception_handler",
    "generic_exception_handler",
    "register_exception_handlers",
]
