"""Persistence tests for AssignmentWriter orchestration."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import MemberData
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemyMemberRepository


def make_identity(tenant_id: str) -> MediaIdentity:
    """Create a synthetic identity with a deterministic 1024D embedding."""
    # Extended embedding: 512 face + 512 metadata
    embedding = np.zeros(1024, dtype=np.float32)
    embedding[0] = 1.0  # Face component
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
