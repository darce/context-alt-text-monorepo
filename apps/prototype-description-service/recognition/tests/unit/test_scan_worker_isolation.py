"""E15-27 Slice 3: per-item tenant isolation in concurrent scan batches."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import IdentityScanJobItem, Tenant
from recognition.application.scan.queue_repository import ScanQueueItem
from recognition.domain.job import ScanItemStatus
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.worker.handlers.scan import ScanItemHandler


def _claimed_item(
    *,
    item_id: uuid.UUID,
    job_id: uuid.UUID,
    tenant_id: uuid.UUID,
    media_id: int,
) -> ScanQueueItem:
    now = datetime.now(tz=UTC)
    return ScanQueueItem(
        id=item_id,
        job_id=job_id,
        tenant_id=tenant_id,
        media_id=media_id,
        media_url=f"http://example.test/{media_id}.jpg",
        status=ScanItemStatus.PROCESSING.value,
        attempts=1,
        identities_detected=0,
        last_error=None,
        created_at=now,
        started_at=now,
    )


@pytest.mark.asyncio
async def test_process_items_isolates_poisoned_tenant_among_three(
    db_session: AsyncSession,
) -> None:
    """One tenant's exception must not abort sibling tenants in the same batch."""
    tenants = [Tenant(site_url=f"http://tenant-{index}.test") for index in range(3)]
    db_session.add_all(tenants)
    await db_session.commit()
    for tenant in tenants:
        await db_session.refresh(tenant)

    poison_tenant_id = tenants[1].id
    repo = SqlAlchemyScanQueueRepository(db_session)
    job_ids: list[uuid.UUID] = []
    claimed: list[ScanQueueItem] = []
    for index, tenant in enumerate(tenants):
        job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[index + 1])
        job_ids.append(job_id)
        await repo.enqueue_items(
            job_id=job_id,
            tenant_id=tenant.id,
            items=[(index + 1, f"http://example.test/{index + 1}.jpg")],
        )
        item_row = (
            await db_session.execute(select(IdentityScanJobItem).where(IdentityScanJobItem.job_id == job_id))
        ).scalar_one()
        claimed.append(
            _claimed_item(
                item_id=item_row.id,
                job_id=job_id,
                tenant_id=tenant.id,
                media_id=index + 1,
            )
        )
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    async def _process_media_item(
        *,
        tenant_id: str,
        media_id: int,
        media_url: str,
        job_id: uuid.UUID | str | None = None,
    ) -> int:
        if uuid.UUID(tenant_id) == poison_tenant_id:
            raise RuntimeError("poisoned tenant")
        return 1

    handler = ScanItemHandler(
        session_factory=session_factory,
        detector=AsyncMock(),
        generator=AsyncMock(),
        max_attempts=3,
        max_concurrency=3,
    )

    with (
        patch.object(handler, "_build_scan_service") as build_svc,
        patch.object(handler, "_refresh_job_progress", new=AsyncMock()),
    ):
        svc = AsyncMock()
        svc.process_media_item = _process_media_item
        build_svc.return_value = svc
        await handler.process_items(claimed=claimed)

    result = await db_session.execute(
        select(IdentityScanJobItem.job_id, IdentityScanJobItem.status, IdentityScanJobItem.last_error)
    )
    rows = {(job_id, status, last_error) for job_id, status, last_error in result.all()}

    healthy_job_ids = {job_ids[0], job_ids[2]}
    poison_job_id = job_ids[1]
    assert any(job_id in healthy_job_ids and status == ScanItemStatus.COMPLETED.value for job_id, status, _ in rows)
    assert any(
        job_id == poison_job_id and status == ScanItemStatus.PENDING.value and last_error == "poisoned tenant"
        for job_id, status, last_error in rows
    )


@pytest.mark.asyncio
async def test_persist_integrity_error_is_terminal_no_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOCAL47C-03: PersistIntegrityError is deterministic/terminal on the queue path.

    ScanItemHandler must:
    - rollback staged identity work before writing failure status
    - NOT call release_item_for_retry even when attempts < max
    - mark the item FAILED immediately
    """
    from recognition.application.scan.service import PersistIntegrityError

    tenant_id = uuid.uuid4()
    job_id = uuid.uuid4()
    item_id = uuid.uuid4()
    item = _claimed_item(
        item_id=item_id,
        job_id=job_id,
        tenant_id=tenant_id,
        media_id=42,
    )
    # attempts < max so generic exceptions would still retry — integrity must not.
    assert item.attempts == 1

    integrity_exc = PersistIntegrityError("embedding length 127 != pgvector_dimension 128")
    partial_row = SimpleNamespace(kind="partial_identity", media_id=42)
    ops: list[str] = []
    released: dict[str, object] = {}
    failed: dict[str, object] = {}
    pending: list[object] = []
    committed_batches: list[list[object]] = []

    class _Repo:
        async def mark_item_completed(self, **_kwargs):  # noqa: ANN001
            raise AssertionError("integrity failure must not complete the item")

        async def release_item_for_retry(self, *, item_id, error_message):  # noqa: ANN001
            ops.append("release_item_for_retry")
            released["item_id"] = item_id
            released["error_message"] = error_message

        async def mark_item_failed(self, *, item_id, completed_at, error_message):  # noqa: ANN001
            ops.append("mark_item_failed")
            failed["item_id"] = item_id
            failed["error_message"] = error_message
            failed["completed_at"] = completed_at

    class _Session:
        def add(self, obj) -> None:
            pending.append(obj)
            ops.append("add")

        async def flush(self) -> None:
            ops.append("flush")

        async def rollback(self) -> None:
            ops.append("rollback")
            pending.clear()

        async def commit(self) -> None:
            ops.append("commit")
            committed_batches.append(list(pending))
            pending.clear()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    session = _Session()

    class _Factory:
        def __call__(self):
            return session

    class _ScanService:
        async def process_media_item(self, **_kwargs):  # noqa: ANN001
            # Flush-only path stages identity work then hits deterministic integrity error.
            session.add(partial_row)
            await session.flush()
            raise integrity_exc

        def emit_pending_scan_media_reconciled(self) -> None:
            raise AssertionError("must not emit reconcile events after integrity failure")

    handler = ScanItemHandler(
        session_factory=_Factory(),  # type: ignore[arg-type]
        detector=AsyncMock(),
        generator=AsyncMock(),
        max_attempts=3,
        max_concurrency=1,
    )

    monkeypatch.setattr(
        "recognition.worker.handlers.scan.enable_rls_bypass",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "recognition.worker.handlers.scan.SqlAlchemyScanQueueRepository",
        lambda _session: _Repo(),
    )
    handler._refresh_job_progress = AsyncMock()  # type: ignore[method-assign]
    handler._build_scan_service = lambda _session: _ScanService()  # type: ignore[method-assign]

    await handler.process_items(claimed=[item])

    assert "release_item_for_retry" not in ops, (
        "PersistIntegrityError must not retry even when attempts < max"
    )
    assert released == {}, "release_item_for_retry must not be called for integrity errors"
    assert failed.get("item_id") == item_id
    assert "embedding length" in str(failed.get("error_message") or "")
    assert failed.get("completed_at") is not None
    assert "rollback" in ops, "must rollback staged identity work before failure status"
    assert ops.index("rollback") < ops.index("mark_item_failed"), (
        "rollback must precede writing FAILED status"
    )
    assert ops.index("mark_item_failed") < ops.index("commit"), (
        "FAILED status write must be committed after mark_item_failed"
    )
    all_committed = [item for batch in committed_batches for item in batch]
    assert not any(getattr(row, "kind", None) == "partial_identity" for row in all_committed), (
        "partial identity rows must not be committed with the failure status"
    )


@pytest.mark.asyncio
async def test_generic_exception_still_releases_for_retry_under_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOCAL47C-03 control: non-integrity exceptions keep existing retry behavior."""
    tenant_id = uuid.uuid4()
    job_id = uuid.uuid4()
    item_id = uuid.uuid4()
    item = _claimed_item(
        item_id=item_id,
        job_id=job_id,
        tenant_id=tenant_id,
        media_id=43,
    )
    assert item.attempts == 1

    released: dict[str, object] = {}
    failed: dict[str, object] = {}

    class _Repo:
        async def mark_item_completed(self, **_kwargs):  # noqa: ANN001
            raise AssertionError("transient failure must not complete")

        async def release_item_for_retry(self, *, item_id, error_message):  # noqa: ANN001
            released["item_id"] = item_id
            released["error_message"] = error_message

        async def mark_item_failed(self, **kwargs):  # noqa: ANN001
            failed.update(kwargs)

    class _Session:
        async def rollback(self) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _Factory:
        def __call__(self):
            return _Session()

    class _ScanService:
        async def process_media_item(self, **_kwargs):  # noqa: ANN001
            raise RuntimeError("transient adapter blip")

        def emit_pending_scan_media_reconciled(self) -> None:
            raise AssertionError("must not emit on failure")

    handler = ScanItemHandler(
        session_factory=_Factory(),  # type: ignore[arg-type]
        detector=AsyncMock(),
        generator=AsyncMock(),
        max_attempts=3,
        max_concurrency=1,
    )

    monkeypatch.setattr(
        "recognition.worker.handlers.scan.enable_rls_bypass",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "recognition.worker.handlers.scan.SqlAlchemyScanQueueRepository",
        lambda _session: _Repo(),
    )
    handler._refresh_job_progress = AsyncMock()  # type: ignore[method-assign]
    handler._build_scan_service = lambda _session: _ScanService()  # type: ignore[method-assign]

    await handler.process_items(claimed=[item])

    assert released.get("item_id") == item_id
    assert "transient adapter blip" in str(released.get("error_message") or "")
    assert failed == {}, "generic exceptions under max attempts must not mark FAILED"


@pytest.mark.asyncio
async def test_failure_path_restores_rls_bypass_after_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIR-FINAL2-LOCAL-01: SET LOCAL bypass is cleared by rollback; restore before status write.

    Under FORCE RLS, mark_item_failed / release_item_for_retry affect zero rows
    when bypass is not re-enabled after session.rollback(). Contract order:
    enable_rls_bypass (start) → process → rollback → enable_rls_bypass →
    failure update → commit.
    """
    tenant_id = uuid.uuid4()
    job_id = uuid.uuid4()
    item_id = uuid.uuid4()
    item = _claimed_item(
        item_id=item_id,
        job_id=job_id,
        tenant_id=tenant_id,
        media_id=44,
    )
    assert item.attempts == 1

    ops: list[str] = []
    failed: dict[str, object] = {}
    released: dict[str, object] = {}

    class _Repo:
        async def mark_item_completed(self, **_kwargs):  # noqa: ANN001
            raise AssertionError("failure path must not complete")

        async def release_item_for_retry(self, *, item_id, error_message):  # noqa: ANN001
            ops.append("release_item_for_retry")
            released["item_id"] = item_id
            released["error_message"] = error_message

        async def mark_item_failed(self, *, item_id, completed_at, error_message):  # noqa: ANN001
            ops.append("mark_item_failed")
            failed["item_id"] = item_id
            failed["error_message"] = error_message
            failed["completed_at"] = completed_at

    class _Session:
        async def rollback(self) -> None:
            ops.append("rollback")

        async def commit(self) -> None:
            ops.append("commit")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    async def _track_bypass(_session) -> None:  # noqa: ANN001
        ops.append("enable_rls_bypass")

    class _Factory:
        def __call__(self):
            return _Session()

    class _ScanService:
        async def process_media_item(self, **_kwargs):  # noqa: ANN001
            ops.append("process_media_item")
            raise RuntimeError("adapter boom")

        def emit_pending_scan_media_reconciled(self) -> None:
            raise AssertionError("must not emit on failure")

    handler = ScanItemHandler(
        session_factory=_Factory(),  # type: ignore[arg-type]
        detector=AsyncMock(),
        generator=AsyncMock(),
        max_attempts=3,
        max_concurrency=1,
    )

    monkeypatch.setattr(
        "recognition.worker.handlers.scan.enable_rls_bypass",
        _track_bypass,
    )
    monkeypatch.setattr(
        "recognition.worker.handlers.scan.SqlAlchemyScanQueueRepository",
        lambda _session: _Repo(),
    )
    handler._refresh_job_progress = AsyncMock()  # type: ignore[method-assign]
    handler._build_scan_service = lambda _session: _ScanService()  # type: ignore[method-assign]

    await handler.process_items(claimed=[item])

    # Durable status: retry release (attempts < max), not silent no-op.
    assert released.get("item_id") == item_id
    assert "adapter boom" in str(released.get("error_message") or "")
    assert failed == {}

    assert ops.count("enable_rls_bypass") >= 2, (
        "must re-enable RLS bypass after rollback before failure status write; "
        f"ops={ops}"
    )
    assert "rollback" in ops
    assert "release_item_for_retry" in ops
    assert "commit" in ops

    first_bypass = ops.index("enable_rls_bypass")
    process_idx = ops.index("process_media_item")
    rollback_idx = ops.index("rollback")
    # Second bypass must land after rollback and before the failure update.
    post_rollback = ops[rollback_idx + 1 :]
    assert "enable_rls_bypass" in post_rollback, (
        f"enable_rls_bypass missing after rollback; ops={ops}"
    )
    second_bypass_rel = post_rollback.index("enable_rls_bypass")
    failure_rel = post_rollback.index("release_item_for_retry")
    commit_rel = post_rollback.index("commit")
    assert first_bypass < process_idx < rollback_idx
    assert second_bypass_rel < failure_rel < commit_rel, (
        "contract: rollback → enable_rls_bypass → failure update → commit; "
        f"ops={ops}"
    )
