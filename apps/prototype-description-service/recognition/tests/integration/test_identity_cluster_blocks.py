"""Integration tests for identity-cluster block persistence and curation flow."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from db.models import IdentityClusterBlock, IdentityClusteringJob, Tenant
from db.models import MediaIdentity as MediaIdentityModel
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import SuggestionCreateData
from recognition.domain.suggestion import SuggestionStatus
from recognition.infrastructure.repositories import (
    SqlAlchemyClusterRepository,
    SqlAlchemyIdentityClusterBlockRepository,
    SqlAlchemyMemberRepository,
    SqlAlchemySuggestionRepository,
)
from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router


def _make_client(session) -> TestClient:
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_override():
        yield session

    app.dependency_overrides[dependencies.get_session] = _session_override
    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    return TestClient(app)


@pytest.mark.asyncio
async def test_block_repository_adds_and_removes_block(db_session, tenant: Tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    block_repo = SqlAlchemyIdentityClusterBlockRepository(db_session, tenant_id=str(tenant.id))

    embedding = [0.0] * 512
    embedding[0] = 1.0
    identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=701,
        media_url="http://example.test/701.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
    )
    db_session.add(identity)
    await db_session.flush()

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Blocked Cluster",
            is_labeled=True,
            identity_count=1,
            created_at=None,
        )
    )

    block = await block_repo.add_block(
        tenant_id=str(tenant.id),
        identity_id=str(identity.id),
        blocked_cluster_id=str(cluster.id),
        reason="manual_removal",
    )

    assert block.identity_id == str(identity.id)
    assert await block_repo.is_blocked(
        tenant_id=str(tenant.id),
        identity_id=str(identity.id),
        cluster_id=str(cluster.id),
    )

    blocks = await block_repo.get_blocks_for_identity(tenant_id=str(tenant.id), identity_id=str(identity.id))
    assert len(blocks) == 1
    assert blocks[0].blocked_cluster_id == str(cluster.id)

    removed = await block_repo.remove_block(
        tenant_id=str(tenant.id),
        identity_id=str(identity.id),
        blocked_cluster_id=str(cluster.id),
    )
    assert removed is True
    assert not await block_repo.is_blocked(
        tenant_id=str(tenant.id),
        identity_id=str(identity.id),
        cluster_id=str(cluster.id),
    )


@pytest.mark.asyncio
async def test_reassign_removal_creates_block_and_job(db_session, tenant: Tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    embedding = [0.0] * 512
    embedding[0] = 1.0
    identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=702,
        media_url="http://example.test/702.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
    )
    db_session.add(identity)
    await db_session.flush()

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Source Cluster",
            is_labeled=True,
            identity_count=1,
            created_at=None,
        )
    )
    await member_repo.add_member(cluster.id, identity_id=str(identity.id), similarity=0.9)
    await db_session.commit()

    client = _make_client(db_session)
    resp = client.post(
        "/recognition/clusters/reassign",
        json={
            "tenant_id": str(tenant.id),
            "identity_id": str(identity.id),
            "target_cluster_id": None,
            "block_from_cluster": True,
        },
    )
    assert resp.status_code == 200

    blocks = (await db_session.execute(select(IdentityClusterBlock))).scalars().all()
    assert len(blocks) == 1
    assert str(blocks[0].identity_id) == str(identity.id)
    assert str(blocks[0].blocked_cluster_id) == str(cluster.id)

    members = await member_repo.get_by_identity_id(str(identity.id))
    assert members == []

    jobs = (await db_session.execute(select(IdentityClusteringJob))).scalars().all()
    assert any(job.job_type == "curation" for job in jobs)


@pytest.mark.asyncio
async def test_reassign_removal_rejects_pending_suggestion(db_session, tenant: Tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    suggestion_repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))

    embedding = [0.0] * 512
    embedding[0] = 1.0
    identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=705,
        media_url="http://example.test/705.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
    )
    db_session.add(identity)
    await db_session.flush()

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Suggestion Source",
            is_labeled=True,
            identity_count=1,
            created_at=None,
        )
    )
    await member_repo.add_member(cluster.id, identity_id=str(identity.id), similarity=0.9)
    await db_session.commit()

    await suggestion_repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(identity.id),
            cluster_id=str(cluster.id),
            representative_similarity=0.72,
            member_similarity=0.72,
            confidence_score=0.72,
        ),
    )
    await db_session.commit()

    client = _make_client(db_session)
    resp = client.post(
        "/recognition/clusters/reassign",
        json={
            "tenant_id": str(tenant.id),
            "identity_id": str(identity.id),
            "target_cluster_id": None,
            "block_from_cluster": True,
        },
    )
    assert resp.status_code == 200

    # get_by_identity only returns pending suggestions, so rejected ones should NOT appear
    suggestions = await suggestion_repo.get_by_identity(str(tenant.id), str(identity.id))
    matching = [s for s in suggestions if s.cluster_id == str(cluster.id)]
    assert not matching, "Rejected suggestion should not appear in pending suggestions"
