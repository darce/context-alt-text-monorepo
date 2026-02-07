"""Contract tests for AssignmentWriter interface (Phase 5, TDD first)."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.persistence.assignment_writer import AssignmentWriter, ClusterNotFoundError
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import IdentityMember, MemberRepository
from recognition.tests.stubs import NullClusterRepository


class NullMemberRepo(MemberRepository):
    async def get_by_cluster(self, cluster_id: str) -> list[IdentityMember]:
        return []

    async def add_member(self, cluster_id: str, identity_id: str, similarity: float) -> IdentityMember:
        return IdentityMember(
            id="member-id",
            cluster_id=cluster_id,
            identity_id=identity_id,
            similarity=similarity,
        )

    async def add_member_if_not_exists(
        self, cluster_id: str, identity_id: str, similarity: float
    ) -> IdentityMember | None:
        return await self.add_member(cluster_id, identity_id, similarity)

    async def bulk_add_members(self, cluster_id: str, members) -> list[IdentityMember]:
        return [
            IdentityMember(
                id=f"member-{idx}",
                cluster_id=cluster_id,
                identity_id=member.identity_id,
                similarity=member.similarity,
            )
            for idx, member in enumerate(members)
        ]

    async def move_members(self, source_cluster_id: str, target_cluster_id: str) -> int:
        return 0

    async def remove_member(self, member_id: str) -> None:
        return None

    async def get_by_identity_id(self, identity_id: str) -> list[IdentityMember]:
        return []

    async def remove_by_identity_id(self, identity_id: str) -> bool:
        return False


def _make_identity() -> MediaIdentity:
    return MediaIdentity(
        id="id-1",
        tenant_id="tenant-1",
        media_id="media-1",
        embedding=np.zeros(1, dtype=float),
        confidence=0.9,
        bbox_width=1,
        bbox_height=1,
    )


def _make_decision(outcome: AssignmentOutcome = AssignmentOutcome.ACCEPT) -> AssignmentDecision:
    candidate = AssignmentCandidate(
        identity=_make_identity(),
        identity_vector=np.zeros(1, dtype=float),
        cluster_id="cluster-1",
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.9,
    )
    return AssignmentDecision(
        outcome=outcome,
        candidate=candidate,
        checks_passed=[],
        checks_failed=[],
    )


@pytest.mark.asyncio
async def test_assignment_writer_methods_raise_not_implemented() -> None:
    """AssignmentWriter should validate inputs before delegating to repositories."""
    writer = AssignmentWriter(ClusteringSettings(), NullClusterRepository(), NullMemberRepo())

    decision = _make_decision(outcome=AssignmentOutcome.SUGGEST)
    with pytest.raises(ValueError):
        await writer.persist_assignment(decision)

    accept_decision = _make_decision()
    with pytest.raises(ClusterNotFoundError):
        await writer.persist_assignment(accept_decision)


@pytest.mark.asyncio
async def test_persist_new_cluster_requires_matching_lengths() -> None:
    writer = AssignmentWriter(ClusteringSettings(), NullClusterRepository(), NullMemberRepo())

    with pytest.raises(ValueError):
        await writer.persist_new_cluster(
            tenant_id="tenant-1",
            identities=[_make_identity()],
            similarities=[0.9, 0.8],
            algorithm="graph",
        )


@pytest.mark.asyncio
async def test_persist_new_cluster_raises_when_cluster_id_missing() -> None:
    writer = AssignmentWriter(ClusteringSettings(), NullClusterRepository(), NullMemberRepo())

    with pytest.raises(ClusterNotFoundError):
        await writer.persist_new_cluster(
            tenant_id="tenant-1",
            identities=[_make_identity()],
            similarities=[0.9],
            algorithm="graph",
        )


@pytest.mark.asyncio
async def test_update_cluster_metadata_requires_existing_cluster() -> None:
    writer = AssignmentWriter(ClusteringSettings(), NullClusterRepository(), NullMemberRepo())

    with pytest.raises(ClusterNotFoundError):
        await writer.update_cluster_metadata(cluster_id="cluster-1", label="Confirmed")


@pytest.mark.asyncio
async def test_assign_to_existing_cluster_requires_cluster() -> None:
    writer = AssignmentWriter(ClusteringSettings(), NullClusterRepository(), NullMemberRepo())

    with pytest.raises(ClusterNotFoundError):
        await writer.assign_to_existing_cluster(identity=_make_identity(), cluster_id="cluster-1", similarity=0.9)
