"""Regression tests for bounded JSON analyze requests."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import ValidationError

from recognition.interface_adapters.http.routers import analyze as analyze_module
from recognition.interface_adapters.http.routers.analyze import MAX_ANALYZE_BODY_BYTES, router as analyze_router
from recognition.interface_adapters.http.schemas.requests import MAX_ANALYZE_MEDIA_ITEMS, AnalyzeRequest


def test_analyze_rejects_too_many_media_ids() -> None:
    with pytest.raises(ValidationError):
        AnalyzeRequest(tenant_id=str(uuid.uuid4()), media_ids=["1"] * (MAX_ANALYZE_MEDIA_ITEMS + 1))


def test_analyze_rejects_too_many_media_items() -> None:
    items = [
        {"media_id": index, "media_url": f"https://example.test/{index}.jpg"}
        for index in range(MAX_ANALYZE_MEDIA_ITEMS + 1)
    ]
    with pytest.raises(ValidationError):
        AnalyzeRequest(tenant_id=str(uuid.uuid4()), media_items=items)


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "/recognition"])
async def test_analyze_rejects_oversized_json_before_parsing(prefix: str) -> None:
    app = FastAPI()
    app.include_router(analyze_router, prefix=prefix)
    # Invalid JSON ensures an unbounded route fails at parsing, before dependencies.
    body = b"[" + b" " * MAX_ANALYZE_BODY_BYTES + b"!"
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"{prefix}/analyze", content=body, headers={"content-type": "application/json"})

    assert response.status_code == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "/recognition"])
async def test_analyze_rejects_oversized_chunked_json_body(prefix: str) -> None:
    app = FastAPI()
    app.include_router(analyze_router, prefix=prefix)
    transport = httpx.ASGITransport(app=app)

    async def body_chunks():
        yield b" " * MAX_ANALYZE_BODY_BYTES
        yield b" "

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"{prefix}/analyze",
            content=body_chunks(),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413


class _StreamingRequest:
    headers: dict[str, str] = {}

    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self):
        return self._chunks()


@pytest.mark.asyncio
async def test_analyze_body_read_returns_408_after_idle_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analyze_module, "ANALYZE_BODY_IDLE_TIMEOUT_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(analyze_module, "ANALYZE_BODY_TOTAL_TIMEOUT_SECONDS", 0.1, raising=False)
    blocked = asyncio.Event()

    async def chunks():
        yield b"{"
        await blocked.wait()

    with pytest.raises(HTTPException) as exc_info:
        await asyncio.wait_for(analyze_module._read_bounded_analyze_body(_StreamingRequest(chunks)), timeout=0.08)

    assert exc_info.value.status_code == 408


@pytest.mark.asyncio
async def test_analyze_body_read_returns_408_after_total_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analyze_module, "ANALYZE_BODY_IDLE_TIMEOUT_SECONDS", 0.1, raising=False)
    monkeypatch.setattr(analyze_module, "ANALYZE_BODY_TOTAL_TIMEOUT_SECONDS", 0.025, raising=False)

    async def chunks():
        while True:
            await asyncio.sleep(0.015)
            yield b" "

    with pytest.raises(HTTPException) as exc_info:
        await asyncio.wait_for(analyze_module._read_bounded_analyze_body(_StreamingRequest(chunks)), timeout=0.08)

    assert exc_info.value.status_code == 408
