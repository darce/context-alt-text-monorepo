"""FIR23-01: discovery must not cosine across embedding spaces (CVUP1-GR-02 / R3)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.orchestration.clustering.discovery_pipeline import (
    GalleryProvenanceStats,
    _load_representative_embedding_models,
    _resolve_assignment_session,
    prepare_cluster_caches,
    run_discovery_pipeline,
)
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


def _make_settings(threshold: float = 0.5) -> ClusteringSettings:
    return ClusteringSettings(
        similarity_threshold=threshold,
        complete_link_min_floor=0.75,
        complete_link_avg_threshold=0.85,
        min_representatives_for_maturity=2,
        member_validation_min_floor=0.8,
        member_validation_avg_threshold=0.85,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.9,
        hdbscan_max_batch_size=None,
    )


def _make_identity(vec: np.ndarray) -> MediaIdentity:
    return MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=vec,
        confidence=0.95,
        bbox_width=100,
        bbox_height=100,
    )


def _cluster(
    cluster_id: str,
    *,
    embedding: np.ndarray,
    embedding_model: str | None,
    label: str | None = None,
    user_confirmed: bool = False,
    centroid: np.ndarray | None = None,
    extra_reps: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    rep = SimpleNamespace(
        embedding=embedding,
        identity_id=str(generate_id()),
    )
    # Domain ClusterRepresentative has no embedding_model field; only set when
    # the test intentionally stamps provenance on the stub rep.
    if embedding_model is not None:
        rep.embedding_model = embedding_model
    reps = [rep]
    if extra_reps:
        reps.extend(extra_reps)
    return SimpleNamespace(
        id=cluster_id,
        label=label,
        user_confirmed=user_confirmed,
        representatives=reps,
        centroid=centroid if centroid is not None else embedding,
    )


class _FakeWriter:
    def __init__(self, clusters: list[object]) -> None:
        self.cluster_repository = SimpleNamespace(
            get_by_tenant=AsyncMock(return_value=clusters),
            _session=None,
        )
        # Tests reassign this to session doubles; keep it open so mypy does not
        # pin the attribute to None.
        self._session: Any = None


class _NestedSavepointCM:
    """Async context manager mirroring session.begin_nested() (R3-G2-3)."""

    def __init__(self, session: _TxnAwareSession) -> None:
        self._session = session

    async def __aenter__(self) -> _NestedSavepointCM:
        self._session._in_savepoint = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        self._session._in_savepoint = False
        # Savepoint rollback recovers the outer txn.
        return False


class _TxnAwareSession:
    """Session mock that aborts the outer txn when execute fails outside a savepoint.

    Mirrors PostgreSQL: a failed statement aborts the enclosing transaction unless
    isolated by a savepoint (begin_nested). Used to prove R3-G2-3 wiring.
    """

    def __init__(self, *, error: BaseException | None = None, rows: list | None = None) -> None:
        self._error = error
        self._rows = rows if rows is not None else []
        self._aborted = False
        self._in_savepoint = False
        self.begin_nested_calls = 0
        self.execute = AsyncMock(side_effect=self._execute)

    def begin_nested(self) -> _NestedSavepointCM:
        self.begin_nested_calls += 1
        return _NestedSavepointCM(self)

    async def _execute(self, stmt, *args, **kwargs):  # noqa: ANN001, ANN002
        if self._aborted and not self._in_savepoint:
            raise RuntimeError("InFailedSqlTransaction: current transaction is aborted")
        if self._error is not None:
            if not self._in_savepoint:
                self._aborted = True
            raise self._error
        result = MagicMock()
        result.all = MagicMock(return_value=list(self._rows))
        return result


@pytest.mark.asyncio
async def test_prepare_cluster_caches_excludes_foreign_embedding_model() -> None:
    """Gallery cache keeps only reps in the active embedding space."""
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    foreign_space = "opencv-sface@128d/l2/cosine"
    vec_same = _normalize(np.array([1.0, 0.0, 0.0]))
    vec_foreign = _normalize(np.array([0.0, 1.0, 0.0]))

    clusters = [
        _cluster("c-same", embedding=vec_same, embedding_model=same_space, label="Alice", user_confirmed=True),
        _cluster("c-foreign", embedding=vec_foreign, embedding_model=foreign_space, label="Bob", user_confirmed=True),
    ]
    writer = _FakeWriter(clusters)

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=same_space,
    ):
        reps, centroids, labeled, stats = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert set(reps) == {"c-same"}
    assert "c-foreign" not in reps
    assert "c-foreign" not in centroids
    assert "c-same" in centroids
    assert labeled == {"c-same", "c-foreign"}
    assert isinstance(stats, GalleryProvenanceStats)


@pytest.mark.asyncio
async def test_run_discovery_produces_no_cross_space_candidates() -> None:
    """Probes must not match foreign-space cluster representatives.

    Fails against unfixed code that would cosine the probe against both
    same-space and foreign-space reps and emit a candidate for the foreign
    cluster when that garbage score clears the threshold.
    """
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    foreign_space = "opencv-sface@128d/l2/cosine"
    # Near-orthogonal vectors so a true same-space match is unambiguous, but
    # leave foreign rep close enough to pass a low threshold if wrongly kept.
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    same_rep = _normalize(np.array([0.99, 0.01, 0.0]))
    foreign_rep = _normalize(np.array([0.95, 0.05, 0.0]))  # high cosine if compared

    clusters = [
        _cluster("c-same", embedding=same_rep, embedding_model=same_space),
        _cluster("c-foreign", embedding=foreign_rep, embedding_model=foreign_space),
    ]
    writer = _FakeWriter(clusters)

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=same_space,
    ):
        reps, centroids, labeled, _stats = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert "c-foreign" not in reps

    settings = _make_settings(threshold=0.5)
    rep_discovery = RepresentativeDiscovery(settings=settings)
    # Centroid/graph stubs: only representative path is under test here.
    centroid_discovery = SimpleNamespace(discover=AsyncMock(return_value=[]))
    graph_discovery = SimpleNamespace(discover=AsyncMock(return_value=SimpleNamespace(candidates=[], new_clusters=[])))

    probe = _make_identity(probe_vec)
    candidates, _ = await run_discovery_pipeline(
        chunk=[probe],
        representative_discovery=rep_discovery,
        centroid_discovery=centroid_discovery,
        graph_discovery=graph_discovery,
        representatives_by_cluster=reps,
        centroids_by_cluster=centroids,
        labeled_cluster_ids=labeled,
    )

    assert all(c.cluster_id != "c-foreign" for c in candidates)
    assert any(c.cluster_id == "c-same" for c in candidates)


@pytest.mark.asyncio
async def test_prepare_cluster_caches_single_model_is_noop() -> None:
    """When every rep shares one model matching active, all stay (FIR23 no-op)."""
    model = "buffalo_l@insightface"
    clusters = [
        _cluster("c1", embedding=_normalize(np.array([1.0, 0.0])), embedding_model=model),
        _cluster("c2", embedding=_normalize(np.array([0.0, 1.0])), embedding_model=model),
    ]
    writer = _FakeWriter(clusters)

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=model,
    ):
        reps, centroids, _, stats = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert set(reps) == {"c1", "c2"}
    assert set(centroids) == {"c1", "c2"}
    assert stats.representatives_excluded_unresolvable == 0
    assert stats.gallery_wiped is False


@pytest.mark.asyncio
async def test_prepare_cluster_caches_excludes_unresolvable_when_provenance_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CVUP1-GR-21: unresolvable reps must not silently enter the gallery.

    Domain representatives drop embedding_model. When target_model is known but
    provenance cannot be loaded (no session / empty map), the pre-fix path kept
    every rep and discovery resumed cosining across spaces with no operator
    signal. Fail closed: exclude the rep, drop its centroid, and warn.
    """
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    vec = _normalize(np.array([1.0, 0.0, 0.0]))

    # Domain-like: no embedding_model on the rep (None → attribute omitted).
    clusters = [
        _cluster(
            "c-unresolved",
            embedding=vec,
            embedding_model=None,
            label="Mystery",
            user_confirmed=True,
        ),
    ]
    writer = _FakeWriter(clusters)

    with (
        patch(
            "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
            return_value=same_space,
        ),
        caplog.at_level(logging.WARNING),
    ):
        reps, centroids, labeled, stats = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert "c-unresolved" not in reps
    assert "c-unresolved" not in centroids
    # Labeled-status tracking is independent of gallery admission.
    assert labeled == {"c-unresolved"}
    assert stats.representatives_excluded_unresolvable == 1
    assert stats.clusters_excluded_unresolvable == 1
    assert stats.centroids_excluded_untrusted == 1
    assert stats.gallery_wiped is True
    assert any("provenance unavailable" in record.message and "excluded" in record.message for record in caplog.records)
    # R3-G2-1 / R3-G2-7: exclusion count must be named in a WARNING.
    assert any(
        "excluded 1 representatives" in record.message or "excluded_reps=1" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_prepare_cluster_caches_uses_explicit_session_for_provenance() -> None:
    """Explicit session param is preferred over private _session probing (R3-G2-6).

    Plants a competing writer._session that would return the foreign model for
    the same identity. If the explicit argument is ignored, the gallery would
    keep the foreign-mapped row (or wipe same-space) and this assertion fails.
    """
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    foreign_space = "opencv-sface@128d/l2/cosine"
    vec_same = _normalize(np.array([1.0, 0.0, 0.0]))
    vec_foreign = _normalize(np.array([0.0, 1.0, 0.0]))

    same_id = str(generate_id())
    foreign_id = str(generate_id())

    # Domain-like reps: resolve via session-backed provenance map only.
    rep_same = SimpleNamespace(embedding=vec_same, identity_id=same_id)
    rep_foreign = SimpleNamespace(embedding=vec_foreign, identity_id=foreign_id)
    clusters = [
        SimpleNamespace(
            id="c-same",
            label="Alice",
            user_confirmed=True,
            representatives=[rep_same],
            centroid=vec_same,
        ),
        SimpleNamespace(
            id="c-foreign",
            label="Bob",
            user_confirmed=True,
            representatives=[rep_foreign],
            centroid=vec_foreign,
        ),
    ]
    writer = _FakeWriter(clusters)

    class _ExplicitRows:
        def all(self):
            return [(same_id, same_space), (foreign_id, foreign_space)]

    class _CompetingRows:
        """Writer private session: deliberately swaps model labels."""

        def all(self):
            return [(same_id, foreign_space), (foreign_id, same_space)]

    explicit_session = SimpleNamespace(execute=AsyncMock(return_value=_ExplicitRows()))
    competing_session = SimpleNamespace(execute=AsyncMock(return_value=_CompetingRows()))
    writer._session = competing_session
    writer.cluster_repository._session = competing_session

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=same_space,
    ):
        reps, centroids, _, stats = await prepare_cluster_caches(
            writer,
            tenant_id=str(generate_id()),
            session=explicit_session,
        )

    assert set(reps) == {"c-same"}
    assert "c-foreign" not in reps
    assert "c-foreign" not in centroids
    explicit_session.execute.assert_awaited()
    competing_session.execute.assert_not_awaited()
    assert stats.provenance_loaded is True


# ---------------------------------------------------------------------------
# R3-G4-3 — centroid path gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_centroid_excluded_when_cluster_has_no_representatives() -> None:
    """R3-G4-3 hole 1: empty-rep cluster must not admit its centroid unconditionally.

    Pre-fix code hit `if not reps: continue` before foreign_space tracking, so
    the centroid loop admitted every empty-rep cluster's centroid. Reverting the
    centroid trust check re-admits c-empty into centroids.
    """
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    vec = _normalize(np.array([1.0, 0.0, 0.0]))
    empty_rep_cluster = SimpleNamespace(
        id="c-empty",
        label="OrphanCentroid",
        user_confirmed=True,
        representatives=[],
        centroid=vec,
    )
    writer = _FakeWriter([empty_rep_cluster])

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=same_space,
    ):
        reps, centroids, labeled, stats = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert reps == {}
    assert "c-empty" not in centroids
    assert labeled == {"c-empty"}
    assert stats.centroids_excluded_untrusted == 1


@pytest.mark.asyncio
async def test_centroid_excluded_for_mixed_space_cluster_even_when_same_space_rep_kept() -> None:
    """R3-G4-3 hole 2: mixed cluster centroid is majority-of-members, not trusted.

    Keeping one same-space rep used to set foreign_only=False and admit the
    (possibly legacy-space) centroid. Rule: admit centroid only when EVERY
    embedding-bearing rep resolved to the active model.
    """
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    foreign_space = "opencv-sface@128d/l2/cosine"
    vec_same = _normalize(np.array([1.0, 0.0, 0.0]))
    vec_foreign = _normalize(np.array([0.0, 1.0, 0.0]))
    # Centroid deliberately closer to foreign (majority-legacy transition).
    centroid_vec = _normalize(np.array([0.1, 0.9, 0.0]))

    foreign_rep = SimpleNamespace(
        embedding=vec_foreign,
        identity_id=str(generate_id()),
        embedding_model=foreign_space,
    )
    mixed = _cluster(
        "c-mixed",
        embedding=vec_same,
        embedding_model=same_space,
        label="Transition",
        user_confirmed=True,
        centroid=centroid_vec,
        extra_reps=[foreign_rep],
    )
    writer = _FakeWriter([mixed])

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=same_space,
    ):
        reps, centroids, _, stats = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    # Same-space rep survives for representative discovery.
    assert "c-mixed" in reps
    assert len(reps["c-mixed"]) == 1
    # But centroid must not be admitted — majority vector may be legacy-space.
    assert "c-mixed" not in centroids
    assert stats.centroids_excluded_untrusted == 1


@pytest.mark.asyncio
async def test_centroid_admitted_when_all_reps_resolve_to_active_model() -> None:
    """Positive control for R3-G4-3: mono-space cluster keeps its centroid."""
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    vec = _normalize(np.array([1.0, 0.0, 0.0]))
    clusters = [
        _cluster("c-ok", embedding=vec, embedding_model=same_space, label="Alice", user_confirmed=True),
    ]
    writer = _FakeWriter(clusters)

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=same_space,
    ):
        reps, centroids, _, stats = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert "c-ok" in reps
    assert "c-ok" in centroids
    assert stats.centroids_excluded_untrusted == 0


# ---------------------------------------------------------------------------
# R3-G2-7 / R3-G3-3 — provenance_loaded=True empty map still fails closed + warns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_provenance_map_with_loaded_true_excludes_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R3-G2-7 / R3-G3-3: successful empty map must not be silent.

    provenance_loaded=True with {} still leaves every domain rep unresolvable.
    Pre-fix code gated the WARNING on `not provenance_loaded`, so this path
    stayed green under a partial botch that returned ({}, True). Discrimination:
    revert the unresolvable-count warning gate and this assert on 'excluded N
    representatives' goes red.
    """
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    vec = _normalize(np.array([1.0, 0.0, 0.0]))
    identity_id = str(generate_id())
    rep = SimpleNamespace(embedding=vec, identity_id=identity_id)  # no embedding_model
    clusters = [
        SimpleNamespace(
            id="c-domain",
            label="DomainOnly",
            user_confirmed=True,
            representatives=[rep],
            centroid=vec,
        ),
    ]
    writer = _FakeWriter(clusters)

    class _EmptyRows:
        def all(self):
            return []  # query succeeded, no model stamps

    session = SimpleNamespace(execute=AsyncMock(return_value=_EmptyRows()))

    with (
        patch(
            "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
            return_value=same_space,
        ),
        caplog.at_level(logging.WARNING),
    ):
        reps, centroids, _, stats = await prepare_cluster_caches(
            writer,
            tenant_id=str(generate_id()),
            session=session,
        )

    assert "c-domain" not in reps
    assert "c-domain" not in centroids
    assert stats.provenance_loaded is True
    assert stats.representatives_excluded_unresolvable == 1
    assert stats.clusters_excluded_unresolvable == 1
    assert stats.gallery_wiped is True
    # Must warn even though provenance_loaded is True (R3-G2-7).
    assert any(
        "excluded 1 representatives" in record.message and "provenance_loaded=True" in record.message
        for record in caplog.records
    )
    # Must NOT rely only on the old "provenance unavailable" gate (that path is
    # silent when provenance_loaded=True).
    assert not any("provenance unavailable" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# R3-G2-4 — probe model resolution fails closed and loud
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unresolved_probe_model_wipes_gallery_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R3-G2-4: blind gate must fail closed, not silently disable the filter.

    Pre-fix `_resolve_probe_embedding_model` swallowed exceptions → None, and
    prepare_cluster_caches treated None as 'filter off' (fail open). Reverting
    the early-return wipe re-admits c1 into reps.
    """
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    vec = _normalize(np.array([1.0, 0.0, 0.0]))
    clusters = [
        _cluster("c1", embedding=vec, embedding_model=same_space, label="Alice", user_confirmed=True),
    ]
    writer = _FakeWriter(clusters)

    with (
        patch(
            "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
            return_value=None,
        ),
        caplog.at_level(logging.WARNING),
    ):
        reps, centroids, labeled, stats = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert reps == {}
    assert centroids == {}
    assert labeled == {"c1"}
    assert stats.active_embedding_model is None
    assert stats.gallery_wiped is True
    assert any("gallery wiped" in record.message or "unresolved" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_resolve_probe_embedding_model_logs_on_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R3-G2-4: exception path of the probe helper itself must not be silent."""
    from recognition.application.orchestration.clustering import discovery_pipeline as dp

    with (
        patch(
            "recognition.application.embedding.manifest.active_embedding_model_id",
            side_effect=RuntimeError("manifest boom"),
        ),
        caplog.at_level(logging.WARNING),
    ):
        result = dp._resolve_probe_embedding_model()

    assert result is None
    assert any("active embedding_model unresolved" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# R3-G2-3 — SAVEPOINT isolation for provenance query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provenance_query_failure_uses_savepoint_and_leaves_session_usable() -> None:
    """R3-G2-3: failed provenance SELECT must not poison the job session.

    Without begin_nested, the raise aborts the outer txn and a follow-up
    execute raises InFailedSqlTransaction. Discrimination: remove the
    begin_nested wrapper and assert begin_nested_calls >= 1 / follow-up
    execute succeeds goes red.
    """
    session = _TxnAwareSession(error=RuntimeError("relation does not exist"))
    writer = _FakeWriter([])
    writer._session = session
    writer.cluster_repository._session = session

    model_map, loaded = await _load_representative_embedding_models(
        writer,
        tenant_id=str(generate_id()),
        session=session,
    )

    assert model_map == {}
    assert loaded is False
    assert session.begin_nested_calls >= 1
    # Outer txn not aborted — a follow-up execute still works.
    session._error = None
    follow = await session.execute("SELECT 1")
    assert follow is not None
    assert follow.all() == []


# ---------------------------------------------------------------------------
# R3-G2-5 — session resolution priority
# ---------------------------------------------------------------------------


def test_resolve_assignment_session_prefers_repo_over_writer() -> None:
    """R3-G2-5: after explicit, prefer cluster_repository session over writer.

    Gallery rows are loaded via the repository session; provenance should use
    the same transactional view when no explicit session is threaded.
    """
    repo_session = object()
    writer_session = object()
    writer = SimpleNamespace(
        _session=writer_session,
        cluster_repository=SimpleNamespace(_session=repo_session),
    )
    assert _resolve_assignment_session(writer) is repo_session


def test_resolve_assignment_session_explicit_wins_over_both() -> None:
    """Explicit job session always wins (orchestrator production path)."""
    explicit = object()
    writer = SimpleNamespace(
        _session=object(),
        cluster_repository=SimpleNamespace(_session=object()),
    )
    assert _resolve_assignment_session(writer, session=explicit) is explicit


# ---------------------------------------------------------------------------
# R3-G2-1 — stats payload shape for orchestrator
# ---------------------------------------------------------------------------


def test_gallery_provenance_stats_to_payload_shape() -> None:
    """Job payload key is stable and JSON-friendly for operators."""
    stats = GalleryProvenanceStats(
        active_embedding_model="opencv-sface+cv5@128d/l2/cosine",
        provenance_loaded=False,
        representatives_excluded_unresolvable=3,
        clusters_excluded_unresolvable=2,
        centroids_excluded_untrusted=2,
        gallery_wiped=True,
    )
    payload = stats.to_payload()
    assert payload["gallery_wiped"] is True
    assert payload["representatives_excluded_unresolvable"] == 3
    assert payload["clusters_excluded_unresolvable"] == 2
    assert payload["centroids_excluded_untrusted"] == 2
    assert payload["provenance_loaded"] is False
    assert payload["active_embedding_model"] == "opencv-sface+cv5@128d/l2/cosine"
