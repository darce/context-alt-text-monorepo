"""Slice 9 sub-slice 3a / 3a-fix: _should_add_representative returns an explicit RepAdmission.

3a removed the ``_last_*`` temporal coupling (the decision is now an explicit return
value). 3a-fix then restored the upgrade signal: a genuine quality upgrade reports
``was_upgrade=True``, so the ``representative_upgrade`` reason and ``representative_upgraded``
event fire again (previously dead code behind a reset bug). ``rep_count`` remains the
pre-upgrade-removal count that persist_assignment passes as existing_rep_count.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.persistence.assignment_writer import AssignmentWriter, RepAdmission
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
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
async def test_admission_rep_count_is_pre_removal_no_upgrade_target(
    writer: AssignmentWriter, cluster_repo: AsyncMock
) -> None:
    reps = [_rep("c1", i) for i in range(8)]  # no pose -> no upgrade target; count >= max_total -> reject
    cluster_repo.get_all_representatives.return_value = reps

    adm = await writer._should_add_representative(_accept(_candidate("c1")))

    assert adm.should_add is False
    assert adm.rep_count == 8  # current_count (pre-removal) — what persist_assignment passes
    assert adm.was_upgrade is False  # no upgrade target found (not the latent reset)


@pytest.mark.asyncio
async def test_admission_upgrade_sets_was_upgrade(writer: AssignmentWriter, cluster_repo: AsyncMock) -> None:
    """3a-fix: a genuine quality upgrade (same pose bucket, higher quality) now reports
    was_upgrade=True, restoring the upgrade reason/event suppressed by the former reset bug."""
    old_rep = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id="c1",
        identity_id="rep-old",
        embedding=_unit_vector(0),
        created_at=None,
        tenant_id="tenant-1",
        pose_pitch=0.0,
        pose_yaw=0.0,
        quality_score=0.1,  # low quality -> upgradeable
    )
    cluster_repo.get_all_representatives.return_value = [old_rep]
    # Same pose bucket (0,0) -> upgrade target; orthogonal embedding -> passes the
    # diversity check run over the pre-removal reps.
    cand = _candidate("c1", index=10, pitch=0.0, yaw=0.0)

    adm = await writer._should_add_representative(_accept(cand))

    assert adm.should_add is True
    assert adm.was_upgrade is True
    assert all(r.id != old_rep.id for r in adm.cached_reps)  # removed rep excluded from cache
    cluster_repo.remove_representative.assert_awaited_once_with(old_rep.id)


@pytest.mark.asyncio
async def test_admission_protected_upgrade_target_is_not_an_upgrade(
    writer: AssignmentWriter, cluster_repo: AsyncMock
) -> None:
    """A user-selected (pinned) rep is protected: no removal, no upgrade flag."""
    pinned = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id="c1",
        identity_id="rep-pinned",
        embedding=_unit_vector(0),
        created_at=None,
        tenant_id="tenant-1",
        pose_pitch=0.0,
        pose_yaw=0.0,
        quality_score=0.1,
        is_user_selected=True,
    )
    cluster_repo.get_all_representatives.return_value = [pinned]
    cand = _candidate("c1", index=10, pitch=0.0, yaw=0.0)

    adm = await writer._should_add_representative(_accept(cand))

    assert adm.should_add is False
    assert adm.was_upgrade is False
    cluster_repo.remove_representative.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_assignment_upgrade_emits_reason_and_event() -> None:
    """3a-fix event-reason regression: an upgrade decision records reason
    'representative_upgrade' and emits exactly one representative_upgraded event."""
    settings = ClusteringSettings(
        max_representatives_per_cluster=5,
        pose_diversity_bonus=2,
        representative_diversity_threshold=0.9,
        pose_bucket_size=30.0,
    )
    old_rep = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id="c1",
        identity_id="rep-old",
        embedding=_unit_vector(0),
        created_at=None,
        tenant_id="tenant-1",
        pose_pitch=0.0,
        pose_yaw=0.0,
        quality_score=0.1,
    )
    cluster_repo = AsyncMock()
    cluster_repo.get_all_representatives.return_value = [old_rep]
    cluster_repo.get_by_id.return_value = IdentityCluster(
        id="c1", tenant_id="tenant-1", label=None, is_labeled=False, identity_count=0
    )
    run_ctx = Mock()
    writer = AssignmentWriter(settings, cluster_repo, AsyncMock(), run_context=run_ctx)

    await writer.persist_assignment(_accept(_candidate("c1", index=10, pitch=0.0, yaw=0.0)))

    events = run_ctx.add_event.call_args_list
    selected = [c for c in events if c.kwargs.get("event_type") == "representative_selected"]
    upgraded = [c for c in events if c.kwargs.get("event_type") == "representative_upgraded"]
    assert len(selected) == 1
    assert selected[0].kwargs["payload"]["reason"] == "representative_upgrade"
    assert len(upgraded) == 1


@pytest.mark.asyncio
async def test_admission_novel_pose_sets_flag(writer: AssignmentWriter, cluster_repo: AsyncMock) -> None:
    covered = [_rep("c1", i, pitch=0.0, yaw=0.0) for i in range(5)]  # bucket (0,0); count == max_base
    cluster_repo.get_all_representatives.return_value = covered
    cand = _candidate("c1", index=10, pitch=90.0, yaw=90.0)  # bucket (3,3) -> novel

    adm = await writer._should_add_representative(_accept(cand))

    assert adm.should_add is True
    assert adm.was_novel_pose is True
    assert adm.was_upgrade is False


@pytest.mark.asyncio
async def test_persist_assignments_chunk_upgrade_emits_event() -> None:
    """BR-01: the batch path emits the representative_upgraded event on an upgrade, at
    parity with the single-item persist_assignment path (previously only the single path did)."""
    settings = ClusteringSettings(
        max_representatives_per_cluster=5,
        pose_diversity_bonus=2,
        representative_diversity_threshold=0.9,
        pose_bucket_size=30.0,
    )
    old_rep = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id="c1",
        identity_id="rep-old",
        embedding=_unit_vector(0),
        created_at=None,
        tenant_id="tenant-1",
        pose_pitch=0.0,
        pose_yaw=0.0,
        quality_score=0.1,
    )
    cluster_repo = AsyncMock()
    cluster_repo.get_all_representatives.return_value = [old_rep]
    cluster_repo.get_by_id.return_value = IdentityCluster(
        id="c1", tenant_id="tenant-1", label=None, is_labeled=False, identity_count=0
    )
    cand = _candidate("c1", index=10, pitch=0.0, yaw=0.0)
    member_repo = AsyncMock()
    member_repo.bulk_add_members_if_not_exists.return_value = ([Mock(identity_id=cand.identity.id)], 0)
    run_ctx = Mock()
    writer = AssignmentWriter(settings, cluster_repo, member_repo, run_context=run_ctx)

    await writer.persist_assignments_chunk([_accept(cand)])

    events = run_ctx.add_event.call_args_list
    selected = [c for c in events if c.kwargs.get("event_type") == "representative_selected"]
    upgraded = [c for c in events if c.kwargs.get("event_type") == "representative_upgraded"]
    assert len(selected) == 1
    assert selected[0].kwargs["payload"]["reason"] == "representative_upgrade"
    assert len(upgraded) == 1


@pytest.mark.asyncio
async def test_persist_assignment_novel_pose_reason_no_upgrade_event() -> None:
    """TA-01: a novel-pose accept records reason 'novel_pose_addition' and emits no upgrade event."""
    settings = ClusteringSettings(
        max_representatives_per_cluster=5,
        pose_diversity_bonus=2,
        representative_diversity_threshold=0.9,
        pose_bucket_size=30.0,
    )
    covered = [_rep("c1", i, pitch=0.0, yaw=0.0) for i in range(5)]  # bucket (0,0) covered
    cluster_repo = AsyncMock()
    cluster_repo.get_all_representatives.return_value = covered
    cluster_repo.get_by_id.return_value = IdentityCluster(
        id="c1", tenant_id="tenant-1", label=None, is_labeled=False, identity_count=0
    )
    run_ctx = Mock()
    writer = AssignmentWriter(settings, cluster_repo, AsyncMock(), run_context=run_ctx)

    await writer.persist_assignment(_accept(_candidate("c1", index=10, pitch=90.0, yaw=90.0)))

    events = run_ctx.add_event.call_args_list
    selected = [c for c in events if c.kwargs.get("event_type") == "representative_selected"]
    upgraded = [c for c in events if c.kwargs.get("event_type") == "representative_upgraded"]
    assert len(selected) == 1
    assert selected[0].kwargs["payload"]["reason"] == "novel_pose_addition"
    assert upgraded == []


@pytest.mark.asyncio
async def test_persist_assignment_diverse_reason_no_upgrade_event() -> None:
    """TA-01: a plain diverse accept (empty cluster) records reason 'diverse_addition', no upgrade event."""
    settings = ClusteringSettings(
        max_representatives_per_cluster=5,
        pose_diversity_bonus=2,
        representative_diversity_threshold=0.9,
        pose_bucket_size=30.0,
    )
    cluster_repo = AsyncMock()
    cluster_repo.get_all_representatives.return_value = []
    cluster_repo.get_by_id.return_value = IdentityCluster(
        id="c1", tenant_id="tenant-1", label=None, is_labeled=False, identity_count=0
    )
    run_ctx = Mock()
    writer = AssignmentWriter(settings, cluster_repo, AsyncMock(), run_context=run_ctx)

    await writer.persist_assignment(_accept(_candidate("c1", index=10)))

    events = run_ctx.add_event.call_args_list
    selected = [c for c in events if c.kwargs.get("event_type") == "representative_selected"]
    upgraded = [c for c in events if c.kwargs.get("event_type") == "representative_upgraded"]
    assert len(selected) == 1
    assert selected[0].kwargs["payload"]["reason"] == "diverse_addition"
    assert upgraded == []


@pytest.mark.asyncio
async def test_persist_assignment_centroid_uses_unit_normalized_mean() -> None:
    """TA-02: the accept-path centroid equals CentroidMaintainer.unit_normalized_mean of the
    cached reps plus the new rep — pins the single-source dedup invariant (not re-inlined math)."""
    settings = ClusteringSettings(
        max_representatives_per_cluster=5,
        pose_diversity_bonus=2,
        representative_diversity_threshold=0.9,
        pose_bucket_size=30.0,
    )
    cluster_repo = AsyncMock()
    cluster_repo.get_all_representatives.return_value = []
    cluster = IdentityCluster(id="c1", tenant_id="tenant-1", label=None, is_labeled=False, identity_count=0)
    cluster_repo.get_by_id.return_value = cluster
    cand = _candidate("c1", index=10)
    writer = AssignmentWriter(settings, cluster_repo, AsyncMock())

    await writer.persist_assignment(_accept(cand))

    expected = writer._centroids.unit_normalized_mean([cand.identity.embedding])
    assert expected is not None
    assert cluster.centroid is not None
    assert np.allclose(cluster.centroid, expected)
