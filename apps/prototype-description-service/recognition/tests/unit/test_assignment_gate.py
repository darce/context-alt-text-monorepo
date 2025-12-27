"""Tests for AssignmentGate orchestration over validation checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.checks.base import AssignmentCheck, CheckResult
from recognition.application.assignment.decision import AssignmentOutcome
from recognition.application.assignment.gate import AssignmentGate
from recognition.application.settings import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.maturity import ClusterMaturityInfo
from recognition.domain.repositories import ClusterRepository
from recognition.domain.representative import ClusterRepresentative
from recognition.shared.ids import generate_id


class NoopRepository(ClusterRepository):
    """ClusterRepository stub that should never be called in these gate tests."""

    async def get_by_id(self, cluster_id: str):
        return None

    async def get_by_tenant(self, tenant_id: str, *, limit: int = 100, offset: int = 0, labeled_only: bool = False):
        return []

    async def save(self, cluster):
        return cluster

    async def update(self, cluster):
        return cluster

    async def delete(self, cluster_id: str) -> None:
        return None

    async def refresh_centroids_view(self) -> None:
        pass

    async def get_unclustered(self, tenant_id):
        raise NotImplementedError

    async def get_representative_count(self, cluster_id):
        raise NotImplementedError

    async def get_all_representatives(self, cluster_id):
        raise NotImplementedError

    async def get_member_embeddings(self, cluster_id):
        raise NotImplementedError

    async def get_member_identities(self, cluster_id: str) -> list[MediaIdentity]:
        raise NotImplementedError

    async def save_cluster(self, cluster):
        raise NotImplementedError

    async def assign_identity_to_cluster(self, identity, cluster_id):
        raise NotImplementedError

    async def add_representative(self, representative):
        raise NotImplementedError

    async def clear_representatives(self, cluster_id: str) -> None:
        raise NotImplementedError

    async def remove_representative(self, representative_id: str) -> None:
        raise NotImplementedError

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
        raise NotImplementedError

    async def get_user_selected_representatives(self, cluster_id: str) -> list[ClusterRepresentative]:
        raise NotImplementedError

    async def confirm_provisional_representatives(self, cluster_id: str) -> int:
        raise NotImplementedError

    async def confirm_all_provisional_reps(self, tenant_id: str) -> int:
        raise NotImplementedError

    async def cleanup_orphaned_provisional_reps(self, tenant_id: str) -> int:
        raise NotImplementedError


def make_candidate() -> AssignmentCandidate:
    """Create a minimal candidate for gate tests."""
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=np.ones(4, dtype=np.float32),
        confidence=0.9,
        bbox_width=10,
        bbox_height=12,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=np.ones(4, dtype=np.float32),
        cluster_id=str(generate_id()),
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.8,
    )


def make_settings() -> ClusteringSettings:
    """Create a fully populated settings object."""
    return ClusteringSettings(
        similarity_threshold=0.7,
        complete_link_min_floor=0.7,
        complete_link_avg_threshold=0.8,
        min_representatives_for_maturity=2,
        member_validation_min_floor=0.7,
        member_validation_avg_threshold=0.8,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.9,
        adaptive_threshold_maturity_point=5,
        hdbscan_max_batch_size=None,
    )


@dataclass
class FakeCheck(AssignmentCheck):
    """Simple check that returns a predefined result."""

    name: str
    enabled: bool
    result: CheckResult
    called: bool = False

    def is_enabled(self) -> bool:
        return self.enabled

    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        self.called = True
        return self.result


@pytest.mark.asyncio
async def test_gate_accepts_when_all_checks_pass() -> None:
    """Gate should return ACCEPT when every enabled check passes."""
    gate = AssignmentGate(
        settings=make_settings(),
        cluster_repository=NoopRepository(),
        checks=[
            FakeCheck(name="check_a", enabled=True, result=CheckResult(passed=True)),
            FakeCheck(name="check_b", enabled=True, result=CheckResult(passed=True)),
        ],
    )

    decision = await gate.evaluate(make_candidate())

    assert decision.outcome is AssignmentOutcome.ACCEPT
    assert decision.checks_passed == ["check_a", "check_b"]
    assert decision.checks_failed == []


@pytest.mark.asyncio
async def test_gate_stops_on_fatal_suggest() -> None:
    """Gate should stop at the first fatal failure and return SUGGEST when should_reject is False."""
    fatal_result = CheckResult(passed=False, is_fatal=True, should_reject=False, reason="low similarity")
    gate = AssignmentGate(
        settings=make_settings(),
        cluster_repository=NoopRepository(),
        checks=[
            FakeCheck(name="check_a", enabled=True, result=CheckResult(passed=True)),
            FakeCheck(name="complete_link", enabled=True, result=fatal_result),
            FakeCheck(name="later_check", enabled=True, result=CheckResult(passed=True)),
        ],
    )

    decision = await gate.evaluate(make_candidate())

    assert decision.outcome is AssignmentOutcome.SUGGEST
    assert decision.checks_passed == ["check_a"]
    assert decision.checks_failed == ["complete_link"]
    assert decision.rejection_reason == "low similarity"


@pytest.mark.asyncio
async def test_gate_rejects_when_should_reject_true() -> None:
    """Gate should return REJECT when a fatal failure requests rejection."""
    fatal_reject = CheckResult(passed=False, is_fatal=True, should_reject=True, reason="conflict with members")
    gate = AssignmentGate(
        settings=make_settings(),
        cluster_repository=NoopRepository(),
        checks=[
            FakeCheck(name="member_distribution", enabled=True, result=fatal_reject),
        ],
    )

    decision = await gate.evaluate(make_candidate())

    assert decision.checks_passed == []
    assert decision.checks_failed == ["member_distribution"]
    assert decision.rejection_reason == "conflict with members"


@pytest.mark.asyncio
async def test_gate_aggregates_metadata_from_all_checks() -> None:
    """Gate should aggregate metadata from both passed and failed checks."""
    gate = AssignmentGate(
        settings=make_settings(),
        cluster_repository=NoopRepository(),
        checks=[
            FakeCheck(name="check_a", enabled=True, result=CheckResult(passed=True, metadata={"a": 1})),
            FakeCheck(name="check_b", enabled=True, result=CheckResult(passed=True, metadata={"b": 2})),
            FakeCheck(name="check_c", enabled=True, result=CheckResult(passed=False, is_fatal=True, metadata={"c": 3})),
        ],
    )

    decision = await gate.evaluate(make_candidate())

    assert decision.metadata is not None
    assert decision.metadata["a"] == 1
    assert decision.metadata["b"] == 2
    assert decision.metadata["c"] == 3
    assert decision.outcome is AssignmentOutcome.SUGGEST  # Stopped at check_c


@pytest.mark.asyncio
async def test_gate_skips_disabled_checks() -> None:
    """Gate should ignore disabled checks and not record them."""
    disabled = FakeCheck(name="disabled_check", enabled=False, result=CheckResult(passed=True))
    enabled = FakeCheck(name="enabled_check", enabled=True, result=CheckResult(passed=True))
    gate = AssignmentGate(
        settings=make_settings(),
        cluster_repository=NoopRepository(),
        checks=[disabled, enabled],
    )

    decision = await gate.evaluate(make_candidate())

    assert decision.outcome is AssignmentOutcome.ACCEPT
    assert decision.checks_passed == ["enabled_check"]
    assert decision.checks_failed == []
    assert disabled.called is False
    assert enabled.called is True


@pytest.mark.asyncio
async def test_gate_continues_after_nonfatal_failure() -> None:
    """Gate should continue after non-fatal failures and still accept."""
    gate = AssignmentGate(
        settings=make_settings(),
        cluster_repository=NoopRepository(),
        checks=[
            FakeCheck(name="check_a", enabled=True, result=CheckResult(passed=True)),
            FakeCheck(name="soft_fail", enabled=True, result=CheckResult(passed=False, reason="soft failure")),
            FakeCheck(name="check_c", enabled=True, result=CheckResult(passed=True)),
        ],
    )

    decision = await gate.evaluate(make_candidate())

    assert decision.outcome is AssignmentOutcome.ACCEPT
    assert decision.checks_passed == ["check_a", "check_c"]
    assert decision.checks_failed == ["soft_fail"]
    assert decision.rejection_reason is None
