"""Unit tests for background surfacing task behavior."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.application.tasks.clustering import (
    run_background_backfill_suggestions,
    run_background_refresh_suggestions,
    run_background_surface_suggestions,
)


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


@pytest.mark.asyncio
async def test_background_surface_suggestions_commits_chunk_session(monkeypatch) -> None:
    preload_session = AsyncMock()
    chunk_session = AsyncMock()
    sessions = [preload_session, chunk_session]

    @asynccontextmanager
    async def _session_factory():
        yield sessions.pop(0)

    class _RepCache:
        def get_representatives(self, _cluster_id: str):
            return [np.array([1.0], dtype=np.float32)]

    async def _fake_rep_load(_cluster_ids, _cluster_repo):
        return _RepCache()

    from recognition.application.tasks import clustering as clustering_tasks

    monkeypatch.setattr(clustering_tasks.RepresentativeCache, "load", _fake_rep_load)

    unlabeled = SimpleNamespace(id="cluster-unlabeled", user_confirmed=False, label=None, identity_count=1)
    cluster_repository = SimpleNamespace(get_by_tenant=AsyncMock(return_value=[unlabeled]))
    refresh_service = SimpleNamespace(surface_for_newly_labeled_cluster=AsyncMock(return_value=1))
    cluster_service = SimpleNamespace(cluster_repository=cluster_repository, suggestion_refresh_service=refresh_service)

    async def _builder(*, session, tenant_id):  # noqa: ANN001
        return cluster_service

    await run_background_surface_suggestions(
        "tenant-1",
        "cluster-target",
        "Label",
        session_factory=_session_factory,
        cluster_service_builder=_builder,
    )

    refresh_service.surface_for_newly_labeled_cluster.assert_awaited_once()
    chunk_session.commit.assert_awaited_once()
    preload_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_refresh_suggestions_commits_session() -> None:
    session = AsyncMock()

    @asynccontextmanager
    async def _session_factory():
        yield session

    refresh_service = SimpleNamespace(refresh_for_cluster=AsyncMock())
    cluster_service = SimpleNamespace(suggestion_refresh_service=refresh_service)

    async def _builder(*, session, tenant_id):  # noqa: ANN001
        return cluster_service

    await run_background_refresh_suggestions(
        "tenant-1",
        "cluster-1",
        session_factory=_session_factory,
        cluster_service_builder=_builder,
    )

    refresh_service.refresh_for_cluster.assert_awaited_once_with("cluster-1")
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_background_backfill_suggestions_commits_session() -> None:
    session = AsyncMock()

    @asynccontextmanager
    async def _session_factory():
        yield session

    refresh_service = SimpleNamespace(backfill_for_new_unlabeled_clusters=AsyncMock(return_value=3))
    cluster_service = SimpleNamespace(suggestion_refresh_service=refresh_service)

    async def _builder(*, session, tenant_id):  # noqa: ANN001
        return cluster_service

    await run_background_backfill_suggestions(
        "tenant-1",
        ["cluster-a", "cluster-b"],
        fallback_window_minutes=0,
        session_factory=_session_factory,
        cluster_service_builder=_builder,
    )

    refresh_service.backfill_for_new_unlabeled_clusters.assert_awaited_once_with(
        tenant_id="tenant-1",
        created_cluster_ids=["cluster-a", "cluster-b"],
        fallback_window_minutes=0,
    )
    session.commit.assert_awaited_once()
