"""Contract tests for AssignmentWriter interface (Phase 5, TDD first)."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.persistence.assignment_writer import AssignmentWriter, ClusterNotFoundError
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, IdentityMember, MemberRepository


class NullClusterRepo(ClusterRepository):
    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None:
        return None

    async def get_by_tenant(self, tenant_id: str, *, limit: int = 100, offset: int = 0) -> list[IdentityCluster]:
        return []

    async def save(self, cluster: IdentityCluster) -> IdentityCluster:
        return cluster

    async def update(self, cluster: IdentityCluster) -> IdentityCluster:
        return cluster

    async def delete(self, cluster_id: str) -> None:
        return None

    async def refresh_centroids_view(self) -> None:
        return None

    async def get_unclustered(self, tenant_id: str):
        return []

    async def get_representative_count(self, cluster_id: str) -> int:
        return 0

    async def get_all_representatives(self, cluster_id: str):
        return []

    async def get_member_embeddings(self, cluster_id: str):
        return []

    async def get_member_identities(self, cluster_id: str) -> list[MediaIdentity]:
        return []

    async def assign_identity_to_cluster(self, identity: MediaIdentity, cluster_id: str) -> None:
        return None

    async def add_representative(self, representative) -> None:
        return None

    async def clear_representatives(self, cluster_id: str) -> None:
        return None

    async def count_labeled(self) -> int:
        return 0


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


def _make_decision(outcome: AssignmentOutcome = AssignmentOutcome.ACCEPT) -> AssignmentDecision:
    candidate = AssignmentCandidate(
        identity=MediaIdentity(
            id="id-1",
            tenant_id="tenant-1",
            media_id="media-1",
            embedding=np.zeros(1, dtype=float),
            confidence=0.9,
            bbox_width=1,
            bbox_height=1,
        ),
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
    writer = AssignmentWriter(ClusteringSettings(), NullClusterRepo(), NullMemberRepo())

    decision = _make_decision(outcome=AssignmentOutcome.SUGGEST)
    with pytest.raises(ValueError):
        await writer.persist_assignment(decision)

    accept_decision = _make_decision()
    with pytest.raises(ClusterNotFoundError):
        await writer.persist_assignment(accept_decision)
