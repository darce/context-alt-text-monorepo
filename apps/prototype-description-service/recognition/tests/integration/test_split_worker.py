"""Integration tests for split job execution in the worker."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from db.models import IdentityClusteringJob
from db.models import MediaIdentity as MediaIdentityModel
from recognition.domain.cluster import IdentityCluster
from recognition.interface_adapters.http import dependencies
from recognition.worker.scan_worker import ScanWorker, ScanWorkerConfig


@pytest.mark.asyncio
async def test_worker_executes_split_job(db_session, tenant) -> None:
    """Worker should execute split jobs and update status."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    embedding_a = [0.0] * 512
    embedding_a[0] = 1.0
    embedding_b = [0.0] * 512
    embedding_b[1] = 1.0

    identities = [
        MediaIdentityModel(
            tenant_id=tenant.id,
            media_id=2001,
            media_url="http://example.test/2001.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=embedding_a,
        ),
        MediaIdentityModel(
            tenant_id=tenant.id,
            media_id=2002,
            media_url="http://example.test/2002.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=embedding_a,
        ),
        MediaIdentityModel(
            tenant_id=tenant.id,
            media_id=2003,
            media_url="http://example.test/2003.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=embedding_b,
        ),
        MediaIdentityModel(
            tenant_id=tenant.id,
            media_id=2004,
            media_url="http://example.test/2004.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=embedding_b,
        ),
    ]
    db_session.add_all(identities)
    await db_session.flush()

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Worker Split",
            is_labeled=True,
            identity_count=len(identities),
            created_at=None,
        )
    )
    for identity in identities:
        await member_repo.add_member(cluster.id, identity_id=str(identity.id), similarity=0.9)
    await db_session.commit()

    job = IdentityClusteringJob(
        tenant_id=tenant.id,
        job_type="split",
        status="pending",
        progress=0.0,
        total_identities=0,
        processed_identities=0,
        payload={
            "cluster_id": cluster.id,
            "n_clusters": 2,
            "anchor_identity_id": str(identities[0].id),
        },
    )
    db_session.add(job)
    await db_session.commit()

    worker = ScanWorker(ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:"))
    processed = await worker._process_pending_clustering_jobs(session=db_session, now=datetime.now(tz=UTC))
    assert processed is True
    await db_session.commit()

    refreshed = await db_session.get(IdentityClusteringJob, job.id)
    assert refreshed is not None
    assert refreshed.status == "completed"
    assert refreshed.progress == 1.0

    clusters = await cluster_repo.get_by_tenant(str(tenant.id), limit=50)
    assert len(clusters) > 1
