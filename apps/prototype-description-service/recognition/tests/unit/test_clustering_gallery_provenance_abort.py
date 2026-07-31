"""R3-03: an infrastructure-caused gallery wipe must fail the clustering job.

Recording the counters (R3-G2-1) makes the wipe visible but still lets the job
report COMPLETED with an empty gallery, which fragments the tenant into
duplicate clusters. These tests pin the *discrimination*: infrastructure causes
abort, a legitimate embedding-space migration proceeds.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from recognition.application.orchestration.clustering.dependencies import (
    ClusteringDependencies,
    ClusteringRuntimeConfig,
)
from recognition.application.orchestration.clustering.discovery_pipeline import (
    GalleryProvenanceStats,
    GalleryProvenanceUnavailableError,
)
from recognition.application.orchestration.clustering.orchestrator import (
    IncrementalClusteringRunner,
)
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id

ACTIVE_MODEL = "opencv-sface+cv5@128d/l2/cosine"


def _stats(**overrides: Any) -> GalleryProvenanceStats:
    """Stats for a wiped gallery caused by a legitimate migration, by default."""
    base: dict[str, Any] = {
        "active_embedding_model": ACTIVE_MODEL,
        "provenance_loaded": True,
        "representatives_excluded_unresolvable": 0,
        "clusters_excluded_unresolvable": 0,
        "centroids_excluded_untrusted": 4,
        "gallery_wiped": True,
    }
    base.update(overrides)
    return GalleryProvenanceStats(**base)


# ---------------------------------------------------------------------------
# abort_reason — the discrimination itself
# ---------------------------------------------------------------------------


def test_intact_gallery_never_aborts() -> None:
    """Exclusions alone are not an abort while some anchor survived."""
    stats = _stats(
        representatives_excluded_unresolvable=7,
        clusters_excluded_unresolvable=3,
        gallery_wiped=False,
    )
    assert stats.abort_reason() is None


def test_unresolved_active_model_aborts() -> None:
    """No probe manifest => the filter is blind, not migrating."""
    reason = _stats(active_embedding_model=None, gallery_wiped=True).abort_reason()
    assert reason is not None
    assert "active embedding_model unresolved" in reason


def test_provenance_query_unavailable_aborts() -> None:
    """No session / failed provenance query is infrastructure, and retryable."""
    reason = _stats(provenance_loaded=False).abort_reason()
    assert reason is not None
    assert "provenance unavailable" in reason
    assert ACTIVE_MODEL in reason


def test_unstamped_representatives_abort() -> None:
    """Reps carrying no embedding_model are a data gap, not a migration."""
    reason = _stats(
        representatives_excluded_unresolvable=12,
        clusters_excluded_unresolvable=5,
    ).abort_reason()
    assert reason is not None
    assert "12 representative(s) across 5 cluster(s)" in reason


def test_legitimate_space_migration_does_not_abort() -> None:
    """The case that must stay green.

    Every representative resolved to a real model that is simply not the active
    one. Aborting here would permanently block clustering after a space-token
    rollout — the wipe is the intended FIR23-01 behaviour, not a failure.
    """
    assert _stats().abort_reason() is None


# ---------------------------------------------------------------------------
# Orchestrator wiring — the guard actually runs before the chunk loop
# ---------------------------------------------------------------------------


def _make_runner() -> IncrementalClusteringRunner:
    stub = MagicMock()
    return IncrementalClusteringRunner(
        session=MagicMock(),
        dependencies=ClusteringDependencies(
            gate=stub,
            representative_discovery=stub,
            centroid_discovery=stub,
            graph_discovery=stub,
            assignment_writer=stub,
            suggestion_service=stub,
        ),
        runtime_config=ClusteringRuntimeConfig(commit=False),
    )


def test_runner_raises_on_infrastructure_wipe() -> None:
    """Guard converts an unprovenanced wipe into a job failure."""
    runner = _make_runner()
    with pytest.raises(GalleryProvenanceUnavailableError) as excinfo:
        runner._abort_on_unprovenanced_gallery("job-1", _stats(provenance_loaded=False))
    message = str(excinfo.value)
    assert "gallery wiped" in message
    assert "excluded_centroids=4" in message


def test_runner_does_not_raise_on_migration_wipe() -> None:
    """Same wiped gallery, legitimate cause: the job proceeds."""
    runner = _make_runner()
    runner._abort_on_unprovenanced_gallery("job-1", _stats())


@pytest.mark.asyncio
async def test_process_chunks_aborts_before_processing_any_chunk(monkeypatch) -> None:
    """Wiring check: the guard fires between cache prep and the chunk loop.

    Also pins that the counters are recorded on the payload first, so the
    operator-visible stats exist even on the failing path.
    """
    runner = _make_runner()
    chunks_processed: list[Any] = []

    async def fake_prepare(*_args: Any, **_kwargs: Any) -> Any:
        return {}, {}, set(), _stats(active_embedding_model=None)

    monkeypatch.setattr(
        "recognition.application.orchestration.clustering.orchestrator.prepare_cluster_caches",
        fake_prepare,
    )

    async def fake_chunk(**kwargs: Any) -> Any:
        chunks_processed.append(kwargs)
        raise AssertionError("chunk loop must not run after an abort")

    monkeypatch.setattr(runner, "_process_single_chunk", fake_chunk)

    job = MagicMock()
    job.payload = None
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=np.zeros(128, dtype=np.float32),
        confidence=0.95,
        bbox_width=100,
        bbox_height=100,
    )

    with pytest.raises(GalleryProvenanceUnavailableError):
        await runner._process_chunks(
            tenant_id=str(generate_id()),
            job_id="job-1",
            job_label="job-1",
            clustering_job=job,
            identities=[identity],
        )

    assert chunks_processed == []
    assert job.payload["gallery_provenance"]["gallery_wiped"] is True
