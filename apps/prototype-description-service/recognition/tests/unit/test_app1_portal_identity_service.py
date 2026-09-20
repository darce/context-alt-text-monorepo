"""APP-1 portal identity service tests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from db.models import PortalIdentity
from recognition.application.services.portal_identity_service import (
    PortalIdentityClaimRefused,
    SqlAlchemyPortalIdentityService,
)
from recognition.domain.portal_contracts import PortalIdentityService, PortalIdentityStatus


@dataclass
class _Invitation:
    token: str
    tenant_id: UUID
    email: str


class _InMemoryPortalIdentityRepository:
    """Redemption double that models the invitation gate and both uniqueness constraints."""

    def __init__(self) -> None:
        self.rows: list[PortalIdentity] = []
        self.lookup_keys: list[tuple[str, str]] = []
        self.invitations: dict[str, _Invitation] = {}
        self.redeemed: set[str] = set()

    def invite(self, tenant_id: UUID, email: str) -> str:
        token = f"invite-{len(self.invitations)}"
        self.invitations[token] = _Invitation(token=token, tenant_id=tenant_id, email=email)
        return token

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
        invitation_token: str,
    ) -> PortalIdentity:
        invitation = self.invitations.get(invitation_token)
        if invitation is None or invitation_token in self.redeemed:
            raise PortalIdentityClaimRefused("portal identity claim was refused")
        if email is None or email.strip().lower() != invitation.email:
            raise PortalIdentityClaimRefused("portal identity claim was refused")
        if any(row.issuer == issuer and row.subject == subject for row in self.rows):
            raise PortalIdentityClaimRefused("portal identity claim was refused")
        if any(row.tenant_id == invitation.tenant_id for row in self.rows):
            raise PortalIdentityClaimRefused("portal identity claim was refused")
        row = PortalIdentity(
            tenant_id=invitation.tenant_id,
            issuer=issuer,
            subject=subject,
            email=email,
            status=PortalIdentityStatus.ACTIVE,
        )
        self.rows.append(row)
        self.redeemed.add(invitation_token)
        return row


@pytest.mark.asyncio
async def test_claim_and_resolve_return_the_owned_active_principal() -> None:
    repository = _InMemoryPortalIdentityRepository()
    tenant_id = uuid4()
    token = repository.invite(tenant_id, "person@example.test")
    service = SqlAlchemyPortalIdentityService(repository)

    principal = await service.claim_tenant(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="person@example.test",
        invitation_token=token,
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
    owner_token = repository.invite(owner_tenant, "owner@example.test")
    attacker_token = repository.invite(uuid4(), "attacker@example.test")
    service = SqlAlchemyPortalIdentityService(repository)
    await service.claim_tenant(
        issuer="https://issuer.example.test",
        subject="stable-subject",
        email="owner@example.test",
        invitation_token=owner_token,
    )

    with pytest.raises(PortalIdentityClaimRefused):
        await service.claim_tenant(
            issuer="https://issuer.example.test",
            subject="stable-subject",
            email="attacker@example.test",
            invitation_token=attacker_token,
        )

    resolved = await service.resolve_principal("https://issuer.example.test", "stable-subject")
    assert resolved is not None
    assert resolved.tenant_id == owner_tenant
    assert resolved.email == "owner@example.test"


@pytest.mark.asyncio
async def test_claim_refuses_tenant_conflict_without_reassigning_it() -> None:
    repository = _InMemoryPortalIdentityRepository()
    tenant_id = uuid4()
    first_token = repository.invite(tenant_id, "first@example.test")
    second_token = repository.invite(tenant_id, "second@example.test")
    service = SqlAlchemyPortalIdentityService(repository)
    await service.claim_tenant(
        issuer="https://issuer.example.test",
        subject="first-subject",
        email="first@example.test",
        invitation_token=first_token,
    )

    with pytest.raises(PortalIdentityClaimRefused):
        await service.claim_tenant(
            issuer="https://issuer.example.test",
            subject="second-subject",
            email="second@example.test",
            invitation_token=second_token,
        )

    resolved = await service.resolve_principal("https://issuer.example.test", "first-subject")
    assert resolved is not None
    assert resolved.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_blank_invitation_token_is_refused_without_a_claim() -> None:
    repository = _InMemoryPortalIdentityRepository()
    service = SqlAlchemyPortalIdentityService(repository)

    with pytest.raises(PortalIdentityClaimRefused):
        await service.claim_tenant(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="person@example.test",
            invitation_token="   ",
        )

    assert repository.rows == []


@pytest.mark.asyncio
async def test_unknown_invitation_token_is_refused_without_a_claim() -> None:
    repository = _InMemoryPortalIdentityRepository()
    service = SqlAlchemyPortalIdentityService(repository)

    with pytest.raises(PortalIdentityClaimRefused):
        await service.claim_tenant(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="person@example.test",
            invitation_token="never-issued",
        )

    assert repository.rows == []


@pytest.mark.asyncio
async def test_invitation_cannot_be_redeemed_twice() -> None:
    repository = _InMemoryPortalIdentityRepository()
    tenant_id = uuid4()
    token = repository.invite(tenant_id, "person@example.test")
    service = SqlAlchemyPortalIdentityService(repository)
    await service.claim_tenant(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="person@example.test",
        invitation_token=token,
    )

    with pytest.raises(PortalIdentityClaimRefused):
        await service.claim_tenant(
            issuer="https://other-issuer.example.test",
            subject="subject-2",
            email="person@example.test",
            invitation_token=token,
        )

    assert len(repository.rows) == 1
