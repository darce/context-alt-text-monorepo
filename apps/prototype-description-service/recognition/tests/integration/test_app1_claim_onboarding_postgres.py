"""PostgreSQL proof for invitation-gated create-on-claim.

The pg_empty_engine fixture refuses privileged roles; IDENTITY_PG_REQUIRED=1
fails instead of skip. Mock-only unit coverage is not sufficient for APP1-CLAIM-RV01.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import AuditEvent, PortalIdentity, PortalTenantInvitation, TenantEntitlement
from db.models.tenant import Tenant
from db.tenant_context import set_tenant_context
from recognition.application.services.audit_service import AuditService
from recognition.application.services.portal_identity_service import (
    PortalIdentityClaimError,
    SqlAlchemyPortalIdentityService,
)

pytestmark = pytest.mark.pg

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")
ISSUER = "https://issuer.example.test"
EMAIL = "owner@example.test"


def _async_url(engine) -> str:
    return (
        engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _insert_invitation(
    session: AsyncSession,
    *,
    token: str,
    email: str = EMAIL,
    tenant_id: UUID | None = None,
    expires_at: datetime | None = None,
) -> PortalTenantInvitation:
    invitation = PortalTenantInvitation(
        tenant_id=tenant_id,
        invited_email=email,
        token_hash=_token_hash(token),
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=1),
    )
    session.add(invitation)
    await session.flush()
    return invitation


def _service(session: AsyncSession, **kwargs: object) -> SqlAlchemyPortalIdentityService:
    return SqlAlchemyPortalIdentityService(session=session, audit_service=AuditService(), **kwargs)


@pytest.mark.asyncio
async def test_postgres_pending_claim_creates_tenant_identity_grant_accept_audit_atomically(
    pg_empty_engine,
) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        role = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
        invitation_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'portal_tenant_invitation' AND column_name = 'tenant_id'"
            )
        ).scalar()
    assert role[1] is False
    assert role[2] is False
    assert invitation_nullable == "YES"

    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    token = "pending-claim-token"
    try:
        async with session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            await _insert_invitation(session, token=token, email=" Owner@Example.com ")
            await session.commit()

        async with session_factory() as session:
            outcome = await _service(session).claim_onboarding(
                issuer=ISSUER,
                subject="subject-1",
                email="owner@example.com",
                invitation_token=token,
            )
            await session.commit()

        assert outcome.replayed is False
        tenant_id = outcome.principal.tenant_id

        async with session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
            identity = (await session.execute(select(PortalIdentity))).scalar_one()
            invitation = (await session.execute(select(PortalTenantInvitation))).scalar_one()
            entitlement = (await session.execute(select(TenantEntitlement))).scalar_one()
            audits = (await session.execute(select(AuditEvent))).scalars().all()
            tenant_count = (await session.execute(select(func.count()).select_from(Tenant))).scalar_one()

        assert tenant.site_url
        assert identity.tenant_id == tenant_id
        assert identity.issuer == ISSUER
        assert identity.email == "owner@example.com"
        assert invitation.tenant_id == tenant_id
        assert invitation.accepted_at is not None
        assert invitation.accepted_by_identity_id == identity.id
        assert entitlement.tenant_id == tenant_id
        assert entitlement.source == "portal.onboarding.claim"
        assert any(event.event_type == "portal.identity.claim" for event in audits)
        assert tenant_count == 1

        async with session_factory() as session:
            replay = await _service(session).claim_onboarding(
                issuer=ISSUER,
                subject="subject-1",
                email="owner@example.com",
                invitation_token=token,
            )
            await session.commit()

        async with session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            tenant_count = (await session.execute(select(func.count()).select_from(Tenant))).scalar_one()
            identity_count = (await session.execute(select(func.count()).select_from(PortalIdentity))).scalar_one()
            grant_count = (await session.execute(select(func.count()).select_from(TenantEntitlement))).scalar_one()
            claim_audits = (
                await session.execute(
                    select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == "portal.identity.claim")
                )
            ).scalar_one()

        assert replay.replayed is True
        assert replay.principal.tenant_id == tenant_id
        assert tenant_count == 1
        assert identity_count == 1
        assert grant_count == 1
        assert claim_audits == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_injected_grant_failure_leaves_no_orphan_tenant_grant_or_audit(
    pg_empty_engine,
) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    token = "failing-claim-token"

    async def failing_grant(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("grant failed")

    try:
        async with session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            await _insert_invitation(session, token=token)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(PortalIdentityClaimError) as error:
                await _service(session, beta_grant=failing_grant).claim_onboarding(
                    issuer=ISSUER,
                    subject="subject-1",
                    email=EMAIL,
                    invitation_token=token,
                )
            await session.rollback()

        assert error.value.code == "portal_identity_unavailable"

        async with session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            assert (await session.execute(select(func.count()).select_from(Tenant))).scalar_one() == 0
            assert (await session.execute(select(func.count()).select_from(PortalIdentity))).scalar_one() == 0
            assert (await session.execute(select(func.count()).select_from(TenantEntitlement))).scalar_one() == 0
            assert (await session.execute(select(func.count()).select_from(AuditEvent))).scalar_one() == 0
            invitation = (await session.execute(select(PortalTenantInvitation))).scalar_one()
            assert invitation.tenant_id is None
            assert invitation.accepted_at is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_bound_invitation_replays_same_tenant_without_creating_another(
    pg_empty_engine,
) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    token = "bound-claim-token"
    tenant = Tenant(site_url="https://legacy-bound.example.test")
    try:
        async with session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            session.add(tenant)
            await session.flush()
            await _insert_invitation(session, token=token, tenant_id=tenant.id)
            await session.commit()
            tenant_id = tenant.id

        async with session_factory() as session:
            first = await _service(session).claim_onboarding(
                issuer=ISSUER,
                subject="subject-1",
                email=EMAIL,
                invitation_token=token,
            )
            await session.commit()
        async with session_factory() as session:
            replay = await _service(session).claim_onboarding(
                issuer=ISSUER,
                subject="subject-1",
                email=EMAIL,
                invitation_token=token,
            )
            await session.commit()

        async with session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            tenant_count = (await session.execute(select(func.count()).select_from(Tenant))).scalar_one()
            invitation = (await session.execute(select(PortalTenantInvitation))).scalar_one()

        assert first.replayed is False
        assert replay.replayed is True
        assert first.principal.tenant_id == tenant_id
        assert replay.principal.tenant_id == tenant_id
        assert tenant_count == 1
        assert invitation.tenant_id == tenant_id
        assert invitation.accepted_at is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_two_token_concurrency_same_identity_does_not_orphan_or_leave_unredeemed(
    pg_empty_engine,
) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    token_a = "race-token-a"
    token_b = "race-token-b"
    try:
        async with session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            await _insert_invitation(session, token=token_a)
            await _insert_invitation(session, token=token_b)
            await session.commit()

        async def claim(token: str):
            async with session_factory() as session:
                try:
                    outcome = await _service(session).claim_onboarding(
                        issuer=ISSUER,
                        subject="subject-1",
                        email=EMAIL,
                        invitation_token=token,
                    )
                    await session.commit()
                    return outcome
                except Exception:
                    await session.rollback()
                    raise

        results = await asyncio.gather(claim(token_a), claim(token_b), return_exceptions=True)
        successes = [result for result in results if not isinstance(result, BaseException)]
        assert len(successes) == 2
        assert sorted(result.replayed for result in successes) == [False, True]
        tenant_ids = {result.principal.tenant_id for result in successes}
        assert len(tenant_ids) == 1

        async with session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            tenants = (await session.execute(select(Tenant))).scalars().all()
            identities = (await session.execute(select(PortalIdentity))).scalars().all()
            invitations = (await session.execute(select(PortalTenantInvitation))).scalars().all()
            grants = (await session.execute(select(TenantEntitlement))).scalars().all()

        assert len(tenants) == 1
        assert len(identities) == 1
        assert {invitation.accepted_at is not None for invitation in invitations} == {True}
        assert {invitation.tenant_id for invitation in invitations} == {tenants[0].id}
        assert len(grants) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_claim_maintains_tenant_isolation(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            await _insert_invitation(session, token="iso-a", email="a@example.test")
            await _insert_invitation(session, token="iso-b", email="b@example.test")
            await session.commit()

        async with session_factory() as session:
            first = await _service(session).claim_onboarding(
                issuer=ISSUER,
                subject="subject-a",
                email="a@example.test",
                invitation_token="iso-a",
            )
            await session.commit()
        async with session_factory() as session:
            second = await _service(session).claim_onboarding(
                issuer=ISSUER,
                subject="subject-b",
                email="b@example.test",
                invitation_token="iso-b",
            )
            await session.commit()

        assert first.principal.tenant_id != second.principal.tenant_id

        async with session_factory() as session:
            await set_tenant_context(session, first.principal.tenant_id)
            visible = (await session.execute(select(PortalIdentity))).scalars().all()
            assert [row.tenant_id for row in visible] == [first.principal.tenant_id]
            other = (
                (
                    await session.execute(
                        select(PortalIdentity).where(PortalIdentity.tenant_id == second.principal.tenant_id)
                    )
                )
                .scalars()
                .all()
            )
            assert other == []
    finally:
        await engine.dispose()
