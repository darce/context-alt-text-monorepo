"""Operator CLI for API key lifecycle (create / list / revoke).

Referenced from `.env.prod.example`. Delegates persistence to
`SqlAlchemyApiKeyRepository`; never issues raw SQL; never prints raw keys
except the single labeled post-create line on stdout.

Usage:
    python -m scripts.manage_api_keys --env {prod,dev,local} create --tenant <uuid> [--expires-in <days>] [--tier STANDARD|PRO|ENTERPRISE]
    python -m scripts.manage_api_keys --env {prod,dev,local} list --tenant <uuid> [--include-revoked]
    python -m scripts.manage_api_keys --env {prod,dev,local} revoke --key-id <uuid>
    python -m scripts.manage_api_keys --env {prod,dev,local} tenant create --tenant <uuid> --site-url <url>
    python -m scripts.manage_api_keys --env {prod,dev,local} tenant list [--limit <n>]

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
import sys
import uuid
from collections.abc import Sequence
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant
from recognition.application.services.api_key_admin_service import mint_api_key
from recognition.config.security import RateLimitTier
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

    p_tenant = sub.add_parser("tenant", help="manage tenant bootstrap rows")
    tenant_sub = p_tenant.add_subparsers(dest="tenant_command", required=True)

    p_tenant_create = tenant_sub.add_parser("create", help="create or update a tenant row")
    p_tenant_create.add_argument("--tenant", required=True)
    p_tenant_create.add_argument("--site-url", required=True)

    p_tenant_list = tenant_sub.add_parser("list", help="list tenant rows")
    p_tenant_list.add_argument("--limit", type=int, default=100)

    return parser


async def _cmd_create(args, session: AsyncSession) -> int:
    try:
        record, raw = await mint_api_key(
            session,
            tenant_id=uuid.UUID(args.tenant),
            tier=RateLimitTier(args.tier),
            expires_in_days=args.expires_in,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        message = str(exc).lower()
        if "foreign key" in message and "tenant" in message:
            sys.stderr.write(
                "error: tenant not found; bootstrap it first with `tenant create --tenant <uuid> --site-url <url>`.\n"
            )
            sys.stderr.flush()
            return 1
        raise

    # stdout: one labeled secret line so operators do not confuse it with key_id.
    sys.stdout.write(f"api_key={raw}\n")
    sys.stdout.flush()
    # stderr: operator-facing breadcrumb.
    sys.stderr.write(f"key_id={record.id}\n")
    sys.stderr.flush()
    return 0


async def _cmd_list(args, session: AsyncSession) -> int:
    repo = SqlAlchemyApiKeyRepository(session)
    rows = await repo.list_for_tenant(uuid.UUID(args.tenant), include_revoked=args.include_revoked)
    for r in rows:
        # E15-12-BR-04: emit the hash tail with an explicit `hash:` prefix so
        # operators cannot mistake it for the raw-key tail. The raw key is
        # only printed once at create time and is unrecoverable from the
        # stored SHA-256; this column has always been a hash fingerprint.
        hash_tail = "hash:" + (r.api_key_hash or "")[-4:]
        sys.stdout.write(
            "\t".join(
                [
                    str(r.id),
                    hash_tail,
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


async def _cmd_tenant_create(args, session: AsyncSession) -> int:
    tenant_id = uuid.UUID(args.tenant)
    existing = await session.get(Tenant, tenant_id)
    if existing is None:
        tenant = Tenant(id=tenant_id, site_url=args.site_url)
        session.add(tenant)
        action = "created"
    else:
        existing.site_url = args.site_url
        tenant = existing
        action = "updated"

    await session.commit()
    await session.refresh(tenant)
    sys.stderr.write(f"{action} tenant_id={tenant.id} site_url={tenant.site_url}\n")
    sys.stderr.flush()
    return 0


async def _cmd_tenant_list(args, session: AsyncSession) -> int:
    stmt = select(Tenant).order_by(Tenant.created_at, Tenant.id).limit(int(args.limit))
    rows = (await session.execute(stmt)).scalars().all()
    for tenant in rows:
        sys.stdout.write("\t".join([str(tenant.id), tenant.site_url, _fmt(tenant.created_at)]) + "\n")
    sys.stdout.flush()
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
        if args.command == "tenant":
            if args.tenant_command == "create":
                return await _cmd_tenant_create(args, session)
            if args.tenant_command == "list":
                return await _cmd_tenant_list(args, session)
        parser.error(f"unknown command: {args.command}")
    finally:
        if opened_session:
            await session.close()


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":  # pragma: no cover
    main()
