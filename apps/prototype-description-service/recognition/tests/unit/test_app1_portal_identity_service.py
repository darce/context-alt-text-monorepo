"""APP-1 portal identity service tests."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from db.models import PortalIdentity
from recognition.application.services.portal_identity_service import (
    PortalClaimOutcome,
    PortalIdentityClaimError,
    PortalIdentityClaimRefused,
    SqlAlchemyPortalIdentityService,
)
from recognition.application.services.tenant_entitlement_service import TenantEntitlementService
from recognition.domain.portal_contracts import PortalIdentityService, PortalIdentityStatus, PortalPrincipal


@dataclass
class _Invitation:
    token: str
    tenant_id: UUID | None
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

    def invite_pending(self, email: str) -> str:
        token = f"invite-{len(self.invitations)}"
        self.invitations[token] = _Invitation(token=token, tenant_id=None, email=email)
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
        if invitation is None or invitation.tenant_id is None or invitation_token in self.redeemed:
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

    async def claim_onboarding(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        invitation_token: str,
    ) -> object:
        from recognition.infrastructure.repositories.portal_identity_repository import (
            PortalIdentityClaimRecord,
        )

        invitation = self.invitations.get(invitation_token)
        if invitation is None:
            raise PortalIdentityClaimError("not_admitted")
        if email is None or email.strip().lower() != invitation.email:
            raise PortalIdentityClaimError("not_admitted")
        existing = next((row for row in self.rows if row.issuer == issuer and row.subject == subject), None)
        if invitation_token in self.redeemed:
            owner = next(
                (
                    row
                    for row in self.rows
                    if invitation.tenant_id is not None and row.tenant_id == invitation.tenant_id
                ),
                None,
            )
            if existing is not None and existing.tenant_id == invitation.tenant_id and owner is existing:
                return PortalIdentityClaimRecord(identity=existing, replayed=True)
            if existing is not None and invitation.tenant_id is not None and existing.tenant_id != invitation.tenant_id:
                raise PortalIdentityClaimError("identity_already_bound")
            raise PortalIdentityClaimError("invitation_consumed")
        if existing is not None:
            if invitation.tenant_id is not None and existing.tenant_id != invitation.tenant_id:
                raise PortalIdentityClaimError("identity_already_bound")
            invitation.tenant_id = existing.tenant_id
            self.redeemed.add(invitation_token)
            return PortalIdentityClaimRecord(identity=existing, replayed=True)
        if invitation.tenant_id is not None and any(row.tenant_id == invitation.tenant_id for row in self.rows):
            raise PortalIdentityClaimError("invitation_consumed")
        tenant_id = invitation.tenant_id or uuid4()
        invitation.tenant_id = tenant_id
        row = PortalIdentity(
            tenant_id=tenant_id,
            issuer=issuer,
            subject=subject,
            email=email,
            status=PortalIdentityStatus.ACTIVE,
        )
        self.rows.append(row)
        self.redeemed.add(invitation_token)
        return PortalIdentityClaimRecord(identity=row, replayed=False)


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


class _GrantRecorder:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.calls: list[tuple[UUID, dict[str, object]]] = []
        self.error = error

    async def grant_beta(
        self,
        tenant_id: UUID,
        *,
        allowance_jobs: int,
        allowance_version: str,
        period_start: object,
        period_end: object,
        source: str,
    ) -> None:
        self.calls.append(
            (
                tenant_id,
                {
                    "allowance_jobs": allowance_jobs,
                    "allowance_version": allowance_version,
                    "period_start": period_start,
                    "period_end": period_end,
                    "source": source,
                },
            )
        )
        if self.error is not None:
            raise self.error


class _AuditRecorder:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.error = error

    async def record_event(self, session: object, **payload: object) -> dict[str, object]:
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return payload


class _SessionWithRollback:
    def __init__(self) -> None:
        self.rolled_back = False

    async def rollback(self) -> None:
        self.rolled_back = True


def test_claim_onboarding_matches_grant_beta_producer_shape() -> None:
    grant_signature = inspect.signature(TenantEntitlementService.grant_beta)
    onboarding_signature = inspect.signature(SqlAlchemyPortalIdentityService.claim_onboarding)
    assert list(grant_signature.parameters) == [
        "self",
        "tenant_id",
        "allowance_jobs",
        "allowance_version",
        "period_start",
        "period_end",
        "source",
    ]
    assert onboarding_signature.return_annotation in {PortalClaimOutcome, "PortalClaimOutcome"}
    assert inspect.signature(SqlAlchemyPortalIdentityService.claim_tenant).return_annotation in {
        PortalPrincipal,
        "PortalPrincipal",
    }


@pytest.mark.asyncio
async def test_claim_onboarding_replays_same_principal_without_second_grant() -> None:
    repository = _InMemoryPortalIdentityRepository()
    tenant_id = uuid4()
    token = repository.invite(tenant_id, "person@example.test")
    grant = _GrantRecorder()
    audit = _AuditRecorder()
    service = SqlAlchemyPortalIdentityService(repository, beta_grant=grant.grant_beta, audit_service=audit)

    first = await service.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="person@example.test",
        invitation_token=token,
    )
    replay = await service.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="person@example.test",
        invitation_token=token,
    )

    assert isinstance(first, PortalClaimOutcome)
    assert first.replayed is False
    assert replay.replayed is True
    assert first.principal.tenant_id == tenant_id
    assert replay.principal == first.principal
    assert len(grant.calls) == 1
    assert grant.calls[0][0] == tenant_id
    assert grant.calls[0][1]["source"] == "portal.onboarding.claim"
    assert len(audit.calls) == 1
    assert repository.lookup_keys == []
    protocol_replay_refused = False
    try:
        await service.claim_tenant(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="person@example.test",
            invitation_token=token,
        )
    except PortalIdentityClaimRefused:
        protocol_replay_refused = True
    assert protocol_replay_refused is True


@pytest.mark.asyncio
async def test_claim_onboarding_cross_tenant_conflicts_are_typed() -> None:
    repository = _InMemoryPortalIdentityRepository()
    owner_tenant = uuid4()
    other_tenant = uuid4()
    owner_token = repository.invite(owner_tenant, "owner@example.test")
    other_token = repository.invite(other_tenant, "owner@example.test")
    consumed_token = repository.invite(uuid4(), "other@example.test")
    grant = _GrantRecorder()
    service = SqlAlchemyPortalIdentityService(repository, beta_grant=grant.grant_beta, audit_service=_AuditRecorder())
    await service.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="stable-subject",
        email="owner@example.test",
        invitation_token=owner_token,
    )
    await service.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="other-subject",
        email="other@example.test",
        invitation_token=consumed_token,
    )

    with pytest.raises(PortalIdentityClaimError) as bound:
        await service.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="stable-subject",
            email="owner@example.test",
            invitation_token=other_token,
        )
    with pytest.raises(PortalIdentityClaimError) as consumed:
        await service.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="intruder",
            email="other@example.test",
            invitation_token=consumed_token,
        )

    assert bound.value.code == "identity_already_bound"
    assert consumed.value.code == "invitation_consumed"
    assert str(bound.value) == "portal identity claim was refused"
    assert len(grant.calls) == 2


@pytest.mark.asyncio
async def test_grant_or_audit_failure_rolls_back_first_claim() -> None:
    repository = _InMemoryPortalIdentityRepository()
    tenant_id = uuid4()
    token = repository.invite(tenant_id, "person@example.test")
    session = _SessionWithRollback()
    repository.session = session
    grant = _GrantRecorder(error=RuntimeError("grant failed"))
    service = SqlAlchemyPortalIdentityService(repository, beta_grant=grant.grant_beta, audit_service=_AuditRecorder())

    with pytest.raises(PortalIdentityClaimError) as error:
        await service.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="person@example.test",
            invitation_token=token,
        )

    assert error.value.code == "portal_identity_unavailable"
    assert session.rolled_back is True
    assert len(grant.calls) == 1
    assert len(repository.rows) == 1

    repository.rows.clear()
    repository.redeemed.clear()
    session.rolled_back = False
    grant.error = None
    audit = _AuditRecorder(error=RuntimeError("audit failed"))
    service = SqlAlchemyPortalIdentityService(repository, beta_grant=grant.grant_beta, audit_service=audit)
    with pytest.raises(PortalIdentityClaimError) as audit_error:
        await service.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="person@example.test",
            invitation_token=token,
        )
    assert audit_error.value.code == "portal_identity_unavailable"
    assert session.rolled_back is True


@pytest.mark.asyncio
async def test_claim_onboarding_pending_token_grants_once_and_replays_without_second_tenant() -> None:
    repository = _InMemoryPortalIdentityRepository()
    token = repository.invite_pending("person@example.test")
    grant = _GrantRecorder()
    audit = _AuditRecorder()
    service = SqlAlchemyPortalIdentityService(repository, beta_grant=grant.grant_beta, audit_service=audit)

    first = await service.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="person@example.test",
        invitation_token=token,
    )
    replay = await service.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="person@example.test",
        invitation_token=token,
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert first.principal.tenant_id == replay.principal.tenant_id
    assert repository.invitations[token].tenant_id == first.principal.tenant_id
    assert len(grant.calls) == 1
    assert len(audit.calls) == 1


@pytest.mark.asyncio
async def test_claim_onboarding_two_pending_tokens_same_identity_consume_both_without_second_grant() -> None:
    repository = _InMemoryPortalIdentityRepository()
    first_token = repository.invite_pending("owner@example.test")
    second_token = repository.invite_pending("owner@example.test")
    grant = _GrantRecorder()
    service = SqlAlchemyPortalIdentityService(repository, beta_grant=grant.grant_beta, audit_service=_AuditRecorder())

    first = await service.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="owner@example.test",
        invitation_token=first_token,
    )
    second = await service.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="owner@example.test",
        invitation_token=second_token,
    )

    assert first.replayed is False
    assert second.replayed is True
    assert first.principal.tenant_id == second.principal.tenant_id
    assert {first_token, second_token} <= repository.redeemed
    assert len(grant.calls) == 1


@pytest.mark.asyncio
async def test_pending_grant_failure_rolls_back_without_leaving_service_success() -> None:
    repository = _InMemoryPortalIdentityRepository()
    token = repository.invite_pending("person@example.test")
    session = _SessionWithRollback()
    repository.session = session
    grant = _GrantRecorder(error=RuntimeError("grant failed"))
    service = SqlAlchemyPortalIdentityService(repository, beta_grant=grant.grant_beta, audit_service=_AuditRecorder())

    with pytest.raises(PortalIdentityClaimError) as error:
        await service.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="person@example.test",
            invitation_token=token,
        )

    assert error.value.code == "portal_identity_unavailable"
    assert session.rolled_back is True
    assert len(grant.calls) == 1
