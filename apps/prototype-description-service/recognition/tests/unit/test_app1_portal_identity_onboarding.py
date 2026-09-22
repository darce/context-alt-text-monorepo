"""APP-1 invitation-gated portal identity onboarding tests."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from db.models import PortalIdentity
from recognition.application.services.portal_identity_service import (
    PortalIdentityClaimError,
    PortalIdentityClaimRefused,
    SqlAlchemyPortalIdentityService,
)
from recognition.domain.portal_contracts import PortalIdentityStatus
from recognition.infrastructure.repositories import portal_identity_repository as repository_module
from recognition.infrastructure.repositories.portal_identity_repository import (
    PortalIdentityClaimRecord,
    SqlAlchemyPortalIdentityRepository,
)


class _ModelBase(DeclarativeBase):
    pass


class _InvitationModel(_ModelBase):
    __tablename__ = "portal_tenant_invitation"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    invited_email: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    accepted_by_identity_id: Mapped[str | None] = mapped_column(String, nullable=True)


class _Result:
    def __init__(self, value: object = None, *, rowcount: int = 0) -> None:
        self.value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> object:
        return self.value


class _Session:
    def __init__(self, value: object = None) -> None:
        self.value = value
        self.identities: list[PortalIdentity] = []
        self.added: PortalIdentity | None = None
        self.flush_errors: list[BaseException] = []
        self.rollback_errors: list[BaseException] = []
        self.rolled_back = False
        self.executed: list[object] = []
        self.locked_selects: list[bool] = []
        self.execute_error: BaseException | None = None
        self.update_rowcount = 1

    def add(self, value: PortalIdentity) -> None:
        self.added = value
        self.identities.append(value)

    def begin_nested(self):
        session = self

        class _Nested:
            async def __aenter__(self) -> _Session:
                return session

            async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
                return False

        return _Nested()

    async def execute(self, statement: object, *args, **kwargs) -> _Result:
        self.executed.append(statement)
        if self.execute_error is not None:
            raise self.execute_error
        locked = getattr(statement, "_for_update_arg", None) is not None
        if getattr(statement, "is_select", False):
            self.locked_selects.append(locked)
            entity = None
            descriptions = getattr(statement, "column_descriptions", None)
            if descriptions:
                entity = descriptions[0].get("entity")
            if entity is PortalIdentity:
                if self.identities:
                    issuer = self.identities[-1].issuer
                    subject = self.identities[-1].subject
                    for identity in self.identities:
                        if identity.issuer == issuer and identity.subject == subject:
                            return _Result(identity)
                    return _Result(self.identities[-1])
                if isinstance(self.value, PortalIdentity):
                    return _Result(self.value)
                return _Result(None)
            return _Result(self.value)
        return _Result(rowcount=self.update_rowcount)

    async def flush(self) -> None:
        if self.flush_errors:
            raise self.flush_errors.pop(0)

    async def rollback(self) -> None:
        self.rolled_back = True
        if self.added is not None and self.added in self.identities:
            self.identities.remove(self.added)
        self.added = None
        if isinstance(self.value, _InvitationModel):
            self.value.accepted_at = None
            self.value.accepted_by_identity_id = None
        if self.rollback_errors:
            raise self.rollback_errors.pop(0)


def _invitation(token: str, tenant_id: UUID, *, email: str = "owner@example.test") -> _InvitationModel:
    return _InvitationModel(
        id=str(uuid4()),
        tenant_id=str(tenant_id),
        invited_email=email,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )


def _install_rls_doubles(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    events: list[str] = []

    async def enable(_session: object) -> None:
        events.append("enable")

    async def disable(_session: object) -> None:
        events.append("disable")

    monkeypatch.setattr(repository_module, "enable_rls_bypass", enable)
    monkeypatch.setattr(repository_module, "disable_rls_bypass", disable)
    monkeypatch.setattr(repository_module, "_invitation_model", lambda: _InvitationModel)
    return events


@pytest.mark.asyncio
async def test_valid_invitation_derives_tenant_and_accepts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "single-use-secret"
    tenant_id = uuid4()
    invitation = _invitation(token, tenant_id)
    session = _Session(invitation)
    events = _install_rls_doubles(monkeypatch)
    service = SqlAlchemyPortalIdentityService(session=session)

    signature = inspect.signature(SqlAlchemyPortalIdentityService.claim_tenant)
    assert "tenant_id" not in signature.parameters

    principal = await service.claim_tenant(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email=" OWNER@example.test ",
        invitation_token=token,
    )

    assert principal.tenant_id == tenant_id
    assert principal.email == "owner@example.test"
    assert invitation.accepted_at is not None
    assert session.added is not None
    assert str(invitation.accepted_by_identity_id) == str(session.added.id)
    assert token not in repr(session.added)
    assert token not in " ".join(str(statement) for statement in session.executed)
    assert events == ["enable", "disable"]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["expired", "accepted", "unknown"])
async def test_invalid_invitation_states_share_one_opaque_refusal(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    token = "single-use-secret"
    invitation = _invitation(token, uuid4())
    if state == "expired":
        invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif state == "accepted":
        invitation.accepted_at = datetime.now(UTC)
    session = _Session(None if state == "unknown" else invitation)
    _install_rls_doubles(monkeypatch)
    service = SqlAlchemyPortalIdentityService(session=session)

    with pytest.raises(PortalIdentityClaimRefused) as error:
        await service.claim_tenant(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="owner@example.test",
            invitation_token=token,
        )

    assert str(error.value) == "portal identity claim was refused"
    assert token not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["other@example.test", None])
async def test_invitation_email_mismatch_and_unverified_email_are_opaque(
    monkeypatch: pytest.MonkeyPatch,
    email: str | None,
) -> None:
    token = "single-use-secret"
    invitation = _invitation(token, uuid4())
    session = _Session(invitation)
    _install_rls_doubles(monkeypatch)
    service = SqlAlchemyPortalIdentityService(session=session)

    with pytest.raises(PortalIdentityClaimRefused) as error:
        await service.claim_tenant(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email=email,
            invitation_token=token,
        )

    assert str(error.value) == "portal identity claim was refused"
    assert invitation.accepted_at is None
    assert session.added is None


@pytest.mark.asyncio
async def test_pre_auth_lookup_resets_rls_context_on_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = PortalIdentity(
        tenant_id=uuid4(),
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="owner@example.test",
        status=PortalIdentityStatus.ACTIVE,
    )
    session = _Session(identity)
    events = _install_rls_doubles(monkeypatch)
    repository = SqlAlchemyPortalIdentityRepository(session)

    assert await repository.get_by_issuer_subject(identity.issuer, identity.subject) is identity
    assert events == ["enable", "disable"]

    events.clear()
    session.execute_error = RuntimeError("database failure")
    with pytest.raises(RuntimeError, match="database failure"):
        await repository.get_by_issuer_subject(identity.issuer, identity.subject)
    assert events == ["enable", "disable"]


@pytest.mark.asyncio
async def test_flush_timeout_rolls_back_and_retry_can_redeem(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "single-use-secret"
    invitation = _invitation(token, uuid4())
    session = _Session(invitation)
    session.flush_errors.append(TimeoutError("flush timed out"))
    _install_rls_doubles(monkeypatch)
    repository = SqlAlchemyPortalIdentityRepository(session)

    with pytest.raises(TimeoutError, match="flush timed out"):
        await repository.claim(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="owner@example.test",
            invitation_token=token,
        )
    assert session.rolled_back is True
    assert invitation.accepted_at is None

    identity = await repository.claim(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="owner@example.test",
        invitation_token=token,
    )
    assert identity.tenant_id == UUID(invitation.tenant_id)
    assert invitation.accepted_at is not None


@pytest.mark.asyncio
async def test_rollback_failure_does_not_mask_flush_error(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "single-use-secret"
    session = _Session(_invitation(token, uuid4()))
    session.flush_errors.append(TimeoutError("flush timed out"))
    session.rollback_errors.append(RuntimeError("rollback failed"))
    _install_rls_doubles(monkeypatch)
    repository = SqlAlchemyPortalIdentityRepository(session)

    with pytest.raises(TimeoutError, match="flush timed out"):
        await repository.claim(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="owner@example.test",
            invitation_token=token,
        )


class _ConcurrentRepository:
    def __init__(self, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id
        self.identity: PortalIdentity | None = None
        self.accepted = False
        self.lock = asyncio.Lock()

    async def get_by_issuer_subject(self, issuer: str, subject: str) -> PortalIdentity | None:
        if self.identity is not None and self.identity.issuer == issuer and self.identity.subject == subject:
            return self.identity
        return None

    async def claim(self, *, issuer: str, subject: str, email: str | None, invitation_token: str) -> PortalIdentity:
        async with self.lock:
            if self.accepted:
                raise PortalIdentityClaimRefused("portal identity claim was refused")
            await asyncio.sleep(0)
            self.identity = PortalIdentity(
                id=uuid4(),
                tenant_id=self.tenant_id,
                issuer=issuer,
                subject=subject,
                email=email,
                status=PortalIdentityStatus.ACTIVE,
            )
            self.accepted = True
            return self.identity


@pytest.mark.asyncio
async def test_concurrent_claims_produce_one_identity() -> None:
    repository = _ConcurrentRepository(uuid4())
    first = SqlAlchemyPortalIdentityService(repository)
    second = SqlAlchemyPortalIdentityService(repository)

    results = await asyncio.gather(
        first.claim_tenant(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="owner@example.test",
            invitation_token="single-use-secret",
        ),
        second.claim_tenant(
            issuer="https://issuer.example.test",
            subject="subject-2",
            email="owner@example.test",
            invitation_token="single-use-secret",
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, PortalIdentityClaimRefused) for result in results) == 1
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert repository.identity is not None


def _is_locked(statement: object) -> bool:
    return getattr(statement, "_for_update_arg", None) is not None


@pytest.mark.asyncio
async def test_claim_onboarding_locks_invitation_before_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "single-use-secret"
    tenant_id = uuid4()
    invitation = _invitation(token, tenant_id)
    session = _Session(invitation)
    events = _install_rls_doubles(monkeypatch)
    repository = SqlAlchemyPortalIdentityRepository(session)

    first = await repository.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="owner@example.test",
        invitation_token=token,
    )
    replay = await repository.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="owner@example.test",
        invitation_token=token,
    )

    assert isinstance(first, PortalIdentityClaimRecord)
    assert first.replayed is False
    assert replay.replayed is True
    assert first.identity.tenant_id == tenant_id
    assert replay.identity.tenant_id == tenant_id
    assert session.locked_selects
    assert all(session.locked_selects)
    assert any(_is_locked(statement) for statement in session.executed if getattr(statement, "is_select", False))
    assert events == ["enable", "disable", "enable", "disable"]


@pytest.mark.asyncio
async def test_claim_onboarding_cross_tenant_and_consumed_are_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "single-use-secret"
    invitation = _invitation(token, uuid4())
    session = _Session(invitation)
    _install_rls_doubles(monkeypatch)
    repository = SqlAlchemyPortalIdentityRepository(session)
    await repository.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="owner",
        email="owner@example.test",
        invitation_token=token,
    )

    with pytest.raises(PortalIdentityClaimError) as consumed:
        await repository.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="intruder",
            email="owner@example.test",
            invitation_token=token,
        )
    other = _invitation("other-secret", uuid4(), email="owner@example.test")
    other_session = _Session(other)
    other_session.identities.append(
        PortalIdentity(
            id=uuid4(),
            tenant_id=uuid4(),
            issuer="https://issuer.example.test",
            subject="owner",
            email="owner@example.test",
            status=PortalIdentityStatus.ACTIVE,
        )
    )
    other_repository = SqlAlchemyPortalIdentityRepository(other_session)
    with pytest.raises(PortalIdentityClaimError) as bound:
        await other_repository.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="owner",
            email="owner@example.test",
            invitation_token="other-secret",
        )

    assert consumed.value.code == "invitation_consumed"
    assert bound.value.code == "identity_already_bound"


@pytest.mark.asyncio
async def test_claim_onboarding_flush_failure_rolls_back_and_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "single-use-secret"
    invitation = _invitation(token, uuid4())
    session = _Session(invitation)
    session.flush_errors.append(TimeoutError("flush timed out"))
    _install_rls_doubles(monkeypatch)
    repository = SqlAlchemyPortalIdentityRepository(session)

    with pytest.raises(TimeoutError, match="flush timed out"):
        await repository.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="owner@example.test",
            invitation_token=token,
        )
    assert session.rolled_back is True
    assert invitation.accepted_at is None

    outcome = await repository.claim_onboarding(
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="owner@example.test",
        invitation_token=token,
    )
    assert outcome.replayed is False
    assert invitation.accepted_at is not None


class _OnboardingConcurrentRepository:
    def __init__(self, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id
        self.identity: PortalIdentity | None = None
        self.lock = asyncio.Lock()

    async def get_by_issuer_subject(self, issuer: str, subject: str) -> PortalIdentity | None:
        raise AssertionError("durable claim must not infer replay from unlocked get_by_issuer_subject")

    async def claim(self, **kwargs: object) -> PortalIdentity:
        raise AssertionError("durable claim must use claim_onboarding")

    async def claim_onboarding(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        invitation_token: str,
    ) -> PortalIdentityClaimRecord:
        async with self.lock:
            await asyncio.sleep(0)
            if self.identity is not None:
                if self.identity.issuer == issuer and self.identity.subject == subject:
                    return PortalIdentityClaimRecord(identity=self.identity, replayed=True)
                raise PortalIdentityClaimError("invitation_consumed")
            self.identity = PortalIdentity(
                id=uuid4(),
                tenant_id=self.tenant_id,
                issuer=issuer,
                subject=subject,
                email=email,
                status=PortalIdentityStatus.ACTIVE,
            )
            return PortalIdentityClaimRecord(identity=self.identity, replayed=False)


@pytest.mark.asyncio
async def test_concurrent_onboarding_same_principal_replays_once() -> None:
    repository = _OnboardingConcurrentRepository(uuid4())
    first = SqlAlchemyPortalIdentityService(repository, beta_grant=_noop_grant, audit_service=_NoopAudit())
    second = SqlAlchemyPortalIdentityService(repository, beta_grant=_noop_grant, audit_service=_NoopAudit())

    results = await asyncio.gather(
        first.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="owner@example.test",
            invitation_token="single-use-secret",
        ),
        second.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="owner@example.test",
            invitation_token="single-use-secret",
        ),
    )

    assert sorted(result.replayed for result in results) == [False, True]
    assert len({result.principal.tenant_id for result in results}) == 1


@pytest.mark.asyncio
async def test_concurrent_onboarding_different_subjects_consume_once() -> None:
    repository = _OnboardingConcurrentRepository(uuid4())
    first = SqlAlchemyPortalIdentityService(repository, beta_grant=_noop_grant, audit_service=_NoopAudit())
    second = SqlAlchemyPortalIdentityService(repository, beta_grant=_noop_grant, audit_service=_NoopAudit())

    results = await asyncio.gather(
        first.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="subject-1",
            email="owner@example.test",
            invitation_token="single-use-secret",
        ),
        second.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="subject-2",
            email="owner@example.test",
            invitation_token="single-use-secret",
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, PortalIdentityClaimError) for result in results) == 1
    consumed = next(result for result in results if isinstance(result, PortalIdentityClaimError))
    assert consumed.code == "invitation_consumed"
    assert sum(not isinstance(result, BaseException) and result.replayed is False for result in results) == 1


async def _noop_grant(tenant_id: UUID, **kwargs: object) -> None:
    return None


class _NoopAudit:
    async def record_event(self, session: object, **payload: object) -> dict[str, object]:
        return payload
