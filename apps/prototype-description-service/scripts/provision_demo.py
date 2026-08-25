"""Operator CLI for per-prospect demo provisioning (DS-3 / launch-plan §5).

Usage:
    python -m scripts.provision_demo --env {prod,dev,local} provision --label "Acme Gallery" [--seed default]
    python -m scripts.provision_demo --env {prod,dev,local} expire --slug <slug>

``provision`` mints a tenant + API key via the shared minter, records the named
seed bundle, inserts a ``demo_instances`` row, and prints the demo URL. The
raw key is printed once on stdout (operator terminal only) and is never stored
in the registry. ``expire`` marks the slug revoked.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from enum import StrEnum
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.demo_provisioning_service import (
    DEFAULT_RECOGNITION_QUOTA,
    KNOWN_SEED_BUNDLES,
    DemoInstanceNotFoundError,
    UnknownSeedBundleError,
    expire_demo,
    provision_demo,
)

_ENV_CHOICES = ("prod", "dev", "local")


class AccountKind(StrEnum):
    """Demo credential kind. CI is a distinct least-privilege identity."""

    VIEWER = "viewer"
    CI = "ci"


CI_RECOGNITION_QUOTA = 20


class CiAccountCollisionError(ValueError):
    """CI identity must not equal the demo wp-admin username."""


def _dsn_host(dsn: str) -> str:
    return (urlparse(dsn).hostname or "").lower()


def _is_local_host(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")


def _validate_env_vs_dsn(env: str, dsn: str) -> str | None:
    host = _dsn_host(dsn)
    if not host:
        return f"env={env}: DSN has no host; refusing to run"
    if env == "prod" and _is_local_host(host):
        return f"env=prod but DSN host '{host}' looks local; refusing to run"
    if env in {"dev", "local"} and not _is_local_host(host):
        return f"env={env} but DSN host '{host}' is not a local host; refusing to run"
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="provision_demo")
    parser.add_argument(
        "--env",
        required=True,
        choices=list(_ENV_CHOICES),
        help="target environment; validated against the DSN host",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_provision = sub.add_parser("provision", help="mint tenant+key, seed selection, insert demo_instances row")
    p_provision.add_argument("--label", required=True, help="prospect label (e.g. 'Acme Gallery')")
    p_provision.add_argument(
        "--seed",
        default="default",
        help=f"named seed bundle ({', '.join(sorted(KNOWN_SEED_BUNDLES))})",
    )
    p_provision.add_argument(
        "--account",
        choices=[kind.value for kind in AccountKind],
        default=AccountKind.VIEWER.value,
        help="viewer = prospect demo key; ci = least-privilege CI key (must not equal --admin-user)",
    )
    p_provision.add_argument(
        "--admin-user",
        default="",
        help="demo wp-admin username; required for --account ci to refuse identity collision",
    )

    p_expire = sub.add_parser("expire", help="mark a demo instance revoked")
    p_expire.add_argument("--slug", required=True, help="demo slug to expire")

    return parser


def resolve_account_issuance(*, account: str, label: str, admin_user: str) -> tuple[AccountKind, int]:
    """Return (kind, quota). CI must not collide with the demo wp-admin username."""
    kind = AccountKind(account)
    if kind is AccountKind.VIEWER:
        return kind, DEFAULT_RECOGNITION_QUOTA
    admin = (admin_user or "").strip()
    if not admin:
        raise CiAccountCollisionError(
            "CI issuance requires --admin-user so the CI identity cannot collide with demo wp-admin"
        )
    if (label or "").strip() == admin:
        raise CiAccountCollisionError("CI account label must differ from the demo wp-admin username")
    return kind, CI_RECOGNITION_QUOTA


async def _cmd_provision(args, session: AsyncSession) -> int:
    try:
        kind, quota = resolve_account_issuance(
            account=args.account,
            label=args.label,
            admin_user=args.admin_user,
        )
        result = await provision_demo(
            session,
            label=args.label,
            seed=args.seed,
            recognition_quota=quota,
        )
        await session.commit()
    except (UnknownSeedBundleError, CiAccountCollisionError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        sys.stderr.flush()
        return 1

    instance = result.instance
    # stdout: operator-facing URL + one-time raw key (never stored in registry).
    sys.stdout.write(f"demo_url={result.demo_url}\n")
    sys.stdout.write(f"api_key={result.raw_api_key}\n")
    sys.stdout.flush()
    # stderr: non-secret metadata for operators/scripts.
    sys.stderr.write(
        f"account={kind.value}\tslug={instance.slug}\ttenant_id={instance.tenant_id}\t"
        f"seed_bundle={instance.seed_bundle}\texpires_at={instance.expires_at.isoformat()}\t"
        f"recognition_quota={instance.recognition_quota}\n"
    )
    sys.stderr.flush()
    return 0


async def _cmd_expire(args, session: AsyncSession) -> int:
    try:
        instance = await expire_demo(session, slug=args.slug)
        await session.commit()
    except DemoInstanceNotFoundError as exc:
        sys.stderr.write(f"error: {exc}\n")
        sys.stderr.flush()
        return 1

    sys.stderr.write(f"expired slug={instance.slug} revoked={instance.revoked}\n")
    sys.stderr.flush()
    return 0


async def run(argv: Sequence[str] | None = None, *, session: AsyncSession | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

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
        if args.command == "provision":
            return await _cmd_provision(args, session)
        if args.command == "expire":
            return await _cmd_expire(args, session)
        parser.error(f"unknown command: {args.command}")
    finally:
        if opened_session:
            await session.close()


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":  # pragma: no cover
    main()
