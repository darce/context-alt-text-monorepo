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
            member_count=0,
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
    assert updated_cluster.member_count == 1

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
            member_count=0,
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
    assert cluster.member_count == len(identities)

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
            member_count=0,
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
            member_count=3,
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
