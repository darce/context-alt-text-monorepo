"""Regression coverage for DEFWAVE-2 suggestion pagination."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from recognition.interface_adapters.http.routers.suggestions import _collect_min_confidence_page


@pytest.mark.asyncio
async def test_min_confidence_page_walks_past_ten_batches() -> None:
    rows = [SimpleNamespace(confidence_score=0.2) for _ in range(10)]
    match = SimpleNamespace(confidence_score=0.9)
    rows.append(match)
    requested_offsets: list[int] = []

    async def fetch_page(limit: int, offset: int) -> list[SimpleNamespace]:
        requested_offsets.append(offset)
        return rows[offset : offset + limit]

    result = await _collect_min_confidence_page(
        fetch_page,
        limit=1,
        offset=0,
        min_confidence=0.8,
        batch_size=1,
    )

    assert result == [match]
    assert requested_offsets == list(range(11))
