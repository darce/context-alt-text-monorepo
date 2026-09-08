"""Demo quota on clustering compute routes (DS2B-PM-S2-03).

Behavioral: demo key increments recognition_used by 1 per route; non-demo key
leaves the demo registry row untouched.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.tenant import ApiKey, DemoInstance, Tenant
from recognition.application.services.demo_provisioning_service import provision_demo
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth


def _stub_cluster_result():
    now = datetime.now(tz=UTC)
    return type(
        "Result",
        (),
        {
            "job_id": str(uuid.uuid4()),
            "started_at": now,
            "finished_at": now,
            "completed": 0,
            "total": 0,
            "accepted": 0,
            "suggested": 0,
            "rejected": 0,
            "clusters_created": 0,
        },
    )()


@contextmanager
def _clustering_demo_client(*, recognition_quota: int = 5, non_demo: bool = False):
    path = os.path.join(tempfile.gettempdir(), f"ds2c_clust_{uuid.uuid4().hex}.db")
    url = f"sqlite+aiosqlite:///{path}"

    async def _init() -> None:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=cast(list[Table], [Tenant.__table__, ApiKey.__table__, DemoInstance.__table__]),
            )
        await engine.dispose()

    asyncio.run(_init())
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async def _provision():
        async with sf() as s:
            result = await provision_demo(s, label="Cluster Demo", seed="default", recognition_quota=recognition_quota)
            await s.commit()
            return result

    provisioned = asyncio.run(_provision())
    tenant_id = str(provisioned.instance.tenant_id)
    slug = provisioned.instance.slug

    if non_demo:
        auth = AuthContext(
            token="not-a-demo-key",
            tenant_claim=tenant_id,
            api_key_id=None,
            is_admin=False,
            enabled=True,
        )
    else:
        auth = AuthContext(
            token=provisioned.raw_api_key,
            tenant_claim=tenant_id,
            api_key_id=None,
            is_admin=False,
            enabled=True,
        )

    async def _session():
        async with sf() as s:
            yield s

    class StubService:
        async def cluster_unclustered_identities(self, _tenant_id: str):
            return _stub_cluster_result()

    def cluster_builder():
        async def _build(_tenant_id: str):
            return StubService()

        return _build

    async def job_service_dep():
        from recognition.tests.fakes import FakeJobService

        return FakeJobService()

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[require_auth] = lambda: auth
    app.dependency_overrides[dependencies.get_optional_session] = _session
    app.dependency_overrides[dependencies.get_session] = _session
    app.dependency_overrides[dependencies.get_clustering_session] = _session
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder
    app.dependency_overrides[dependencies.get_cluster_service_builder_clustering] = cluster_builder
    app.dependency_overrides[dependencies.get_persisted_cluster_job_service_clustering] = job_service_dep

    try:
        with TestClient(app) as client:
            yield client, sf, tenant_id, slug
    finally:
        asyncio.run(engine.dispose())
        with suppress(OSError):
            os.unlink(path)


def _used(sf, slug: str) -> int:
    async def _read() -> int:
        async with sf() as s:
            row = await s.get(DemoInstance, slug)
            assert row is not None
            return int(row.recognition_used)

    return asyncio.run(_read())


def test_demo_quota_clustering_jobs_charges_one_unit():
    with _clustering_demo_client(recognition_quota=3) as (client, sf, tenant_id, slug):
        resp = client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": tenant_id, "mode": "sync"},
        )
        assert resp.status_code in (200, 202), resp.text
        assert _used(sf, slug) == 1


def test_demo_quota_recover_orphans_charges_one_unit():
    with _clustering_demo_client(recognition_quota=3) as (client, sf, tenant_id, slug):
        resp = client.post(
            "/recognition/clusters/recover-orphans",
            json={"tenant_id": tenant_id},
        )
        assert resp.status_code == 200, resp.text
        assert _used(sf, slug) == 1


def test_demo_quota_refresh_centroids_charges_one_unit(monkeypatch):
    import recognition.infrastructure.repositories.cluster_repository as repo_mod

    class _RepoFactory:
        def __init__(self, _session):
            pass

        async def refresh_centroids_view_concurrent(self):
            return repo_mod.MvRefreshOutcome.REFRESHED

    monkeypatch.setattr(repo_mod, "SqlAlchemyClusterRepository", _RepoFactory)

    with _clustering_demo_client(recognition_quota=3) as (client, sf, _tenant_id, slug):
        resp = client.post("/recognition/clusters/maintenance/refresh-centroids")
        assert resp.status_code == 202, resp.text
        assert _used(sf, slug) == 1


def test_demo_quota_clustering_routes_non_demo_key_unaffected():
    with _clustering_demo_client(recognition_quota=1, non_demo=True) as (client, sf, tenant_id, slug):
        r1 = client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": tenant_id, "mode": "sync"},
        )
        r2 = client.post(
            "/recognition/clusters/recover-orphans",
            json={"tenant_id": tenant_id},
        )
        assert r1.status_code in (200, 202), r1.text
        assert r2.status_code == 200, r2.text
        assert _used(sf, slug) == 0
