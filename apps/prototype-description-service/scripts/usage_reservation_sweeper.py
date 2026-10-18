"""Bounded reclamation of usage reservations stranded in ``reserved`` state."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_MAX_BATCHES = 100
DEFAULT_BATCH_SIZE = 100
DEFAULT_STALE_AFTER_SECONDS = 300.0
DEFAULT_NO_PROGRESS_LIMIT = 3
DEFAULT_TIMEOUT_SECONDS = 0.0


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _non_negative_float(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number")
    parsed = float(value)
    if not parsed >= 0 or parsed == float("inf") or parsed == float("-inf"):
        raise ValueError(f"{name} must be a finite non-negative number")
    return parsed


async def _maybe_await(value: Any) -> Any:
    if isinstance(value, Awaitable):
        return await value
    return value


@dataclass(slots=True)
class UsageSweepResult:
    """Bounded sweep outcome suitable for both tests and CLI reporting."""

    batches: int = 0
    stale_seen: int = 0
    released: int = 0
    failed: int = 0
    no_progress_cycles: int = 0
    stalled: bool = False

    @property
    def exit_code(self) -> int:
        return 1 if self.stalled else 0


async def _release_batch(repository: object, rows: list[object]) -> int:
    for method_name in ("release_stale_reservations", "release_batch", "release_reservations"):
        method = getattr(repository, method_name, None)
        if not callable(method):
            continue
        result = await _maybe_await(method(rows))
        return len(rows) if result is None else max(0, int(result))

    release = getattr(repository, "release", None) or getattr(repository, "release_reservation", None)
    if not callable(release):
        raise RuntimeError("usage repository has no batch or single-row release method")

    released = 0
    for row in rows:
        try:
            await _maybe_await(release(row))
        except Exception:  # noqa: BLE001 - one stranded row must not block its batch
            continue
        released += 1
    return released


async def sweep_stale_reservations(
    repository: object,
    *,
    max_batches: int = DEFAULT_MAX_BATCHES,
    batch_size: int = DEFAULT_BATCH_SIZE,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    no_progress_limit: int = DEFAULT_NO_PROGRESS_LIMIT,
) -> UsageSweepResult:
    """Release stale rows for a bounded number of cycles.

    A repository returning rows that cannot be released is considered stalled;
    after the bounded no-progress threshold the caller receives a non-zero
    result instead of an endlessly retrying process.
    """
    max_batches = _positive_int(max_batches, name="max_batches")
    batch_size = _positive_int(batch_size, name="batch_size")
    stale_after_seconds = _non_negative_float(stale_after_seconds, name="stale_after_seconds")
    no_progress_limit = _positive_int(no_progress_limit, name="no_progress_limit")

    report = UsageSweepResult()
    while report.batches < max_batches:
        report.batches += 1
        try:
            rows = await _maybe_await(
                repository.list_stale_reservations(stale_after_seconds, limit=batch_size),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            report.failed += 1
            report.no_progress_cycles += 1
            if report.no_progress_cycles >= no_progress_limit:
                report.stalled = True
                break
            continue

        bounded_rows = list(rows)[:batch_size]
        if not bounded_rows:
            break
        report.stale_seen += len(bounded_rows)

        try:
            released = await _release_batch(repository, bounded_rows)
        except asyncio.CancelledError:
            raise
        except Exception:
            report.failed += 1
            released = 0

        report.released += released
        if released > 0:
            report.no_progress_cycles = 0
        else:
            report.no_progress_cycles += 1
            if report.no_progress_cycles >= no_progress_limit:
                report.stalled = True
                break

    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="usage_reservation_sweeper")
    parser.add_argument("--max-batches", type=int, default=DEFAULT_MAX_BATCHES)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--stale-after-seconds", type=float, default=DEFAULT_STALE_AFTER_SECONDS)
    parser.add_argument(
        "--no-progress-limit",
        type=int,
        default=DEFAULT_NO_PROGRESS_LIMIT,
        help="consecutive no-progress cycles before a non-zero exit (rg-007)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="optional wall-clock bound; 0 disables the extra timeout (max-batches still applies)",
    )
    return parser


async def run(
    argv: Sequence[str] | None = None,
    *,
    repository: object | None = None,
    session: object | None = None,
    max_batches: int | None = None,
    batch_size: int | None = None,
    stale_after_seconds: float | None = None,
    no_progress_limit: int | None = None,
    timeout_seconds: float | None = None,
) -> int:
    """Run the CLI through UsageSettlementService.sweep_stale_reservations only."""
    if argv is not None or (repository is None and session is None and max_batches is None):
        args = _build_parser().parse_args(list(argv) if argv is not None else None)
        max_batches = args.max_batches
        batch_size = args.batch_size
        stale_after_seconds = args.stale_after_seconds
        no_progress_limit = args.no_progress_limit
        timeout_seconds = args.timeout_seconds
    else:
        max_batches = DEFAULT_MAX_BATCHES if max_batches is None else max_batches
        batch_size = DEFAULT_BATCH_SIZE if batch_size is None else batch_size
        stale_after_seconds = DEFAULT_STALE_AFTER_SECONDS if stale_after_seconds is None else stale_after_seconds
        no_progress_limit = DEFAULT_NO_PROGRESS_LIMIT if no_progress_limit is None else no_progress_limit
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds

    if session is None and repository is not None:
        sys.stderr.write(
            "error: usage reservation sweep requires a DB session; age-only repository release is removed\n"
        )
        sys.stderr.flush()
        return 1

    own_session = session is None
    if session is None:
        from db.session import async_session_factory

        session = async_session_factory()

    from db.tenant_context import enable_rls_bypass
    from recognition.application.services.usage_settlement_service import UsageSettlementService

    await enable_rls_bypass(session)
    timeout_seconds = _non_negative_float(timeout_seconds, name="timeout_seconds")

    async def _sweep() -> object:
        return await UsageSettlementService(session).sweep_stale_reservations(
            stale_after_seconds=stale_after_seconds,
            max_batches=max_batches,
            batch_size=batch_size,
            no_progress_limit=no_progress_limit,
        )

    try:
        if timeout_seconds > 0:
            report = await asyncio.wait_for(_sweep(), timeout=timeout_seconds)
        else:
            report = await _sweep()
        await session.commit()
    except TimeoutError:
        if session is not None:
            await session.rollback()
        sys.stderr.write("usage_reservation_sweeper stalled=True fail_closed=0 rejected=0 released=0 timeout=True\n")
        sys.stderr.flush()
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI reports operational failures
        if session is not None:
            await session.rollback()
        sys.stderr.write(f"error: usage reservation sweep failed: {exc}\n")
        sys.stderr.flush()
        return 1
    finally:
        if own_session and session is not None:
            await session.close()

    failed = int(getattr(report, "fail_closed", 0)) + int(getattr(report, "rejected", 0))
    stalled = bool(getattr(report, "stalled", False))
    sys.stderr.write(
        "usage_reservation_sweeper "
        f"batches={report.batches} stale={report.stale_seen} released={report.released} "
        f"committed={getattr(report, 'committed', 0)} skipped_active={getattr(report, 'skipped_active', 0)} "
        f"rejected={getattr(report, 'rejected', 0)} fail_closed={getattr(report, 'fail_closed', 0)} "
        f"failed={failed} stalled={stalled}\n"
    )
    sys.stderr.flush()
    return int(getattr(report, "exit_code", 1 if stalled else 0))


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_MAX_BATCHES",
    "DEFAULT_NO_PROGRESS_LIMIT",
    "DEFAULT_STALE_AFTER_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "UsageSweepResult",
    "main",
    "run",
    "sweep_stale_reservations",
]
