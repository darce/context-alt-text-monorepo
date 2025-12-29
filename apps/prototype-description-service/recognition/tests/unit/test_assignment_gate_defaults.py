"""Integration-style tests for AssignmentGate default checks."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentOutcome
from recognition.application.assignment.gate import AssignmentGate
from recognition.application.settings import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.maturity import ClusterMaturityInfo
from recognition.domain.repositories import (
    ClusterRepository,
    IdentityClusterBlockRepository,
    IdentityConstraintRepository,
    IdentityMember,
    MemberRepository,
)
from recognition.domain.representative import ClusterRepresentative
from recognition.shared.ids import generate_id


class GateRepoStub(ClusterRepository):
    """Repository stub providing data for all default checks."""

    def __init__(self, reps: dict[str, list[np.ndarray]], members: dict[str, list[np.ndarray]]) -> None:
        self._reps = reps
        self._members = members

    async def get_by_id(self, cluster_id: str):
        return None

    async def get_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        labeled_only: bool = False,
        search: str | None = None,
    ):
        return []

    async def save(self, cluster):
        return cluster

    async def update(self, cluster):
        return cluster

    async def delete(self, cluster_id: str) -> None:
        return None

    async def refresh_centroids_view(self) -> None:
        pass

    async def refresh_centroids_view_concurrent(self) -> None:
        pass

    async def get_unclustered(self, tenant_id: str):
        return []

    async def get_representative_count(self, cluster_id: str) -> int:
        return len(self._reps.get(cluster_id, []))

    async def get_all_representatives(self, cluster_id: str) -> list[ClusterRepresentative]:
        vectors = self._reps.get(cluster_id, [])
        return [
            ClusterRepresentative(
                id=str(generate_id()),
                cluster_id=cluster_id,
                identity_id=str(generate_id()),
                embedding=v,
                created_at=datetime.now(tz=UTC),
                quality_score=0.9,
            )
            for v in vectors
        ]

    async def get_member_embeddings(self, cluster_id: str) -> list[np.ndarray]:
        return self._members.get(cluster_id, [])

    async def get_member_identities(self, cluster_id: str) -> list[MediaIdentity]:
        raise NotImplementedError

    async def save_cluster(self, cluster):
        raise NotImplementedError

    async def assign_identity_to_cluster(self, identity, cluster_id: str):
        raise NotImplementedError

    async def add_representative(self, representative):
        raise NotImplementedError

    async def clear_representatives(self, cluster_id: str) -> None:
        raise NotImplementedError

    async def remove_representative(self, representative_id: str) -> None:
        pass

    async def count_labeled(self) -> int:
        return 10  # Return a mature count so adaptive threshold is relaxed

    async def get_labeled_with_representatives(
        self,
        tenant_id: str,
    ) -> list[tuple[IdentityCluster, list[ClusterRepresentative]]]:
        return []

    async def get_maturity_info(self, cluster_id: str) -> ClusterMaturityInfo | None:
        return None

    async def get_top_unlabeled(self, tenant_id: str, limit: int = 10) -> list[IdentityCluster]:
        return []

    async def mark_representative_user_selected(self, representative_id: str, is_selected: bool = True) -> None:
        pass

    async def get_user_selected_representatives(self, cluster_id: str) -> list[ClusterRepresentative]:
        return []

    async def confirm_provisional_representatives(self, cluster_id: str) -> int:
        return 0

    async def confirm_all_provisional_reps(self, tenant_id: str) -> int:
        return 0

    async def cleanup_orphaned_provisional_reps(self, tenant_id: str) -> int:
        return 0


class BlockRepoStub(IdentityClusterBlockRepository):
    """Block repository stub controlling a single blocked state."""

    def __init__(self, blocked: bool) -> None:
        self._blocked = blocked
        self.called = False

    async def block(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        cluster_id: str,
        reason: str | None = None,
        created_by_user_id: int | None = None,
        expires_at: datetime | None = None,
    ):
        raise NotImplementedError

    async def add_block(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        blocked_cluster_id: str,
        reason: str | None = None,
        created_by_user_id: int | None = None,
        expires_at: datetime | None = None,
    ):
        raise NotImplementedError

    async def remove_block(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        blocked_cluster_id: str,
    ) -> bool:
        raise NotImplementedError

    async def get_blocks_for_identity(
        self,
        *,
        tenant_id: str,
        identity_id: str,
    ) -> list:
        return []

    async def is_blocked(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        cluster_id: str,
    ) -> bool:
        self.called = True
        return self._blocked


class ConstraintRepoStub(IdentityConstraintRepository):
    """Constraint repository stub controlling cannot-link state."""

    def __init__(self, cannot_link: bool) -> None:
        self._cannot_link = cannot_link
        self.called = False

    async def create_cannot_link(
        self,
        tenant_id: str,
        identity_a: str,
        identity_b: str,
        source: str,
        created_by_user_id: int | None = None,
    ):
        raise NotImplementedError

    async def create(
        self,
        tenant_id: str,
        identity_a: str,
        identity_b: str,
        constraint_type: str,
        source: str,
        created_by_user_id: int | None = None,
    ):
        raise NotImplementedError

    async def get(self, tenant_id: str, identity_a: str, identity_b: str):
        raise NotImplementedError

    async def get_all_for_identity(self, tenant_id: str, identity_id: str):
        raise NotImplementedError

    async def get_all(self, tenant_id: str):
        raise NotImplementedError

    async def has_cannot_link(
        self,
        tenant_id: str,
        identity_id: str,
        cluster_member_ids: list[str],
    ) -> bool:
        self.called = True
        return self._cannot_link


class MemberRepoStub(MemberRepository):
    """Member repository stub that returns a fixed list of members."""

    def __init__(self, members: list[IdentityMember]) -> None:
        self._members = members

    async def get_by_cluster(self, cluster_id: str) -> list[IdentityMember]:
        return self._members

    async def add_member(self, cluster_id: str, identity_id: str, similarity: float):
        raise NotImplementedError

    async def add_member_if_not_exists(self, cluster_id: str, identity_id: str, similarity: float):
        raise NotImplementedError

    async def bulk_add_members(self, cluster_id: str, members):
        raise NotImplementedError

    async def move_members(self, source_cluster_id: str, target_cluster_id: str) -> int:
        raise NotImplementedError

    async def remove_member(self, member_id: str) -> None:
        raise NotImplementedError

    async def get_by_identity_id(self, identity_id: str) -> list[IdentityMember]:
        raise NotImplementedError

    async def remove_by_identity_id(self, identity_id: str) -> bool:
        raise NotImplementedError


def make_settings() -> ClusteringSettings:
    """Create clustering settings enabling all default checks."""
    return ClusteringSettings(
        similarity_threshold=0.75,
        complete_link_min_floor=0.7,
        complete_link_avg_threshold=0.8,
        min_representatives_for_maturity=2,
        member_validation_min_floor=0.7,
        member_validation_avg_threshold=0.8,
        early_stage_suggestion_enabled=True,
        suggestion_floor=0.5,
        suggestion_ceiling=0.75,
        early_stage_high_confidence_threshold=0.9,
        adaptive_threshold_maturity_point=5,
        hdbscan_max_batch_size=None,
    )


def make_candidate(vector: np.ndarray, cluster_id: str, similarity: float) -> AssignmentCandidate:
    """Create an assignment candidate."""
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=vector,
        confidence=0.95,
        bbox_width=100,
        bbox_height=100,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=vector,
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=similarity,
    )


def normalize(vector: np.ndarray) -> np.ndarray:
    """Return a normalized copy of the vector."""
    norm = float(np.linalg.norm(vector))
    return vector.astype(np.float32) / norm


@pytest.mark.asyncio
async def test_default_checks_accept_when_all_pass() -> None:
    """Default gate should accept when confidence check passes."""
    cluster_id = str(generate_id())
    base = normalize(np.array([1.0, 0.0, 0.0]))
    reps = {cluster_id: [base, normalize(base + np.array([0.0, 0.1, 0.0]))]}
    members = {cluster_id: [normalize(base + np.array([0.05, 0.0, 0.0]))]}

    gate = AssignmentGate(settings=make_settings(), cluster_repository=GateRepoStub(reps, members))
    decision = await gate.evaluate(make_candidate(normalize(base + np.array([0.05, 0.02, 0.0])), cluster_id, 0.95))

    assert decision.outcome is AssignmentOutcome.ACCEPT
    assert decision.checks_failed == []
    # Gate now uses only confidence check (maturity, complete_link, member_distribution removed)
    assert set(decision.checks_passed) == {"confidence"}


@pytest.mark.asyncio
async def test_default_checks_suggest_on_low_confidence() -> None:
    """Default gate should suggest when confidence check fails."""
    cluster_id = str(generate_id())
    base = normalize(np.array([1.0, 0.0, 0.0]))
    reps = {cluster_id: [base, normalize(base + np.array([0.0, 0.1, 0.0]))]}
    members = {cluster_id: [normalize(base + np.array([0.05, 0.0, 0.0]))]}

    gate = AssignmentGate(settings=make_settings(), cluster_repository=GateRepoStub(reps, members))
    decision = await gate.evaluate(make_candidate(normalize(base + np.array([0.05, 0.02, 0.0])), cluster_id, 0.5))

    assert decision.outcome is AssignmentOutcome.SUGGEST
    assert "confidence" in decision.checks_failed
    # Gate now uses only confidence check (maturity, complete_link, member_distribution removed)
    assert decision.checks_passed == []


@pytest.mark.asyncio
async def test_default_checks_include_block_and_constraint_when_configured() -> None:
    """Default gate should include block and constraint checks when repositories provided."""
    cluster_id = str(generate_id())
    base = normalize(np.array([1.0, 0.0, 0.0]))

    gate = AssignmentGate(
        settings=make_settings(),
        cluster_repository=GateRepoStub({cluster_id: [base]}, {cluster_id: [base]}),
        block_repository=BlockRepoStub(blocked=False),
        constraint_repository=ConstraintRepoStub(cannot_link=False),
        member_repository=MemberRepoStub(
            [IdentityMember(id="m1", cluster_id=cluster_id, identity_id="id-1", similarity=0.9)]
        ),
    )

    decision = await gate.evaluate(make_candidate(normalize(base + np.array([0.05, 0.02, 0.0])), cluster_id, 0.95))

    assert decision.outcome is AssignmentOutcome.ACCEPT
    assert decision.checks_failed == []
    assert decision.checks_passed == ["block_check", "ConstraintCheck", "confidence"]


@pytest.mark.asyncio
async def test_default_checks_reject_when_blocked() -> None:
    """Block check should short-circuit the pipeline and reject the candidate."""
    cluster_id = str(generate_id())
    base = normalize(np.array([1.0, 0.0, 0.0]))
    block_repo = BlockRepoStub(blocked=True)
    constraint_repo = ConstraintRepoStub(cannot_link=False)

    gate = AssignmentGate(
        settings=make_settings(),
        cluster_repository=GateRepoStub({cluster_id: [base]}, {cluster_id: [base]}),
        block_repository=block_repo,
        constraint_repository=constraint_repo,
        member_repository=MemberRepoStub(
            [IdentityMember(id="m1", cluster_id=cluster_id, identity_id="id-1", similarity=0.9)]
        ),
    )

    decision = await gate.evaluate(make_candidate(normalize(base + np.array([0.05, 0.02, 0.0])), cluster_id, 0.95))

    assert decision.outcome is AssignmentOutcome.REJECT
    assert decision.checks_failed == ["block_check"]
    assert decision.checks_passed == []
    assert block_repo.called is True
    assert constraint_repo.called is False
