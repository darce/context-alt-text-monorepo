"""Tests for connection pool monitoring and session cleanup."""

from __future__ import annotations

import uuid

import pytest

from db.session import get_pool_stats
from db.settings import get_database_settings
from recognition.interface_adapters.http.deps import session as session_module


def test_pool_stats_returns_valid_metrics() -> None:
    """Pool stats should return all expected metrics."""
    stats = get_pool_stats()

    assert "size" in stats
    assert "overflow" in stats
    assert "checked_out" in stats
    assert "checked_in" in stats
    assert "overflow_count" in stats
    assert "total_capacity" in stats
    assert "utilization_percent" in stats
    assert 0 <= stats["utilization_percent"] <= 100


def test_database_settings_use_higher_pool_defaults(monkeypatch) -> None:
    for key in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT", "DB_POOL_RECYCLE"):
        monkeypatch.delenv(key, raising=False)

    get_database_settings.cache_clear()
    try:
        settings = get_database_settings()
    finally:
        get_database_settings.cache_clear()

    assert settings.pool_size == 20
    assert settings.max_overflow == 10


@pytest.mark.asyncio
async def test_session_cleanup_on_context_failure(monkeypatch) -> None:
    """Session should close even if set_tenant_context fails."""
    events: list[str] = []
    session = object()

    async def fake_session_source():
        events.append("open")
        try:
            yield session
        finally:
            events.append("close")

    async def fail_set(_session, _tenant_id):
        events.append("set")
        raise RuntimeError("Simulated failure")

    async def fake_clear(_session):
        events.append("clear")

    # Patch in the session module where these are actually used
    monkeypatch.setattr(session_module, "_get_session", fake_session_source)
    monkeypatch.setattr(session_module, "set_tenant_context", fail_set)
    monkeypatch.setattr(session_module, "clear_tenant_context", fake_clear)

    with pytest.raises(RuntimeError, match="Simulated failure"):
        async for _ in session_module.get_session(tenant_id=str(uuid.uuid4())):
            pass

    assert "clear" in events
    assert "close" in events
