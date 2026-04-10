"""Tests for connection pool monitoring and session cleanup."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from db.session import get_pool_stats
from db.settings import get_database_settings
from recognition.interface_adapters.http.deps import session as session_module
from recognition.interface_adapters.http.deps.circuit_breaker import initialize_session_dependency_circuit_breaker


def test_pool_stats_returns_valid_metrics() -> None:
    """Pool stats should return all expected metrics."""
    stats = get_pool_stats()

    assert set(stats) == {"business", "observability"}
    for pool_name in ("business", "observability"):
        pool_stats = stats[pool_name]
        assert "size" in pool_stats
        assert "overflow" in pool_stats
        assert "checked_out" in pool_stats
        assert "checked_in" in pool_stats
        assert "overflow_count" in pool_stats
        assert "total_capacity" in pool_stats
        assert "utilization_percent" in pool_stats
        assert 0 <= pool_stats["utilization_percent"] <= 100


def test_database_settings_use_higher_pool_defaults(monkeypatch) -> None:
    for key in (
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE",
        "DB_OBSERVABILITY_POOL_SIZE",
        "DB_OBSERVABILITY_MAX_OVERFLOW",
        "DB_OBSERVABILITY_POOL_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)

    get_database_settings.cache_clear()
    try:
        settings = get_database_settings()
    finally:
        get_database_settings.cache_clear()

    assert settings.pool_size == 20
    assert settings.max_overflow == 10
    assert settings.observability_pool_size == 2
    assert settings.observability_max_overflow == 0
    assert settings.observability_pool_timeout == 5


@pytest.mark.asyncio
async def test_session_cleanup_on_context_failure(monkeypatch) -> None:
    """Session should close even if set_tenant_context fails."""
    events: list[str] = []

    class StubSession:
        bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()

        async def execute(self, _statement, _params=None):  # noqa: ANN001
            return None

        async def commit(self) -> None:
            events.append("commit")

        async def rollback(self) -> None:
            events.append("rollback")

        async def close(self) -> None:
            events.append("close")

        async def connection(self):
            return type("AsyncConnection", (), {"sync_connection": object()})()

    session = StubSession()

    async def fail_set(_session, _tenant_id):
        events.append("set")
        raise RuntimeError("Simulated failure")

    monkeypatch.setattr(session_module, "async_session_factory", lambda: session)
    monkeypatch.setattr(session_module, "set_tenant_context", fail_set)
    app = FastAPI()
    initialize_session_dependency_circuit_breaker(app)
    request = Request({"type": "http", "method": "GET", "path": "/test", "headers": [], "app": app})

    with pytest.raises(RuntimeError, match="Simulated failure"):
        async for _ in session_module.get_session(request=request, tenant_id=str(uuid.uuid4())):
            pass

    assert "close" in events
