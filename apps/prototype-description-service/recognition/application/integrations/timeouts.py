"""Shared timeout helpers for external adapter calls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

ResultT = TypeVar("ResultT")


class AdapterTimeoutError(TimeoutError):
    """Raised when an external adapter call exceeds its configured deadline."""

    def __init__(self, adapter_name: str, timeout_s: float) -> None:
        super().__init__(f"Adapter {adapter_name} timed out after {timeout_s:.2f}s")
        self.adapter_name = adapter_name
        self.timeout_s = timeout_s


async def wait_for_adapter[ResultT](
    coro: asyncio.Future[ResultT] | asyncio.Task[ResultT] | Awaitable[ResultT],
    *,
    timeout_s: float,
    adapter_name: str,
) -> ResultT:
    """Await an adapter coroutine under a fixed deadline."""

    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except TimeoutError as exc:
        raise AdapterTimeoutError(adapter_name=adapter_name, timeout_s=timeout_s) from exc


__all__ = ["AdapterTimeoutError", "wait_for_adapter"]
