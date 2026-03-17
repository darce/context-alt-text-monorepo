"""Integration tests for cluster label persistence across sessions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import db.session as db_session_module
from db.base import Base
from db.models import IdentityCluster, Tenant
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.routers import clusters as cluster_router


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    return TestClient(app)


@pytest_asyncio.fixture
async def sqlite_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        tables: list[Table] = [
            Table("identity_clusters", Base.metadata),
            Table("identity_cluster_representatives", Base.metadata),
            Table("identity_members", Base.metadata),
            Table("cluster_merge_suggestions", Base.metadata),
            Table("identity_cluster_blocks", Base.metadata),
            Table("identity_clustering_jobs", Base.metadata),
            Table("identity_scan_jobs", Base.metadata),
            Table("identity_scan_job_items", Base.metadata),
            Table("identity_suggestions", Base.metadata),
            Table("recognition_runs", Base.metadata),
            Table("recognition_events", Base.metadata),
            Table("api_keys", Base.metadata),
            Table("clustering_job_reports", Base.metadata),
            Table("assignment_decisions", Base.metadata),
            Table("media_identities", Base.metadata),
            Table("identity_constraints", Base.metadata),
            Table("tenants", Base.metadata),
        ]
        await conn.run_sync(Base.metadata.create_all, tables=tables)
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS mv_identity_cluster_centroids (
                    cluster_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    identity_count INTEGER NOT NULL DEFAULT 0,
                    centroid BLOB,
                    refreshed_at TIMESTAMP
                )
                """
            )
        )

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    sqlite_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
    monkeypatch.setattr(db_session_module, "async_session_factory", factory)
    monkeypatch.setattr(cluster_router.db_session_module, "async_session_factory", factory)
    yield factory


@pytest.mark.asyncio
async def test_patch_cluster_label_persists_across_sessions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid.uuid4()
    cluster_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(Tenant(id=tenant_id, site_url="http://example.test"))
        session.add(IdentityCluster(id=cluster_id, tenant_id=tenant_id, label=None, identity_count=0))
        await session.commit()

    with _make_client() as client:
        response = client.patch(
            f"/recognition/clusters/{cluster_id}",
            headers={"X-Tenant-ID": str(tenant_id)},
            json={"tenant_id": str(tenant_id), "label": "Persisted"},
        )

    assert response.status_code == 200

    async with session_factory() as session:
        refreshed = await session.get(IdentityCluster, cluster_id)
        assert refreshed is not None
        assert refreshed.label == "Persisted"
        assert refreshed.user_confirmed is True


@pytest.mark.asyncio
async def test_patch_then_list_clusters_returns_label(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid.uuid4()
    cluster_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(Tenant(id=tenant_id, site_url="http://example.test"))
        session.add(IdentityCluster(id=cluster_id, tenant_id=tenant_id, label=None, identity_count=0))
        await session.commit()

    with _make_client() as client:
        patch = client.patch(
            f"/recognition/clusters/{cluster_id}",
            headers={"X-Tenant-ID": str(tenant_id)},
            json={"tenant_id": str(tenant_id), "label": "Persisted"},
        )
        assert patch.status_code == 200

        resp = client.get(
            "/recognition/clusters",
            headers={"X-Tenant-ID": str(tenant_id)},
            params={"tenant_id": str(tenant_id)},
        )
    assert resp.status_code == 200
    clusters = resp.json()
    assert isinstance(clusters, list)

    match = next((c for c in clusters if c["id"] == str(cluster_id)), None)
    assert match is not None
    assert match["label"] == "Persisted"
    assert match["is_labeled"] is True
    assert match["is_auto_label"] is False
