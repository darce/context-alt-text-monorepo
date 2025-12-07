"""TDD-first tests for ClusterService merge/label/outlier operations (Phase 7.4)."""

from __future__ import annotations

import uuid

import pytest

from recognition.domain.cluster import IdentityCluster
from recognition.interface_adapters.http import dependencies


@pytest.mark.asyncio
async def test_merge_reassigns_members_and_deletes_source(db_session, tenant) -> None:
    """Merging should move members to target and remove the source cluster."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer._clusters
    member_repo = cluster_service.assignment_writer._members
    audit: list[tuple[str, str]] = []

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

    # Monkeypatch audit logging hook
    async def fake_audit(source_id: str, target_id: str) -> None:
        audit.append((source_id, target_id))

    import types

    cluster_service.log_merge_audit = types.MethodType(lambda self, s, t: fake_audit(s, t), cluster_service)

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
    # Audit entry recorded
    assert audit == [(source.id, target.id)]


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
