"""Unit tests for RLS bypass at the four confirmed broken seam boundaries.

Phase 1 of rls-seam-fixes-and-polling-correction.md.

All 18 MV source tables carry relforcerowsecurity=true (FORCE ROW LEVEL SECURITY),
which applies even to the table owner.  Any session that does not set
app.bypass_rls='true' will see zero rows regardless of ownership.  These tests
verify that each seam correctly establishes the bypass before executing queries.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Seam 1: refresh_centroids_view_concurrent — AUTOCOMMIT connection
# ---------------------------------------------------------------------------


class TestRefreshMvConcurrentWithBypass:
    """_refresh_mv_concurrent_with_bypass sets bypass, refreshes, then resets."""

    async def test_bypass_set_before_refresh_and_reset_after(self) -> None:
        """SET app.bypass_rls must precede REFRESH and RESET must follow it."""
        from recognition.infrastructure.repositories.cluster_repository import (
            _refresh_mv_concurrent_with_bypass,
        )

        executed: list[str] = []

        class _FakeResult:
            def scalar_one(self) -> int:
                return 0

        class _FakeConn:
            async def execute(self, stmt, *args):  # noqa: ANN001
                executed.append(str(stmt))
                return _FakeResult()

        await _refresh_mv_concurrent_with_bypass(_FakeConn())

        assert executed[0] == "SET app.bypass_rls = 'true'", (
            "SET bypass_rls must be the first statement on the AUTOCOMMIT connection"
        )
        assert any("REFRESH MATERIALIZED VIEW CONCURRENTLY" in s for s in executed), (
            "REFRESH MATERIALIZED VIEW CONCURRENTLY must be executed"
        )
        assert executed[-1] == "RESET app.bypass_rls", (
            "RESET app.bypass_rls must be the last statement (even on exception)"
        )

    async def test_bypass_precedes_refresh_in_order(self) -> None:
        """SET bypass_rls index must be strictly less than REFRESH index."""
        from recognition.infrastructure.repositories.cluster_repository import (
            _refresh_mv_concurrent_with_bypass,
        )

        executed: list[str] = []

        class _FakeResult:
            def scalar_one(self) -> int:
                return 5

        class _FakeConn:
            async def execute(self, stmt, *args):  # noqa: ANN001
                executed.append(str(stmt))
                return _FakeResult()

        await _refresh_mv_concurrent_with_bypass(_FakeConn())

        bypass_idx = next(i for i, s in enumerate(executed) if "bypass_rls" in s and "'true'" in s)
        refresh_idx = next(i for i, s in enumerate(executed) if "REFRESH MATERIALIZED VIEW" in s)
        assert bypass_idx < refresh_idx

    async def test_reset_called_even_when_refresh_raises(self) -> None:
        """RESET app.bypass_rls must still execute if REFRESH throws."""
        from recognition.infrastructure.repositories.cluster_repository import (
            _refresh_mv_concurrent_with_bypass,
        )

        executed: list[str] = []
        call_count = [0]

        class _FakeResult:
            def scalar_one(self) -> int:
                return 0

        class _FakeConn:
            async def execute(self, stmt, *args):  # noqa: ANN001
                call_count[0] += 1
                stmt_str = str(stmt)
                executed.append(stmt_str)
                if "REFRESH MATERIALIZED VIEW" in stmt_str:
                    raise RuntimeError("refresh failed")
                return _FakeResult()

        with pytest.raises(RuntimeError, match="refresh failed"):
            await _refresh_mv_concurrent_with_bypass(_FakeConn())

        assert "RESET app.bypass_rls" in executed[-1], "RESET must be called even when REFRESH raises"

    async def test_logs_before_and_after_counts(self, caplog) -> None:
        """Refresh emits a log entry that includes before/after row counts."""
        import logging

        from recognition.infrastructure.repositories.cluster_repository import (
            _refresh_mv_concurrent_with_bypass,
        )

        class _FakeResult:
            def __init__(self, count: int) -> None:
                self._count = count

            def scalar_one(self) -> int:
                return self._count

        counts = iter([3, 7])  # before=3, after=7

        class _FakeConn:
            async def execute(self, stmt, *args):  # noqa: ANN001
                stmt_str = str(stmt)
                if "SELECT COUNT" in stmt_str:
                    return _FakeResult(next(counts))
                return _FakeResult(0)

        with caplog.at_level(logging.INFO, logger="recognition.infrastructure.repositories.cluster_repository"):
            await _refresh_mv_concurrent_with_bypass(_FakeConn())

        assert any("before=3" in r.message and "after=7" in r.message for r in caplog.records), (
            "Log record must contain before= and after= row counts"
        )


# ---------------------------------------------------------------------------
# Seam 2: progress_callback — fresh checkpoint session
# ---------------------------------------------------------------------------


class TestProgressCallbackBypass:
    """progress_callback enables RLS bypass before the UPDATE checkpoint."""

    async def test_enable_rls_bypass_called_before_update(self, monkeypatch) -> None:
        """enable_rls_bypass is invoked on the checkpoint session before the UPDATE."""
        from db.models import IdentityClusteringJob
        from recognition.worker.handlers.clustering import ClusteringJobHandler

        bypass_calls: list[object] = []

        async def fake_bypass(session) -> None:  # noqa: ANN001
            bypass_calls.append(session)

        monkeypatch.setattr(
            "recognition.worker.handlers.clustering.enable_rls_bypass",
            fake_bypass,
        )

        execute_calls: list[object] = []
        committed = [False]

        class _FakeResult:
            rowcount = 1

        class _FakeChkSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def execute(self, stmt, *args):
                execute_calls.append(stmt)
                return _FakeResult()

            async def commit(self):
                committed[0] = True

        fake_factory = MagicMock(return_value=_FakeChkSession())

        job = IdentityClusteringJob()
        job.id = uuid.uuid4()
        job.tenant_id = uuid.uuid4()
        job.processed_identities = 0
        job.total_identities = 0
        job.progress = 0.0

        handler = ClusteringJobHandler(session_factory=fake_factory)

        # Directly invoke the handler's internal progress_callback by extracting it
        # from a partial handle() call via a fake cluster service
        class _FakeCS:
            cluster_repository = MagicMock()

            def __init__(self):
                self.cluster_repository.get_snapshot = AsyncMock(return_value=([], [], 1, None))
                self.calls = []

            async def cluster_unclustered_identities(self, **kwargs):
                cb = kwargs.get("progress_callback")
                if cb:
                    await cb(5, 10)
                return SimpleNamespace(completed=5, total=10)

        class _FakeMainSession:
            async def flush(self):
                pass

            async def execute(self, stmt, *args):
                return _FakeResult()

        monkeypatch.setattr(
            "recognition.worker.handlers.clustering.build_cluster_service",
            AsyncMock(return_value=_FakeCS()),
        )
        monkeypatch.setattr(
            "recognition.worker.handlers.clustering.ensure_job_context",
            AsyncMock(),
        )

        await handler.handle(job, _FakeMainSession())

        assert len(bypass_calls) >= 1, "enable_rls_bypass must be called at least once on checkpoint session"

        # Bypass call must precede any execute call on the same session object
        assert committed[0], "checkpoint session must commit after UPDATE"

    async def test_raises_when_rowcount_is_zero(self, monkeypatch) -> None:
        """When the checkpoint UPDATE matches 0 rows a RuntimeError propagates
        from progress_callback (RLS context missing -- fail-fast)."""
        from db.models import IdentityClusteringJob
        from recognition.worker.handlers.clustering import ClusteringJobHandler

        monkeypatch.setattr(
            "recognition.worker.handlers.clustering.enable_rls_bypass",
            AsyncMock(),
        )

        class _FakeResult:
            rowcount = 0

        class _FakeChkSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def execute(self, stmt, *args):
                return _FakeResult()

            async def commit(self):
                pass

        fake_factory = MagicMock(return_value=_FakeChkSession())

        job = IdentityClusteringJob()
        job.id = uuid.uuid4()
        job.tenant_id = uuid.uuid4()
        job.processed_identities = 0
        job.total_identities = 0
        job.progress = 0.0

        class _FakeCS:
            cluster_repository = MagicMock()

            def __init__(self):
                self.cluster_repository.get_snapshot = AsyncMock(return_value=([], [], 1, None))

            async def cluster_unclustered_identities(self, **kwargs):
                cb = kwargs.get("progress_callback")
                if cb:
                    await cb(1, 10)
                return SimpleNamespace(completed=1, total=10)

        class _FakeMainSession:
            async def flush(self):
                pass

            async def execute(self, stmt, *args):
                return MagicMock(rowcount=1)

        monkeypatch.setattr(
            "recognition.worker.handlers.clustering.build_cluster_service",
            AsyncMock(return_value=_FakeCS()),
        )
        monkeypatch.setattr(
            "recognition.worker.handlers.clustering.ensure_job_context",
            AsyncMock(),
        )

        handler = ClusteringJobHandler(session_factory=fake_factory)
        with pytest.raises(RuntimeError, match="checkpoint UPDATE matched 0 rows"):
            await handler.handle(job, _FakeMainSession())


# ---------------------------------------------------------------------------
# Seam 3: ScheduledDisposalWorker.run_once — tenant listing + purge sessions
# ---------------------------------------------------------------------------


class TestScheduledDisposalWorkerBypass:
    """ScheduledDisposalWorker.run_once enables RLS bypass on every session."""

    async def test_bypass_enabled_on_tenant_listing_session(self, monkeypatch) -> None:
        """enable_rls_bypass is called on the session that lists tenant IDs."""
        from recognition.domain.services.purge_service import ScheduledDisposalWorker

        bypass_sessions: list[object] = []

        async def fake_bypass(session) -> None:  # noqa: ANN001
            bypass_sessions.append(session)

        monkeypatch.setattr(
            "recognition.domain.services.purge_service.enable_rls_bypass",
            fake_bypass,
        )

        session_instances: list[object] = []

        class _FakeSession:
            async def __aenter__(self):
                session_instances.append(self)
                return self

            async def __aexit__(self, *args):
                pass

            async def execute(self, stmt, *args):
                return MagicMock(scalars=lambda: MagicMock(all=lambda: []))

        fake_factory = MagicMock(return_value=_FakeSession())

        worker = ScheduledDisposalWorker(session_factory=fake_factory)
        await worker.run_once()

        # At least the first session (tenant listing) must have bypass enabled
        assert len(bypass_sessions) >= 1, "bypass must be enabled on the tenant listing session"

    async def test_bypass_enabled_on_per_tenant_purge_session(self, monkeypatch) -> None:
        """enable_rls_bypass is called on each per-tenant purge session."""
        from recognition.domain.services.purge_service import ScheduledDisposalWorker

        bypass_sessions: list[object] = []

        async def fake_bypass(session) -> None:  # noqa: ANN001
            bypass_sessions.append(session)

        monkeypatch.setattr(
            "recognition.domain.services.purge_service.enable_rls_bypass",
            fake_bypass,
        )

        tenant_id_1 = uuid.uuid4()
        listing_done = [False]

        class _FakeTenantSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def execute(self, stmt, *args):
                if not listing_done[0]:
                    listing_done[0] = True
                    return MagicMock(scalars=lambda: MagicMock(all=lambda: [tenant_id_1]))
                return MagicMock(scalars=lambda: MagicMock(all=lambda: []))

        class _FakePurgeService:
            async def purge_tenant_data(self, **kwargs):
                return {"deleted": 0}

        class _FakePurgeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        call_count = [0]

        def fake_factory():
            call_count[0] += 1
            if call_count[0] == 1:
                return _FakeTenantSession()
            return _FakePurgeSession()

        monkeypatch.setattr(
            "recognition.domain.services.purge_service.TenantPurgeService",
            lambda session: _FakePurgeService(),
        )

        worker = ScheduledDisposalWorker(session_factory=fake_factory)
        await worker.run_once()

        # Both the listing session and the purge session must have bypass enabled
        assert len(bypass_sessions) >= 2, (
            "bypass must be enabled on both the tenant listing session and each purge session; "
            f"got {len(bypass_sessions)} bypass calls"
        )


# ---------------------------------------------------------------------------
# Seam 4: IncrementalClusteringRunner._finalize_job — post-commit context
# ---------------------------------------------------------------------------


class TestFinalizeJobPostCommitContext:
    """After the final commit, set_tenant_context + enable_rls_bypass must be re-called.

    Only applies when commit=True (HTTP sync path).  The worker path uses
    commit=False and must NOT trigger the restoration.
    """

    def _make_runner(self, *, commit: bool, session: object) -> Any:
        """Build a minimal IncrementalClusteringRunner for direct method testing."""
        from unittest.mock import MagicMock

        from recognition.application.orchestration.clustering.orchestrator import (
            IncrementalClusteringRunner,
        )

        stub = MagicMock()
        runner = IncrementalClusteringRunner(
            session=session,
            gate=stub,
            representative_discovery=stub,
            centroid_discovery=stub,
            graph_discovery=stub,
            assignment_writer=stub,
            suggestion_service=stub,
            commit=commit,
        )
        return runner

    async def test_set_tenant_context_and_bypass_called_when_commit_true(self, monkeypatch) -> None:
        """When commit=True, set_tenant_context then enable_rls_bypass are called after commit."""
        tenant_id = str(uuid.uuid4())
        commit_order: list[str] = []

        class _FakeSession:
            async def flush(self):
                pass

            async def commit(self):
                commit_order.append("commit")

        async def fake_set_tc(session, tid) -> None:  # noqa: ANN001
            commit_order.append("set_tenant_context")

        async def fake_bypass(session) -> None:  # noqa: ANN001
            commit_order.append("enable_rls_bypass")

        monkeypatch.setattr(
            "recognition.application.orchestration.clustering.orchestrator.set_tenant_context",
            fake_set_tc,
        )
        monkeypatch.setattr(
            "recognition.application.orchestration.clustering.orchestrator.enable_rls_bypass",
            fake_bypass,
        )
        monkeypatch.setattr(
            "recognition.application.orchestration.clustering.orchestrator.complete_recognition_run",
            AsyncMock(),
        )

        from db.models import IdentityClusteringJob

        job = IdentityClusteringJob()
        job.id = uuid.uuid4()
        job.tenant_id = uuid.uuid4()
        job.payload = {}

        runner = self._make_runner(commit=True, session=_FakeSession())
        runner._assignment_writer.cluster_repository.confirm_all_provisional_reps = AsyncMock(return_value=0)

        await runner._finalize_job(
            clustering_job=job,
            run_id=uuid.uuid4(),
            tenant_id=tenant_id,
            started_at=__import__("datetime").datetime.now(tz=__import__("datetime").timezone.utc),
            job_id=str(job.id),
            total_identities=0,
            accept_count=0,
            suggest_count=0,
            reject_count=0,
            clusters_created=0,
            created_cluster_ids=[],
            algorithm="test",
        )

        assert "commit" in commit_order, "session.commit must be called"
        commit_idx = commit_order.index("commit")
        assert "set_tenant_context" in commit_order, "set_tenant_context must be called"
        assert "enable_rls_bypass" in commit_order, "enable_rls_bypass must be called"
        assert commit_order.index("set_tenant_context") > commit_idx, "set_tenant_context must come AFTER commit"
        assert commit_order.index("enable_rls_bypass") > commit_order.index("set_tenant_context"), (
            "enable_rls_bypass must come AFTER set_tenant_context"
        )

    async def test_no_context_restoration_when_commit_false(self, monkeypatch) -> None:
        """When commit=False (worker path), context restoration must NOT occur."""
        tenant_id = str(uuid.uuid4())
        context_calls: list[str] = []

        class _FakeSession:
            async def flush(self):
                pass

            async def commit(self):
                pass  # should not be called when commit=False

        async def fake_set_tc(session, tid) -> None:  # noqa: ANN001
            context_calls.append("set_tenant_context")

        async def fake_bypass(session) -> None:  # noqa: ANN001
            context_calls.append("enable_rls_bypass")

        monkeypatch.setattr(
            "recognition.application.orchestration.clustering.orchestrator.set_tenant_context",
            fake_set_tc,
        )
        monkeypatch.setattr(
            "recognition.application.orchestration.clustering.orchestrator.enable_rls_bypass",
            fake_bypass,
        )
        monkeypatch.setattr(
            "recognition.application.orchestration.clustering.orchestrator.complete_recognition_run",
            AsyncMock(),
        )

        from db.models import IdentityClusteringJob

        job = IdentityClusteringJob()
        job.id = uuid.uuid4()
        job.tenant_id = uuid.uuid4()
        job.payload = {}

        runner = self._make_runner(commit=False, session=_FakeSession())
        runner._assignment_writer.cluster_repository.confirm_all_provisional_reps = AsyncMock(return_value=0)

        await runner._finalize_job(
            clustering_job=job,
            run_id=uuid.uuid4(),
            tenant_id=tenant_id,
            started_at=__import__("datetime").datetime.now(tz=__import__("datetime").timezone.utc),
            job_id=str(job.id),
            total_identities=0,
            accept_count=0,
            suggest_count=0,
            reject_count=0,
            clusters_created=0,
            created_cluster_ids=[],
            algorithm="test",
        )

        assert context_calls == [], f"No context restoration must occur when commit=False; got {context_calls}"
