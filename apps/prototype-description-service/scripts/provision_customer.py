"""Operator CLI: concierge sell-and-provision fast-path (AP-7).

Mints a real (non-demo) tenant + API key via the shared recognition minter.
Prints the raw API key **once** on first create, plus tenant id and a
copy-paste WordPress install snippet. Idempotent on EMAIL.

Usage:
    python -m scripts.provision_customer --env {prod,dev,local} \\
        --email customer@example.com [--plan pro] [--label "Acme Co"]

Env:
    ACX_RECOGNITION_URL / RECOGNITION_PUBLIC_URL — API URL embedded in the WP snippet
        (default: https://api.altcontext.com).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.customer_provision_service import (
    ProvisionResult,
    provision_customer,
)

_ENV_CHOICES = ("prod", "dev", "local")
_DEFAULT_API_URL = "https://api.altcontext.com"


def _dsn_host(dsn: str) -> str:
    return (urlparse(dsn).hostname or "").lower()


def _is_local_host(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")


def _validate_env_vs_dsn(env: str, dsn: str) -> str | None:
    """Mirror manage_api_keys BR-02 env/DSN guard."""
    host = _dsn_host(dsn)
    if not host:
        return f"env={env}: DSN has no host; refusing to run"
    if env == "prod" and _is_local_host(host):
        return f"env=prod but DSN host '{host}' looks local; refusing to run"
    if env in {"dev", "local"} and not _is_local_host(host):
        return f"env={env} but DSN host '{host}' is not a local host; refusing to run"
    return None


def _public_api_url() -> str:
    for key in ("ACX_RECOGNITION_URL", "RECOGNITION_PUBLIC_URL"):
        value = (os.environ.get(key) or "").strip().rstrip("/")
        if value:
            return value
    return _DEFAULT_API_URL


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="provision_customer")
    parser.add_argument(
        "--env",
        required=True,
        choices=list(_ENV_CHOICES),
        help="target environment; validated against the DSN host",
    )
    parser.add_argument("--email", required=True, help="customer email (idempotency key)")
    parser.add_argument(
        "--plan",
        default="pro",
        help="commercial plan slug: free|pro|enterprise (default: pro)",
    )
    parser.add_argument(
        "--label",
        default=None,
        help='optional customer display name, e.g. "Acme Gallery"',
    )
    return parser


def _format_wp_snippet(*, api_url: str, api_key: str | None, tenant_id: str) -> str:
    key_line = (
        f"define('ACX_RECOGNITION_API_KEY', '{api_key}');"
        if api_key
        else "define('ACX_RECOGNITION_API_KEY', '<paste-key-from-first-mint>');"
    )
    return "\n".join(
        [
            "# WordPress install snippet (wp-config.php / WORDPRESS_CONFIG_EXTRA)",
            f"define('ACX_RECOGNITION_URL', '{api_url}');",
            key_line,
            f"define('ACX_RECOGNITION_TENANT_ID', '{tenant_id}');",
            "define('ACX_RECOGNITION_SOURCE', 'service');",
        ]
    )


def _emit_result(result: ProvisionResult, *, api_url: str) -> None:
    """Print operator-facing lines. Raw key only on status=created, stdout once."""
    lines = [
        f"status={result.status}",
        f"tenant_id={result.tenant_id}",
        f"email={result.email}",
        f"plan={result.plan}",
        f"label={result.label or ''}",
    ]
    if result.key_id is not None:
        lines.append(f"key_id={result.key_id}")
    if result.raw_key is not None:
        # Single labeled secret line — same convention as manage_api_keys create.
        lines.append(f"api_key={result.raw_key}")
    elif result.status == "existing":
        lines.append("note=tenant already provisioned for this email; raw key was shown only at first mint")

    sys.stdout.write("\n".join(lines) + "\n\n")
    sys.stdout.write(
        _format_wp_snippet(
            api_url=api_url,
            api_key=result.raw_key,
            tenant_id=str(result.tenant_id),
        )
        + "\n"
    )
    sys.stdout.flush()


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
        from db.tenant_context import enable_rls_bypass

        session = async_session_factory()
        opened_session = True
        # Concierge provisioning is cross-tenant admin work: bypass RLS (SET LOCAL,
        # transaction-scoped) so writes to RLS-forced tables like audit_events clear
        # the tenant-isolation policy — same seam as the /admin router's session.
        await enable_rls_bypass(session)

    try:
        try:
            result = await provision_customer(
                session,
                email=args.email,
                plan=args.plan,
                label=args.label,
            )
        except ValueError as exc:
            sys.stderr.write(f"error: {exc}\n")
            sys.stderr.flush()
            return 1

        _emit_result(result, api_url=_public_api_url())
        return 0
    except Exception:
        if opened_session:
            await session.rollback()
        raise
    finally:
        if opened_session:
            await session.close()


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":  # pragma: no cover
    main()
