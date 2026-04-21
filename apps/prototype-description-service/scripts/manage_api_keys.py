"""Operator CLI for API key lifecycle (create / list / revoke).

Referenced from `.env.prod.example`. Delegates persistence to
`SqlAlchemyApiKeyRepository`; never issues raw SQL; never prints raw keys
except the single post-create line on stdout.

Usage:
    python -m scripts.manage_api_keys --env {prod,dev,local} create --tenant <uuid> [--expires-in <days>] [--tier STANDARD|PRO|ENTERPRISE]
    python -m scripts.manage_api_keys --env {prod,dev,local} list --tenant <uuid> [--include-revoked]
    python -m scripts.manage_api_keys --env {prod,dev,local} revoke --key-id <uuid>

`--env` is mandatory (E15-3a-BR-02): the CLI refuses to run against a DSN
whose host does not match the declared environment. Prod aborts on loopback
or *.local hosts; dev/local abort on any remote host. This prevents the
original BR-02 incident where a "prod" key was silently written to a local
dev DB because DSN resolution fell through to whatever the shell happened
to configure.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import secrets
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.config.security import RateLimitTier, get_security_settings
from recognition.infrastructure.repositories.api_key_repository import SqlAlchemyApiKeyRepository

_ENV_CHOICES = ("prod", "dev", "local")


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manage_api_keys")
    parser.add_argument(
        "--env",
        required=True,
        choices=list(_ENV_CHOICES),
        help="target environment; validated against the DSN host",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="create a new API key")
    p_create.add_argument("--tenant", required=True)
    p_create.add_argument("--expires-in", type=int, default=None, help="days until expiry")
    p_create.add_argument(
        "--tier",
        choices=[t.value for t in RateLimitTier],
        default=RateLimitTier.STANDARD.value,
    )

    p_list = sub.add_parser("list", help="list API keys for a tenant")
    p_list.add_argument("--tenant", required=True)
    p_list.add_argument("--include-revoked", action="store_true")

    p_revoke = sub.add_parser("revoke", help="soft-revoke a key by id")
    p_revoke.add_argument("--key-id", required=True)

    return parser


async def _cmd_create(args, session: AsyncSession) -> int:
    settings = get_security_settings()
    raw = secrets.token_urlsafe(32)
    digest = hashlib.new(settings.api_key_hash_algorithm)
    digest.update(raw.encode("utf-8"))
    hashed = digest.hexdigest()

    expires_at: datetime | None = None
    if args.expires_in is not None:
        expires_at = datetime.now(tz=UTC) + timedelta(days=int(args.expires_in))

    repo = SqlAlchemyApiKeyRepository(session)
    record = await repo.create(
        tenant_id=uuid.UUID(args.tenant),
        hashed_key=hashed,
        rate_limit_tier=RateLimitTier(args.tier),
        expires_at=expires_at,
    )
    await session.commit()

    # stdout: raw key only (one line).
    sys.stdout.write(raw + "\n")
    sys.stdout.flush()
    # stderr: operator-facing breadcrumb.
    sys.stderr.write(f"key_id={record.id}\n")
    sys.stderr.flush()
    return 0


async def _cmd_list(args, session: AsyncSession) -> int:
    repo = SqlAlchemyApiKeyRepository(session)
    rows = await repo.list_for_tenant(uuid.UUID(args.tenant), include_revoked=args.include_revoked)
    for r in rows:
        last4 = (r.api_key_hash or "")[-4:]
        sys.stdout.write(
            "\t".join(
                [
                    str(r.id),
                    last4,
                    _fmt(r.created_at),
                    _fmt(r.last_used_at),
                    _fmt(r.expires_at),
                    _fmt(r.revoked_at),
                ]
            )
            + "\n"
        )
    sys.stdout.flush()
    return 0


async def _cmd_revoke(args, session: AsyncSession) -> int:
    repo = SqlAlchemyApiKeyRepository(session)
    try:
        record = await repo.revoke(uuid.UUID(args.key_id))
    except LookupError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    await session.commit()
    sys.stderr.write(f"revoked key_id={record.id} revoked_at={_fmt(record.revoked_at)}\n")
    sys.stderr.flush()
    return 0


def _fmt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


async def run(argv: Sequence[str] | None = None, *, session: AsyncSession | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    # BR-02 env/DSN guard runs before opening any connection. Read the
    # configured DSN via the canonical settings accessor (no connection),
    # validate, then proceed. When `session` is supplied by tests, we still
    # validate against the configured DSN to keep the guard exercised.
    from db.settings import get_database_settings

    dsn = get_database_settings().postgres_dsn
    mismatch = _validate_env_vs_dsn(args.env, dsn)
    if mismatch is not None:
        sys.stderr.write(f"error: {mismatch}\n")
        sys.stderr.flush()
        return 1

    opened_session = False
    if session is None:
        from db.session import async_session_factory

        session = async_session_factory()
        opened_session = True

    try:
        if args.command == "create":
            return await _cmd_create(args, session)
        if args.command == "list":
            return await _cmd_list(args, session)
        if args.command == "revoke":
            return await _cmd_revoke(args, session)
        parser.error(f"unknown command: {args.command}")
        return 2  # pragma: no cover
    finally:
        if opened_session:
            await session.close()


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":  # pragma: no cover
    main()
