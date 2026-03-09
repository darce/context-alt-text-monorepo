"""Phase 7 integration tests to drive real pipeline wiring (analyze + clustering)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import cast

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from db.models import (
    IdentityCluster,
    IdentityClusteringJob,
    IdentityMember,
    IdentityScanJob,
    MediaIdentity,
    RecognitionRun,
    Tenant,
)
from recognition.application.discovery.graph.algorithm import GraphAlgorithm
from recognition.application.embedding.detector import StubFaceDetector
from recognition.application.embedding.generator import StubEmbeddingGenerator
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.scan.service import ScanService
from recognition.domain.identity import MediaIdentity as DomainMediaIdentity
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router


def _make_client(session, tenant: Tenant) -> TestClient:
    """Create a test client with session override using stub detector/generator."""
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_override():
        yield session

    def _scan_service_builder():
        async def _builder(tenant_id: str) -> ScanService:
            return ScanService(
                session=session,
                detector=StubFaceDetector(),
                generator=StubEmbeddingGenerator(),
            )

        return _builder

    async def _scan_queue_service_override():
        return ScanQueueService(SqlAlchemyScanQueueRepository(session))

    app.dependency_overrides[dependencies.get_session] = _session_override
    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.get_scan_service_builder] = _scan_service_builder
    app.dependency_overrides[dependencies.get_scan_queue_service] = _scan_queue_service_override
    return TestClient(app)


class DeterministicGraphAlgorithm(GraphAlgorithm):
    """Assign all embeddings to a single cluster to make outcomes deterministic."""

    def cluster(
        self,
        embeddings: Sequence[np.ndarray],
        identities: Sequence[DomainMediaIdentity] | None = None,
    ) -> list[int]:
        return [0] * len(embeddings)


@pytest.mark.asyncio
async def test_analyze_persists_media_identities(db_session, tenant) -> None:
    """POST /analyze should persist detected identities for the tenant."""
    client = _make_client(db_session, tenant)
    media_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    resp = client.post("/recognition/analyze", json={"media_ids": media_ids, "tenant_id": str(tenant.id)})

    assert resp.status_code == 202
    rows = (await db_session.execute(select(MediaIdentity))).scalars().all()
    assert len(rows) == len(media_ids)
    # Verify all identities belong to this tenant (media_id values come from hash of UUID)
    assert all(str(row.tenant_id) == str(tenant.id) for row in rows)
    assert all(isinstance(row.media_id, int) for row in rows)


@pytest.mark.asyncio
async def test_clustering_job_creates_clusters_from_unclustered_identities(db_session, tenant) -> None:
    """Clustering job should create clusters and members for unclustered identities."""
    # Seed unclustered identities
    embedding = [0.0] * 512
    embedding[0] = 1.0
    identities = [
        MediaIdentity(
            tenant_id=tenant.id,
            media_id=101,
            media_url="http://example.test/101.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=embedding,
        ),
        MediaIdentity(
            tenant_id=tenant.id,
            media_id=102,
            media_url="http://example.test/102.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.98,
            embedding=embedding,
        ),
    ]
    db_session.add_all(identities)
    await db_session.commit()

    def _cluster_service_builder_override():
        async def _builder(tenant_id: str):
            cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=tenant_id)
            cluster_service.graph_discovery.set_algorithm(DeterministicGraphAlgorithm())
            return cluster_service

        return _builder

    client = _make_client(db_session, tenant)
    app = cast(FastAPI, client.app)
    app.dependency_overrides[dependencies.get_cluster_service_builder] = _cluster_service_builder_override
    resp = client.post("/recognition/clustering/jobs", json={"tenant_id": str(tenant.id), "mode": "sync"})

    assert resp.status_code == 202
    payload = resp.json()
    assert payload["clusters_created"] == 1
    assert payload["progress"]["completed"] == 2
    assert payload["progress"]["total"] == 2
    clusters = (await db_session.execute(select(IdentityCluster))).scalars().all()
    members = (await db_session.execute(select(IdentityMember))).scalars().all()
    assert len(clusters) == 1
    assert len(members) == len(identities)
    assert {m.identity_id for m in members} == {identities[0].id, identities[1].id}


@pytest.mark.asyncio
async def test_analyze_creates_scan_job_row(db_session, tenant) -> None:
    """Analyze should create a scan job row with totals."""
    client = _make_client(db_session, tenant)
    media_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    resp = client.post(
        "/recognition/analyze",
        json={"media_ids": media_ids, "tenant_id": str(tenant.id)},
    )

    assert resp.status_code == 202
    job_rows = (await db_session.execute(select(IdentityScanJob))).scalars().all()
    assert len(job_rows) == 1
    job = job_rows[0]
    assert str(job.tenant_id) == str(tenant.id)
    assert job.total_media == 2
    assert job.processed_media == 2
    # media_ids are derived from hash of input UUIDs, not hardcoded values
    assert len(job.media_ids) == 2
    assert all(isinstance(mid, int) for mid in job.media_ids)
    assert job.status in {"completed", "running"}


@pytest.mark.asyncio
async def test_clustering_job_persists_job_row(db_session, tenant) -> None:
    """Clustering job should create a job record with counts."""
    identities = [
        MediaIdentity(
            tenant_id=tenant.id,
            media_id=201,
            media_url="http://example.test/201.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.97,
            embedding=[0.2] * 512,
        ),
        MediaIdentity(
            tenant_id=tenant.id,
            media_id=202,
            media_url="http://example.test/202.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.96,
            embedding=[0.3] * 512,
        ),
    ]
    db_session.add_all(identities)
    await db_session.commit()

    client = _make_client(db_session, tenant)
    resp = client.post("/recognition/clustering/jobs", json={"tenant_id": str(tenant.id), "mode": "sync"})
    assert resp.status_code == 202

    job_rows = (await db_session.execute(select(IdentityClusteringJob))).scalars().all()
    assert len(job_rows) == 1
    job = job_rows[0]
    assert str(job.tenant_id) == str(tenant.id)
    assert job.status in {"completed", "running"}
    assert job.total_identities == len(identities)
    assert job.processed_identities == len(identities)

    runs = (await db_session.execute(select(RecognitionRun))).scalars().all()
    assert len(runs) == 1
    assert runs[0].clustering_job_id == job.id
    assert runs[0].status in {"completed", "running"}
