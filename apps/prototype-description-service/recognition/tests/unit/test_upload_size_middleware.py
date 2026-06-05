"""Unit tests for the body-size limit ASGI middleware (E15-11 Slice 1.3).

The multipart variant of /recognition/analyze must reject oversize requests
*before* FastAPI buffers the entire body into memory. The custom ASGI
middleware enforces a Content-Length cap (413) and refuses chunked
requests with no Content-Length (411) on the protected paths.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from recognition.interface_adapters.http.middleware.upload_size import (
    UploadSizeLimitMiddleware,
)


async def _ok(_request):
    return PlainTextResponse("ok")


async def _unused_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    return None


@pytest.fixture
def client() -> TestClient:
    app = Starlette(
        routes=[
            Route("/recognition/analyze", _ok, methods=["GET", "POST"]),
            Route("/other", _ok, methods=["GET", "POST"]),
        ]
    )
    app.add_middleware(
        UploadSizeLimitMiddleware,
        max_bytes=1024,
        paths={"/recognition/analyze"},
    )
    return TestClient(app)


def test_post_within_limit_passes(client: TestClient) -> None:
    response = client.post("/recognition/analyze", content=b"x" * 100)
    assert response.status_code == 200
    assert response.text == "ok"


def test_post_at_exact_limit_passes(client: TestClient) -> None:
    response = client.post("/recognition/analyze", content=b"x" * 1024)
    assert response.status_code == 200


def test_post_over_limit_returns_413(client: TestClient) -> None:
    response = client.post("/recognition/analyze", content=b"x" * 1025)
    assert response.status_code == 413
    assert "limit" in response.text.lower() or "too large" in response.text.lower()


def test_post_with_no_content_length_returns_411(client: TestClient) -> None:
    """Starlette's TestClient defaults to Content-Length on bytes bodies; we
    simulate the chunked-transfer case by sending an empty content header set
    with Transfer-Encoding only via raw http call. Easier check: directly
    invoke the middleware ASGI scope without a content-length header."""
    import asyncio

    middleware = UploadSizeLimitMiddleware(
        app=_unused_app,  # never called
        max_bytes=1024,
        paths={"/recognition/analyze"},
    )

    captured: list[dict] = []

    async def send(message):
        captured.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/recognition/analyze",
        "headers": [(b"transfer-encoding", b"chunked")],
    }
    asyncio.run(middleware(scope, receive, send))
    statuses = [m for m in captured if m["type"] == "http.response.start"]
    assert statuses, "middleware must have started a response"
    assert statuses[0]["status"] == 411


def test_get_with_no_content_length_passes(client: TestClient) -> None:
    response = client.get("/recognition/analyze")
    assert response.status_code == 200


def test_unprotected_path_skips_enforcement(client: TestClient) -> None:
    response = client.post("/other", content=b"x" * 4096)
    assert response.status_code == 200


def test_invalid_content_length_returns_400(client: TestClient) -> None:
    """A malformed Content-Length is a client bug; reject early rather than
    leaking the parser exception."""
    import asyncio

    middleware = UploadSizeLimitMiddleware(
        app=_unused_app,
        max_bytes=1024,
        paths={"/recognition/analyze"},
    )
    captured: list[dict] = []

    async def send(message):
        captured.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/recognition/analyze",
        "headers": [(b"content-length", b"not-a-number")],
    }
    asyncio.run(middleware(scope, receive, send))
    statuses = [m for m in captured if m["type"] == "http.response.start"]
    assert statuses[0]["status"] == 400


def test_non_http_scope_passes_through() -> None:
    """The middleware must not reject websocket or lifespan scopes."""
    import asyncio

    forwarded: list[dict] = []

    async def downstream(scope, receive, send):
        forwarded.append(scope)

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):  # pragma: no cover - never called
        raise AssertionError("middleware must not write on lifespan scope")

    middleware = UploadSizeLimitMiddleware(app=downstream, max_bytes=1024, paths={"/recognition/analyze"})
    asyncio.run(middleware({"type": "lifespan"}, receive, send))
    assert len(forwarded) == 1
