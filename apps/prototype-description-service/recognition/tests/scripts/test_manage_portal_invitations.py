"""Tests for the operator portal invitation CLI."""

from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from db.base import Base
from db.models import PortalIdentity, PortalTenantInvitation, Tenant


@pytest_asyncio.fixture
async def portal_tables(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(
        lambda sync_connection: Base.metadata.create_all(
            sync_connection,
            tables=[PortalIdentity.__table__, PortalTenantInvitation.__table__],
        )
    )


def _import_cli() -> ModuleType:
    import importlib.util

    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "manage_portal_invitations.py"
    spec = importlib.util.spec_from_file_location("manage_portal_invitations_cli", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _configure_local_env(monkeypatch) -> None:
    monkeypatch.delenv("ACX_ENV", raising=False)
    from db import settings as db_settings

    monkeypatch.setattr(
        db_settings,
        "get_database_settings",
        lambda: SimpleNamespace(postgres_dsn="postgresql+asyncpg://localhost/testdb"),
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def _printed_token(output: str) -> str:
    token_lines = [line for line in output.splitlines() if line.startswith("invitation_token=")]
    _require(len(token_lines) == 1, "create output must contain exactly one labeled invitation token")
    token = token_lines[0].partition("=")[2]
    _require(bool(token), "create output must contain a non-empty invitation token")
    return token


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def test_cli_module_importable() -> None:
    cli = _import_cli()
    assert hasattr(cli, "main")


def test_cli_module_exec_help_succeeds() -> None:
    app_root = pathlib.Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-m", "scripts.manage_portal_invitations", "--help"],
        cwd=app_root,
        capture_output=True,
        text=True,
        env={},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage: manage_portal_invitations" in result.stdout
    assert "create a single-use portal invitation" in result.stdout


@pytest.mark.asyncio
async def test_create_stores_hash_only_normalizes_email_and_prints_token_once(
    db_session: AsyncSession,
    portal_tables: None,
    capsys,
    monkeypatch,
) -> None:
    _configure_local_env(monkeypatch)
    cli = _import_cli()
    before = datetime.now(UTC)
    exit_code = await cli.run(
        argv=["--env", "local", "create", "--email", "Portal.User@Example.Test", "--ttl-hours", "4"],
        session=db_session,
    )
    after = datetime.now(UTC)

    _require(exit_code == 0, "valid invitation creation must succeed")
    captured = capsys.readouterr()
    raw_token = _printed_token(captured.out)
    _require(captured.out.count(raw_token) == 1, "raw token must appear exactly once in create output")
    _require(raw_token not in captured.err, "raw token must not appear on stderr")
    invitation = await db_session.scalar(select(PortalTenantInvitation))
    _require(invitation is not None, "create must store an invitation row")
    assert invitation is not None
    _require(
        invitation.token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        "stored digest must match the printed token",
    )
    _require(invitation.invited_email == "portal.user@example.test", "stored email must use repository normalization")
    _require(invitation.tenant_id is None, "new invitation must not be assigned a tenant")
    expires_at = _as_utc(invitation.expires_at)
    _require(
        before + timedelta(hours=4) <= expires_at <= after + timedelta(hours=4),
        "invitation expiry must use the requested TTL",
    )

    metadata_lines = [line for line in captured.out.splitlines() if line.startswith("invitation_id=")]
    _require(len(metadata_lines) == 1, "create must print one token-free invitation metadata line")
    _require(raw_token not in metadata_lines[0], "metadata line must not contain the raw token")
    _require(str(invitation.id) in metadata_lines[0], "metadata line must include the invitation id")
    _require(invitation.invited_email in metadata_lines[0], "metadata line must include the normalized email")
    _require(invitation.expires_at.isoformat() in metadata_lines[0], "metadata line must include the expiry")

    await cli.run(argv=["--env", "local", "list"], session=db_session)
    listed = capsys.readouterr().out
    _require(raw_token not in listed, "list must never reveal the raw token")
    _require(invitation.token_hash not in listed, "list must never reveal the stored digest")


@pytest.mark.parametrize("ttl_hours", [1, 336])
@pytest.mark.asyncio
async def test_create_accepts_ttl_boundaries(
    db_session: AsyncSession,
    portal_tables: None,
    capsys,
    monkeypatch,
    ttl_hours: int,
) -> None:
    _configure_local_env(monkeypatch)
    cli = _import_cli()
    exit_code = await cli.run(
        argv=["--env", "local", "create", "--email", "ttl@example.test", "--ttl-hours", str(ttl_hours)],
        session=db_session,
    )
    _require(exit_code == 0, "inclusive TTL boundary must be accepted")
    output = capsys.readouterr().out
    _printed_token(output)
    invitation = await db_session.scalar(select(PortalTenantInvitation))
    _require(invitation is not None, "valid boundary TTL must create an invitation")
    assert invitation is not None
    remaining = _as_utc(invitation.expires_at) - datetime.now(UTC)
    _require(
        timedelta(hours=ttl_hours) - timedelta(seconds=2) <= remaining <= timedelta(hours=ttl_hours),
        "boundary TTL must be applied to the invitation expiry",
    )


@pytest.mark.parametrize("ttl_hours", ["0", "337", "not-an-integer"])
def test_invalid_ttl_is_a_usage_error(ttl_hours: str) -> None:
    cli = _import_cli()
    with pytest.raises(SystemExit) as exc_info:
        cli._build_parser().parse_args(
            ["--env", "local", "create", "--email", "valid@example.test", "--ttl-hours", ttl_hours]
        )
    assert exc_info.value.code == 2


def test_default_ttl_is_72_hours() -> None:
    cli = _import_cli()
    args = cli._build_parser().parse_args(["--env", "local", "create", "--email", "default@example.test"])
    assert args.ttl_hours == 72


@pytest.mark.parametrize("email", ["missing-at.example.test", "one@@two.example.test", "bad address@example.test"])
def test_malformed_email_is_a_usage_error(email: str) -> None:
    cli = _import_cli()
    with pytest.raises(SystemExit) as exc_info:
        cli._build_parser().parse_args(["--env", "local", "create", "--email", email])
    assert exc_info.value.code == 2


@pytest.mark.asyncio
async def test_list_filters_pending_and_reports_all_states(
    db_session: AsyncSession,
    portal_tables: None,
    capsys,
    monkeypatch,
) -> None:
    _configure_local_env(monkeypatch)
    now = datetime.now(UTC)
    tenant = Tenant(site_url="https://invitation-list.example.test")
    db_session.add(tenant)
    await db_session.flush()
    pending = PortalTenantInvitation(
        invited_email="pending@example.test",
        token_hash=hashlib.sha256(b"fake-pending-token").hexdigest(),
        expires_at=now + timedelta(hours=2),
    )
    accepted = PortalTenantInvitation(
        tenant_id=tenant.id,
        invited_email="accepted@example.test",
        token_hash=hashlib.sha256(b"fake-accepted-token").hexdigest(),
        expires_at=now + timedelta(hours=2),
        accepted_at=now,
    )
    expired = PortalTenantInvitation(
        invited_email="expired@example.test",
        token_hash=hashlib.sha256(b"fake-expired-token").hexdigest(),
        expires_at=now - timedelta(hours=1),
    )
    db_session.add_all([pending, accepted, expired])
    await db_session.commit()

    cli = _import_cli()
    exit_code = await cli.run(argv=["--env", "local", "list"], session=db_session)
    _require(exit_code == 0, "list must succeed")
    pending_lines = capsys.readouterr().out.splitlines()
    _require(len(pending_lines) == 1, "default list must include pending invitations only")
    _require(pending_lines[0].split("\t")[0] == str(pending.id), "default list must include the pending id")
    _require(pending_lines[0].split("\t")[-1] == "pending", "default list must mark pending invitations")

    exit_code = await cli.run(
        argv=["--env", "local", "list", "--include-inactive"],
        session=db_session,
    )
    _require(exit_code == 0, "inclusive list must succeed")
    state_by_id = {line.split("\t")[0]: line.split("\t")[-1] for line in capsys.readouterr().out.splitlines()}
    _require(state_by_id.get(str(pending.id)) == "pending", "inclusive list must report pending state")
    _require(state_by_id.get(str(accepted.id)) == "accepted", "inclusive list must report accepted state")
    _require(state_by_id.get(str(expired.id)) == "expired", "inclusive list must report expired state")


@pytest.mark.asyncio
async def test_revoke_expires_a_pending_invitation(
    db_session: AsyncSession,
    portal_tables: None,
    capsys,
    monkeypatch,
) -> None:
    _configure_local_env(monkeypatch)
    invitation = PortalTenantInvitation(
        invited_email="revoke@example.test",
        token_hash=hashlib.sha256(b"fake-revoke-token").hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db_session.add(invitation)
    await db_session.commit()

    cli = _import_cli()
    before = datetime.now(UTC)
    exit_code = await cli.run(
        argv=["--env", "local", "revoke", "--invitation-id", str(invitation.id)],
        session=db_session,
    )
    after = datetime.now(UTC)
    _require(exit_code == 0, "pending invitation revoke must succeed")
    await db_session.refresh(invitation)
    expires_at = _as_utc(invitation.expires_at)
    _require(before <= expires_at <= after, "revoke must set expiry to the current time")
    _require(invitation.accepted_at is None, "revoke must leave the invitation unaccepted")
    _require(str(invitation.id) in capsys.readouterr().err, "revoke must identify the expired invitation")


@pytest.mark.asyncio
async def test_revoke_refuses_accepted_and_unknown_invitations(
    db_session: AsyncSession,
    portal_tables: None,
    monkeypatch,
) -> None:
    _configure_local_env(monkeypatch)
    tenant = Tenant(site_url="https://accepted-invitation.example.test")
    db_session.add(tenant)
    await db_session.flush()
    accepted_at = datetime.now(UTC)
    invitation = PortalTenantInvitation(
        tenant_id=tenant.id,
        invited_email="accepted@example.test",
        token_hash=hashlib.sha256(b"fake-accepted-revoke-token").hexdigest(),
        expires_at=accepted_at + timedelta(days=1),
        accepted_at=accepted_at,
    )
    db_session.add(invitation)
    await db_session.commit()
    original_expiry = _as_utc(invitation.expires_at)

    cli = _import_cli()
    accepted_result = await cli.run(
        argv=["--env", "local", "revoke", "--invitation-id", str(invitation.id)],
        session=db_session,
    )
    unknown_result = await cli.run(
        argv=["--env", "local", "revoke", "--invitation-id", str(uuid.uuid4())],
        session=db_session,
    )
    _require(accepted_result == 1, "accepted invitation revoke must be refused")
    _require(unknown_result == 1, "unknown invitation revoke must be refused")
    await db_session.refresh(invitation)
    _require(_as_utc(invitation.expires_at) == original_expiry, "refused revoke must not change accepted expiry")


@pytest.mark.asyncio
async def test_claim_committed_before_revoke_write_preserves_acceptance_and_replay(
    tmp_path: pathlib.Path,
    capsys,
    monkeypatch,
) -> None:
    from recognition.infrastructure.repositories.portal_identity_repository import SqlAlchemyPortalIdentityRepository

    _configure_local_env(monkeypatch)
    cli = _import_cli()
    # A file-backed database gives the claimant and revoker independent
    # connections, without changing the shared db_session/savepoint fixture.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'revoke-claim.sqlite'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enforce_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection,
                    tables=[Tenant.__table__, PortalIdentity.__table__, PortalTenantInvitation.__table__],
                )
            )
        raw_token = "fake-interleaved-claim-token"
        original_expiry = datetime.now(UTC) + timedelta(days=1)
        async with AsyncSession(engine, expire_on_commit=False) as setup_session:
            invitation = PortalTenantInvitation(
                invited_email="interleaved@example.test",
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=original_expiry,
            )
            setup_session.add(invitation)
            await setup_session.commit()
            invitation_id = invitation.id

        claim_arguments = {
            "issuer": "https://issuer.example.test",
            "subject": "fake-interleaved-subject",
            "email": "interleaved@example.test",
            "invitation_token": raw_token,
        }
        async with (
            AsyncSession(engine, expire_on_commit=False) as revoke_session,
            AsyncSession(engine, expire_on_commit=False) as claim_session,
        ):
            # Reproduce the stale pending view the old unlocked read could see.
            pending = await revoke_session.get(PortalTenantInvitation, invitation_id)
            assert pending is not None and pending.accepted_at is None
            revoke_connection = await revoke_session.connection()
            claim_connection = await claim_session.connection()
            assert (
                revoke_connection.sync_connection.connection.dbapi_connection
                is not claim_connection.sync_connection.connection.dbapi_connection
            )
            repository = SqlAlchemyPortalIdentityRepository(claim_session)
            claim = None

            async def commit_claim_before_write() -> None:
                nonlocal claim
                if claim is None:
                    claim = await repository.claim_onboarding(**claim_arguments)
                    await claim_session.commit()
                    assert not claim.replayed

            real_execute = revoke_session.execute
            real_flush = revoke_session.flush

            async def execute_after_claim(statement, *args, **kwargs):
                if getattr(statement, "is_update", False):
                    await commit_claim_before_write()
                return await real_execute(statement, *args, **kwargs)

            async def flush_after_claim(*args, **kwargs):
                # Also intercept the old ORM dirty-row write, so this regression
                # runs against the original implementation and proves it fails.
                await commit_claim_before_write()
                return await real_flush(*args, **kwargs)

            monkeypatch.setattr(revoke_session, "execute", execute_after_claim)
            monkeypatch.setattr(revoke_session, "flush", flush_after_claim)
            exit_code = await cli.run(
                argv=["--env", "local", "revoke", "--invitation-id", str(invitation_id)],
                session=revoke_session,
            )
            assert claim is not None, "claim must commit at the revoke write boundary"
            claimed_identity_id = claim.identity.id
            claimed_tenant_id = claim.identity.tenant_id

        # Inspect durable rows and exercise actual repository replay through a
        # fresh session; neither the write nor its outcome is a SQL-shaped fake.
        async with AsyncSession(engine, expire_on_commit=False) as verification_session:
            accepted = await verification_session.get(PortalTenantInvitation, invitation_id)
            assert accepted is not None
            assert accepted.accepted_at is not None
            assert accepted.accepted_by_identity_id == claimed_identity_id
            assert accepted.tenant_id == claimed_tenant_id
            assert _as_utc(accepted.expires_at) == original_expiry
            assert await verification_session.get(Tenant, claimed_tenant_id) is not None
            replay = await SqlAlchemyPortalIdentityRepository(verification_session).claim_onboarding(**claim_arguments)
            await verification_session.commit()
            assert replay.replayed
            assert replay.identity.id == claimed_identity_id
            assert replay.identity.tenant_id == claimed_tenant_id

        assert exit_code == 1, "revoke must refuse an invitation accepted before its write"
        output = capsys.readouterr()
        assert output.out == ""
        assert output.err == "error: invitation not found or not pending\n"
    finally:
        await engine.dispose()


class _UntouchedSession:
    def __init__(self) -> None:
        self.touched = False

    def __getattr__(self, name: str):
        self.touched = True
        raise AssertionError(f"session method {name} must not be used after an environment refusal")


@pytest.mark.asyncio
async def test_acx_env_dev_allows_dev_without_reading_dsn(
    db_session: AsyncSession,
    portal_tables: None,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ACX_ENV", "dev")
    from db import settings as db_settings

    def unexpected_settings_read():
        raise AssertionError("ACX_ENV must take precedence over DSN validation")

    monkeypatch.setattr(db_settings, "get_database_settings", unexpected_settings_read)
    cli = _import_cli()
    exit_code = await cli.run(argv=["--env", "dev", "list"], session=db_session)
    _require(exit_code == 0, "matching ACX_ENV and --env must allow the CLI")


@pytest.mark.asyncio
async def test_acx_env_mismatch_refuses_before_touching_injected_session(monkeypatch) -> None:
    monkeypatch.setenv("ACX_ENV", "dev")
    session = _UntouchedSession()
    cli = _import_cli()
    exit_code = await cli.run(argv=["--env", "prod", "list"], session=session)
    _require(exit_code == 1, "ACX_ENV mismatch must be refused")
    _require(not session.touched, "environment refusal must happen before touching an injected session")


@pytest.mark.parametrize("configured_env", ["staging", "dev-fir"])
@pytest.mark.asyncio
async def test_non_cli_acx_envs_always_refuse_before_touching_session(monkeypatch, configured_env: str) -> None:
    monkeypatch.setenv("ACX_ENV", configured_env)
    session = _UntouchedSession()
    cli = _import_cli()
    exit_code = await cli.run(argv=["--env", "dev", "list"], session=session)
    _require(exit_code == 1, "staging and dev-fir environments must be refused")
    _require(not session.touched, "unsupported ACX_ENV refusal must happen before touching a session")


@pytest.mark.asyncio
async def test_unset_acx_env_falls_back_to_dsn_host_guard(monkeypatch) -> None:
    monkeypatch.delenv("ACX_ENV", raising=False)
    from db import settings as db_settings

    monkeypatch.setattr(
        db_settings,
        "get_database_settings",
        lambda: SimpleNamespace(postgres_dsn="postgresql+asyncpg://db.example.test/testdb"),
    )
    session = _UntouchedSession()
    cli = _import_cli()
    exit_code = await cli.run(argv=["--env", "dev", "list"], session=session)
    _require(exit_code == 1, "remote DSN must fail the unset ACX_ENV fallback check for dev")
    _require(not session.touched, "DSN mismatch refusal must happen before touching an injected session")


@pytest.mark.asyncio
async def test_cli_created_invitation_round_trips_through_onboarding_claim(
    db_session: AsyncSession,
    portal_tables: None,
    capsys,
    monkeypatch,
) -> None:
    _configure_local_env(monkeypatch)
    cli = _import_cli()
    exit_code = await cli.run(
        argv=["--env", "local", "create", "--email", "Claim.User@example.test"],
        session=db_session,
    )
    _require(exit_code == 0, "round-trip invitation creation must succeed")
    raw_token = _printed_token(capsys.readouterr().out)

    from recognition.infrastructure.repositories.portal_identity_repository import (
        PortalIdentityClaimError,
        SqlAlchemyPortalIdentityRepository,
    )

    # CLI and API requests use separate sessions. The suite's db_session
    # restarts savepoints in after_transaction_end, which is incompatible
    # with onboarding's own begin_nested() context manager on that session.
    async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as claim_session:
        repository = SqlAlchemyPortalIdentityRepository(claim_session)
        with pytest.raises(PortalIdentityClaimError) as mismatch:
            await repository.claim_onboarding(
                issuer="https://issuer.example.test",
                subject="fake-subject",
                email="someone-else@example.test",
                invitation_token=raw_token,
            )
        _require(mismatch.value.code == "not_admitted", "mismatched email must be refused before acceptance")
        await claim_session.rollback()

        claim = await repository.claim_onboarding(
            issuer="https://issuer.example.test",
            subject="fake-subject",
            email="CLAIM.USER@EXAMPLE.TEST",
            invitation_token=raw_token,
        )
        await claim_session.commit()
        _require(claim.identity.email == "claim.user@example.test", "matching email must be normalized during claim")
        _require(claim.identity.tenant_id is not None, "NULL-tenant invitation must create a tenant during claim")
        _require(not claim.replayed, "first matching-email claim must redeem the pending invitation")
        claimed_identity_id = claim.identity.id
        claimed_tenant_id = claim.identity.tenant_id

    # Read committed acceptance through another request session, rather than
    # trusting only the repository's in-memory claim result.
    async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as verification_session:
        invitation = await verification_session.scalar(select(PortalTenantInvitation))
        _require(invitation is not None, "claimed invitation must remain stored")
        assert invitation is not None
        _require(invitation.accepted_at is not None, "successful claim must persist acceptance")
        _require(invitation.accepted_by_identity_id == claimed_identity_id, "acceptance must identify the claimant")
        _require(invitation.tenant_id == claimed_tenant_id, "acceptance must bind the newly created tenant")
        _require(
            invitation.token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            "claim must retain hash-only token storage",
        )
        _require(
            await verification_session.get(Tenant, claimed_tenant_id) is not None, "claimed tenant must be durable"
        )

        repository = SqlAlchemyPortalIdentityRepository(verification_session)
        with pytest.raises(PortalIdentityClaimError) as consumed:
            await repository.claim_onboarding(
                issuer="https://issuer.example.test",
                subject="another-subject",
                email="claim.user@example.test",
                invitation_token=raw_token,
            )
        _require(consumed.value.code == "invitation_consumed", "another identity must not redeem an accepted token")
