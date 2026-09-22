"""Validated API request-id middleware and logging filter.

The HTTP request id is deliberately separate from authentication.  The
middleware accepts only a canonical lowercase UUIDv4 from
``X-ACX-Request-Id``; malformed or repeated values are replaced before the id
can reach a response or a log record.  It binds the validated value through a
:mod:`contextvars` variable and emits the one request-scoped access record that
replaces uvicorn's post-response access logger.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from enum import StrEnum
from uuid import UUID, uuid4


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


CORRELATION_ID_HEADER = "X-ACX-Request-Id"
CORRELATION_ID_LOG_FIELD = "correlation_id"
CORRELATION_ID_PLACEHOLDER = "-"
ACCESS_LOGGER_NAME = "recognition.access"

_correlation_id_var: ContextVar[str | None] = ContextVar("recognition_correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current request scope, or ``None``."""
    return _correlation_id_var.get()


def validate_correlation_id(value: bytes | str) -> str | None:
    """Return a canonical UUIDv4, or ``None`` for any untrusted value.

    The length check happens before decoding/parsing so oversized values are
    rejected at the transport boundary.  Canonical spelling is required on
    input as well as output: lowercase hex, hyphens, and exactly 36 ASCII
    bytes.  In particular, no invalid header value is ever logged or echoed.
    """

    if isinstance(value, bytes):
        if len(value) != 36:
            return None
        try:
            candidate = value.decode("ascii")
        except UnicodeDecodeError:
            return None
    else:
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError:
            return None
        if len(encoded) != 36:
            return None
        candidate = value

    try:
        parsed = UUID(candidate)
    except (ValueError, AttributeError):
        return None
    if parsed.version != 4 or str(parsed) != candidate:
        return None
    return candidate


def generate_correlation_id() -> str:
    """Generate a canonical lowercase UUIDv4 request id."""
    return str(uuid4())


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
        # Reset on success; deliberately leak on exceptions so the outer
        # ServerErrorMiddleware can still read the id for the registered 500 handler.
        token = _correlation_id_var.set(correlation_id)
        response_status: int | None = None
        encoded_header = (self._header_key, correlation_id.encode("latin-1"))

        async def send_wrapper(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = int(message.get("status", 500))
                existing = [
                    (key, value) for key, value in message.get("headers", []) if key.lower() != self._header_key
                ]
                existing.append(encoded_header)
                message["headers"] = existing
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException:
            # Deliberately do NOT reset: ServerErrorMiddleware sits outside this
            # middleware and its 500 handler still needs the bound id.
            self._log_access(scope, correlation_id, response_status or 500)
            raise
        else:
            self._log_access(scope, correlation_id, response_status or 500)
            _correlation_id_var.reset(token)

    def _read_header(self, scope: Scope) -> str | None:
        values = [value for key, value in scope.get("headers", []) if key.lower() == self._header_key]
        if len(values) != 1:
            return None
        return validate_correlation_id(values[0])

    @staticmethod
    def _log_access(scope: Scope, correlation_id: str, status_code: int) -> None:
        """Emit one access record while the request context is still active.

        Uvicorn's default access record is emitted after the application call,
        outside this request context, so ``api.logging_config`` disables that
        logger and this middleware owns the single correlated access record.
        """

        logging.getLogger(ACCESS_LOGGER_NAME).info(
            "%s %s %s",
            scope.get("method", "-"),
            scope.get("path", "-"),
            status_code,
            extra={
                CORRELATION_ID_LOG_FIELD: correlation_id,
                "method": scope.get("method", "-"),
                "path": scope.get("path", "-"),
                "status_code": status_code,
            },
        )


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
    "ACCESS_LOGGER_NAME",
    "CorrelationIdFilter",
    "CorrelationIdMiddleware",
    "CorrelationSource",
    "generate_correlation_id",
    "get_correlation_id",
    "validate_correlation_id",
]
