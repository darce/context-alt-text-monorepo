"""Tests to verify PostgreSQL row-level security and tenant context enforcement."""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from db.models import IdentityScanJob, MediaIdentity, Tenant
from db.session import async_session_factory
from db.tenant_context import clear_tenant_context, set_tenant_context


async def _create_tenant(session, tenant_id):
    session.add(Tenant(id=tenant_id, site_url=f"https://{tenant_id}.example.com"))
    await session.flush()


async def _create_job(tenant_id):
    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_id)
        tenant = await session.get(Tenant, tenant_id)
        if not tenant:
            await _create_tenant(session, tenant_id)
        job = IdentityScanJob(
            tenant_id=tenant_id,
            status="pending",
            media_ids=[1],
            total_media=1,
        )
        session.add(job)
        await session.commit()
        await set_tenant_context(session, tenant_id)
        await session.refresh(job)
        await clear_tenant_context(session)
        return job


@pytest_asyncio.fixture()
async def require_database():
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except (OperationalError, asyncpg.PostgresError, SQLAlchemyError) as exc:
        pytest.skip(f"PostgreSQL unavailable or misconfigured: {exc}")
    yield


pytestmark = pytest.mark.usefixtures("require_database")


@pytest.mark.asyncio
async def test_rls_limits_reads_to_current_tenant():
    tenant_a = uuid4()
    tenant_b = uuid4()

    async with async_session_factory() as session:
        await session.begin()
        await _create_tenant(session, tenant_a)
        await _create_tenant(session, tenant_b)
        await session.commit()

        await set_tenant_context(session, tenant_a)
        identity_a = MediaIdentity(
            tenant_id=tenant_a,
            media_id=1,
            media_url="https://example.com/a",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.8,
            embedding=[0.0] * 1024,
        )
        session.add(identity_a)
        await session.commit()
        await clear_tenant_context(session)

        await set_tenant_context(session, tenant_b)
        identity_b = MediaIdentity(
            tenant_id=tenant_b,
            media_id=2,
            media_url="https://example.com/b",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.9,
            embedding=[0.5] * 1024,
        )
        session.add(identity_b)
        await session.commit()
        await clear_tenant_context(session)

        await set_tenant_context(session, tenant_a)
        result = await session.execute(select(MediaIdentity))
        identities = result.scalars().all()
        assert len(identities) == 1
        assert identities[0].tenant_id == tenant_a
        await clear_tenant_context(session)

        await set_tenant_context(session, tenant_b)
        result = await session.execute(select(MediaIdentity))
        identities = result.scalars().all()
        assert len(identities) == 1
        assert identities[0].tenant_id == tenant_b
        await clear_tenant_context(session)


@pytest.mark.asyncio
async def test_rls_blocks_inserts_without_context():
    tenant_id = uuid4()
    async with async_session_factory() as session:
        await session.begin()
        await _create_tenant(session, tenant_id)
        await session.commit()

        identity = MediaIdentity(
            tenant_id=tenant_id,
            media_id=99,
            media_url="https://example.com/99",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.9,
            embedding=[0.1] * 1024,
        )
        session.add(identity)

        with pytest.raises(SQLAlchemyError) as exc_info:
            await session.commit()

        assert "row-level security policy" in str(exc_info.value).lower()
        await session.rollback()


@pytest.mark.asyncio
async def test_job_endpoint_observes_tenant(async_client):
    tenant_a = uuid4()
    tenant_b = uuid4()
    job = await _create_job(tenant_a)

    response = await async_client.get(
        f"/recognition/jobs/{job.id}",
        params={"tenant_id": str(tenant_b)},
    )
    assert response.status_code == 404

    response = await async_client.get(
        f"/recognition/jobs/{job.id}",
        params={"tenant_id": str(tenant_a)},
    )
    assert response.status_code == 200
