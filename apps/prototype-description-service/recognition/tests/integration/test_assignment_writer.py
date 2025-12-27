"""Persistence tests for AssignmentWriter orchestration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import numpy as np
import pytest

from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import MemberData
from recognition.domain.representative import ClusterRepresentative
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemyMemberRepository


def make_identity(tenant_id: str) -> MediaIdentity:
    """Create a synthetic identity with a deterministic 512D embedding."""
    embedding = np.zeros(512, dtype=np.float32)
    embedding[0] = 1.0
    return MediaIdentity(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        media_id=str(uuid.uuid4()),
        embedding=embedding,
        confidence=0.95,
        bbox_width=10,
        bbox_height=10,
    )


def make_candidate(identity: MediaIdentity, cluster_id: str, similarity: float) -> AssignmentCandidate:
    """Helper to build a candidate with a given similarity."""
    return AssignmentCandidate(
        identity=identity,
        identity_vector=identity.extract_face_embedding(),
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=similarity,
    )


def _make_media_identity_model(
    tenant_id: str,
    embedding: np.ndarray,
    *,
    confidence: float = 0.95,
    media_id: int = 1,
) -> MediaIdentityModel:
    tenant_uuid = uuid.UUID(tenant_id)
    identity_id = uuid.uuid4()
    return MediaIdentityModel(
        id=identity_id,
        tenant_id=tenant_uuid,
        media_id=media_id,
        media_url="http://example.test/media.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=confidence,
        embedding=[float(x) for x in embedding.tolist()],
        created_at=datetime.now(tz=UTC),
    )


@pytest.mark.asyncio
async def test_persist_assignment_adds_member_and_updates_count(db_session, tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo)

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

    identity = make_identity(str(tenant.id))
    candidate = make_candidate(identity, cluster.id, similarity=0.91)
    decision = AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=[],
        checks_failed=[],
    )

    await writer.persist_assignment(decision)

    updated_cluster = await cluster_repo.get_by_id(cluster.id)
    assert updated_cluster is not None
    assert updated_cluster.identity_count == 1

    members = await member_repo.get_by_cluster(cluster.id)
    assert len(members) == 1
    assert members[0].identity_id == identity.id
    assert members[0].similarity == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_persist_assignment_rejects_non_accept(db_session, tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo)

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

    identity = make_identity(str(tenant.id))
    candidate = make_candidate(identity, cluster.id, similarity=0.5)
    decision = AssignmentDecision(
        outcome=AssignmentOutcome.SUGGEST,
        candidate=candidate,
        checks_passed=[],
        checks_failed=[],
    )

    with pytest.raises(ValueError):
        await writer.persist_assignment(decision)


@pytest.mark.asyncio
async def test_persist_new_cluster_creates_members(db_session, tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo)

    identities = [make_identity(str(tenant.id)), make_identity(str(tenant.id))]
    similarities = [0.93, 0.94]

    cluster = await writer.persist_new_cluster(
        tenant_id=str(tenant.id),
        identities=identities,
        similarities=similarities,
        algorithm="graph",
    )

    assert cluster.id is not None
    assert cluster.identity_count == len(identities)

    members = await member_repo.get_by_cluster(cluster.id)
    assert len(members) == 2
    assert {m.identity_id for m in members} == {i.id for i in identities}


@pytest.mark.asyncio
async def test_persist_new_cluster_creates_representatives(db_session, tenant) -> None:
    """persist_new_cluster should create representatives from highest-confidence identities."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    settings = ClusteringSettings()
    writer = AssignmentWriter(settings, cluster_repo, member_repo)

    # Create identities with varying confidence
    identities = [make_identity(str(tenant.id)) for _ in range(3)]
    identities[0].confidence = 0.99  # Highest
    identities[1].confidence = 0.95
    identities[2].confidence = 0.90  # Lowest
    similarities = [0.93, 0.94, 0.91]

    cluster = await writer.persist_new_cluster(
        tenant_id=str(tenant.id),
        identities=identities,
        similarities=similarities,
        algorithm="graph",
    )

    assert cluster.id is not None

    # Verify representatives were created
    reps = await cluster_repo.get_all_representatives(cluster.id)
    assert len(reps) > 0, "No representatives created for new cluster"
    # Should have up to max_representatives_per_cluster reps
    expected_num_reps = min(settings.max_representatives_per_cluster, len(identities))
    assert len(reps) == expected_num_reps


@pytest.mark.asyncio
async def test_update_cluster_metadata_updates_label_and_representative(db_session, tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo)

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

    representative_id = str(uuid.uuid4())
    updated = await writer.update_cluster_metadata(cluster.id, label="Confirmed", representative_id=representative_id)

    assert updated.label == "Confirmed"
    assert updated.is_labeled is True
    assert updated.representative_identity_id == representative_id


@pytest.mark.asyncio
async def test_recompute_representatives_clears_and_rebuilds(db_session, tenant) -> None:
    """recompute_representatives should clear old reps and rebuild using FPS diversity."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    settings = ClusteringSettings(max_representatives_per_cluster=2)
    writer = AssignmentWriter(settings, cluster_repo, member_repo)

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster",
            is_labeled=False,
            identity_count=3,
            created_at=datetime.now(tz=UTC),
        )
    )

    # Members: A (high conf), B (similar to A, high conf), C (orthogonal, low conf).
    emb_a = np.zeros(512, dtype=np.float32)
    emb_a[0] = 1.0
    emb_b = np.zeros(512, dtype=np.float32)
    emb_b[0] = 0.99
    emb_b[1] = 0.1
    emb_b /= np.linalg.norm(emb_b)
    emb_c = np.zeros(512, dtype=np.float32)
    emb_c[1] = 1.0

    a = _make_media_identity_model(str(tenant.id), emb_a, confidence=0.99, media_id=101)
    b = _make_media_identity_model(str(tenant.id), emb_b, confidence=0.98, media_id=102)
    c = _make_media_identity_model(str(tenant.id), emb_c, confidence=0.50, media_id=103)
    db_session.add_all([a, b, c])
    await db_session.flush()

    await member_repo.add_member(cluster.id, identity_id=str(a.id), similarity=0.9)
    await member_repo.add_member(cluster.id, identity_id=str(b.id), similarity=0.9)
    await member_repo.add_member(cluster.id, identity_id=str(c.id), similarity=0.9)

    # Add a stale representative that isn't a member.
    old_embedding = np.zeros(512, dtype=np.float32)
    old_embedding[2] = 1.0
    stale = _make_media_identity_model(str(tenant.id), old_embedding, confidence=0.9, media_id=999)
    db_session.add(stale)
    await db_session.flush()

    cluster.representative_identity_id = str(stale.id)
    await cluster_repo.update(cluster)
    await cluster_repo.add_representative(
        # Using the stale identity ensures we can detect that reps were cleared.
        # The embedding is intentionally distinct from A/B/C.
        # id is generated by the repo table default, but the domain object requires one.
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=cluster.id,
            identity_id=str(stale.id),
            embedding=old_embedding,
            created_at=datetime.now(tz=UTC),
            tenant_id=str(tenant.id),
        )
    )

    assert await cluster_repo.get_representative_count(cluster.id) == 1

    await writer.recompute_representatives(cluster.id)

    # Reps rebuilt to max (2) and stale rep removed.
    reps = await cluster_repo.get_all_representatives(cluster.id)
    assert len(reps) == 2
    # reps are ClusterRepresentative objects, not arrays. Extract embedding.
    rep_embeddings = [r.embedding for r in reps]
    assert not any(np.allclose(rep_emb, old_embedding) for rep_emb in rep_embeddings)

    # FPS should pick A (highest conf) and C (most diverse), not B (similar).
    assert any(np.allclose(rep_emb, emb_a) for rep_emb in rep_embeddings)
    assert any(np.allclose(rep_emb, emb_c) for rep_emb in rep_embeddings)

    updated_cluster = await cluster_repo.get_by_id(cluster.id)
    assert updated_cluster is not None
    assert updated_cluster.representative_identity_id == str(a.id)


@pytest.mark.asyncio
async def test_should_not_upgrade_user_selected_representative(db_session, tenant) -> None:
    """_should_add_representative should return False if trying to upgrade a user-selected rep."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    # Note: member_repo needs tenant_id for its internal logic
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    settings = ClusteringSettings(pose_bucket_size=10.0)
    writer = AssignmentWriter(settings, cluster_repo, member_repo)

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Protected Cluster",
            is_labeled=False,
            identity_count=1,
            created_at=datetime.now(tz=UTC),
        )
    )

    # 1. Add a user-selected representative
    emb_a = np.zeros(512, dtype=np.float32)
    emb_a[0] = 1.0

    # We must persist the identity model first to satisfy FK constraints
    identity_model_a = _make_media_identity_model(str(tenant.id), emb_a, confidence=0.5, media_id=201)
    db_session.add(identity_model_a)
    await db_session.flush()

    rep_a = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        identity_id=str(identity_model_a.id),
        embedding=emb_a,
        created_at=datetime.now(tz=UTC),
        tenant_id=str(tenant.id),
        quality_score=0.5,  # Moderate quality
        is_user_selected=True,
        pose_pitch=0.0,
        pose_yaw=0.0,
    )
    await cluster_repo.add_representative(rep_a)

    # 2. Try to assign a higher-quality identity in the same pose bucket
    emb_b = np.copy(emb_a)
    emb_b[1] = 0.05
    emb_b /= np.linalg.norm(emb_b)

    identity_b = make_identity(str(tenant.id))
    identity_b.confidence = 0.99  # Higher quality
    identity_b.pose_pitch = 2.0  # Same bucket (bucket_size=10)
    identity_b.pose_yaw = 2.0
    identity_b.bbox_width = 100
    identity_b.bbox_height = 100  # Large face = high quality
    identity_b.embedding = emb_b

    candidate = AssignmentCandidate(
        identity=identity_b,
        identity_vector=identity_b.extract_face_embedding(),
        cluster_id=cluster.id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.99,
    )
    decision = AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=[],
        checks_failed=[],
    )

    should_add = await writer._should_add_representative(decision)
    assert should_add is False, "Should not upgrade user-selected representative"


@pytest.mark.asyncio
async def test_recompute_representatives_preserves_pinned_and_best_quality(db_session, tenant) -> None:
    """recompute_representatives should keep pinned reps and best-per-bucket reps."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    # Bucket size 10 means 0-10, 10-20, etc. are different buckets
    settings = ClusteringSettings(max_representatives_per_cluster=3, pose_bucket_size=10.0)
    writer = AssignmentWriter(settings, cluster_repo, member_repo)

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Recompute test",
            is_labeled=False,
            identity_count=4,
            created_at=datetime.now(tz=UTC),
        )
    )

    # Setup identities with distinct embeddings
    def get_emb(val: float):
        e = np.zeros(512, dtype=np.float32)
        e[0] = val
        e[1] = 1.0 - val
        return e / np.linalg.norm(e)

    # A: Bucket (0,0), Quality 0.4, PINNED
    a = _make_media_identity_model(str(tenant.id), get_emb(0.1), confidence=0.4, media_id=301)
    a.pose_pitch, a.pose_yaw = 0.0, 0.0
    # B: Bucket (0,0), Quality 0.9 (Better than A)
    b = _make_media_identity_model(str(tenant.id), get_emb(0.2), confidence=0.9, media_id=302)
    b.pose_pitch, b.pose_yaw = 2.0, 2.0
    # C: Bucket (2,2), Quality 0.6
    c = _make_media_identity_model(str(tenant.id), get_emb(0.8), confidence=0.6, media_id=303)
    c.pose_pitch, c.pose_yaw = 20.0, 20.0
    # D: Bucket (2,2), Quality 0.8 (Better than C)
    d = _make_media_identity_model(str(tenant.id), get_emb(0.9), confidence=0.8, media_id=304)
    d.pose_pitch, d.pose_yaw = 22.0, 22.0

    db_session.add_all([a, b, c, d])
    await db_session.flush()

    for identity in [a, b, c, d]:
        await member_repo.add_member(cluster.id, str(identity.id), 0.9)

    # Create 4 representatives (normally we try to keep 3)
    # This simulates a state where we have redundant or low-quality reps (e.g. after a merge)
    rep_a = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        identity_id=str(a.id),
        embedding=a.embedding,
        created_at=datetime.now(tz=UTC),
        tenant_id=str(tenant.id),
        quality_score=0.4,
        is_user_selected=True,
        pose_pitch=0.0,
        pose_yaw=0.0,
    )
    rep_b = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        identity_id=str(b.id),
        embedding=b.embedding,
        created_at=datetime.now(tz=UTC),
        tenant_id=str(tenant.id),
        quality_score=0.9,
        is_user_selected=False,
        pose_pitch=2.0,
        pose_yaw=2.0,
    )
    rep_c = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        identity_id=str(c.id),
        embedding=c.embedding,
        created_at=datetime.now(tz=UTC),
        tenant_id=str(tenant.id),
        quality_score=0.6,
        is_user_selected=False,
        pose_pitch=20.0,
        pose_yaw=20.0,
    )
    rep_d = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        identity_id=str(d.id),
        embedding=d.embedding,
        created_at=datetime.now(tz=UTC),
        tenant_id=str(tenant.id),
        quality_score=0.8,
        is_user_selected=False,
        pose_pitch=22.0,
        pose_yaw=22.0,
    )
    await cluster_repo.add_representative(rep_a)
    await cluster_repo.add_representative(rep_b)
    await cluster_repo.add_representative(rep_c)
    await cluster_repo.add_representative(rep_d)

    # 3. Recompute
    await writer.recompute_representatives(cluster.id)

    # 4. Verify
    reps = await cluster_repo.get_all_representatives(cluster.id)
    rep_ids = {r.identity_id: r.id for r in reps}

    id_map = {
        "A (pinned)": str(a.id),
        "B (best-0,0)": str(b.id),
        "C (worst-2,2)": str(c.id),
        "D (best-2,2)": str(d.id),
    }

    print(f"DEBUG: Found identity_ids in reps: {list(rep_ids.keys())}")
    print(f"DEBUG: Target map: {id_map}")

    # A must be preserved because it's pinned
    assert id_map["A (pinned)"] in rep_ids, f"Pinned representative A missing. Found: {rep_ids}"
    # B should be preserved because it's best in bucket (0,0)
    assert id_map["B (best-0,0)"] in rep_ids, f"Best-quality rep B missing. Found: {rep_ids}"
    # D should be picked because it's higher quality than C in Bucket (2,2)
    assert id_map["D (best-2,2)"] in rep_ids, f"Best-quality rep D missing. Found: {rep_ids}"
    # C should be gone
    assert id_map["C (worst-2,2)"] not in rep_ids, f"Lower quality unpinned rep C should be dropped. Found: {rep_ids}"

    assert len(reps) == 3, f"Expected 3 reps (limit), got {len(reps)}. Found: {rep_ids}"


@pytest.mark.asyncio
async def test_provisional_representative_lifecycle(db_session, tenant) -> None:
    """Newly added reps should be provisional in batch_mode and confirmable."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo)

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Provisional test",
            is_labeled=False,
            identity_count=0,
            created_at=datetime.now(tz=UTC),
        )
    )

    # 1. Persist with batch_mode=True
    identity = make_identity(str(tenant.id))
    # Must persist identity model first
    model = _make_media_identity_model(str(tenant.id), identity.embedding)
    db_session.add(model)
    await db_session.flush()
    identity.id = str(model.id)

    candidate = make_candidate(identity, cluster.id, similarity=0.95)
    decision = AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=[],
        checks_failed=[],
    )

    await writer.persist_assignment(decision, batch_mode=True)

    # 2. Verify it is provisional
    reps = await cluster_repo.get_all_representatives(cluster.id)
    assert len(reps) == 1
    assert reps[0].is_provisional is True, "Representative should be provisional in batch mode"

    # 3. Confirm all for tenant
    confirmed = await cluster_repo.confirm_all_provisional_reps(str(tenant.id))
    assert confirmed == 1

    # 4. Verify no longer provisional
    reps = await cluster_repo.get_all_representatives(cluster.id)
    assert reps[0].is_provisional is False, "Representative should be confirmed"

    # 5. Test cleanup
    # Add another one and mark it provisional manually for cleanup test
    model2 = _make_media_identity_model(str(tenant.id), identity.embedding, media_id=999)
    db_session.add(model2)
    await db_session.flush()

    rep2 = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        identity_id=str(model2.id),
        embedding=identity.embedding,
        created_at=datetime.now(tz=UTC),
        tenant_id=str(tenant.id),
        is_provisional=True,
    )
    await cluster_repo.add_representative(rep2)

    cleaned = await cluster_repo.cleanup_orphaned_provisional_reps(str(tenant.id))
    assert cleaned == 1

    reps = await cluster_repo.get_all_representatives(cluster.id)
    assert len(reps) == 1
    assert reps[0].identity_id == str(model.id)
