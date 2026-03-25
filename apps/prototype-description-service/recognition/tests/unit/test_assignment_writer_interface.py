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

    async def bulk_add_members_if_not_exists(self, cluster_id: str, members) -> tuple[list[IdentityMember], int]:
        created = [
            IdentityMember(
                id=f"member-{idx}",
                cluster_id=cluster_id,
                identity_id=member.identity_id,
                similarity=member.similarity,
            )
            for idx, member in enumerate(members)
        ]
        return created, 0

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


# ---------------------------------------------------------------------------
# Phase 3: bulk membership writes
# ---------------------------------------------------------------------------


class BulkTrackingMemberRepo(NullMemberRepo):
    """Records bulk_add_members_if_not_exists call args for assertion."""

    def __init__(self) -> None:
        self.bulk_calls: list[tuple[str, list]] = []
        self._skipped = 0

    async def bulk_add_members_if_not_exists(self, cluster_id: str, members) -> tuple[list[IdentityMember], int]:
        self.bulk_calls.append((cluster_id, list(members)))
        created = [
            IdentityMember(
                id=f"member-{idx}",
                cluster_id=cluster_id,
                identity_id=member.identity_id,
                similarity=member.similarity,
            )
            for idx, member in enumerate(members)
        ]
        return created, self._skipped


def _make_cluster(cluster_id: str = "cluster-1") -> IdentityCluster:
    from datetime import UTC, datetime

    return IdentityCluster(
        id=cluster_id,
        tenant_id="tenant-1",
        label=None,
        is_labeled=False,
        identity_count=0,
        created_at=datetime.now(tz=UTC),
    )


def _make_accept_decision(identity_id: str = "id-1", cluster_id: str = "cluster-1") -> AssignmentDecision:
    identity = MediaIdentity(
        id=identity_id,
        tenant_id="tenant-1",
        media_id="media-1",
        embedding=np.zeros(512, dtype=np.float32),
        confidence=0.9,
        bbox_width=1,
        bbox_height=1,
    )
    candidate = AssignmentCandidate(
        identity=identity,
        identity_vector=np.zeros(512, dtype=np.float32),
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.9,
    )
    return AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=[],
        checks_failed=[],
    )


@pytest.mark.asyncio
async def test_persist_assignments_chunk_returns_zero_for_empty_input() -> None:
    member_repo = BulkTrackingMemberRepo()
    writer = AssignmentWriter(ClusteringSettings(), NullClusterRepository(), member_repo)

    persisted, skipped, reps_added = await writer.persist_assignments_chunk([])

    assert persisted == 0
    assert skipped == 0
    assert reps_added == 0
    assert member_repo.bulk_calls == []


@pytest.mark.asyncio
async def test_persist_assignments_chunk_groups_by_cluster_and_calls_bulk_once_per_cluster() -> None:
    """Two decisions for the same cluster should produce one bulk_add_members_if_not_exists call."""
    cluster_repo = NullClusterRepository(clusters_by_id={"cluster-1": _make_cluster("cluster-1")})
    member_repo = BulkTrackingMemberRepo()
    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo)

    decisions = [
        _make_accept_decision(identity_id="id-1", cluster_id="cluster-1"),
        _make_accept_decision(identity_id="id-2", cluster_id="cluster-1"),
    ]
    persisted, skipped, reps_added = await writer.persist_assignments_chunk(decisions)

    # Both members should be persisted; exactly one bulk call for the cluster.
    assert persisted == 2
    assert skipped == 0
    assert len(member_repo.bulk_calls) == 1
    cluster_id_used, members_passed = member_repo.bulk_calls[0]
    assert cluster_id_used == "cluster-1"
    assert len(members_passed) == 2
    assert {m.identity_id for m in members_passed} == {"id-1", "id-2"}


@pytest.mark.asyncio
async def test_persist_assignments_chunk_uses_separate_bulk_call_per_cluster() -> None:
    """Decisions spread across two clusters should produce two bulk calls, one per cluster."""
    cluster_repo = NullClusterRepository(
        clusters_by_id={
            "cluster-1": _make_cluster("cluster-1"),
            "cluster-2": _make_cluster("cluster-2"),
        }
    )
    member_repo = BulkTrackingMemberRepo()
    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo)

    decisions = [
        _make_accept_decision(identity_id="id-1", cluster_id="cluster-1"),
        _make_accept_decision(identity_id="id-2", cluster_id="cluster-2"),
    ]
    persisted, skipped, reps_added = await writer.persist_assignments_chunk(decisions)

    assert persisted == 2
    assert skipped == 0
    assert len(member_repo.bulk_calls) == 2
    used_clusters = {call[0] for call in member_repo.bulk_calls}
    assert used_clusters == {"cluster-1", "cluster-2"}


@pytest.mark.asyncio
async def test_persist_assignments_chunk_counts_skipped_duplicates() -> None:
    """When bulk_add reports skipped rows, persist_assignments_chunk surfaces the count."""
    cluster_repo = NullClusterRepository(clusters_by_id={"cluster-1": _make_cluster("cluster-1")})
    member_repo = BulkTrackingMemberRepo()

    async def _partial_insert(cluster_id, members):
        items = list(members)
        # Return only first member as created; second was skipped (ON CONFLICT)
        created = [IdentityMember(id="m-0", cluster_id=cluster_id, identity_id=items[0].identity_id, similarity=0.9)]
        return created, 1

    member_repo.bulk_add_members_if_not_exists = _partial_insert

    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo)
    decisions = [
        _make_accept_decision(identity_id="id-1", cluster_id="cluster-1"),
        _make_accept_decision(identity_id="id-2", cluster_id="cluster-1"),
    ]
    persisted, skipped, reps_added = await writer.persist_assignments_chunk(decisions)

    assert skipped == 1
