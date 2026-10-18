"""PostgreSQL proof that operator entitlement lookup is tenant-isolated and fail-closed.

Skip is missing release evidence, not a passing result. pg_empty_engine refuses
privileged roles; IDENTITY_PG_REQUIRED=1 fails instead of skip. No external providers.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.portal_billing import TenantEntitlement
from db.models.tenant import Tenant
from db.tenant_context import set_tenant_context
from recognition.domain.portal_contracts import EntitlementStatus
from recognition.infrastructure.repositories.tenant_entitlement_repository import (
    SqlAlchemyTenantEntitlementRepository,
)
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.deps.operator_authorization import (
    OPERATOR_FORBIDDEN_DETAIL,
    OPERATOR_UNAVAILABLE_DETAIL,
    authorize_operator_control,
)

pytestmark = pytest.mark.pg

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")


def _async_url(engine) -> str:
    return (
        engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _auth(tenant_id: UUID) -> AuthContext:
    return AuthContext(
        token="key",
        tenant_claim=str(tenant_id),
        api_key_id="key-1",
        rate_limit_tier="STANDARD",
        enabled=True,
    )


def _repo(session: AsyncSession) -> SqlAlchemyTenantEntitlementRepository:
    return SqlAlchemyTenantEntitlementRepository(session, plan_allowances={"paid": 0})


async def _seed_tenant(
    session: AsyncSession,
    *,
    site_url: str,
    status: EntitlementStatus,
    plan_code: str,
) -> Tenant:
    tenant = Tenant(site_url=site_url)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)
    now = datetime.now(tz=UTC)
    session.add(
        TenantEntitlement(
            tenant_id=tenant.id,
            plan_code=plan_code,
            allowance_version="pg-v1",
            allowance_jobs=1,
            period_start=now - timedelta(minutes=1),
            period_end=now + timedelta(hours=1),
            status=status,
            source="pg-test",
        )
    )
    await session.flush()
    return tenant


@pytest.mark.asyncio
async def test_postgres_operator_entitlement_beta_vs_paid_and_tenant_separation(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'tenant_entitlement'"
            )
        ).one()
        role = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()

    assert flags == (True, True)
    assert role[1] is False
    assert role[2] is False

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as setup:
            beta_tenant = await _seed_tenant(
                setup,
                site_url="https://operator-beta.example.test",
                status=EntitlementStatus.BETA_ACTIVE,
                plan_code="beta",
            )
            await setup.commit()
            beta_id = beta_tenant.id

        async with session_factory() as setup:
            paid_tenant = await _seed_tenant(
                setup,
                site_url="https://operator-paid.example.test",
                status=EntitlementStatus.PAID_ACTIVE,
                plan_code="paid",
            )
            await setup.commit()
            paid_id = paid_tenant.id

        async with session_factory() as session:
            await set_tenant_context(session, beta_id)
            repo = _repo(session)
            beta_row = await repo.get(beta_id)
            foreign_from_beta = await repo.get(paid_id)
            assert beta_row is not None
            assert beta_row.status == EntitlementStatus.BETA_ACTIVE
            assert foreign_from_beta is None

            with pytest.raises(HTTPException) as denied:
                await authorize_operator_control(_auth(beta_id), session=session, repository=repo)
            assert denied.value.status_code == 403
            assert denied.value.detail == OPERATOR_FORBIDDEN_DETAIL

        async with session_factory() as session:
            await set_tenant_context(session, paid_id)
            repo = _repo(session)
            paid_row = await repo.get(paid_id)
            foreign_from_paid = await repo.get(beta_id)
            assert paid_row is not None
            assert paid_row.status == EntitlementStatus.PAID_ACTIVE
            assert foreign_from_paid is None
            await authorize_operator_control(_auth(paid_id), session=session, repository=repo)

        async with session_factory() as session:
            missing_id = uuid4()
            await set_tenant_context(session, missing_id)
            repo = _repo(session)
            with pytest.raises(HTTPException) as missing:
                await authorize_operator_control(_auth(missing_id), session=session, repository=repo)
            assert missing.value.status_code == 503
            assert missing.value.detail == OPERATOR_UNAVAILABLE_DETAIL
    finally:
        await engine.dispose()
