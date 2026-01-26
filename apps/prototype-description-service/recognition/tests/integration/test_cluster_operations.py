"""TDD-first tests for ClusterService merge/label/outlier operations (Phase 7.4)."""

from __future__ import annotations

import uuid

import pytest

from db.models import MediaIdentity as MediaIdentityModel
from recognition.domain.cluster import IdentityCluster
from recognition.infrastructure.repositories import SqlAlchemyIdentityClusterBlockRepository
from recognition.interface_adapters.http import dependencies


@pytest.mark.asyncio
async def test_merge_reassigns_members_and_deletes_source(db_session, tenant) -> None:
    """Merging should move members to target and remove the source cluster."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    target = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="target",
            is_labeled=False,
            identity_count=1,
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
            identity_count=1,
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
    cluster_repo = cluster_service.assignment_writer.cluster_repository

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )

    updated = await cluster_service.update_cluster(cluster.id, str(tenant.id), label="confirmed")

    assert updated is not None
    assert updated.label == "confirmed"
    assert updated.is_labeled is True
    assert updated.user_confirmed is True


@pytest.mark.asyncio
async def test_merge_recomputes_representatives(db_session, tenant) -> None:
    """Merge should recompute representatives based on merged membership."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    embedding_a = [0.0] * 512
    embedding_a[0] = 1.0
    embedding_b = [0.0] * 512
    embedding_b[1] = 1.0
    identity_a = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=401,
        media_url="http://example.test/401.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding_a,
    )
    identity_b = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=402,
        media_url="http://example.test/402.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding_b,
    )
    db_session.add_all([identity_a, identity_b])
    await db_session.flush()

    target = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="target",
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )
    await member_repo.add_member(target.id, identity_id=str(identity_a.id), similarity=0.92)
    source = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="source",
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )
    await member_repo.add_member(source.id, identity_id=str(identity_b.id), similarity=0.88)
    await db_session.commit()

    await cluster_service.merge_cluster(
        source_cluster_id=source.id,
        tenant_id=str(tenant.id),
        target_cluster_id=target.id,
        target_label="merged-target",
    )

    reps = await cluster_repo.get_all_representatives(target.id)
    members = await member_repo.get_by_cluster(target.id)
    assert len(members) == 2
    assert len(reps) == 2


@pytest.mark.asyncio
async def test_create_cluster_for_identity_creates_labeled_cluster_with_member_and_representative(
    db_session, tenant
) -> None:
    """Manual create should produce a labeled, confirmed singleton cluster with membership and representatives."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

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


@pytest.mark.asyncio
async def test_cluster_unclustered_identities_refreshes_centroids_between_chunks(
    db_session, tenant, monkeypatch
) -> None:
    """Chunked clustering should refresh centroids view so later chunks can use centroid discovery."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    assignment_writer = cluster_service.assignment_writer

    refresh_calls = {"count": 0}

    async def fake_refresh() -> None:
        refresh_calls["count"] += 1

    monkeypatch.setattr(assignment_writer, "refresh_centroids_view", fake_refresh, raising=True)

    identities: list[MediaIdentityModel] = []
    for idx in range(6):  # 2 chunks at cold start: 5 + 1
        embedding = [0.0] * 512
        embedding[idx % 512] = 1.0
        identities.append(
            MediaIdentityModel(
                tenant_id=tenant.id,
                media_id=300 + idx,
                media_url=f"http://example.test/{300 + idx}.jpg",
                bbox_x=0,
                bbox_y=0,
                bbox_width=1,
                bbox_height=1,
                confidence=0.99,
                embedding=embedding,
            )
        )
    db_session.add_all(identities)
    await db_session.commit()

    await cluster_service.cluster_unclustered_identities(str(tenant.id))

    # [Optimized] Sync refresh removed, so count should be 0.
    # The scheduled background refresh handles this now.
    assert refresh_calls["count"] == 0


@pytest.mark.asyncio
async def test_split_cluster_preserves_user_label_for_representative_group(db_session, tenant) -> None:
    """Split should keep the user label with the representative's group."""
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
            media_id=501,
            media_url="http://example.test/501.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=embedding_a,
        ),
        MediaIdentityModel(
            tenant_id=tenant.id,
            media_id=502,
            media_url="http://example.test/502.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=embedding_a,
        ),
        MediaIdentityModel(
            tenant_id=tenant.id,
            media_id=503,
            media_url="http://example.test/503.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=embedding_a,
        ),
    ]
    representative = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=504,
        media_url="http://example.test/504.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding_b,
    )
    db_session.add_all([*identities, representative])
    await db_session.flush()

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Alex Rivera",
            is_labeled=True,
            identity_count=4,
            representative_identity_id=str(representative.id),
            user_confirmed=True,
            created_at=None,
        )
    )

    for identity in [*identities, representative]:
        await member_repo.add_member(cluster.id, identity_id=str(identity.id), similarity=0.9)
    await db_session.commit()

    new_ids, counts = await cluster_service.split_cluster(cluster.id, n_clusters=2)

    assert len(new_ids) == 1
    assert counts == [1]

    new_cluster = await cluster_repo.get_by_id(new_ids[0])
    original_cluster = await cluster_repo.get_by_id(cluster.id)

    assert new_cluster is not None
    assert original_cluster is not None
    assert new_cluster.label == "Alex Rivera"
    assert original_cluster.label == "Alex Rivera (split 1)"

    new_members = await member_repo.get_by_cluster(new_ids[0])
    assert [member.identity_id for member in new_members] == [str(representative.id)]


@pytest.mark.asyncio
async def test_split_cluster_keeps_label_on_anchor_group(db_session, tenant) -> None:
    """Split should keep the user label on the anchor identity's group."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    embedding_a = [0.0] * 512
    embedding_a[0] = 1.0
    embedding_b = [0.0] * 512
    embedding_b[1] = 1.0

    anchor_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=601,
        media_url="http://example.test/601.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding_a,
    )
    group_a_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=602,
        media_url="http://example.test/602.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding_a,
    )
    representative = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=603,
        media_url="http://example.test/603.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding_b,
    )
    group_b_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=604,
        media_url="http://example.test/604.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding_b,
    )
    db_session.add_all([anchor_identity, group_a_identity, representative, group_b_identity])
    await db_session.flush()

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Casey Jordan",
            is_labeled=True,
            identity_count=4,
            representative_identity_id=str(representative.id),
            user_confirmed=True,
            created_at=None,
        )
    )
    for identity in [anchor_identity, group_a_identity, representative, group_b_identity]:
        await member_repo.add_member(cluster.id, identity_id=str(identity.id), similarity=0.9)
    await db_session.commit()

    new_ids, _counts = await cluster_service.split_cluster(
        cluster.id,
        n_clusters=2,
        anchor_identity_id=str(anchor_identity.id),
    )

    assert len(new_ids) == 1
    anchor_memberships = await member_repo.get_by_identity_id(str(anchor_identity.id))
    assert anchor_memberships
    anchor_cluster_id = anchor_memberships[0].cluster_id
    anchor_cluster = await cluster_repo.get_by_id(anchor_cluster_id)

    assert anchor_cluster is not None
    assert anchor_cluster.label == "Casey Jordan"


@pytest.mark.asyncio
async def test_split_cluster_forces_two_groups_with_anchor(db_session, tenant) -> None:
    """Split should force two groups when an anchor is provided and faces are similar."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    embedding = [0.0] * 512
    embedding[0] = 1.0

    anchor_identity = MediaIdentityModel(
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
    other_identity = MediaIdentityModel(
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
    db_session.add_all([anchor_identity, other_identity])
    await db_session.flush()

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Jamie Lee",
            is_labeled=True,
            identity_count=2,
            representative_identity_id=str(anchor_identity.id),
            user_confirmed=True,
            created_at=None,
        )
    )
    await member_repo.add_member(cluster.id, identity_id=str(anchor_identity.id), similarity=0.9)
    await member_repo.add_member(cluster.id, identity_id=str(other_identity.id), similarity=0.9)
    await db_session.commit()

    new_ids, counts = await cluster_service.split_cluster(
        cluster.id,
        n_clusters=2,
        anchor_identity_id=str(anchor_identity.id),
    )

    assert len(new_ids) == 1
    assert counts == [1]

    anchor_membership = await member_repo.get_by_identity_id(str(anchor_identity.id))
    other_membership = await member_repo.get_by_identity_id(str(other_identity.id))
    assert anchor_membership and other_membership
    assert anchor_membership[0].cluster_id != other_membership[0].cluster_id

    anchor_cluster = await cluster_repo.get_by_id(anchor_membership[0].cluster_id)
    assert anchor_cluster is not None
    assert anchor_cluster.label == "Jamie Lee"


@pytest.mark.asyncio
async def test_split_cluster_blocks_moved_identities(db_session, tenant) -> None:
    """Split should block moved identities from rejoining the original cluster."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository
    block_repo = SqlAlchemyIdentityClusterBlockRepository(db_session, tenant_id=str(tenant.id))

    embedding = [0.0] * 512
    embedding[0] = 1.0

    anchor_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=703,
        media_url="http://example.test/703.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
    )
    moved_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=704,
        media_url="http://example.test/704.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
    )
    db_session.add_all([anchor_identity, moved_identity])
    await db_session.flush()

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Taylor Quinn",
            is_labeled=True,
            identity_count=2,
            representative_identity_id=str(anchor_identity.id),
            user_confirmed=True,
            created_at=None,
        )
    )
    await member_repo.add_member(cluster.id, identity_id=str(anchor_identity.id), similarity=0.9)
    await member_repo.add_member(cluster.id, identity_id=str(moved_identity.id), similarity=0.9)
    await db_session.commit()

    new_ids, _counts = await cluster_service.split_cluster(
        cluster.id,
        n_clusters=2,
        anchor_identity_id=str(anchor_identity.id),
    )

    assert len(new_ids) == 1
    new_cluster_id = new_ids[0]

    anchor_membership = await member_repo.get_by_identity_id(str(anchor_identity.id))
    moved_membership = await member_repo.get_by_identity_id(str(moved_identity.id))
    assert anchor_membership and moved_membership

    anchor_cluster_id = anchor_membership[0].cluster_id
    assert await block_repo.is_blocked(
        tenant_id=str(tenant.id),
        identity_id=str(moved_identity.id),
        cluster_id=anchor_cluster_id,
    )
    assert await block_repo.is_blocked(
        tenant_id=str(tenant.id),
        identity_id=str(anchor_identity.id),
        cluster_id=new_cluster_id,
    )


@pytest.mark.asyncio
async def test_pin_representative(db_session, tenant) -> None:
    """Pinning a representative should update the is_user_selected flag."""
    from datetime import UTC, datetime

    from recognition.domain.representative import ClusterRepresentative

    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Pin Test",
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )

    rep_id = str(uuid.uuid4())

    # Must create identity first to satisfy FK
    embedding = [0.1] * 512
    identity_model = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=999,
        media_url="http://example.test/999.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
    )
    db_session.add(identity_model)
    await db_session.flush()
    identity_id = str(identity_model.id)

    rep = ClusterRepresentative(
        id=rep_id,
        cluster_id=cluster.id,
        identity_id=identity_id,
        embedding=[0.1] * 512,
        created_at=datetime.now(tz=UTC),
        tenant_id=str(tenant.id),
        is_user_selected=False,
    )
    await cluster_repo.add_representative(rep)

    # 1. Pin it
    await cluster_repo.mark_representative_user_selected(rep_id, is_selected=True)

    # 2. Verify
    reps = await cluster_repo.get_all_representatives(cluster.id)
    assert len(reps) == 1
    assert reps[0].id == rep_id
    assert reps[0].is_user_selected is True

    # 3. Unpin it
    await cluster_repo.mark_representative_user_selected(rep_id, is_selected=False)

    # 4. Verify
    reps = await cluster_repo.get_all_representatives(cluster.id)
    assert reps[0].is_user_selected is False
