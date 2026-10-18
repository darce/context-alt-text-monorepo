"""Operator-audited retry of one quarantined billing recovery item.

Default is dry-run. Real apply only records C0 retry_pending under a fenced
lease and never grants paid entitlement or prints credentials.

Audited retry is database-only: it requires a session and explicit
environment/seller CLI values. Polar credentials and an HTTP client are not
used. [RES-01] [GRPH-09] [Release It ch4 independent dependency]

Usage:
    python -m scripts.billing_reconcile_retry --remote-id sub-x \\
        --environment sandbox --seller-account org_sandbox \\
        --operator-identity ops --operator-reason "mapped seller"
    python -m scripts.billing_reconcile_retry --apply --remote-id sub-x ...
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import inspect
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TextIO

from recognition.domain.portal_contracts import ReconciliationKind
from scripts.billing_reconcile import (
    ConfigurationError,
    audited_retry_quarantine,
)


class _RetryRuntime:
    __slots__ = ("recovery_repository", "session")

    def __init__(self, session: object, recovery_repository: object) -> None:
        self.session = session
        self.recovery_repository = recovery_repository

    async def close(self) -> None:
        close = getattr(self.session, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result


async def _maybe_await(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


async def _build_retry_runtime(
    *,
    session_factory: Callable[[], object] | None = None,
) -> _RetryRuntime:
    factory = session_factory
    if factory is None:
        from db.session import async_session_factory

        factory = async_session_factory
    session = await _maybe_await(factory())
    try:
        from recognition.infrastructure.repositories.billing_reconciliation_repository import (
            BillingReconciliationRepository,
        )

        repository = BillingReconciliationRepository(session)
        if getattr(repository, "session", None) is None:
            with contextlib.suppress(AttributeError, TypeError):
                repository.session = session  # type: ignore[attr-defined]
        return _RetryRuntime(session=session, recovery_repository=repository)
    except Exception:
        close = getattr(session, "close", None)
        if callable(close):
            await _maybe_await(close())
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="billing_reconcile_retry")
    parser.add_argument("--remote-id", required=True, help="quarantined vendor remote id")
    parser.add_argument("--environment", required=True, choices=("sandbox", "live"))
    parser.add_argument("--seller-account", required=True)
    parser.add_argument("--provider", default="polar", choices=("polar", "fake"))
    parser.add_argument("--kind", default=ReconciliationKind.SUBSCRIPTIONS.value)
    parser.add_argument("--operator-identity", default="")
    parser.add_argument("--operator-reason", default="")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="persist retry_pending; default is dry-run",
    )
    return parser


async def run(
    argv: Sequence[str] | None = None,
    *,
    recovery_repository: object | None = None,
    session_factory: Callable[[], object] | None = None,
    stderr: TextIO | None = None,
    clock: Callable[[], datetime] | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    err = stderr if stderr is not None else sys.stderr
    if not args.operator_identity.strip() or not args.operator_reason.strip():
        err.write("error: operator identity and reason are required\n")
        err.flush()
        return 2
    runtime = None
    repository = recovery_repository
    if repository is None:
        try:
            runtime = await _build_retry_runtime(session_factory=session_factory)
        except ConfigurationError as exc:
            err.write(f"error: {exc}\n")
            err.flush()
            return 2
        repository = runtime.recovery_repository
    try:
        report = await audited_retry_quarantine(
            repository,
            remote_id=args.remote_id,
            operator_identity=args.operator_identity,
            operator_reason=args.operator_reason,
            environment=args.environment,
            seller_account=args.seller_account,
            provider=args.provider,
            kind=ReconciliationKind(args.kind),
            dry_run=not args.apply,
            clock=clock or (lambda: datetime.now(UTC)),
        )
        err.write(
            "billing_reconcile_retry "
            f"remote_id={args.remote_id} dry_run={not args.apply} "
            f"processed={report.processed} would_change={report.would_change} "
            f"exit={report.exit_code}\n"
        )
        err.flush()
        return report.exit_code
    except ConfigurationError as exc:
        err.write(f"error: {exc}\n")
        err.flush()
        return 2
    finally:
        if runtime is not None:
            await runtime.close()


def main(
    argv: Sequence[str] | None = None,
    *,
    stderr: TextIO | None = None,
) -> int:
    return asyncio.run(run(argv, stderr=stderr))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
