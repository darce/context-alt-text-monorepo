"""Slice 9 sub-slice 3a: _should_add_representative returns an explicit RepAdmission.

Pins the CURRENT observed contract before the temporal-coupling removal so the
refactor stays behaviour-preserving. Notably `was_upgrade` is always False today
(latent reset bug at assignment_writer.py:655, documented in the increment-3 plan
and fixed separately in 3a-fix), and `rep_count` is the pre-upgrade-removal count
that persist_assignment passes as existing_rep_count.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.persistence.assignment_writer import AssignmentWriter, RepAdmission
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.domain.representative import ClusterRepresentative


def _unit_vector(index: int, length: int = 512) -> np.ndarray:
    vec = np.zeros(length, dtype=np.float32)
    vec[index] = 1.0
    return vec


def _candidate(
    cluster_id: str, *, index: int = 0, pitch: float | None = None, yaw: float | None = None
) -> AssignmentCandidate:
    vector = _unit_vector(index)
    return AssignmentCandidate(
        identity=MediaIdentity(
            id=f"id-{index}",
            tenant_id="tenant-1",
            media_id="media-1",
            embedding=vector,
            confidence=0.95,
            bbox_width=100,
            bbox_height=100,
            pose_pitch=pitch,
            pose_yaw=yaw,
        ),
        identity_vector=vector,
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.92,
    )


def _accept(candidate: AssignmentCandidate) -> AssignmentDecision:
    return AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT, candidate=candidate, checks_passed=["all"], checks_failed=[]
    )


def _rep(cluster_id: str, index: int, *, pitch: float | None = None, yaw: float | None = None) -> ClusterRepresentative:
    return ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id=cluster_id,
        identity_id=f"rep-{index}",
        embedding=_unit_vector(index + 1),
        created_at=None,
        tenant_id="tenant-1",
        pose_pitch=pitch,
        pose_yaw=yaw,
    )


@pytest.fixture
def settings() -> ClusteringSettings:
    return ClusteringSettings(
        max_representatives_per_cluster=5,
        pose_diversity_bonus=2,
        representative_diversity_threshold=0.9,
        pose_bucket_size=30.0,
    )


@pytest.fixture
def cluster_repo() -> AsyncMock:
    repo = AsyncMock(spec=ClusterRepository)
    repo.get_all_representatives.return_value = []
    return repo


@pytest.fixture
def writer(settings: ClusteringSettings, cluster_repo: AsyncMock) -> AssignmentWriter:
    return AssignmentWriter(settings, cluster_repo, AsyncMock(spec=MemberRepository))


@pytest.mark.asyncio
async def test_admission_empty_cluster_diverse_add(writer: AssignmentWriter, cluster_repo: AsyncMock) -> None:
    cluster_repo.get_all_representatives.return_value = []

    adm = await writer._should_add_representative(_accept(_candidate("c1")))

    assert isinstance(adm, RepAdmission)
    assert adm.should_add is True
    assert adm.rep_count == 0
    assert adm.was_upgrade is False
    assert adm.was_novel_pose is False
    assert adm.cached_reps == []


@pytest.mark.asyncio
async def test_admission_rep_count_is_pre_removal_and_never_upgrade(
    writer: AssignmentWriter, cluster_repo: AsyncMock
) -> None:
    reps = [_rep("c1", i) for i in range(8)]  # no pose -> no upgrade target; count >= max_total -> reject
    cluster_repo.get_all_representatives.return_value = reps

    adm = await writer._should_add_representative(_accept(_candidate("c1")))

    assert adm.should_add is False
    assert adm.rep_count == 8  # current_count (pre-removal) — what persist_assignment passes
    assert adm.was_upgrade is False  # documents the always-False latent state


@pytest.mark.asyncio
async def test_admission_novel_pose_sets_flag(writer: AssignmentWriter, cluster_repo: AsyncMock) -> None:
    covered = [_rep("c1", i, pitch=0.0, yaw=0.0) for i in range(5)]  # bucket (0,0); count == max_base
    cluster_repo.get_all_representatives.return_value = covered
    cand = _candidate("c1", index=10, pitch=90.0, yaw=90.0)  # bucket (3,3) -> novel

    adm = await writer._should_add_representative(_accept(cand))

    assert adm.should_add is True
    assert adm.was_novel_pose is True
    assert adm.was_upgrade is False
