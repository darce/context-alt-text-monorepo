"""Unit tests for the per-chunk phase methods extracted from _process_chunks.

ORCH-4 (completion): _process_chunks was decomposed into a thin loop + a
_process_single_chunk orchestrator calling named phase methods. These pin the
two phases that carry observable side effects but fake cleanly:
_persist_accepted_assignments and _commit_chunk_progress. The heavier
new-cluster phase and the thin loop are guarded by the integration suite.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import cast

import pytest

from recognition.application.assignment import AssignmentDecision
from recognition.application.orchestration.clustering import orchestrator as orchestrator_module
from recognition.application.orchestration.clustering.orchestrator import IncrementalClusteringRunner
from recognition.domain.identity import MediaIdentity


def _bare_runner() -> IncrementalClusteringRunner:
    """Construct a runner without running __init__ (which needs full DI).

    Each test sets only the attributes the method under test touches.
    """
    return object.__new__(IncrementalClusteringRunner)


def _accepted_decision(identity_id: str, cluster_id: str) -> AssignmentDecision:
    # Duck-typed: _persist_accepted_assignments reads only decision.candidate.{identity.id,identity.media_id,cluster_id}.
    return cast(
        AssignmentDecision,
        SimpleNamespace(
            candidate=SimpleNamespace(
                identity=SimpleNamespace(id=identity_id, media_id=f"m-{identity_id}"),
                cluster_id=cluster_id,
            )
        ),
    )


class _RecordingAssignmentWriter:
    def __init__(self, result: tuple[int, int, int]) -> None:
        self._result = result
        self.calls: list[tuple[object, bool]] = []

    async def persist_assignments_chunk(self, decisions: object, *, batch_mode: bool) -> tuple[int, int, int]:
        self.calls.append((decisions, batch_mode))
        return self._result


class _RecordingSuggestionService:
    def __init__(self) -> None:
        self.resolved: list[tuple[str, str, str]] = []

    async def resolve_for_identity_exclusive(self, *, identity_id: str, accepted_cluster_id: str, reason: str) -> None:
        self.resolved.append((identity_id, accepted_cluster_id, reason))


@pytest.mark.asyncio
async def test_persist_accepted_assignments_bulk_persists_and_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _bare_runner()
    writer = _RecordingAssignmentWriter((2, 1, 5))  # persisted, skipped, reps_added
    suggestions = _RecordingSuggestionService()
    monkeypatch.setattr(runner, "_assignment_writer", writer, raising=False)
    monkeypatch.setattr(runner, "_suggestion_service", suggestions, raising=False)

    decisions = [_accepted_decision("a1", "c1"), _accepted_decision("a2", "c2")]
    reps_added = await runner._persist_accepted_assignments(decisions, job_id="job-1", verbose=False)

    assert reps_added == 5
    # One bulk call carrying the whole decision list in batch mode.
    assert writer.calls == [(decisions, True)]
    # Suggestions resolved once per accepted decision, with the candidate's ids.
    assert suggestions.resolved == [
        ("a1", "c1", "auto_assignment"),
        ("a2", "c2", "auto_assignment"),
    ]


@pytest.mark.asyncio
async def test_persist_accepted_assignments_noop_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _bare_runner()
    writer = _RecordingAssignmentWriter((0, 0, 0))
    suggestions = _RecordingSuggestionService()
    monkeypatch.setattr(runner, "_assignment_writer", writer, raising=False)
    monkeypatch.setattr(runner, "_suggestion_service", suggestions, raising=False)

    reps_added = await runner._persist_accepted_assignments([], job_id="job-1", verbose=True)

    assert reps_added == 0
    assert writer.calls == []
    assert suggestions.resolved == []


class _RecordingSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_commit_chunk_progress_writes_payload_commits_and_restores_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _bare_runner()
    session = _RecordingSession()
    obs_factory = object()
    monkeypatch.setattr(runner, "_session", session, raising=False)
    monkeypatch.setattr(runner, "_obs_session_factory", obs_factory, raising=False)

    restored: list[tuple[str, object]] = []

    async def _fake_set_tenant_context(sess: object, tenant: object) -> None:
        restored.append(("tenant", sess))

    async def _fake_enable_rls_bypass(sess: object) -> None:
        restored.append(("bypass", sess))

    monkeypatch.setattr(orchestrator_module, "set_tenant_context", _fake_set_tenant_context)
    monkeypatch.setattr(orchestrator_module, "enable_rls_bypass", _fake_enable_rls_bypass)

    flushed: list[object] = []

    async def _flush(factory: object) -> None:
        flushed.append(factory)

    run_ctx = SimpleNamespace(buffer_events=True, flush_pending_events=_flush)
    job = SimpleNamespace(payload={"existing": "kept"}, processed_identities=None, progress=None)
    tenant_id = str(uuid.uuid4())

    await runner._commit_chunk_progress(
        clustering_job=job,
        processed=40,
        total_identities=100,
        clusters_created=7,
        chunk_len=10,
        tenant_id=tenant_id,
        job_id="job-1",
        run_ctx=run_ctx,
    )

    assert job.processed_identities == 40
    assert job.progress == 0.4
    assert job.payload == {
        "existing": "kept",
        "clusters_created": 7,
        "last_successful_processed_identities": 40,
        "current_chunk_size": 10,
    }
    assert session.commits == 1
    # Tenant context + RLS bypass restored AFTER commit, on the same session.
    assert restored == [("tenant", session), ("bypass", session)]
    assert flushed == [obs_factory]


@pytest.mark.asyncio
async def test_commit_chunk_progress_skips_flush_without_buffered_events(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _bare_runner()
    monkeypatch.setattr(runner, "_session", _RecordingSession(), raising=False)
    monkeypatch.setattr(runner, "_obs_session_factory", object(), raising=False)
    monkeypatch.setattr(orchestrator_module, "set_tenant_context", lambda *a, **k: _noop())
    monkeypatch.setattr(orchestrator_module, "enable_rls_bypass", lambda *a, **k: _noop())

    flushed: list[object] = []

    async def _flush(factory: object) -> None:
        flushed.append(factory)

    run_ctx = SimpleNamespace(buffer_events=False, flush_pending_events=_flush)
    job = SimpleNamespace(payload=None, processed_identities=None, progress=None)

    await runner._commit_chunk_progress(
        clustering_job=job,
        processed=0,
        total_identities=0,
        clusters_created=0,
        chunk_len=5,
        tenant_id=str(uuid.uuid4()),
        job_id="job-1",
        run_ctx=run_ctx,
    )

    # total_identities == 0 -> progress defaults to 1.0 (no ZeroDivisionError).
    assert job.progress == 1.0
    assert flushed == []


async def _noop() -> None:
    return None


def _ident(identity_id: str) -> MediaIdentity:
    # Duck-typed: _create_new_clusters_for_chunk reads only .id off each identity.
    return cast(MediaIdentity, SimpleNamespace(id=identity_id))


@pytest.mark.asyncio
async def test_create_new_clusters_excludes_graph_fallback_ids_from_hac(monkeypatch: pytest.MonkeyPatch) -> None:
    """orch4-BR-01: identities claimed by the graph fallback must be excluded from
    the still_unclustered list handed to HAC; unassigned ones are forwarded."""
    runner = _bare_runner()

    async def _discover(identities: object, anchors: object) -> SimpleNamespace:
        return SimpleNamespace(new_clusters=[("fallback",)])

    monkeypatch.setattr(runner, "_graph_discovery", SimpleNamespace(discover=_discover), raising=False)

    persist_calls: list[str] = []

    async def _fake_persist(
        new_clusters: object,
        *,
        tenant_id: str,
        job_id: str,
        representatives_by_cluster: object,
        centroids_by_cluster: object,
        resolve_reason: str,
        preserve_suggestion_ids: object = None,
        assigned_ids_out: set[str] | None = None,
    ) -> tuple[int, list[str]]:
        persist_calls.append(resolve_reason)
        if resolve_reason == "auto_new_cluster":
            assert assigned_ids_out is not None
            assigned_ids_out.add("a")  # graph fallback claims identity "a"
            return 1, ["cl-fallback"]
        return 2, ["cl-prop1", "cl-prop2"]

    monkeypatch.setattr(runner, "_persist_and_cache_new_clusters", _fake_persist, raising=False)

    hac_seen: dict[str, list[str]] = {}

    async def _fake_hac(*, still_unclustered: list[MediaIdentity], **_kw: object) -> int:
        hac_seen["ids"] = [i.id for i in still_unclustered]
        return 3

    monkeypatch.setattr(orchestrator_module, "run_hac_refinement", _fake_hac)
    for attr in ("_constrained_hac", "_hac_settings", "_assignment_writer", "_clustering_logger"):
        monkeypatch.setattr(runner, attr, object(), raising=False)

    clusters_added, created_ids = await runner._create_new_clusters_for_chunk(
        still_unclustered=[_ident("a"), _ident("b")],
        suggested_ids=set(),
        new_cluster_proposals=[([], [])],
        representatives_by_cluster={},
        centroids_by_cluster={},
        tenant_id="t1",
        job_id="job-1",
    )

    assert clusters_added == 6  # 1 fallback + 2 proposals + 3 hac
    assert created_ids == ["cl-fallback", "cl-prop1", "cl-prop2"]
    assert persist_calls == ["auto_new_cluster", "auto_proposal_new_cluster"]
    # "a" was claimed by the graph fallback -> excluded from HAC; "b" forwarded.
    assert hac_seen["ids"] == ["b"]


@pytest.mark.asyncio
async def test_create_new_clusters_skips_graph_fallback_when_nothing_unclustered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _bare_runner()

    discover_calls: list[object] = []

    async def _discover(identities: object, anchors: object) -> SimpleNamespace:
        discover_calls.append(identities)
        return SimpleNamespace(new_clusters=[])

    monkeypatch.setattr(runner, "_graph_discovery", SimpleNamespace(discover=_discover), raising=False)

    async def _fake_persist(
        new_clusters: object, *, resolve_reason: str, assigned_ids_out: set[str] | None = None, **_kw: object
    ) -> tuple[int, list[str]]:
        return 0, []

    monkeypatch.setattr(runner, "_persist_and_cache_new_clusters", _fake_persist, raising=False)

    hac_seen: dict[str, list[str]] = {}

    async def _fake_hac(*, still_unclustered: list[MediaIdentity], **_kw: object) -> int:
        hac_seen["ids"] = [i.id for i in still_unclustered]
        return 0

    monkeypatch.setattr(orchestrator_module, "run_hac_refinement", _fake_hac)
    for attr in ("_constrained_hac", "_hac_settings", "_assignment_writer", "_clustering_logger"):
        monkeypatch.setattr(runner, attr, object(), raising=False)

    clusters_added, created_ids = await runner._create_new_clusters_for_chunk(
        still_unclustered=[],
        suggested_ids=set(),
        new_cluster_proposals=[([], [])],
        representatives_by_cluster={},
        centroids_by_cluster={},
        tenant_id="t1",
        job_id="job-1",
    )

    assert clusters_added == 0
    assert created_ids == []
    assert discover_calls == []  # no graph fallback when nothing is unclustered
    assert hac_seen["ids"] == []
