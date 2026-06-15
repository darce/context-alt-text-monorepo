"""Integration tests for async split endpoint behavior."""

from __future__ import annotations

import uuid

import pytest
from fastapi import Response

from db.models import IdentityClusteringJob
from db.models import MediaIdentity as MediaIdentityModel
from recognition.domain.cluster import IdentityCluster
from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http.routers.clusters_topology import split_cluster as split_cluster_endpoint
from recognition.interface_adapters.http.schemas.requests import SplitClusterRequest
from recognition.interface_adapters.http.schemas.responses import AsyncSplitClusterResponse


@pytest.mark.asyncio
async def test_async_split_returns_202_with_job_id(db_session, tenant) -> None:
    """Async split should return 202 Accepted with job_id."""
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
            media_id=1001,
            media_url="http://example.test/1001.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=embedding_a,
        ),
        MediaIdentityModel(
            tenant_id=tenant.id,
            media_id=1002,
            media_url="http://example.test/1002.jpg",
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
            label="Async Split",
            is_labeled=True,
            identity_count=len(identities),
            created_at=None,
        )
    )
    for identity in identities:
        await member_repo.add_member(cluster.id, identity_id=str(identity.id), similarity=0.9)
    await db_session.commit()

    request = SplitClusterRequest(
        tenant_id=str(tenant.id),
        n_clusters=2,
        mode="async",
    )
    response = Response()

    result = await split_cluster_endpoint(
        cluster_id=cluster.id,
        request=request,
        auth=None,
        session=db_session,
        response=response,
    )

    assert response.status_code == 202
    assert isinstance(result, AsyncSplitClusterResponse)
    assert result.job_id
    assert result.status == "pending"

    job = await db_session.get(IdentityClusteringJob, uuid.UUID(result.job_id))
    assert job is not None
    assert job.job_type == "split"
    assert job.payload.get("cluster_id") == cluster.id
