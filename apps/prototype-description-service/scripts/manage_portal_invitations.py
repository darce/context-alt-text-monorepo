"""Operator CLI for portal invitation lifecycle (create / list / revoke).

Usage:
    python -m scripts.manage_portal_invitations --env {prod,dev,local} create --email ADDR [--ttl-hours N]
    python -m scripts.manage_portal_invitations --env {prod,dev,local} list [--include-inactive]
    python -m scripts.manage_portal_invitations --env {prod,dev,local} revoke --invitation-id UUID

An invitation token is single-use. Its SHA-256 digest is stored; the raw token
is printed once after creation and must never be logged or displayed again.
When ACX_ENV is set, --env must match it exactly. Without ACX_ENV, the CLI
checks the configured DSN host before opening or using a database session.
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
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PortalTenantInvitation
from db.tenant_context import disable_rls_bypass, enable_rls_bypass
from recognition.infrastructure.repositories.portal_identity_repository import (
    _hash_invitation_token,
    _normalize_email,
)

_ENV_CHOICES = ("prod", "dev", "local")
_DEFAULT_TTL_HOURS = 72
_MIN_TTL_HOURS = 1
_MAX_TTL_HOURS = 336


def _dsn_host(dsn: str) -> str:
    return (urlparse(dsn).hostname or "").lower()


def _is_local_host(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")


def _validate_env_vs_dsn(env: str, dsn: str) -> str | None:
    """Return an error string on mismatch, or None when env and DSN agree."""
    host = _dsn_host(dsn)
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


def _validate_runtime_env(env: str) -> str | None:
    configured_env = os.environ.get("ACX_ENV")
    if configured_env is not None:
        if configured_env != env:
            return f"ACX_ENV={configured_env!r} does not match --env={env!r}; refusing to run"
        return None

    # This settings read does not open a session or connection. The DSN check
    # preserves manage_api_keys' fail-closed behavior outside VM containers.
    from db.settings import get_database_settings

    return _validate_env_vs_dsn(env, get_database_settings().postgres_dsn)


async def _create(args: argparse.Namespace, session: AsyncSession) -> tuple[PortalTenantInvitation, str]:
    raw_token = secrets.token_urlsafe(32)
    invitation = PortalTenantInvitation(
        tenant_id=None,
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
    invitation = await session.get(PortalTenantInvitation, args.invitation_id)
    now = datetime.now(UTC)
    if invitation is None or _state(invitation, now) != "pending":
        return None
    invitation.expires_at = now
    await session.flush()
    return invitation


async def run(argv: Sequence[str] | None = None, *, session: AsyncSession | None = None) -> int:
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

    issued: tuple[PortalTenantInvitation, str] | None = None
    revoked: PortalTenantInvitation | None = None
    status = 0
    try:
        try:
            await enable_rls_bypass(session)
            try:
                if args.command == "create":
                    issued = await _create(args, session)
                elif args.command == "list":
                    await _list(args, session)
                elif args.command == "revoke":
                    revoked = await _revoke(args, session)
                    if revoked is None:
                        status = 1
            finally:
                await disable_rls_bypass(session)

            if status == 0:
                await session.commit()
            else:
                await session.rollback()
        except BaseException:
            await session.rollback()
            raise

        if issued is not None:
            invitation, raw_token = issued
            # Emit the raw token only after the hash-only row has committed.
            sys.stdout.write(f"invitation_token={raw_token}\n")
            sys.stdout.write(
                f"invitation_id={invitation.id}\temail={invitation.invited_email}"
                f"\texpires_at={_format(invitation.expires_at)}\n"
            )
            sys.stdout.flush()
        elif args.command == "revoke":
            if revoked is None:
                sys.stderr.write("error: invitation not found or not pending\n")
            else:
                sys.stderr.write(f"revoked invitation_id={revoked.id} expires_at={_format(revoked.expires_at)}\n")
            sys.stderr.flush()
        return status
    finally:
        if opened_session:
            await session.close()


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":  # pragma: no cover
    main()
