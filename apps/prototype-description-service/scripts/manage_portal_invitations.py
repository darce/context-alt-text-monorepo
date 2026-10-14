"""Operator CLI for portal invitation lifecycle (create / list / revoke).

Usage:
    python -m scripts.manage_portal_invitations --env ENV create --email ADDR [--ttl-hours N] [--tenant UUID]
    python -m scripts.manage_portal_invitations --env ENV list [--include-inactive]
    python -m scripts.manage_portal_invitations --env ENV revoke --invitation-id UUID

An invitation token is single-use. Its SHA-256 digest is stored; the raw token
is printed once after creation and must never be logged or displayed again.
When ACX_ENV is set, --env must match it exactly. Without ACX_ENV, the CLI
checks the configured DSN host before opening or using a database session.
A matching --env prod still checks the DSN host, because a matching ACX_ENV is
not proof of a nonlocal database. Matching dev and local skip the settings read.
The portal-enabled Aura label dev-auraface is admitted only for its exact
context and effective DSN identity; staging/prod Aura portal labels are refused (see
scripts/_aura_target_guard.py).
dev-fir requires its exact ACX_ENV and dedicated role/database on postgres or
an explicit loopback endpoint. --tenant binds an invitation to an existing
tenant in that guarded store without creating or linking a portal identity.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlsplit

from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PortalIdentity, PortalTenantInvitation, Tenant
from db.tenant_context import disable_rls_bypass, enable_rls_bypass
from recognition.infrastructure.repositories.portal_identity_repository import (
    _hash_invitation_token,
    _normalize_email,
)
from scripts._aura_target_guard import AURA_LABELS, has_connection_overrides, validate_aura_target
from scripts._aura_target_guard import dsn_host as _dsn_host
from scripts._aura_target_guard import is_local_host as _is_local_host

_ENV_CHOICES = ("prod", "dev", "local", "dev-fir", *AURA_LABELS)
_DEFAULT_TTL_HOURS = 72
_MIN_TTL_HOURS = 1
_MAX_TTL_HOURS = 336


def _validate_env_vs_dsn(env: str, dsn: str) -> str | None:
    """Return an error string on mismatch, or None when env and DSN agree."""
    try:
        host = _dsn_host(dsn)
    except ValueError as exc:
        return f"env={env}: {exc}; refusing to run"
    if not host:
        return f"env={env}: DSN has no host; refusing to run"
    if env == "prod" and _is_local_host(host):
        return f"env=prod but DSN host '{host}' looks local; refusing to run"
    if env in {"dev", "local"} and not _is_local_host(host):
        return f"env={env} but DSN host '{host}' is not a local host; refusing to run"
    return None


def _parse_email(value: str) -> str:
    if value.count("@") != 1 or not value or any(character.isspace() for character in value):
        raise argparse.ArgumentTypeError("email must contain exactly one @ and no whitespace")
    local_part, domain = value.split("@", 1)
    if not local_part or not domain:
        raise argparse.ArgumentTypeError("email must contain a local part and domain")
    normalized = _normalize_email(value)
    if normalized is None:
        raise argparse.ArgumentTypeError("email must not be empty")
    return normalized


def _parse_ttl_hours(value: str) -> int:
    try:
        ttl_hours = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ttl-hours must be an integer") from exc
    if not _MIN_TTL_HOURS <= ttl_hours <= _MAX_TTL_HOURS:
        raise argparse.ArgumentTypeError(f"ttl-hours must be between {_MIN_TTL_HOURS} and {_MAX_TTL_HOURS}")
    return ttl_hours


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manage_portal_invitations")
    parser.add_argument("--env", required=True, choices=list(_ENV_CHOICES), help="target environment")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="create a single-use portal invitation")
    p_create.add_argument("--email", required=True, type=_parse_email)
    p_create.add_argument("--ttl-hours", type=_parse_ttl_hours, default=_DEFAULT_TTL_HOURS)
    p_create.add_argument("--tenant", type=uuid.UUID, help="existing target-local tenant UUID")

    p_list = sub.add_parser("list", help="list portal invitations")
    p_list.add_argument("--include-inactive", action="store_true")

    p_revoke = sub.add_parser("revoke", help="expire a pending portal invitation")
    p_revoke.add_argument("--invitation-id", required=True, type=uuid.UUID)
    return parser


def _format(value: datetime | None) -> str:
    return "" if value is None else value.isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _state(invitation: PortalTenantInvitation, now: datetime) -> str:
    if invitation.accepted_at is not None:
        return "accepted"
    if _as_utc(invitation.expires_at) <= now:
        return "expired"
    return "pending"


def _validate_aura_runtime(env: str) -> str | None:
    """Admit an Aura label only for its exact context and effective DSN identity (scripts/_aura_target_guard.py)."""
    from db.settings import get_database_settings

    return validate_aura_target(
        env,
        configured_env=os.environ.get("ACX_ENV"),
        compose_project=os.environ.get("COMPOSE_PROJECT_NAME"),
        read_dsn=lambda: get_database_settings().postgres_dsn,
    )


def _validate_runtime_env(env: str) -> str | None:
    if env in {"staging-auraface", "prod-auraface"}:
        return f"env={env}: portal is disabled for this target; refusing to run"
    if env == "dev-fir":
        return _validate_fir_runtime()
    if env in AURA_LABELS:
        return _validate_aura_runtime(env)

    configured_env = os.environ.get("ACX_ENV")
    if configured_env is not None:
        if configured_env != env:
            return f"ACX_ENV={configured_env!r} does not match --env={env!r}; refusing to run"
        if env != "prod":
            # Matched dev and local keep the no-settings-read fast path.
            return None
        # Matched prod is not exempt from the DSN host guard: a matching
        # ACX_ENV does not prove the database is nonlocal (loopback bypass).

    # This settings read does not open a session or connection. The DSN check
    # preserves manage_api_keys' fail-closed behavior outside VM containers.
    from db.settings import get_database_settings

    return _validate_env_vs_dsn(env, get_database_settings().postgres_dsn)


def _validate_fir_runtime() -> str | None:
    """Validate configuration only; never resolve a target through another store."""
    if os.environ.get("ACX_ENV") != "dev-fir":
        return "ACX_ENV must match --env=dev-fir; refusing to run"
    from db.settings import get_database_settings

    refusal = "env=dev-fir: invalid dedicated PostgreSQL target; refusing to run"
    try:
        dsn = get_database_settings().postgres_dsn
        if not isinstance(dsn, str) or not dsn:
            return refusal
        url = make_url(dsn)
        query_keys = [key for key, _ in parse_qsl(urlsplit(dsn).query, keep_blank_values=True)]
        if (
            url.drivername not in {"postgresql", "postgresql+asyncpg"}
            or url.username != "acx_dev_fir"
            or url.database != "alt_context_dev_fir"
            or (url.host or "").lower() not in {"postgres", "localhost", "127.0.0.1", "::1"}
            or (url.port is not None and not 1 <= url.port <= 65535)
            or has_connection_overrides([*url.query, *query_keys])
        ):
            return refusal
    except Exception:
        # Settings and parser exceptions can contain credentials. Never render them.
        return refusal
    return None


async def _create(args: argparse.Namespace, session: AsyncSession) -> tuple[PortalTenantInvitation, str]:
    if args.tenant is not None:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.id == args.tenant).limit(1).with_for_update()
        )).scalar_one_or_none()
        if tenant is None:
            raise ValueError("target tenant missing")
        owner = (await session.execute(
            select(PortalIdentity).where(PortalIdentity.tenant_id == args.tenant).limit(1).with_for_update()
        )).scalar_one_or_none()
        if owner is not None:
            raise ValueError("target tenant occupied")
        conflict = (await session.execute(
            select(PortalIdentity).where(
                func.lower(func.trim(PortalIdentity.email)).label("email") == args.email,
                PortalIdentity.tenant_id != args.tenant,
            ).limit(1).with_for_update()
        )).scalar_one_or_none()
        if conflict is not None:
            raise ValueError("invitee already bound")
    raw_token = secrets.token_urlsafe(32)
    invitation = PortalTenantInvitation(
        tenant_id=args.tenant,
        invited_email=args.email,
        token_hash=_hash_invitation_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=args.ttl_hours),
    )
    session.add(invitation)
    await session.flush()
    return invitation, raw_token


async def _list(args: argparse.Namespace, session: AsyncSession) -> None:
    statement = select(PortalTenantInvitation).order_by(
        PortalTenantInvitation.created_at,
        PortalTenantInvitation.id,
    )
    invitations = (await session.execute(statement)).scalars().all()
    now = datetime.now(UTC)
    for invitation in invitations:
        state = _state(invitation, now)
        if state != "pending" and not args.include_inactive:
            continue
        sys.stdout.write(
            "\t".join(
                [
                    str(invitation.id),
                    invitation.invited_email,
                    _format(invitation.created_at),
                    _format(invitation.expires_at),
                    state,
                ]
            )
            + "\n"
        )
    sys.stdout.flush()


async def _revoke(args: argparse.Namespace, session: AsyncSession) -> PortalTenantInvitation | None:
    now = datetime.now(UTC)
    # Check pending state in the write itself: a claimant may commit after
    # an unlocked read, and its acceptance must retain the original expiry.
    statement = (
        update(PortalTenantInvitation)
        .where(
            PortalTenantInvitation.id == args.invitation_id,
            PortalTenantInvitation.accepted_at.is_(None),
            PortalTenantInvitation.expires_at > now,
        )
        .values(expires_at=now)
        .returning(PortalTenantInvitation)
        .execution_options(synchronize_session="fetch", populate_existing=True)
    )
    # RETURNING yields no row when the compare-and-set refuses the revoke.
    return (await session.execute(statement)).scalar_one_or_none()


async def run(argv: Sequence[str] | None = None, *, session: AsyncSession | None = None) -> int:
    """Run with cooperative deadlines, not a universal wall-clock ceiling.

    The transaction deadline is anchor + 10s; rollback and close/invalidation
    have absolute caps of +12s and +14s. Cancellation-resistant operations can
    settle after those caps; expired cleanup is skipped. An injected session
    whose rollback fails is invalidated within the remaining cleanup budget.
    Callers must discard it if that recovery also fails or times out.
    """
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    # Check the explicit VM environment or fallback DSN before creating a
    # session and even when callers inject a session (for example, tests).
    mismatch = _validate_runtime_env(args.env)
    if mismatch is not None:
        sys.stderr.write(f"error: {mismatch}\n")
        sys.stderr.flush()
        return 1

    opened_session = False
    if session is None:
        from db.session import async_session_factory

        session = async_session_factory()
        opened_session = True

    # Absolute deadlines bound cooperative waits. Cancellation settlement may
    # overrun; cleanup never STARTS after its anchor + 12 / + 14 cap.
    loop = asyncio.get_running_loop()
    anchor = loop.time()
    issued = None
    revoked_metadata = None
    revoke_not_pending = False
    invitation_id = args.invitation_id if args.command == "revoke" else None
    status = 0
    committed = False
    commit_started = False
    cancelled = None
    try:
        async with asyncio.timeout_at(anchor + 10):
            await enable_rls_bypass(session)
            _check_deadline(anchor + 10)
            if args.command == "create":
                invitation, raw_token = await _create(args, session)
                invitation_id = invitation.id
                # Snapshot before commit: expired ORM attributes must never
                # trigger an implicit read after commit or owned-session close.
                issued = (raw_token, invitation.id, invitation.invited_email, _format(invitation.expires_at))
            elif args.command == "list":
                await _list(args, session)
            elif args.command == "revoke":
                revoked = await _revoke(args, session)
                if revoked is None:
                    revoke_not_pending = True
                    status = 1
                else:
                    revoked_metadata = (revoked.id, _format(revoked.expires_at))
            _check_deadline(anchor + 10)
            await disable_rls_bypass(session)
            if status == 0:
                # A completed await may consume the budget before the loop
                # dispatches its timeout callback. Check at the commit boundary.
                _check_deadline(anchor + 10)
                commit_started = True
                await session.commit()
                committed = True
    except asyncio.CancelledError as exc:
        # External cancellation remains cancellation, after bounded cleanup.
        cancelled = exc
        status = 1
    except Exception:
        # Neither database exceptions nor validation details are safe to echo.
        status = 1
        revoke_not_pending = False
        if commit_started:
            target = "invitation list" if args.command == "list" else f"invitation_id={invitation_id}"
            recovery = " before reissue" if args.command == "create" else ""
            sys.stderr.write(f"error: commit unacknowledged; reconcile {target}{recovery}\n")
        else:
            sys.stderr.write("error: invitation operation failed or refused\n")
    finally:
        if not committed:
            rolled_back = await _cleanup(session.rollback, min(loop.time() + 2, anchor + 12), "rollback")
            if not opened_session and not rolled_back:
                async def invalidate():
                    await session.invalidate()
                await _cleanup(invalidate, min(loop.time() + 2, anchor + 14), "invalidate")
        if opened_session:
            await _cleanup(session.close, min(loop.time() + 2, anchor + 14), "close")

    if cancelled is not None:
        raise cancelled
    if committed and issued is not None:
        raw_token, saved_id, saved_email, saved_expiry = issued
        try:
            # One write delivers the token exactly once, only after commit
            # acknowledgement and the bounded owned-session close attempt.
            sys.stdout.write(
                f"invitation_token={raw_token}\n"
                f"invitation_id={saved_id}\temail={saved_email}\texpires_at={saved_expiry}\n"
            )
            sys.stdout.flush()
        except Exception:
            sys.stderr.write(f"error: committed invitation_id={saved_id}; token delivery failed; reconcile before reissue\n")
            return 1
    elif args.command == "revoke" and status == 0 and revoked_metadata is not None:
        saved_id, saved_expiry = revoked_metadata
        sys.stderr.write(f"revoked invitation_id={saved_id} expires_at={_format(saved_expiry)}\n")
    elif args.command == "revoke" and revoke_not_pending:
        sys.stderr.write("error: invitation not found or not pending\n")
    sys.stderr.flush()
    return status


async def _cleanup(operation, deadline: float, label: str) -> bool:
    """Preserve the primary outcome, with no raw exception text or token."""
    try:
        _check_deadline(deadline)
        async with asyncio.timeout_at(deadline):
            await operation()
        return True
    except Exception:
        sys.stderr.write(f"warning: session {label} cleanup failed or timed out\n")
        return False


def _check_deadline(deadline: float) -> None:
    if asyncio.get_running_loop().time() >= deadline:
        raise TimeoutError


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":  # pragma: no cover
    main()
