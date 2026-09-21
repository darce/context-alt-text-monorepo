"""Regression tests for the SQLite persist-lock transaction ownership."""

import asyncio

import pytest
from sqlalchemy import select

from db.models import MediaIdentity
from recognition.application.scan.service import (
    _InProcessPersistLockEntry,
    _persist_lock_owner_matches,
)


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
