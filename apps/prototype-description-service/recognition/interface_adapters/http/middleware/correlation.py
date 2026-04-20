"""Correlation ID middleware and logging filter.

Middleware extracts the ``X-Request-ID`` header from the incoming request (or
generates a new ``req-<uuid7>`` when absent), publishes it via a
:mod:`contextvars` variable so downstream code and log filters can read it, and
echoes the same value back on the response so clients can correlate logs with
observed requests.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from enum import StrEnum

from uuid_extensions import uuid7


class CorrelationSource(StrEnum):
    """Origin of a correlation_id on a persisted scan queue row or log record.

    Single import surface for API vs worker-origin correlation ids. All
    producers (HTTP enqueue, worker fallback) and consumers (log fields,
    repository writes, tests) must use these members instead of magic strings.
    """

    API = "api"
    WORKER = "worker"


try:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send
except ImportError:  # pragma: no cover - starlette is a FastAPI dep
    ASGIApp = Receive = Scope = Send = Message = object  # type: ignore[assignment,misc]


CORRELATION_ID_HEADER = "X-Request-ID"
CORRELATION_ID_LOG_FIELD = "correlation_id"
CORRELATION_ID_PLACEHOLDER = "-"

_correlation_id_var: ContextVar[str | None] = ContextVar("recognition_correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current request scope, or ``None``."""
    return _correlation_id_var.get()


def generate_correlation_id() -> str:
    """Generate a fresh ``req-<uuid7>`` identifier."""
    return f"req-{uuid7()}"


class CorrelationIdMiddleware:
    """Pure-ASGI middleware that binds a correlation id to the request scope."""

    def __init__(self, app: ASGIApp, *, header_name: str = CORRELATION_ID_HEADER) -> None:
        self.app = app
        self._header_key = header_name.lower().encode("latin-1")
        self._header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        incoming = self._read_header(scope)
        correlation_id = incoming or generate_correlation_id()
        # Don't reset the contextvar in a finally block: Starlette's
        # ServerErrorMiddleware sits outside user middleware, so resetting here
        # clears the id before the registered 500 handler runs. Each request
        # runs in its own asyncio task/context, so the binding is naturally
        # scoped to the request lifetime.
        _correlation_id_var.set(correlation_id)
        encoded_header = (self._header_key, correlation_id.encode("latin-1"))

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = [
                    (key, value) for key, value in message.get("headers", []) if key.lower() != self._header_key
                ]
                existing.append(encoded_header)
                message["headers"] = existing
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _read_header(self, scope: Scope) -> str | None:
        for key, value in scope.get("headers", []):
            if key.lower() == self._header_key:
                try:
                    return value.decode("latin-1").strip() or None
                except UnicodeDecodeError:
                    return None
        return None


class CorrelationIdFilter(logging.Filter):
    """Logging filter that stamps every record with the active correlation id."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - stdlib signature
        if not hasattr(record, CORRELATION_ID_LOG_FIELD):
            setattr(
                record,
                CORRELATION_ID_LOG_FIELD,
                _correlation_id_var.get() or CORRELATION_ID_PLACEHOLDER,
            )
        return True


__all__ = [
    "CORRELATION_ID_HEADER",
    "CORRELATION_ID_LOG_FIELD",
    "CORRELATION_ID_PLACEHOLDER",
    "CorrelationIdFilter",
    "CorrelationIdMiddleware",
    "CorrelationSource",
    "generate_correlation_id",
    "get_correlation_id",
]
