"""APP-1 portal identity service and repository tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from db.models import PortalIdentity
from recognition.application.services.portal_identity_service import (
    PortalIdentityClaimRefused,
    SqlAlchemyPortalIdentityService,
)
from recognition.domain.portal_contracts import PortalIdentityService, PortalIdentityStatus
from recognition.infrastructure.repositories.portal_identity_repository import SqlAlchemyPortalIdentityRepository


class _InMemoryPortalIdentityRepository:
    """Insert-only double that models both database uniqueness constraints."""

    def __init__(self) -> None:
        self.rows: list[PortalIdentity] = []
        self.lookup_keys: list[tuple[str, str]] = []

    async def get_by_issuer_subject(self, issuer: str, subject: str) -> PortalIdentity | None:
        self.lookup_keys.append((issuer, subject))
        for row in self.rows:
            if row.issuer == issuer and row.subject == subject and row.status == PortalIdentityStatus.ACTIVE:
                return row
        return None

    async def claim(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        tenant_id: UUID,
    ) -> PortalIdentity:
        if any(row.issuer == issuer and row.subject == subject for row in self.rows):
            raise PortalIdentityClaimRefused("portal identity claim was refused")
        if any(row.tenant_id == tenant_id for row in self.rows):
            raise PortalIdentityClaimRefused("portal identity claim was refused")
        row = PortalIdentity(
            tenant_id=tenant_id,
            issuer=issuer,
            subject=subject,
            email=email,
            status=PortalIdentityStatus.ACTIVE,
        )
        self.rows.append(row)
        return row


@pytest.mark.asyncio
async def test_claim_and_resolve_return_the_owned_active_principal() -> None:
    repository = _InMemoryPortalIdentityRepository()
    tenant_id = uuid4()
    service = SqlAlchemyPortalIdentityService(repository)

    principal = await service.claim_tenant(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="person@example.test",
        tenant_id=tenant_id,
    )

    assert isinstance(service, PortalIdentityService)
    assert principal.tenant_id == tenant_id
    assert principal.issuer == "https://issuer.example.test"
    assert principal.subject == "subject-1"
    assert principal.email == "person@example.test"
    assert await service.resolve_principal(principal.issuer, principal.subject) == principal
    assert repository.rows[0].status == PortalIdentityStatus.ACTIVE


@pytest.mark.asyncio
async def test_suspended_identity_is_not_resolved() -> None:
    repository = _InMemoryPortalIdentityRepository()
    repository.rows.append(
        PortalIdentity(
            tenant_id=uuid4(),
            issuer="https://issuer.example.test",
            subject="suspended-subject",
            email="person@example.test",
            status=PortalIdentityStatus.SUSPENDED,
        )
    )
    service = SqlAlchemyPortalIdentityService(repository)

    assert await service.resolve_principal("https://issuer.example.test", "suspended-subject") is None


@pytest.mark.asyncio
async def test_resolve_never_falls_back_to_email() -> None:
    repository = _InMemoryPortalIdentityRepository()
    repository.rows.append(
        PortalIdentity(
            tenant_id=uuid4(),
            issuer="https://issuer.example.test",
            subject="verified-subject",
            email="shared@example.test",
            status=PortalIdentityStatus.ACTIVE,
        )
    )
    service = SqlAlchemyPortalIdentityService(repository)

    assert await service.resolve_principal("https://other-issuer.example.test", "unknown-subject") is None
    assert repository.lookup_keys == [("https://other-issuer.example.test", "unknown-subject")]


@pytest.mark.asyncio
async def test_claim_refuses_pair_conflict_without_transferring_owner() -> None:
    repository = _InMemoryPortalIdentityRepository()
    owner_tenant = uuid4()
    replacement_tenant = uuid4()
    service = SqlAlchemyPortalIdentityService(repository)
    await service.claim_tenant(
        issuer="https://issuer.example.test",
        subject="stable-subject",
        email="owner@example.test",
        tenant_id=owner_tenant,
    )

    with pytest.raises(PortalIdentityClaimRefused):
        await service.claim_tenant(
            issuer="https://issuer.example.test",
            subject="stable-subject",
            email="attacker@example.test",
            tenant_id=replacement_tenant,
        )

    resolved = await service.resolve_principal("https://issuer.example.test", "stable-subject")
    assert resolved is not None
    assert resolved.tenant_id == owner_tenant
    assert resolved.email == "owner@example.test"


@pytest.mark.asyncio
async def test_claim_refuses_tenant_conflict_without_reassigning_it() -> None:
    repository = _InMemoryPortalIdentityRepository()
    tenant_id = uuid4()
    service = SqlAlchemyPortalIdentityService(repository)
    await service.claim_tenant(
        issuer="https://issuer.example.test",
        subject="first-subject",
        email="first@example.test",
        tenant_id=tenant_id,
    )

    with pytest.raises(PortalIdentityClaimRefused):
        await service.claim_tenant(
            issuer="https://issuer.example.test",
            subject="second-subject",
            email="second@example.test",
            tenant_id=tenant_id,
        )

    resolved = await service.resolve_principal("https://issuer.example.test", "first-subject")
    assert resolved is not None
    assert resolved.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_missing_tenant_id_is_refused_without_a_claim() -> None:
    repository = _InMemoryPortalIdentityRepository()
    service = SqlAlchemyPortalIdentityService(repository)

    with pytest.raises(PortalIdentityClaimRefused):
        await service.claim_tenant(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email=None,
        )

    assert repository.rows == []


class _InsertOnlySession:
    def __init__(self) -> None:
        self.added: PortalIdentity | None = None
        self.flushed = False
        self.rolled_back = False

    def add(self, value: PortalIdentity) -> None:
        self.added = value

    async def flush(self) -> None:
        self.flushed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def execute(self, *args, **kwargs):
        raise AssertionError("claim must not read before inserting")


class _ConflictingSession(_InsertOnlySession):
    async def flush(self) -> None:
        raise IntegrityError("insert", {}, RuntimeError("unique conflict"))


@pytest.mark.asyncio
async def test_repository_claim_is_insert_only_and_translates_integrity_refusal() -> None:
    session = _ConflictingSession()
    repository = SqlAlchemyPortalIdentityRepository(session)

    with pytest.raises(PortalIdentityClaimRefused):
        await repository.claim(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email=None,
            tenant_id=uuid4(),
        )

    assert session.added is not None
    assert session.flushed is False
    assert session.rolled_back is True
