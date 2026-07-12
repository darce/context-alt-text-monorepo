"""Daily demo expiry sweep (DS-4 / DS-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, DemoInstance
from recognition.application.services.demo_provisioning_service import (
    expire_demo,
    provision_demo,
    sweep_expired_demos,
)
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository


@pytest.mark.asyncio
async def test_demo_expiry_sweep_revokes_row_and_api_key(db_session: AsyncSession) -> None:
    past = await provision_demo(db_session, label="Past", seed="default")
    future = await provision_demo(db_session, label="Future", seed="default")
    await db_session.commit()

    past_row = await db_session.get(DemoInstance, past.instance.slug)
    assert past_row is not None
    past_row.expires_at = datetime.now(tz=UTC) - timedelta(days=1)
    await db_session.commit()

    result = await sweep_expired_demos(db_session)
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
