"""Daily demo expiry sweep (DS-4 / DS-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, DemoInstance
from recognition.application.services.demo_provisioning_service import (
    WordPressSeedState,
    expire_demo,
    provision_demo,
    sweep_expired_demos,
)
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository


class RecordingWordPressGateway:
    def __init__(self) -> None:
        self.disabled: list[str] = []

    async def provision_user(self, *, username: str, password: str, seed_bundle: str) -> WordPressSeedState:
        return WordPressSeedState(faces_count=0, people_count=0)

    async def disable_user(self, *, username: str) -> None:
        self.disabled.append(username)


@pytest.mark.asyncio
async def test_demo_expiry_sweep_revokes_row_and_api_key(db_session: AsyncSession) -> None:
    wordpress = RecordingWordPressGateway()
    past = await provision_demo(db_session, label="Past", seed="default")
    future = await provision_demo(db_session, label="Future", seed="default")
    await db_session.commit()

    past_row = await db_session.get(DemoInstance, past.instance.slug)
    assert past_row is not None
    past_row.expires_at = datetime.now(tz=UTC) - timedelta(days=1)
    await db_session.commit()

    result = await sweep_expired_demos(db_session, wordpress=wordpress)
    await db_session.commit()

    assert result.expired == 1
    assert past.instance.slug in result.slugs_expired
    assert result.stalled is False

    reloaded = await db_session.get(DemoInstance, past.instance.slug)
    assert reloaded is not None
    assert reloaded.revoked is True

    key = (
        await db_session.execute(select(ApiKey).where(ApiKey.api_key_hash == past.instance.api_key_ref))
    ).scalar_one()
    assert key.revoked_at is not None
    assert await SqlAlchemyApiKeyRepository(db_session).get_by_hash(past.instance.api_key_ref) is None

    still_active = await db_session.get(DemoInstance, future.instance.slug)
    assert still_active is not None
    assert still_active.revoked is False
    assert wordpress.disabled == [past.wordpress_username]


@pytest.mark.asyncio
async def test_demo_expiry_sweep_disables_every_swept_wordpress_user(db_session: AsyncSession) -> None:
    wordpress = RecordingWordPressGateway()
    first = await provision_demo(db_session, label="First", seed="default")
    second = await provision_demo(db_session, label="Second", seed="default")
    await db_session.commit()

    for provisioned in (first, second):
        row = await db_session.get(DemoInstance, provisioned.instance.slug)
        assert row is not None
        row.expires_at = datetime.now(tz=UTC) - timedelta(hours=1)
    await db_session.commit()

    result = await sweep_expired_demos(db_session, wordpress=wordpress)

    assert result.expired == 2
    assert set(wordpress.disabled) == {first.wordpress_username, second.wordpress_username}


@pytest.mark.asyncio
async def test_demo_expiry_sweep_isolates_failures_and_stalls(db_session: AsyncSession) -> None:
    a = await provision_demo(db_session, label="A", seed="default")
    b = await provision_demo(db_session, label="B", seed="default")
    c = await provision_demo(db_session, label="C", seed="default")
    await db_session.commit()

    for slug in (a.instance.slug, b.instance.slug, c.instance.slug):
        row = await db_session.get(DemoInstance, slug)
        assert row is not None
        row.expires_at = datetime.now(tz=UTC) - timedelta(hours=1)
    await db_session.commit()

    fail_count = {"n": 0}

    async def _flaky_expire(session, *, slug: str):  # noqa: ANN001
        fail_count["n"] += 1
        if fail_count["n"] <= 2:
            raise RuntimeError(f"boom-{slug}")
        return await expire_demo(session, slug=slug)

    with patch(
        "recognition.application.services.demo_provisioning_service.expire_demo",
        new=AsyncMock(side_effect=_flaky_expire),
    ):
        # stall_limit=2 → abort after two consecutive failures without processing C.
        result = await sweep_expired_demos(db_session, stall_limit=2)

    assert result.stalled is True
    assert result.failed == 2
    assert result.expired == 0


@pytest.mark.asyncio
async def test_demo_expiry_sweep_db_error_in_one_unit_isolates_others(db_session: AsyncSession) -> None:
    """A DB-level failure in one unit must not lose the others (rg-007 savepoint)."""
    from sqlalchemy.exc import OperationalError

    a = await provision_demo(db_session, label="A", seed="default")
    b = await provision_demo(db_session, label="B", seed="default")
    c = await provision_demo(db_session, label="C", seed="default")
    await db_session.commit()

    for slug in (a.instance.slug, b.instance.slug, c.instance.slug):
        row = await db_session.get(DemoInstance, slug)
        assert row is not None
        row.expires_at = datetime.now(tz=UTC) - timedelta(hours=1)
    await db_session.commit()

    real_expire = expire_demo

    async def _expire_but_fail_b(session, *, slug: str):  # noqa: ANN001
        if slug == b.instance.slug:
            raise OperationalError("boom", None, Exception("db down"))
        return await real_expire(session, slug=slug)

    with patch(
        "recognition.application.services.demo_provisioning_service.expire_demo",
        new=AsyncMock(side_effect=_expire_but_fail_b),
    ):
        # High stall limit: the single B failure must not halt A and C.
        result = await sweep_expired_demos(db_session, stall_limit=5)
    await db_session.commit()

    assert result.failed == 1
    assert result.expired == 2
    assert result.stalled is False

    # A and C committed as revoked; B untouched — the savepoint isolated B's abort.
    for ok_slug in (a.instance.slug, c.instance.slug):
        row = await db_session.get(DemoInstance, ok_slug)
        assert row is not None
        assert row.revoked is True
    b_row = await db_session.get(DemoInstance, b.instance.slug)
    assert b_row is not None
    assert b_row.revoked is False
