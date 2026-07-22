"""FIR-6 S2: within-photo one-to-one conflict resolution + threshold rebinding.

Covers plan items 1–5: scipy import, pure solver, orchestrator wiring/partition
rebinding, photo-atomic chunking, persistent uniqueness guard, knob-off parity,
and per-knob discrimination through profile-resolved consumers.
"""

from __future__ import annotations

import importlib

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.assignment.gate import AssignmentGate
from recognition.application.assignment.joint import (
    group_accepted_by_media,
    resolve_photo_conflicts,
)
from recognition.application.discovery.centroid import CentroidDiscovery
from recognition.application.discovery.graph.selection import select_algorithm
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.orchestration.clustering.chunked_processor import ChunkedIdentityProcessor
from recognition.application.orchestration.clustering.discovery_pipeline import partition_unclustered
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings import ClusteringSettings
from recognition.config.settings import (
    ClusteringLimitsSettings,
    FacePipelineSettings,
    IdentityDetectionSettings,
    apply_resolved_clustering_settings,
    apply_resolved_detection_settings,
    apply_resolved_limits_settings,
    resolve_face_pipeline_knobs,
)
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import IdentityMember
from recognition.shared.ids import generate_id
from recognition.tests.stubs import NullClusterRepository


def test_scipy_importable_clean_env() -> None:
    """rg-001: scipy is a declared dependency and importable (clean-env proof)."""
    scipy = importlib.import_module("scipy")
    linear_sum_assignment = importlib.import_module("scipy.optimize").linear_sum_assignment
    assert scipy is not None
    assert callable(linear_sum_assignment)


def _identity(
    *,
    identity_id: str | None = None,
    media_id: str = "media-1",
    confidence: float = 0.9,
    embedding: np.ndarray | None = None,
) -> MediaIdentity:
    vec = embedding if embedding is not None else np.ones(4, dtype=np.float32)
    return MediaIdentity(
        id=identity_id or str(generate_id()),
        tenant_id="tenant-1",
        media_id=media_id,
        embedding=vec,
        confidence=confidence,
        bbox_width=10,
        bbox_height=10,
    )


def _accept(
    identity: MediaIdentity,
    *,
    cluster_id: str,
    similarity: float,
) -> AssignmentDecision:
    candidate = AssignmentCandidate(
        identity=identity,
        identity_vector=identity.face_vector,
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=similarity,
    )
    return AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=["confidence"],
        checks_failed=[],
    )


def test_duplicate_identity_photo_one_to_one_loser_unknown() -> None:
    """TEST-15: two faces in one photo accepted for same cluster → one winner."""
    winner = _identity(identity_id="face-hi", media_id="photo-a", confidence=0.95)
    loser = _identity(identity_id="face-lo", media_id="photo-a", confidence=0.80)
    decisions = [
        _accept(winner, cluster_id="cluster-x", similarity=0.92),
        _accept(loser, cluster_id="cluster-x", similarity=0.81),
    ]
    result = resolve_photo_conflicts(group_accepted_by_media(decisions))

    assert len(result.accepted) == 1
    assert result.accepted[0].candidate.identity.id == "face-hi"
    assert result.loser_identity_ids == frozenset({"face-lo"})


def test_conflict_loser_reaches_partition_not_orphan() -> None:
    """GR2-01: losers excluded from accepted_ids flow into still_unclustered."""
    a = _identity(identity_id="a", media_id="p1")
    b = _identity(identity_id="b", media_id="p1")
    c = _identity(identity_id="c", media_id="p2")
    chunk = [a, b, c]
    decisions = [
        _accept(a, cluster_id="cl", similarity=0.9),
        _accept(b, cluster_id="cl", similarity=0.7),
        _accept(c, cluster_id="cl2", similarity=0.88),
    ]
    result = resolve_photo_conflicts(group_accepted_by_media(decisions))
    accepted_ids = {d.candidate.identity.id for d in result.accepted}

    part = partition_unclustered(
        chunk=chunk,
        accepted_ids=accepted_ids,
        suggested_ids=set(),
        rejected_ids=set(),
        new_cluster_proposals=[],
    )
    still_ids = {i.id for i in part.still_unclustered}
    assert "b" in still_ids
    assert "a" not in still_ids
    assert "c" not in still_ids
    assert "b" in result.loser_identity_ids


def test_all_below_threshold_empty_matrix_no_crash() -> None:
    """LC-11: empty accepted set (all-below-threshold photo) does not crash."""
    result = resolve_photo_conflicts({})
    assert result.accepted == []
    assert result.loser_identity_ids == frozenset()

    result2 = resolve_photo_conflicts({"media": []})
    assert result2.accepted == []
    assert result2.loser_identity_ids == frozenset()


def test_single_face_photo_unchanged() -> None:
    face = _identity(identity_id="only", media_id="solo")
    decision = _accept(face, cluster_id="c1", similarity=0.9)
    result = resolve_photo_conflicts(group_accepted_by_media([decision]))
    assert len(result.accepted) == 1
    assert result.accepted[0].candidate.identity.id == "only"
    assert result.loser_identity_ids == frozenset()


def test_distinct_clusters_same_photo_all_kept() -> None:
    a = _identity(identity_id="a", media_id="p")
    b = _identity(identity_id="b", media_id="p")
    decisions = [
        _accept(a, cluster_id="c1", similarity=0.9),
        _accept(b, cluster_id="c2", similarity=0.85),
    ]
    result = resolve_photo_conflicts(group_accepted_by_media(decisions))
    assert {d.candidate.identity.id for d in result.accepted} == {"a", "b"}
    assert result.loser_identity_ids == frozenset()


def test_photo_atomic_chunking_never_splits_media() -> None:
    # Confidence ordering would interleave media without photo_atomic.
    identities = [
        _identity(identity_id="a1", media_id="m1", confidence=0.99),
        _identity(identity_id="b1", media_id="m2", confidence=0.98),
        _identity(identity_id="a2", media_id="m1", confidence=0.50),
        _identity(identity_id="b2", media_id="m2", confidence=0.49),
        _identity(identity_id="c1", media_id="m3", confidence=0.40),
    ]
    processor = ChunkedIdentityProcessor(identities, photo_atomic=True)
    # Force tiny chunks so non-atomic mode would split.
    processor._adaptive_size = 1  # noqa: SLF001 — test forces small chunk budget

    chunks = [chunk for chunk, _ in processor.iter_chunks()]
    for chunk in chunks:
        media_ids = {i.media_id for i in chunk}
        # Every media_id present must appear with all its faces in this chunk only.
        for media_id in media_ids:
            in_chunk = [i.id for i in chunk if i.media_id == media_id]
            all_for_media = [i.id for i in identities if i.media_id == media_id]
            assert set(in_chunk) == set(all_for_media)


def test_photo_atomic_off_matches_confidence_slice_sizes() -> None:
    identities = [_identity(identity_id=str(i), media_id=str(i), confidence=1.0) for i in range(30)]
    processor = ChunkedIdentityProcessor(identities, photo_atomic=False)
    sizes = [len(chunk) for chunk, _ in processor.iter_chunks()]
    assert sizes == [5, 5, 5, 5, 10]


@pytest.mark.asyncio
async def test_persistent_guard_rejects_second_batch_duplicate() -> None:
    """Second-batch same-media face rejected under joint_uniqueness_enabled."""
    existing = _identity(identity_id="existing", media_id="photo-dup")
    cluster = IdentityCluster(
        id="cluster-1",
        tenant_id="tenant-1",
        is_labeled=False,
        label=None,
        centroid=None,
        identity_count=1,
    )
    repo = NullClusterRepository(
        clusters_by_id={"cluster-1": cluster},
        member_identities_by_cluster={"cluster-1": [existing]},
    )

    class _MemberRepo:
        def __init__(self) -> None:
            self.bulk_calls: list[tuple[str, list]] = []

        async def bulk_add_members_if_not_exists(self, cluster_id, members):
            self.bulk_calls.append((cluster_id, list(members)))
            created = [
                IdentityMember(
                    id=f"m-{m.identity_id}",
                    cluster_id=cluster_id,
                    identity_id=m.identity_id,
                    similarity=m.similarity,
                )
                for m in members
            ]
            return created, 0

    member_repo = _MemberRepo()
    writer = AssignmentWriter(ClusteringSettings(), repo, member_repo)

    new_face = _identity(identity_id="new-dup", media_id="photo-dup")
    other = _identity(identity_id="other", media_id="photo-other")
    decisions = [
        _accept(new_face, cluster_id="cluster-1", similarity=0.95),
        _accept(other, cluster_id="cluster-1", similarity=0.90),
    ]

    # Guard off (insightface parity): both attempt insert.
    p0, s0, r0, rejected0 = await writer.persist_assignments_chunk(
        decisions, joint_uniqueness_enabled=False
    )
    assert rejected0 == set()
    assert p0 == 2

    member_repo.bulk_calls.clear()
    p1, s1, r1, rejected1 = await writer.persist_assignments_chunk(
        decisions, joint_uniqueness_enabled=True
    )
    assert rejected1 == {"new-dup"}
    assert p1 == 1
    # Only the non-duplicate was bulk-inserted.
    assert len(member_repo.bulk_calls) == 1
    assert {m.identity_id for m in member_repo.bulk_calls[0][1]} == {"other"}


def _resolve_and_apply(
    face: FacePipelineSettings,
    *,
    clustering: ClusteringSettings | None = None,
    limits: ClusteringLimitsSettings | None = None,
    detection: IdentityDetectionSettings | None = None,
) -> tuple[ClusteringSettings, ClusteringLimitsSettings, IdentityDetectionSettings]:
    clustering = clustering or ClusteringSettings()
    limits = limits or ClusteringLimitsSettings()
    detection = detection or IdentityDetectionSettings()
    knobs = resolve_face_pipeline_knobs(
        face_pipeline=face,
        clustering=clustering,
        clustering_limits=limits,
        identity_detection=detection,
    )
    return (
        apply_resolved_clustering_settings(clustering, knobs),
        apply_resolved_limits_settings(limits, knobs),
        apply_resolved_detection_settings(detection, knobs),
    )


@pytest.mark.parametrize(
    "override_field,knob_attr,value",
    [
        ("face_similarity_threshold", "similarity_threshold", 0.77),
        ("face_complete_link_threshold", "complete_link_threshold", 0.66),
        ("face_suggestion_floor", "suggestion_floor", 0.22),
        ("face_suggestion_ceiling", "suggestion_ceiling", 0.88),
        ("face_limits_similarity_threshold", "limits_similarity_threshold", 0.73),
        ("face_detection_default_threshold", "detection_default_threshold", 0.41),
    ],
)
def test_per_knob_rebinding_discrimination(override_field: str, knob_attr: str, value: float) -> None:
    """Mutate each face_* override → moves under face_pipeline only."""
    clustering = ClusteringSettings(
        similarity_threshold=0.55,
        complete_link_threshold=0.45,
        suggestion_floor=0.35,
        suggestion_ceiling=0.55,
    )
    limits = ClusteringLimitsSettings(similarity_threshold=0.6)
    detection = IdentityDetectionSettings(default_threshold=0.45)

    face_on = FacePipelineSettings(profile="face_pipeline", **{override_field: value})
    face_off = FacePipelineSettings(profile="insightface", **{override_field: value})

    cl_on, lim_on, det_on = _resolve_and_apply(
        face_on, clustering=clustering, limits=limits, detection=detection
    )
    cl_off, lim_off, det_off = _resolve_and_apply(
        face_off, clustering=clustering, limits=limits, detection=detection
    )

    if knob_attr == "similarity_threshold":
        assert cl_on.similarity_threshold == value
        assert cl_off.similarity_threshold == clustering.similarity_threshold
        # Discovery consumers observe the rebinding via settings.
        assert CentroidDiscovery(cl_on).settings.similarity_threshold == value
        assert CentroidDiscovery(cl_off).settings.similarity_threshold == clustering.similarity_threshold
        assert RepresentativeDiscovery(cl_on).settings.similarity_threshold == value
        # Gate construction consumes resolved settings.
        gate = AssignmentGate(settings=cl_on, cluster_repository=NullClusterRepository())
        assert gate.settings.similarity_threshold == value
    elif knob_attr == "complete_link_threshold":
        assert cl_on.complete_link_threshold == value
        assert cl_off.complete_link_threshold == clustering.complete_link_threshold
    elif knob_attr == "suggestion_floor":
        assert cl_on.suggestion_floor == value
        assert cl_off.suggestion_floor == clustering.suggestion_floor
    elif knob_attr == "suggestion_ceiling":
        assert cl_on.suggestion_ceiling == value
        assert cl_off.suggestion_ceiling == clustering.suggestion_ceiling
    elif knob_attr == "limits_similarity_threshold":
        assert lim_on.similarity_threshold == value
        assert lim_off.similarity_threshold == limits.similarity_threshold
    elif knob_attr == "detection_default_threshold":
        assert det_on.default_threshold == value
        assert det_off.default_threshold == detection.default_threshold


def test_graph_selection_uses_resolved_similarity_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """graph/selection.py reads settings.similarity_threshold for HDBSCAN epsilon."""
    monkeypatch.setattr(
        "recognition.application.discovery.graph.selection.hdbscan_available",
        lambda: True,
    )

    class _FakeAlgo:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(
        "recognition.infrastructure.clustering.HdbscanGraphAlgorithm",
        _FakeAlgo,
        raising=False,
    )
    # Import path used inside select_algorithm
    import recognition.infrastructure.clustering as clustering_mod

    monkeypatch.setattr(clustering_mod, "HdbscanGraphAlgorithm", _FakeAlgo, raising=False)

    settings = ClusteringSettings(similarity_threshold=0.75)
    algo = select_algorithm(algorithm=None, settings=settings)
    # epsilon = sqrt(2*(1-cosine))
    expected = (2.0 * (1.0 - 0.75)) ** 0.5
    assert abs(algo.kwargs["cluster_selection_epsilon"] - expected) < 1e-9


@pytest.mark.asyncio
async def test_joint_knob_off_parity_via_solver_identity() -> None:
    """When joint is conceptually off, accepted set is unchanged (solver not applied).

    The orchestrator gates on profile+knob; this pins the pure-function contract:
    no conflict ⇒ bit-identical accepted set (knob-off equivalent for non-conflict).
    """
    a = _identity(identity_id="a", media_id="m1")
    b = _identity(identity_id="b", media_id="m2")
    decisions = [
        _accept(a, cluster_id="c1", similarity=0.9),
        _accept(b, cluster_id="c2", similarity=0.8),
    ]
    result = resolve_photo_conflicts(group_accepted_by_media(decisions))
    assert {d.candidate.identity.id for d in result.accepted} == {"a", "b"}
    assert result.loser_identity_ids == frozenset()
