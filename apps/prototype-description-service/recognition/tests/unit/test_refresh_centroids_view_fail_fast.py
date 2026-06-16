"""INFRA-5: MV-refresh failures must be visible, not silently swallowed.

`refresh_centroids_view` previously wrapped the whole refresh in
`try/except Exception: logger.warning(...)` and returned ``None`` regardless of
outcome, so callers could not tell a failed REFRESH from a successful one and
would proceed to read/generate suggestions off stale centroids.  Fail-fast over
silent fallback: the error now propagates.  The one `_concurrent` caller that
ignored its bool result (`TenantPurgeService`) now logs when the refresh fails.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


class _RaisingSession:
    """Async session whose every ``execute`` raises a marker error."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise self._error


async def test_refresh_centroids_view_propagates_postgres_error(monkeypatch) -> None:
    """Postgres branch: a failed REFRESH MATERIALIZED VIEW propagates."""
    from recognition.infrastructure.repositories import cluster_repository as cr

    monkeypatch.setattr(cr, "is_sqlite", lambda _session: False)
    monkeypatch.setattr(cr, "enable_rls_bypass", AsyncMock())

    boom = RuntimeError("REFRESH MATERIALIZED VIEW failed")
    repo = cr.SqlAlchemyClusterRepository(_RaisingSession(boom))

    with pytest.raises(RuntimeError, match="REFRESH MATERIALIZED VIEW failed"):
        await repo.refresh_centroids_view()


async def test_refresh_centroids_view_propagates_sqlite_error(monkeypatch) -> None:
    """SQLite branch: a failed shadow-table rebuild propagates."""
    from recognition.infrastructure.repositories import cluster_repository as cr

    monkeypatch.setattr(cr, "is_sqlite", lambda _session: True)

    boom = RuntimeError("sqlite refresh failed")
    repo = cr.SqlAlchemyClusterRepository(_RaisingSession(boom))

    with pytest.raises(RuntimeError, match="sqlite refresh failed"):
        await repo.refresh_centroids_view()


async def test_purge_rows_warns_when_mv_refresh_fails(monkeypatch, caplog) -> None:
    """When the concurrent refresh returns False the purge logs it (no longer silent)."""
    from recognition.application.services.purge_service import TenantPurgeService

    service = TenantPurgeService(session=MagicMock())
    monkeypatch.setattr(service, "_collect_scope_ids", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(service, "_delete_jobs_for_scope", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_delete_dependency_rows", AsyncMock(return_value={}))
    service._cluster_repository.refresh_centroids_view_concurrent = AsyncMock(return_value=False)

    with caplog.at_level(logging.WARNING, logger="recognition.application.services.purge_service"):
        await service._purge_rows(uuid4(), "all")

    assert any("centroid" in record.message.lower() for record in caplog.records), (
        "a failed post-purge MV refresh must emit a warning"
    )
