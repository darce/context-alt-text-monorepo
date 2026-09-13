"""B05: ClusterJobResult must expose the same probe_space_skip as the job payload.

Decision 10509: payload-only skip counts are not enough. Empty/all-foreign idle
and mixed kept/skipped runs must return the same kept/skipped/distinct-model
metadata on ClusterJobResult as IdentityClusteringJob.payload["probe_space_skip"].
Public field is backward-compatible (empty mapping default).
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from db.models import IdentityClusteringJob
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.embedding.manifest import try_active_embedding_model_id
from recognition.application.orchestration.clustering.dependencies import (
    ClusteringContext,
    ClusteringDependencies,
    ClusteringRuntimeConfig,
)
from recognition.application.orchestration.clustering.discovery_pipeline import GalleryProvenanceStats
from recognition.application.orchestration.clustering.job_result import ClusterJobResult
from recognition.application.orchestration.clustering.orchestrator import (
    IncrementalClusteringRunner,
    probe_space_skip_payload,
)
from recognition.application.suggestions.embedding_space import filter_to_active_embedding_space
from recognition.observability.recognition_runs import RecognitionRunContext

ACTIVE_MODEL = "stub-detector@test"
FOREIGN_MODEL = "legacy-seed@v1"
PRESERVED_NOTE = "keep-me"
PREEXISTING_GALLERY = {
    "active_embedding_model": ACTIVE_MODEL,
    "provenance_loaded": True,
    "representatives_excluded_unresolvable": 0,
    "clusters_excluded_unresolvable": 0,
    "centroids_excluded_untrusted": 0,
    "gallery_wiped": False,
    "preexisting": True,
}


class _ScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _ExecuteResult:
    """Production-shaped execute result: scalars().all() for ORM, .all() for tuples."""

    def __init__(self, *, scalar_rows: list[Any], tuple_rows: list[tuple[Any, ...]]) -> None:
        self._scalar_rows = scalar_rows
        self._tuple_rows = tuple_rows

    def scalars(self) -> _ScalarRows:
        return _ScalarRows(self._scalar_rows)

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._tuple_rows)


class _RecordingSession:
    """Async session stand-in that returns real ORM identity rows and tuple producers."""

    def __init__(
        self,
        *,
        identity_rows: list[MediaIdentityModel],
        existing_job: IdentityClusteringJob,
        provenance_tuples: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.identity_rows = identity_rows
        self.existing_job = existing_job
        self.provenance_tuples = list(provenance_tuples or [])
        self.added: list[object] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.executed: list[object] = []

    async def get(self, model: type[object], pk: UUID) -> IdentityClusteringJob | None:
        if model is IdentityClusteringJob and self.existing_job.id == pk:
            return self.existing_job
        return None

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1

    async def execute(self, stmt: object, *_args: object, **_kwargs: object) -> _ExecuteResult:
        self.executed.append(stmt)
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()
        if "identity_cluster_representatives" in compiled:
            return _ExecuteResult(scalar_rows=[], tuple_rows=self.provenance_tuples)
        return _ExecuteResult(scalar_rows=self.identity_rows, tuple_rows=[])


def _orm_identity(*, tenant_id: UUID, embedding_model: str | None, media_id: int) -> MediaIdentityModel:
    return MediaIdentityModel(
        id=uuid4(),
        tenant_id=tenant_id,
        identity_type="face",
        media_id=media_id,
        media_url=f"https://example.test/{media_id}.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=12,
        bbox_height=14,
        confidence=0.91,
        embedding=[0.0, 0.0, 0.0, 1.0],
        embedding_model=embedding_model,
    )


def _job(*, tenant_id: UUID, job_id: UUID) -> IdentityClusteringJob:
    return IdentityClusteringJob(
        id=job_id,
        tenant_id=tenant_id,
        job_type="clustering",
        status="pending",
        progress=0.0,
        payload={
            "operator_note": PRESERVED_NOTE,
            "gallery_provenance": dict(PREEXISTING_GALLERY),
        },
    )


def _expected_skip(rows: list[MediaIdentityModel], *, active_model: str | None) -> dict[str, object]:
    kept = filter_to_active_embedding_space(rows)
    return probe_space_skip_payload(rows, kept, active_model=active_model)


def _make_runner(session: _RecordingSession, *, commit: bool) -> IncrementalClusteringRunner:
    writer = MagicMock()
    writer.cluster_repository.cleanup_orphaned_provisional_reps = AsyncMock(return_value=0)
    writer.cluster_repository.confirm_all_provisional_reps = AsyncMock(return_value=0)
    writer.cluster_repository.get_by_tenant = AsyncMock(return_value=[])
    writer.persist_assignments_chunk = AsyncMock(return_value=(0, 0, 0, set()))
    writer.persist_new_cluster = AsyncMock(return_value=None)

    graph = MagicMock()
    graph.algorithm_name = "test-graph"
    graph.discover = AsyncMock(return_value=SimpleNamespace(candidates=[], new_clusters=[]))

    representative = MagicMock()
    representative.discover = AsyncMock(return_value=[])
    centroid = MagicMock()
    centroid.discover = AsyncMock(return_value=[])

    gate = MagicMock()
    gate.settings.model_dump.return_value = {}

    suggestion = MagicMock()
    suggestion.resolve_for_identity_exclusive = AsyncMock()

    return IncrementalClusteringRunner(
        session=session,
        dependencies=ClusteringDependencies(
            gate=gate,
            representative_discovery=representative,
            centroid_discovery=centroid,
            graph_discovery=graph,
            assignment_writer=writer,
            suggestion_service=suggestion,
        ),
        runtime_config=ClusteringRuntimeConfig(commit=commit),
    )


async def _fake_create_run(session: object, **kwargs: Any) -> RecognitionRunContext:
    return RecognitionRunContext(session=session, tenant_id=kwargs["tenant_id"], run_id=uuid4())


@pytest.fixture
def clustering_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "recognition.application.orchestration.clustering.orchestrator.create_recognition_run",
        _fake_create_run,
    )
    monkeypatch.setattr(
        "recognition.application.orchestration.clustering.orchestrator.complete_recognition_run",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "recognition.application.orchestration.clustering.orchestrator.set_tenant_context",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "recognition.application.orchestration.clustering.orchestrator.enable_rls_bypass",
        AsyncMock(),
    )


async def _run_job(
    *,
    rows: list[MediaIdentityModel],
    tenant_id: UUID,
    job_id: UUID,
    commit: bool,
    provenance_tuples: list[tuple[Any, ...]] | None = None,
) -> tuple[ClusterJobResult, IdentityClusteringJob, _RecordingSession]:
    job = _job(tenant_id=tenant_id, job_id=job_id)
    session = _RecordingSession(
        identity_rows=rows,
        existing_job=job,
        provenance_tuples=provenance_tuples,
    )
    runner = _make_runner(session, commit=commit)
    result = await runner.run(context=ClusteringContext(tenant_id=str(tenant_id), job_id=str(job_id)))
    return result, job, session


def _assert_unclustered_producer(session: _RecordingSession) -> None:
    assert session.executed, "runner must execute the unclustered-identity select"
    sql = str(session.executed[0].compile(compile_kwargs={"literal_binds": False})).lower()
    assert "media_identities" in sql
    assert "identity_members" in sql


def _assert_result_payload_parity(
    result: ClusterJobResult,
    job: IdentityClusteringJob,
    expected: dict[str, object],
) -> None:
    payload = job.payload or {}
    skip = payload["probe_space_skip"]
    assert skip == expected
    assert "operator_note" in payload
    assert payload["operator_note"] == PRESERVED_NOTE
    assert "gallery_provenance" in payload
    assert result.probe_space_skip == skip
    assert result.probe_space_skip["kept_count"] == expected["kept_count"]
    assert result.probe_space_skip["skipped_count"] == expected["skipped_count"]
    assert result.probe_space_skip["total_count"] == expected["total_count"]
    assert result.probe_space_skip["skipped_models"] == expected["skipped_models"]
    assert result.probe_space_skip["active_embedding_model"] == expected["active_embedding_model"]


def test_cluster_job_result_probe_space_skip_defaults_to_empty_mapping() -> None:
    """Public field must exist with a stable empty default so old constructors keep working."""
    named = {item.name: item for item in fields(ClusterJobResult)}
    assert "probe_space_skip" in named
    now = datetime.now(tz=UTC)
    result = ClusterJobResult(
        job_id="job",
        started_at=now,
        finished_at=now,
        completed=0,
        total=0,
        clusters_created=0,
    )
    assert result.probe_space_skip == {}
    other = ClusterJobResult(
        job_id="other",
        started_at=now,
        finished_at=now,
        completed=0,
        total=0,
        clusters_created=0,
    )
    result.probe_space_skip["skipped_count"] = 1
    assert other.probe_space_skip == {}


@pytest.mark.asyncio
async def test_runner_truly_empty_exposes_zero_skip_metadata_on_result(
    clustering_seams: None,
) -> None:
    tenant_id = uuid4()
    job_id = uuid4()
    rows: list[MediaIdentityModel] = []
    expected = _expected_skip(rows, active_model=try_active_embedding_model_id())

    result, job, session = await _run_job(rows=rows, tenant_id=tenant_id, job_id=job_id, commit=True)

    _assert_unclustered_producer(session)
    assert session.flush_calls >= 1
    assert session.commit_calls == 1
    assert expected["total_count"] == 0
    assert expected["skipped_count"] == 0
    assert expected["kept_count"] == 0
    assert expected["skipped_models"] == []
    _assert_result_payload_parity(result, job, expected)
    assert result.completed == 0
    assert result.total == 0


@pytest.mark.asyncio
async def test_runner_all_foreign_is_not_empty_idle_without_result_metadata(
    clustering_seams: None,
) -> None:
    tenant_id = uuid4()
    job_id = uuid4()
    rows = [
        _orm_identity(tenant_id=tenant_id, embedding_model=FOREIGN_MODEL, media_id=1),
        _orm_identity(tenant_id=tenant_id, embedding_model=FOREIGN_MODEL, media_id=2),
    ]
    expected = _expected_skip(rows, active_model=try_active_embedding_model_id())

    result, job, session = await _run_job(rows=rows, tenant_id=tenant_id, job_id=job_id, commit=True)

    _assert_unclustered_producer(session)
    assert session.commit_calls == 1
    assert expected["active_embedding_model"] == ACTIVE_MODEL
    assert expected["kept_count"] == 0
    assert expected["skipped_count"] == 2
    assert expected["total_count"] == 2
    assert expected["skipped_models"] == [FOREIGN_MODEL]
    _assert_result_payload_parity(result, job, expected)
    empty_expected = _expected_skip([], active_model=try_active_embedding_model_id())
    assert result.probe_space_skip != empty_expected
    assert result.probe_space_skip["total_count"] != empty_expected["total_count"]


@pytest.mark.asyncio
async def test_runner_active_unresolved_fail_closed_records_skip_on_result(
    clustering_seams: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recognition.application.embedding.manifest.try_active_embedding_model_id",
        lambda: None,
    )
    tenant_id = uuid4()
    job_id = uuid4()
    rows = [
        _orm_identity(tenant_id=tenant_id, embedding_model=FOREIGN_MODEL, media_id=1),
        _orm_identity(tenant_id=tenant_id, embedding_model=ACTIVE_MODEL, media_id=2),
    ]
    expected = _expected_skip(rows, active_model=None)

    result, job, session = await _run_job(rows=rows, tenant_id=tenant_id, job_id=job_id, commit=False)

    _assert_unclustered_producer(session)
    assert session.commit_calls == 0
    assert expected["active_embedding_model"] is None
    assert expected["kept_count"] == 0
    assert expected["skipped_count"] == 2
    assert expected["total_count"] == 2
    _assert_result_payload_parity(result, job, expected)


@pytest.mark.asyncio
async def test_runner_mixed_kept_skipped_result_matches_payload_and_keeps_other_keys(
    clustering_seams: None,
) -> None:
    tenant_id = uuid4()
    job_id = uuid4()
    kept_row = _orm_identity(tenant_id=tenant_id, embedding_model=ACTIVE_MODEL, media_id=1)
    foreign_row = _orm_identity(tenant_id=tenant_id, embedding_model=FOREIGN_MODEL, media_id=2)
    unstamped_row = _orm_identity(tenant_id=tenant_id, embedding_model=None, media_id=3)
    rows = [unstamped_row, foreign_row, kept_row]
    provenance_id = uuid4()
    expected = _expected_skip(rows, active_model=try_active_embedding_model_id())

    result, job, session = await _run_job(
        rows=rows,
        tenant_id=tenant_id,
        job_id=job_id,
        commit=True,
        provenance_tuples=[(provenance_id, ACTIVE_MODEL)],
    )

    _assert_unclustered_producer(session)
    assert any(
        "identity_cluster_representatives" in str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()
        for stmt in session.executed
    )
    assert session.commit_calls >= 1
    assert expected["kept_count"] == 1
    assert expected["skipped_count"] == 2
    assert expected["total_count"] == 3
    assert expected["skipped_models"] == [FOREIGN_MODEL, "unstamped"]
    assert expected["active_embedding_model"] == ACTIVE_MODEL
    _assert_result_payload_parity(result, job, expected)
    assert job.payload["gallery_provenance"]["gallery_wiped"] is False
    assert result.completed == 1
    assert result.total == 1
    assert result.probe_space_skip["kept_count"] != result.probe_space_skip["total_count"]


@pytest.mark.asyncio
async def test_runner_all_unstamped_legacy_keeps_all_and_exposes_skip_on_result(
    clustering_seams: None,
) -> None:
    tenant_id = uuid4()
    job_id = uuid4()
    rows = [
        _orm_identity(tenant_id=tenant_id, embedding_model=None, media_id=1),
        _orm_identity(tenant_id=tenant_id, embedding_model="", media_id=2),
    ]
    expected = _expected_skip(rows, active_model=try_active_embedding_model_id())

    result, job, session = await _run_job(rows=rows, tenant_id=tenant_id, job_id=job_id, commit=True)

    _assert_unclustered_producer(session)
    assert expected["kept_count"] == 2
    assert expected["skipped_count"] == 0
    assert expected["total_count"] == 2
    assert expected["skipped_models"] == []
    _assert_result_payload_parity(result, job, expected)
    assert result.completed == 2
    assert result.total == 2


@pytest.mark.asyncio
async def test_process_chunks_gallery_provenance_does_not_drop_probe_space_skip(
    clustering_seams: None,
) -> None:
    """Non-empty path must keep skip metadata when gallery_provenance is merged (Release It partial state)."""
    tenant_id = uuid4()
    job_id = uuid4()
    rows = [
        _orm_identity(tenant_id=tenant_id, embedding_model=ACTIVE_MODEL, media_id=1),
        _orm_identity(tenant_id=tenant_id, embedding_model=FOREIGN_MODEL, media_id=2),
    ]
    expected = _expected_skip(rows, active_model=try_active_embedding_model_id())
    result, job, session = await _run_job(rows=rows, tenant_id=tenant_id, job_id=job_id, commit=True)

    _assert_unclustered_producer(session)
    payload = job.payload or {}
    assert payload["probe_space_skip"] == expected
    assert "gallery_provenance" in payload
    stats = GalleryProvenanceStats(
        active_embedding_model=ACTIVE_MODEL,
        provenance_loaded=True,
        representatives_excluded_unresolvable=0,
        clusters_excluded_unresolvable=0,
        centroids_excluded_untrusted=0,
        gallery_wiped=False,
    )
    assert payload["gallery_provenance"]["gallery_wiped"] is stats.gallery_wiped
    assert result.probe_space_skip == payload["probe_space_skip"]
