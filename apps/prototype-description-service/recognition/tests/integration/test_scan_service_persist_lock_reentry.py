"""Regression tests for the SQLite persist-lock transaction ownership."""

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import MediaIdentity
from recognition.application.scan.service import (
    _IN_PROCESS_PERSIST_LOCKS,
    _InProcessPersistLockEntry,
    _media_persist_lock,
    _persist_lock_key,
    _persist_lock_owner_matches,
)


class _SyncOnlyAsyncSession:
    """Minimal AsyncSession stand-in exposing the two attrs the lock reads."""

    def __init__(self, sync_session: Session, bind: object) -> None:
        self.sync_session = sync_session
        self.bind = bind


@pytest.mark.asyncio
async def test_same_sqlite_transaction_can_rescan_one_media_item(
    db_session,
    tenant,
    scan_service,
) -> None:
    """A same-session replay must re-enter the lock held until commit."""
    await scan_service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=123,
        media_url="http://example.test/image.jpg",
    )

    stmt = select(MediaIdentity).where(
        MediaIdentity.tenant_id == tenant.id,
        MediaIdentity.media_id == 123,
    )
    first_row = (await db_session.execute(stmt)).scalar_one()

    await asyncio.wait_for(
        scan_service.process_media_item(
            tenant_id=str(tenant.id),
            media_id=123,
            media_url="http://example.test/image.jpg",
        ),
        timeout=1.0,
    )

    rows = (await db_session.execute(stmt)).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == first_row.id


def test_persist_lock_owner_does_not_match_distinct_sessions() -> None:
    """A different sync session cannot reuse another session's ownership."""
    owner_session = object()
    other_session = object()
    root_transaction = object()
    entry = _InProcessPersistLockEntry(
        lock=asyncio.Lock(),
        owner_sync_session=owner_session,
        owner_root_transaction=root_transaction,
        reentry_depth=1,
    )

    assert _persist_lock_owner_matches(entry, owner_session, root_transaction)
    assert not _persist_lock_owner_matches(entry, other_session, root_transaction)
    assert not _persist_lock_owner_matches(entry, owner_session, object())


@pytest.mark.asyncio
async def test_stale_owner_cannot_re_enter_after_releasing_to_a_waiter() -> None:
    """Releasing to a waiter must disarm ownership, not re-arm it (RES-13)."""
    engine = create_engine("sqlite://")
    tenant_uuid = uuid.uuid4()
    media_id = 424242
    key = _persist_lock_key(tenant_uuid, media_id)

    sync_a = Session(engine)
    sync_b = Session(engine)
    shim_a = _SyncOnlyAsyncSession(sync_a, engine)
    shim_b = _SyncOnlyAsyncSession(sync_b, engine)

    b_inside = asyncio.Event()
    b_may_exit = asyncio.Event()

    async def hold_as_b() -> None:
        async with _media_persist_lock(shim_b, tenant_uuid, media_id):
            b_inside.set()
            await b_may_exit.wait()

    b_task: asyncio.Task[None] | None = None
    a_ctx = _media_persist_lock(shim_a, tenant_uuid, media_id)
    await a_ctx.__aenter__()
    try:
        b_task = asyncio.create_task(hold_as_b())
        for _ in range(100):
            await asyncio.sleep(0)
            queued = _IN_PROCESS_PERSIST_LOCKS.get(key)
            if queued is not None and queued.waiters >= 2:
                break
        else:  # pragma: no cover - scheduling guard
            pytest.fail("session B never queued on the persist lock")

        sync_a.begin()
        # _release runs here: it clears ownership, frees the lock for B, and
        # defers _remove_listener to the next loop tick. The begin() below
        # lands inside that window, so the still-registered capture listener
        # must refuse to re-arm a lock this section no longer holds.
        sync_a.commit()
        sync_a.begin()
    finally:
        await a_ctx.__aexit__(None, None, None)

    try:
        await asyncio.wait_for(b_inside.wait(), timeout=1.0)
        reentry = _media_persist_lock(shim_a, tenant_uuid, media_id)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(reentry.__aenter__(), timeout=0.25)
    finally:
        b_may_exit.set()
        if b_task is not None:
            await asyncio.wait_for(b_task, timeout=1.0)
        sync_a.rollback()
        sync_a.close()
        sync_b.close()
        engine.dispose()
