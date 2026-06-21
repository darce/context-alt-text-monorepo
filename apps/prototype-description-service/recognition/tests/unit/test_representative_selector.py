"""Slice 9 sub-slice 3b: RepresentativeSelector owns the representative-selection surface.

Pins the selection API directly on the extracted class (admission decision + the
seeded FPS diversity math) and guards the no-cycle seam: the selector must never
import ``assignment_writer`` (selection depends downward only).
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.persistence import representative_selector as rs_module
from recognition.application.persistence.representative_selector import (
    RepAdmission,
    RepresentativeSelector,
    _select_diverse_representatives,
)
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository
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


def _identity(index: int, *, confidence: float = 0.9) -> MediaIdentity:
    return MediaIdentity(
        id=f"id-{index}",
        tenant_id="tenant-1",
        media_id="media-1",
        embedding=_unit_vector(index),
        confidence=confidence,
        bbox_width=100,
        bbox_height=100,
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
def selector(settings: ClusteringSettings, cluster_repo: AsyncMock) -> RepresentativeSelector:
    return RepresentativeSelector(settings, cluster_repo)


def test_selector_never_imports_assignment_writer() -> None:
    """No-cycle seam: the selection module depends downward only."""
    import_lines = [
        line.strip()
        for line in inspect.getsource(rs_module).splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not any("assignment_writer" in line for line in import_lines)


@pytest.mark.asyncio
async def test_should_add_representative_empty_cluster(
    selector: RepresentativeSelector, cluster_repo: AsyncMock
) -> None:
    cluster_repo.get_all_representatives.return_value = []

    adm = await selector.should_add_representative(_accept(_candidate("c1")))

    assert isinstance(adm, RepAdmission)
    assert adm.should_add is True
    assert adm.rep_count == 0
    assert adm.was_upgrade is False
    assert adm.cached_reps == []


@pytest.mark.asyncio
async def test_should_add_representative_upgrade_sets_flag(
    selector: RepresentativeSelector, cluster_repo: AsyncMock
) -> None:
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
    cluster_repo.get_all_representatives.return_value = [old_rep]

    adm = await selector.should_add_representative(_accept(_candidate("c1", index=10, pitch=0.0, yaw=0.0)))

    assert adm.should_add is True
    assert adm.was_upgrade is True
    cluster_repo.remove_representative.assert_awaited_once_with(old_rep.id)
    assert all(r.id != old_rep.id for r in adm.cached_reps)


@pytest.mark.asyncio
async def test_should_add_representative_rejects_above_cap(
    selector: RepresentativeSelector, cluster_repo: AsyncMock
) -> None:
    reps = [
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id="c1",
            identity_id=f"rep-{i}",
            embedding=_unit_vector(i + 1),
            created_at=None,
            tenant_id="tenant-1",
        )
        for i in range(8)  # >= max_total (5 + 2), no pose -> no upgrade target
    ]
    cluster_repo.get_all_representatives.return_value = reps

    adm = await selector.should_add_representative(_accept(_candidate("c1", index=20)))

    assert adm.should_add is False
    assert adm.rep_count == 8
    assert adm.was_upgrade is False


def test_select_diverse_representatives_seeded_picks_orthogonal(selector: RepresentativeSelector) -> None:
    """FPS seeded by an existing rep prefers the candidate farthest from the seed."""
    seed = _unit_vector(0)
    near = _identity(0)  # collinear with seed -> distance ~0
    far = _identity(1)  # orthogonal to seed -> distance ~1

    picked = selector.select_diverse_representatives_seeded([near, far], requested_count=1, seeded_embeddings=[seed])

    assert [p.id for p in picked] == [far.id]


def test_select_diverse_representatives_seeds_highest_confidence_first() -> None:
    """Unseeded FPS starts from the highest-confidence identity."""
    low, high = _identity(1, confidence=0.2), _identity(2, confidence=0.99)

    picked = _select_diverse_representatives([low, high], max_reps=1)

    assert [p.id for p in picked] == [high.id]
