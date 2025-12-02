"""Integration-style tests for complete-link guard behavior."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import numpy as np
import pytest
from numpy.typing import NDArray

from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.representatives.representative_matcher import RepresentativeMatcher

Vector = NDArray[np.float64]


def _normalize(vec: Vector) -> Vector:
    """Return a unit vector."""
    arr = np.asarray(vec, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    return (arr / norm).astype(np.float64)


@pytest.mark.asyncio
async def test_complete_link_logs_and_suggests_when_guard_fails(monkeypatch) -> None:
    """Complete-link failure should log, skip assignment, and create a suggestion."""
    # Strict thresholds to force failure on the weakest rep
    settings = ClusteringSettings(
        complete_link_min_floor=0.90,
        complete_link_avg_threshold=0.95,
        early_stage_suggestion_enabled=False,
    )

    create_suggestion = AsyncMock()
    assign_to_cluster = AsyncMock()
    add_representative = AsyncMock(return_value=None)

    matcher = RepresentativeMatcher(
        threshold=0.70,
        add_representative_embedding=add_representative,
        assign_to_cluster_by_id=assign_to_cluster,
        settings=settings,
        create_suggestion=create_suggestion,
        labeled_cluster_count=50,
    )

    cluster_id = uuid4()
    rep1 = _normalize(np.array([1.0, 0.0] + [0.0] * 510, dtype=np.float32))
    rep2 = _normalize(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32))
    reps = {cluster_id: [rep1, rep2]}

    # Candidate matches rep1 but not rep2 (min similarity should fail the floor)
    candidate_embedding = _normalize(np.array([0.99, 0.05] + [0.0] * 510, dtype=np.float32))

    log_calls: list[dict[str, object]] = []

    def fake_log_complete_link_check(**kwargs) -> None:
        log_calls.append(kwargs)

    monkeypatch.setattr(
        "recognition.application.representatives.representative_matcher.log_complete_link_check",
        fake_log_complete_link_check,
    )

    candidate = MagicMock()
    candidate.id = uuid4()
    candidate.tenant_id = uuid4()
    candidate.embedding = candidate_embedding.tolist()
    candidate.confidence = 0.9
    candidate.bbox_width = 10
    candidate.bbox_height = 10

    assigned, unclustered, _ = await matcher.match([candidate], reps, borderline_upper=0.80)

    # Complete-link failure should create suggestion, not assign or leave unclustered
    assert assigned == 0
    assert len(unclustered) == 0
    create_suggestion.assert_awaited_once()
    assign_to_cluster.assert_not_awaited()

    # Structured complete-link log captured
    assert len(log_calls) == 1
    logged = log_calls[0]
    assert logged["cluster_id"] == cluster_id
    assert logged["identity_id"] == candidate.id
    assert logged["num_reps"] == 2
    assert logged["passed"] is False


@pytest.mark.asyncio
async def test_complete_link_passes_and_assigns_when_all_reps_agree(monkeypatch) -> None:
    """Complete-link pass should assign and log passed=True."""
    settings = ClusteringSettings(
        complete_link_min_floor=0.70,
        complete_link_avg_threshold=0.75,
        early_stage_suggestion_enabled=False,
    )

    create_suggestion = AsyncMock()
    assign_to_cluster = AsyncMock()
    add_representative = AsyncMock(return_value=None)

    matcher = RepresentativeMatcher(
        threshold=0.70,
        add_representative_embedding=add_representative,
        assign_to_cluster_by_id=assign_to_cluster,
        settings=settings,
        create_suggestion=create_suggestion,
        labeled_cluster_count=50,
    )

    cluster_id = uuid4()
    # Representatives tightly clustered near base vector
    base = _normalize(np.array([1.0, 0.0] + [0.0] * 510, dtype=np.float32))
    rep1 = _normalize(base + _normalize(np.random.randn(512)) * 0.01)
    rep2 = _normalize(base + _normalize(np.random.randn(512)) * 0.01)
    reps = {cluster_id: [rep1, rep2]}

    candidate_embedding = _normalize(base + _normalize(np.random.randn(512)) * 0.01)
    candidate = MagicMock()
    candidate.id = uuid4()
    candidate.tenant_id = uuid4()
    candidate.embedding = candidate_embedding.tolist()
    candidate.confidence = 0.95
    candidate.bbox_width = 12
    candidate.bbox_height = 12

    log_calls: list[dict[str, object]] = []

    def fake_log_complete_link_check(**kwargs) -> None:
        log_calls.append(kwargs)

    monkeypatch.setattr(
        "recognition.application.representatives.representative_matcher.log_complete_link_check",
        fake_log_complete_link_check,
    )

    assigned, unclustered, _ = await matcher.match([candidate], reps, borderline_upper=0.90)

    assert assigned == 1
    assert len(unclustered) == 0
    assign_to_cluster.assert_awaited_once()
    create_suggestion.assert_not_awaited()

    assert len(log_calls) == 1
    logged = log_calls[0]
    assert logged["cluster_id"] == cluster_id
    assert logged["identity_id"] == candidate.id
    assert logged["num_reps"] == 2
    assert logged["passed"] is True


@pytest.mark.asyncio
async def test_complete_link_logs_per_tenant(monkeypatch) -> None:
    """Complete-link should emit logs per tenant without cross-contamination."""
    settings = ClusteringSettings(
        complete_link_min_floor=0.85,
        complete_link_avg_threshold=0.90,
        early_stage_suggestion_enabled=False,
    )

    create_suggestion = AsyncMock()
    assign_to_cluster = AsyncMock()
    add_representative = AsyncMock(return_value=None)

    matcher = RepresentativeMatcher(
        threshold=0.80,
        add_representative_embedding=add_representative,
        assign_to_cluster_by_id=assign_to_cluster,
        settings=settings,
        create_suggestion=create_suggestion,
        labeled_cluster_count=10,
    )

    cluster_a = uuid4()
    cluster_b = uuid4()
    rep_anchor = _normalize(np.array([1.0, 0.0] + [0.0] * 510, dtype=np.float32))
    reps = {
        cluster_a: [rep_anchor, _normalize(rep_anchor + _normalize(np.random.randn(512)) * 0.05)],
        cluster_b: [_normalize(np.random.randn(512)), _normalize(np.random.randn(512))],
    }

    tenant_a = uuid4()
    tenant_b = uuid4()
    candidate_a = MagicMock()
    candidate_a.id = uuid4()
    candidate_a.tenant_id = tenant_a
    candidate_a.embedding = rep_anchor.tolist()
    candidate_a.confidence = 0.9
    candidate_a.bbox_width = 10
    candidate_a.bbox_height = 10

    candidate_b_vec = reps[cluster_b][0]
    candidate_b = MagicMock()
    candidate_b.id = uuid4()
    candidate_b.tenant_id = tenant_b
    candidate_b.embedding = candidate_b_vec.tolist()
    candidate_b.confidence = 0.9
    candidate_b.bbox_width = 10
    candidate_b.bbox_height = 10

    log_calls: list[dict[str, object]] = []

    def fake_log_complete_link_check(**kwargs) -> None:
        log_calls.append(kwargs)

    monkeypatch.setattr(
        "recognition.application.representatives.representative_matcher.log_complete_link_check",
        fake_log_complete_link_check,
    )

    await matcher.match([candidate_a, candidate_b], reps, borderline_upper=0.95)

    # Should log one entry per candidate with correct tenant ids
    tenant_ids = {call["tenant_id"] for call in log_calls}
    assert tenant_ids == {tenant_a, tenant_b}
    assert len(log_calls) == 2


def test_complete_link_performance_large_rep_set() -> None:
    """Complete-link check should remain fast with large representative sets."""
    rng = np.random.default_rng(42)
    settings = ClusteringSettings(
        complete_link_min_floor=0.60,
        complete_link_avg_threshold=0.65,
    )
    matcher = RepresentativeMatcher(
        threshold=0.60,
        add_representative_embedding=AsyncMock(),  # not used
        assign_to_cluster_by_id=AsyncMock(),  # not used
        settings=settings,
        labeled_cluster_count=100,
    )

    cluster_id = uuid4()
    reps: list[np.ndarray] = []
    base = _normalize(rng.standard_normal(512).astype(np.float32))
    # Generate many reps near the same base vector to guarantee pass
    for _ in range(50):
        noise = rng.normal(0, 0.02, size=512).astype(np.float32)
        reps.append(_normalize(base + noise))
    representatives = {cluster_id: reps}

    candidate_vec = _normalize(base + rng.normal(0, 0.01, size=512).astype(np.float32))

    start = time.perf_counter()
    passed, _, _, duration_ms = matcher._check_complete_link(candidate_vec, cluster_id, representatives)
    duration_ms = (time.perf_counter() - start) * 1000

    assert passed is True
    # Generous threshold to avoid flakes in CI
    assert duration_ms < 50.0


def test_complete_link_under_10ms_small_rep_set() -> None:
    """Complete-link check should be sub-10ms for modest representative sets."""
    rng = np.random.default_rng(7)
    settings = ClusteringSettings(
        complete_link_min_floor=0.65,
        complete_link_avg_threshold=0.70,
    )
    matcher = RepresentativeMatcher(
        threshold=0.65,
        add_representative_embedding=AsyncMock(),  # not used
        assign_to_cluster_by_id=AsyncMock(),  # not used
        settings=settings,
        labeled_cluster_count=25,
    )

    cluster_id = uuid4()
    base = _normalize(rng.standard_normal(512))
    reps = [_normalize(base + rng.normal(0, 0.02, size=512)) for _ in range(20)]
    representatives = {cluster_id: reps}
    candidate_vec = _normalize(base + rng.normal(0, 0.01, size=512))

    start = time.perf_counter()
    passed, _, _, duration_ms = matcher._check_complete_link(candidate_vec, cluster_id, representatives)
    duration_ms = (time.perf_counter() - start) * 1000

    assert passed is True
    assert duration_ms < 10.0
