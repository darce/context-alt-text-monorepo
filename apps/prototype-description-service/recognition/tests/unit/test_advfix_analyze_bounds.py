"""Regression tests for bounded JSON analyze requests."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

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
async def test_analyze_rejects_oversized_json_before_parsing() -> None:
    app = FastAPI()
    app.include_router(analyze_router)
    body = b"[" + b" " * MAX_ANALYZE_BODY_BYTES + b"]"
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/analyze", content=body, headers={"content-type": "application/json"})

    assert response.status_code == 413


@pytest.mark.asyncio
async def test_analyze_rejects_oversized_chunked_json_body() -> None:
    app = FastAPI()
    app.include_router(analyze_router)
    transport = httpx.ASGITransport(app=app)

    async def body_chunks():
        yield b" " * MAX_ANALYZE_BODY_BYTES
        yield b" "

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/analyze",
            content=body_chunks(),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413
