"""Tests equivalent to the verify_rls script without shelling out."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import select

if os.getenv("ALLOW_RLS_BYPASS_FOR_TESTS") == "1":
    pytest.skip("RLS bypass enabled; skipping RLS verification", allow_module_level=True)

from db.models import MediaIdentity, Tenant
from db.session import async_session_factory
from db.tenant_context import clear_tenant_context, set_tenant_context


@pytest.mark.asyncio
async def test_rls_is_enforced_for_cross_tenants(require_database):
    tenant_a = uuid4()
    tenant_b = uuid4()

    async with async_session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_a, site_url=f"https://{tenant_a}.local"),
                Tenant(id=tenant_b, site_url=f"https://{tenant_b}.local"),
            ]
        )
        await session.commit()

        await set_tenant_context(session, tenant_a)
        identity = MediaIdentity(
            tenant_id=tenant_a,
            media_id=1,
            media_url="https://example.com/a.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=10,
            bbox_height=10,
            confidence=0.9,
            embedding=[1.0] + [0.0] * 1023,
        )
        session.add(identity)
        await session.commit()
        await clear_tenant_context(session)

        await set_tenant_context(session, tenant_b)
        result = await session.execute(select(MediaIdentity))
        assert result.scalars().all() == []
        await clear_tenant_context(session)

        session.add(
            MediaIdentity(
                tenant_id=tenant_b,
                media_id=2,
                media_url="https://example.com/b.jpg",
                bbox_x=0,
                bbox_y=0,
                bbox_width=10,
                bbox_height=10,
                confidence=0.8,
                embedding=[1.0] + [0.0] * 1023,
            )
        )
        # Without tenant context this commit must fail.
        with pytest.raises(Exception):
            await session.commit()
        await session.rollback()
