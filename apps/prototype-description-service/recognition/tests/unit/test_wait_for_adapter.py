"""Unit tests for the shared adapter-timeout helper."""

from __future__ import annotations

import asyncio

import pytest

from recognition.application.integrations.timeouts import AdapterTimeoutError, wait_for_adapter


@pytest.mark.asyncio
async def test_wait_for_adapter_returns_result_before_timeout() -> None:
    async def fast_call() -> str:
        await asyncio.sleep(0)
        return "ok"

    result = await wait_for_adapter(fast_call(), timeout=0.1, adapter_name="insightface")

    assert result == "ok"


@pytest.mark.asyncio
async def test_wait_for_adapter_raises_typed_timeout() -> None:
    async def slow_call() -> str:
        await asyncio.sleep(0.05)
        return "late"

    with pytest.raises(AdapterTimeoutError) as exc_info:
        await wait_for_adapter(slow_call(), timeout=0.01, adapter_name="insightface")

    assert exc_info.value.adapter_name == "insightface"
    assert exc_info.value.timeout_s == 0.01
