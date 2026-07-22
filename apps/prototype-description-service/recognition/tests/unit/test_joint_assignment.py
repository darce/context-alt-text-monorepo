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
    """Non-conflict path: pure solver leaves both faces accepted (identity fallback)."""
    a = _identity(identity_id="a", media_id="m1")
    b = _identity(identity_id="b", media_id="m2")
    decisions = [
        _accept(a, cluster_id="c1", similarity=0.9),
        _accept(b, cluster_id="c2", similarity=0.8),
    ]
    result = resolve_photo_conflicts(group_accepted_by_media(decisions))
    assert {d.candidate.identity.id for d in result.accepted} == {"a", "b"}
    assert result.loser_identity_ids == frozenset()


def test_equal_similarity_tie_is_deterministic() -> None:
    """Equal discovery scores resolve by confidence then identity id (not input order)."""
    lo_conf = _identity(identity_id="face-z", media_id="photo-tie", confidence=0.50)
    hi_conf = _identity(identity_id="face-a", media_id="photo-tie", confidence=0.90)
    # Same similarity; reverse input order should not flip the winner.
    for order in (
        [
            _accept(lo_conf, cluster_id="cluster-x", similarity=0.85),
            _accept(hi_conf, cluster_id="cluster-x", similarity=0.85),
        ],
        [
            _accept(hi_conf, cluster_id="cluster-x", similarity=0.85),
            _accept(lo_conf, cluster_id="cluster-x", similarity=0.85),
        ],
    ):
        result = resolve_photo_conflicts(group_accepted_by_media(order))
        assert len(result.accepted) == 1
        assert result.accepted[0].candidate.identity.id == "face-a"
        assert result.loser_identity_ids == frozenset({"face-z"})


def test_equal_sim_equal_conf_prefers_lexicographically_smaller_id() -> None:
    """FIR6RC-04: LAP tertiary tie-break sign prefers lex-smaller identity id."""
    smaller = _identity(identity_id="face-a", media_id="photo-lex", confidence=0.80)
    larger = _identity(identity_id="face-z", media_id="photo-lex", confidence=0.80)
    for order in (
        [
            _accept(larger, cluster_id="cluster-x", similarity=0.85),
            _accept(smaller, cluster_id="cluster-x", similarity=0.85),
        ],
        [
            _accept(smaller, cluster_id="cluster-x", similarity=0.85),
            _accept(larger, cluster_id="cluster-x", similarity=0.85),
        ],
    ):
        result = resolve_photo_conflicts(group_accepted_by_media(order))
        assert len(result.accepted) == 1
        assert result.accepted[0].candidate.identity.id == "face-a"
        assert result.loser_identity_ids == frozenset({"face-z"})


def test_sentinel_post_filter_when_faces_exceed_clusters() -> None:
    """Rectangular matrix with one real cluster: LAP may assign a sentinel; drop it."""
    # Three faces compete for one cluster; only one real edge column exists.
    # Losers must not stay accepted via a sentinel column assignment.
    f1 = _identity(identity_id="f1", media_id="p", confidence=0.99)
    f2 = _identity(identity_id="f2", media_id="p", confidence=0.80)
    f3 = _identity(identity_id="f3", media_id="p", confidence=0.70)
    decisions = [
        _accept(f1, cluster_id="only", similarity=0.95),
        _accept(f2, cluster_id="only", similarity=0.90),
        _accept(f3, cluster_id="only", similarity=0.85),
    ]
    result = resolve_photo_conflicts(group_accepted_by_media(decisions))
    assert len(result.accepted) == 1
    assert result.accepted[0].candidate.identity.id == "f1"
    assert result.loser_identity_ids == frozenset({"f2", "f3"})


def test_active_faces_predrop_routes_unconnected_to_unknown() -> None:
    """FIR6RC-05: faces with only non-finite edges are pre-dropped as losers (LC-11).

    NaN similarity yields a non-comparable cost cell that fails the active-edge
    threshold (top-k all-below-threshold proxy). A real cluster conflict forces
    the LAP path so the unique-face/unique-cluster fast path cannot skip it.
    """
    hi = _identity(identity_id="hi", media_id="p", confidence=0.95)
    lo = _identity(identity_id="lo", media_id="p", confidence=0.85)
    orphan = _identity(identity_id="orphan", media_id="p", confidence=0.90)
    decisions = [
        _accept(hi, cluster_id="c1", similarity=0.91),
        _accept(lo, cluster_id="c1", similarity=0.80),  # conflict → LAP path
        _accept(orphan, cluster_id="c2", similarity=float("nan")),
    ]
    result = resolve_photo_conflicts(group_accepted_by_media(decisions))
    accepted_ids = {d.candidate.identity.id for d in result.accepted}
    assert accepted_ids == {"hi"}
    assert result.loser_identity_ids == frozenset({"lo", "orphan"})
    assert result.accepted[0].candidate.cluster_id == "c1"


def test_multi_edge_same_photo_keeps_distinct_clusters() -> None:
    """Distinct-cluster multi-edge path: both faces kept with best edges."""
    a = _identity(identity_id="a", media_id="p", confidence=0.9)
    b = _identity(identity_id="b", media_id="p", confidence=0.8)
    decisions = [
        _accept(a, cluster_id="c1", similarity=0.91),
        _accept(a, cluster_id="c2", similarity=0.50),  # worse edge for a
        _accept(b, cluster_id="c2", similarity=0.88),
    ]
    result = resolve_photo_conflicts(group_accepted_by_media(decisions))
    accepted_ids = {d.candidate.identity.id for d in result.accepted}
    assert "a" in accepted_ids
    assert "b" in accepted_ids
    assert result.loser_identity_ids == frozenset()
    by_face = {d.candidate.identity.id: d.candidate.cluster_id for d in result.accepted}
    assert by_face["a"] == "c1"
    assert by_face["b"] == "c2"


@pytest.mark.asyncio
async def test_guard_exempts_own_identity_on_retry() -> None:
    """Idempotent re-persist: identity already in target cluster is not guard-rejected."""
    existing = _identity(identity_id="same-face", media_id="photo-retry")
    other_existing = _identity(identity_id="other-face", media_id="photo-other")
    cluster = IdentityCluster(
        id="cluster-1",
        tenant_id="tenant-1",
        is_labeled=False,
        label=None,
        centroid=None,
        identity_count=2,
    )
    repo = NullClusterRepository(
        clusters_by_id={"cluster-1": cluster},
        member_identities_by_cluster={"cluster-1": [existing, other_existing]},
    )

    class _MemberRepo:
        def __init__(self) -> None:
            self.bulk_calls: list[tuple[str, list]] = []

        async def bulk_add_members_if_not_exists(self, cluster_id, members):
            self.bulk_calls.append((cluster_id, list(members)))
            # ON CONFLICT skip path: report 0 created for the retry identity.
            return [], len(members)

    member_repo = _MemberRepo()
    writer = AssignmentWriter(ClusteringSettings(), repo, member_repo)

    # Re-process the same face after partial persist — must not be guard-rejected.
    retry = _accept(existing, cluster_id="cluster-1", similarity=0.95)
    # A true same-photo new face should still be rejected.
    new_dup = _accept(
        _identity(identity_id="new-dup", media_id="photo-retry"),
        cluster_id="cluster-1",
        similarity=0.90,
    )
    _p, _s, _r, rejected = await writer.persist_assignments_chunk(
        [retry, new_dup], joint_uniqueness_enabled=True
    )
    assert "same-face" not in rejected
    assert "new-dup" in rejected


def test_production_limits_and_detection_readers_rebind(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production resolve_effective_* helpers rebind limits + detection under face_pipeline."""
    # Function-local imports for ALL settings classes: the knob env-ingestion
    # tests importlib.reload() recognition.config.settings, so module-level
    # class objects go stale mid-suite and pydantic isinstance checks fail.
    from recognition.application.orchestration.split import hierarchical as hierarchical_mod
    from recognition.config.settings import (
        ClusteringLimitsSettings,
        ClusteringSettings,
        FacePipelineSettings,
        IdentityDetectionSettings,
        RecognitionSettings,
        resolve_effective_detection_settings,
        resolve_effective_limits_settings,
    )

    base = RecognitionSettings(
        face_pipeline=FacePipelineSettings(
            profile="face_pipeline",
            face_limits_similarity_threshold=0.80,
            face_detection_default_threshold=0.33,
        ),
        clustering_limits=ClusteringLimitsSettings(similarity_threshold=0.6),
        identity_detection=IdentityDetectionSettings(default_threshold=0.45),
    )
    lim = resolve_effective_limits_settings(recognition=base)
    det = resolve_effective_detection_settings(recognition=base)
    assert lim.similarity_threshold == 0.80
    assert det.default_threshold == 0.33
    # Real production getter (FIR6RC-03) — not a re-derived tautological formula.
    monkeypatch.setattr(
        hierarchical_mod,
        "resolve_effective_limits_settings",
        lambda: lim,
    )
    assert hierarchical_mod._split_distance_threshold() == pytest.approx(0.20)

    insight = RecognitionSettings(
        face_pipeline=FacePipelineSettings(
            profile="insightface",
            face_limits_similarity_threshold=0.80,
            face_detection_default_threshold=0.33,
        ),
        clustering_limits=ClusteringLimitsSettings(similarity_threshold=0.6),
        identity_detection=IdentityDetectionSettings(default_threshold=0.45),
    )
    lim_off = resolve_effective_limits_settings(recognition=insight)
    det_off = resolve_effective_detection_settings(recognition=insight)
    assert lim_off.similarity_threshold == 0.6
    assert det_off.default_threshold == 0.45
    monkeypatch.setattr(
        hierarchical_mod,
        "resolve_effective_limits_settings",
        lambda: lim_off,
    )
    # insightface keeps shared 0.6 → distance min(0.30, 0.4) = 0.30.
    assert hierarchical_mod._split_distance_threshold() == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_orchestrator_joint_wiring_discriminates_on_knob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_process_single_chunk: joint ON drops same-photo loser; OFF keeps both (M-01).

    FIR6RC-02: also pins uniqueness-guard plumbing (joint_uniqueness_enabled
    forwarded) and rejected-id rebind into the new-cluster partition.
    FIR6RC-05: joint OFF keeps a *real conflict* pair (both faces persist).
    """
    from types import SimpleNamespace

    from recognition.application.orchestration.clustering import orchestrator as orch_mod
    from recognition.application.orchestration.clustering.orchestrator import (
        IncrementalClusteringRunner,
    )

    winner = _identity(identity_id="face-hi", media_id="photo-a", confidence=0.95)
    loser = _identity(identity_id="face-lo", media_id="photo-a", confidence=0.80)
    # Third face: no conflict, used to exercise guard rejection rebind (FIR6RC-02).
    guard_victim = _identity(identity_id="face-guard", media_id="photo-b", confidence=0.88)
    chunk = [winner, loser, guard_victim]
    conflict_decisions = [
        _accept(winner, cluster_id="cluster-x", similarity=0.92),
        _accept(loser, cluster_id="cluster-x", similarity=0.81),
        _accept(guard_victim, cluster_id="cluster-y", similarity=0.90),
    ]

    class _GateResult:
        def __init__(self, decisions: list[AssignmentDecision]) -> None:
            self.accepted_decisions = list(decisions)
            self.accepted_ids = {d.candidate.identity.id for d in decisions}
            self.suggested_ids: set[str] = set()
            self.rejected_ids: set[str] = set()
            self.accept_count = len(decisions)
            self.suggest_count = 0
            self.reject_count = 0

    async def _fake_discovery(**kwargs):
        return [], []

    async def _fake_evaluate(*, all_candidates, decision_handler, job_id, job_label, verbose):
        return _GateResult(conflict_decisions)

    persisted_batches: list[list[str]] = []
    guard_flags: list[bool] = []

    class _Writer:
        async def persist_assignments_chunk(self, decisions, *, batch_mode=True, joint_uniqueness_enabled=False):
            persisted_batches.append([d.candidate.identity.id for d in decisions])
            guard_flags.append(bool(joint_uniqueness_enabled))
            # When guard is active, reject face-guard so rebind is exercised.
            rejected = {"face-guard"} if joint_uniqueness_enabled else set()
            kept = len(decisions) - len(rejected)
            return kept, 0, 0, rejected

    class _Suggestions:
        async def resolve_for_identity_exclusive(self, **kwargs):
            return None

    created_from: list[list[str]] = []

    async def _fake_create(*, still_unclustered, **kwargs):
        created_from.append([i.id for i in still_unclustered])
        return 0, []

    async def _fake_commit(**kwargs):
        return None

    processor = ChunkedIdentityProcessor(chunk, photo_atomic=True)
    job = SimpleNamespace(payload={}, processed_identities=None, progress=None)

    runner = object.__new__(IncrementalClusteringRunner)
    runner._assignment_writer = _Writer()  # type: ignore[attr-defined]
    runner._suggestion_service = _Suggestions()  # type: ignore[attr-defined]
    runner._decision_handler = object()  # type: ignore[attr-defined]
    runner._representative_discovery = object()  # type: ignore[attr-defined]
    runner._centroid_discovery = object()  # type: ignore[attr-defined]
    runner._graph_discovery = object()  # type: ignore[attr-defined]
    runner._progress_callback = None  # type: ignore[attr-defined]
    monkeypatch.setattr(runner, "_create_new_clusters_for_chunk", _fake_create)
    monkeypatch.setattr(runner, "_commit_chunk_progress", _fake_commit)
    monkeypatch.setattr(orch_mod, "run_discovery_pipeline", _fake_discovery)
    monkeypatch.setattr(orch_mod, "evaluate_chunk_candidates", _fake_evaluate)

    # --- joint ON: conflict loser + guard reject rebind to new-cluster partition ---
    monkeypatch.setattr(orch_mod, "_joint_assignment_active", lambda: True)
    persisted_batches.clear()
    created_from.clear()
    guard_flags.clear()
    await runner._process_single_chunk(
        chunk=chunk,
        processed_before=0,
        clusters_created_before=0,
        representatives_by_cluster={},
        centroids_by_cluster={},
        labeled_cluster_ids=set(),
        tenant_id="tenant-1",
        job_id="job-1",
        job_label="test",
        clustering_job=job,  # type: ignore[arg-type]
        processor=processor,
        total_identities=3,
        run_ctx=None,
        verbose=False,
    )
    # Joint solver drops face-lo before persist; face-hi + face-guard reach writer.
    assert persisted_batches == [["face-hi", "face-guard"]]
    assert guard_flags == [True]  # uniqueness guard plumbing
    # Both joint loser and guard-rejected id must rebind into create partition.
    flat_created = {i for batch in created_from for i in batch}
    assert "face-lo" in flat_created
    assert "face-guard" in flat_created
    assert "face-hi" not in flat_created

    # --- joint OFF on a real conflict: both conflict faces persist; guard off ---
    monkeypatch.setattr(orch_mod, "_joint_assignment_active", lambda: False)
    persisted_batches.clear()
    created_from.clear()
    guard_flags.clear()
    await runner._process_single_chunk(
        chunk=chunk,
        processed_before=0,
        clusters_created_before=0,
        representatives_by_cluster={},
        centroids_by_cluster={},
        labeled_cluster_ids=set(),
        tenant_id="tenant-1",
        job_id="job-1",
        job_label="test",
        clustering_job=job,  # type: ignore[arg-type]
        processor=processor,
        total_identities=3,
        run_ctx=None,
        verbose=False,
    )
    assert set(persisted_batches[0]) == {"face-hi", "face-lo", "face-guard"}
    assert guard_flags == [False]
    assert all("face-lo" not in ids for ids in created_from)
    assert all("face-guard" not in ids for ids in created_from)


def test_per_knob_rebinding_via_production_resolvers() -> None:
    """limits + detection discrimination goes through production resolve_effective_* readers."""
    # Function-local imports for ALL settings classes: the knob env-ingestion
    # tests importlib.reload() recognition.config.settings, so module-level
    # class objects go stale mid-suite and pydantic isinstance checks fail.
    from recognition.config.settings import (
        ClusteringLimitsSettings,
        ClusteringSettings,
        FacePipelineSettings,
        IdentityDetectionSettings,
        RecognitionSettings,
        resolve_effective_detection_settings,
        resolve_effective_limits_settings,
    )

    clustering = ClusteringSettings()
    limits = ClusteringLimitsSettings(similarity_threshold=0.6)
    detection = IdentityDetectionSettings(default_threshold=0.45)

    face_on = FacePipelineSettings(
        profile="face_pipeline",
        face_limits_similarity_threshold=0.73,
        face_detection_default_threshold=0.41,
    )
    face_off = FacePipelineSettings(
        profile="insightface",
        face_limits_similarity_threshold=0.73,
        face_detection_default_threshold=0.41,
    )
    rec_on = RecognitionSettings(
        face_pipeline=face_on, clustering=clustering, clustering_limits=limits, identity_detection=detection
    )
    rec_off = RecognitionSettings(
        face_pipeline=face_off, clustering=clustering, clustering_limits=limits, identity_detection=detection
    )
    assert resolve_effective_limits_settings(recognition=rec_on).similarity_threshold == 0.73
    assert resolve_effective_limits_settings(recognition=rec_off).similarity_threshold == 0.6
    assert resolve_effective_detection_settings(recognition=rec_on).default_threshold == 0.41
    assert resolve_effective_detection_settings(recognition=rec_off).default_threshold == 0.45
