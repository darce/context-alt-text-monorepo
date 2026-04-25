"""ASGI middleware that bounds request body size on protected paths.

Enforced on the multipart variant of ``/recognition/analyze`` so the
recognition service rejects oversize uploads *before* FastAPI buffers the
body into memory. Clients sending chunked-transfer requests with no
Content-Length are refused outright (411 Length Required) on the same
paths — multipart uploads must declare their size up front so the cap is
enforceable before any bytes are consumed.

Anything outside the protected path set passes through unchanged so the
JSON variant of ``/recognition/analyze`` and unrelated routes keep their
existing behaviour.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

_BODY_BEARING_METHODS = frozenset({"POST", "PUT", "PATCH"})


class UploadSizeLimitMiddleware:
    """Reject oversize or undeclared-length requests on protected paths.

    - ``413 Payload Too Large`` when ``Content-Length`` exceeds ``max_bytes``.
    - ``411 Length Required`` when the request omits ``Content-Length`` on a
      protected path (chunked-transfer multipart uploads cannot be sized
      pre-buffer and are therefore not accepted).
    - ``400 Bad Request`` on a malformed ``Content-Length`` header.
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        max_bytes: int,
        paths: Iterable[str] | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._app = app
        self._max_bytes = int(max_bytes)
        self._paths: frozenset[str] | None = frozenset(paths) if paths is not None else None

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "")
        if method not in _BODY_BEARING_METHODS:
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if self._paths is not None and path not in self._paths:
            await self._app(scope, receive, send)
            return

        content_length = _header_value(scope.get("headers", ()), b"content-length")
        if content_length is None:
            await _reject(
                send,
                411,
                "Length Required: chunked uploads without Content-Length are not accepted on this endpoint.",
            )
            return
        try:
            size = int(content_length)
        except (TypeError, ValueError):
            await _reject(send, 400, "Bad Request: malformed Content-Length")
            return
        if size < 0:
            await _reject(send, 400, "Bad Request: negative Content-Length")
            return
        if size > self._max_bytes:
            await _reject(
                send,
                413,
                f"Payload Too Large: limit is {self._max_bytes} bytes",
            )
            return

        await self._app(scope, receive, send)


def _header_value(headers: Iterable[tuple[bytes, bytes]], name: bytes) -> bytes | None:
    name_lower = name.lower()
    for key, value in headers:
        if key.lower() == name_lower:
            return value
    return None


async def _reject(
    send: Callable[[dict[str, Any]], Awaitable[None]],
    status: int,
    body: str,
) -> None:
    body_bytes = body.encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body_bytes)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body_bytes, "more_body": False})
