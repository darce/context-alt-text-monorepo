"""Daily expiry sweep for demo_instances (DS-4 / launch-plan §5).

Selects non-revoked rows past ``expires_at`` and calls the same
``expire_demo`` path used by the operator CLI (revokes demo row +
``api_keys.revoked_at``). Per-instance failures are isolated; repeated
consecutive stalls exit non-zero (rg-007).

Usage:
    python -m scripts.sweep_expired_demos --env {prod,dev,local}
    python -m scripts.sweep_expired_demos --env local --stall-limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DemoInstance
from recognition.application.services.demo_provisioning_service import (
    DEFAULT_SWEEP_STALL_LIMIT,
    WordPressDemoAccountGateway,
    sweep_expired_demos,
)

_ENV_CHOICES = ("prod", "dev", "local")


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
    parser = argparse.ArgumentParser(prog="sweep_expired_demos")
    parser.add_argument(
        "--env",
        required=True,
        choices=list(_ENV_CHOICES),
        help="target environment; validated against the DSN host",
    )
    parser.add_argument(
        "--stall-limit",
        type=int,
        default=DEFAULT_SWEEP_STALL_LIMIT,
        help="consecutive per-instance failures before non-zero exit (rg-007)",
    )
    parser.add_argument(
        "--wp-managed-by-wrapper",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="print currently eligible slugs without changing them (for the WP-CLI wrapper)",
    )
    return parser


async def run(
    argv: Sequence[str] | None = None,
    *,
    session: AsyncSession | None = None,
    wordpress: WordPressDemoAccountGateway | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    from db.settings import get_database_settings

    dsn = get_database_settings().postgres_dsn
    err = _validate_env_vs_dsn(args.env, dsn)
    if err is not None:
        sys.stderr.write(f"error: {err}\n")
        sys.stderr.flush()
        return 2

    own_session = session is None
    if own_session:
        if wordpress is None and not args.wp_managed_by_wrapper:
            sys.stderr.write(
                "error: direct execution cannot disable WordPress users; use make demo-sweep\n"
            )
            sys.stderr.flush()
            return 2
        from db.session import async_session_factory

        session = async_session_factory()

    if session is None:  # explicit guard (sr-006): survives python -O
        raise RuntimeError("no database session available for sweep")
    try:
        if args.list_only:
            rows = (
                (
                    await session.execute(
                        select(DemoInstance.slug).where(
                            DemoInstance.revoked.is_(False),
                            DemoInstance.expires_at < datetime.now(tz=UTC),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for slug in rows:
                sys.stdout.write(f"{slug}\n")
            sys.stdout.flush()
            return 0
        result = await sweep_expired_demos(session, stall_limit=args.stall_limit, wordpress=wordpress)
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        if own_session:
            await session.rollback()
        sys.stderr.write(f"error: sweep failed: {exc}\n")
        sys.stderr.flush()
        return 1
    finally:
        if own_session:
            await session.close()

    sys.stderr.write(f"sweep expired={result.expired} failed={result.failed} stalled={result.stalled}\n")
    if result.slugs_expired:
        sys.stderr.write(f"slugs={','.join(result.slugs_expired)}\n")
    sys.stderr.flush()

    if result.stalled:
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
