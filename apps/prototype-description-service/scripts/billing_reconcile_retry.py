"""Operator-audited retry of one quarantined billing recovery item.

Default is dry-run. Real apply only records C0 retry_pending under a fenced
lease and never grants paid entitlement or prints credentials.

Usage:
    python -m scripts.billing_reconcile_retry --remote-id sub-x \\
        --environment sandbox --seller-account org_sandbox \\
        --operator-identity ops --operator-reason "mapped seller"
    python -m scripts.billing_reconcile_retry --apply --remote-id sub-x ...
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TextIO

from recognition.domain.portal_contracts import ReconciliationKind
from scripts.billing_reconcile import (
    ConfigurationError,
    ReconcileConfig,
    _build_runtime,
    audited_retry_quarantine,
)


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
            runtime = await _build_runtime(ReconcileConfig(), repository=None, provider=None)
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
