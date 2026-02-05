"""Unit tests for background surfacing task behavior."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import pytest

from recognition.application.tasks.clustering import run_background_surface_suggestions


class _ImmediateTimeout:
    async def __aenter__(self) -> None:
        raise TimeoutError

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


def _timeout(_seconds: float) -> _ImmediateTimeout:
    return _ImmediateTimeout()


@pytest.mark.asyncio
async def test_background_surface_suggestions_timeout(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(asyncio, "timeout", _timeout)

    @asynccontextmanager
    async def _session_factory():
        yield None

    async def _builder(*, session, tenant_id):  # noqa: ANN001
        raise AssertionError("cluster_service_builder should not be invoked on timeout")

    await run_background_surface_suggestions(
        "tenant-1",
        "cluster-1",
        "Label",
        session_factory=_session_factory,
        cluster_service_builder=_builder,
    )

    assert "Background surfacing timed out after 30s" in caplog.text
