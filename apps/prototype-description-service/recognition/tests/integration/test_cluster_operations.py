"""TDD-first tests for ClusterService merge/label/outlier operations (Phase 7.4)."""

from __future__ import annotations

import uuid

import pytest

from db.models import MediaIdentity as MediaIdentityModel
from recognition.domain.cluster import IdentityCluster
from recognition.interface_adapters.http import dependencies


@pytest.mark.asyncio
async def test_merge_reassigns_members_and_deletes_source(db_session, tenant) -> None:
    """Merging should move members to target and remove the source cluster."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer._clusters
    member_repo = cluster_service.assignment_writer._members

    target = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="target",
            is_labeled=False,
            member_count=1,
            created_at=None,
        )
    )
    await member_repo.add_member(target.id, identity_id=str(uuid.uuid4()), similarity=0.92)

    source = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="source",
            is_labeled=False,
            member_count=1,
            created_at=None,
        )
    )
    await member_repo.add_member(source.id, identity_id=str(uuid.uuid4()), similarity=0.9)
    await db_session.commit()

    # Note: audit logging is handled internally by merge_cluster, not via a public hook

    result = await cluster_service.merge_cluster(
        source_cluster_id=source.id,
        tenant_id=str(tenant.id),
        target_cluster_id=target.id,
        target_label="merged-target",
    )

    members_after = await member_repo.get_by_cluster(target.id)
    source_after = await cluster_repo.get_by_id(source.id)
    assert len(members_after) == 2
    assert source_after is None

    # Label should reflect merge target
    assert result is not None
    assert result.id == target.id
    assert result.label == "merged-target"


@pytest.mark.asyncio
async def test_label_update_sets_confirmation_flags(db_session, tenant) -> None:
    """Updating label should mark cluster as labeled/confirmed."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer._clusters

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            member_count=0,
            created_at=None,
        )
    )

    updated = await cluster_service.update_cluster(cluster.id, str(tenant.id), label="confirmed")

    assert updated is not None
    assert updated.label == "confirmed"
    assert updated.is_labeled is True
    assert updated.user_confirmed is True


@pytest.mark.asyncio
async def test_merge_recomputes_representatives_and_centroid(db_session, tenant, monkeypatch) -> None:
    """Merge should trigger representative and centroid recomputation hooks."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    assignment_writer = cluster_service.assignment_writer
    cluster_repo = assignment_writer._clusters
    member_repo = assignment_writer._members

    target = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="target",
            is_labeled=False,
            member_count=1,
            created_at=None,
        )
    )
    source = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="source",
            is_labeled=False,
            member_count=1,
            created_at=None,
        )
    )
    await member_repo.add_member(source.id, identity_id=str(uuid.uuid4()), similarity=0.88)
    await db_session.commit()

    recompute_calls = {"reps": 0, "centroid": 0}

    async def fake_recompute_reps(cluster_id: str):
        recompute_calls["reps"] += 1

    async def fake_recompute_centroid(cluster_id: str):
        recompute_calls["centroid"] += 1

    monkeypatch.setattr(assignment_writer, "recompute_representatives", fake_recompute_reps, raising=False)
    monkeypatch.setattr(assignment_writer, "recompute_centroid", fake_recompute_centroid, raising=False)

    await cluster_service.merge_cluster(
        source_cluster_id=source.id,
        tenant_id=str(tenant.id),
        target_cluster_id=target.id,
        target_label="merged-target",
    )

    assert recompute_calls["reps"] >= 1
    assert recompute_calls["centroid"] >= 1


@pytest.mark.asyncio
async def test_create_cluster_for_identity_creates_labeled_cluster_with_member_and_representative(
    db_session, tenant
) -> None:
    """Manual create should produce a labeled, confirmed singleton cluster with membership and representatives."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer._clusters
    member_repo = cluster_service.assignment_writer._members

    embedding = [0.0] * 512
    embedding[0] = 1.0
    identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=201,
        media_url="http://example.test/201.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
    )
    db_session.add(identity)
    await db_session.flush()

    cluster = await cluster_service.create_cluster_for_identity(
        identity_id=str(identity.id),
        label="Manual Person",
        tenant_id=str(tenant.id),
    )

    assert cluster.id is not None
    assert cluster.label == "Manual Person"
    assert cluster.is_labeled is True
    assert cluster.user_confirmed is True
    assert cluster.representative_identity_id == str(identity.id)

    members = await member_repo.get_by_cluster(cluster.id)
    assert len(members) == 1
    assert members[0].identity_id == str(identity.id)

    assert await cluster_repo.get_representative_count(cluster.id) >= 1
