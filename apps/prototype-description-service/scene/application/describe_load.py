"""DB-derived GPU idle-reaper load snapshot for async single-run jobs (VLM-5).

Preserves the atomic tmp+rename write and ``{queue_depth,in_flight,written_at}``
wire contract from the deleted in-memory store (VLMFIX-S2-01). Counts are
global (cross-tenant) and MUST run on a dedicated short-lived RLS-bypassed
session — never a tenant-scoped request/worker session [DIAG-02], [SEC-01].
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import math
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.scene import DescribeRun, DescribeRunItem
from recognition.shared.db.dialect import is_sqlite
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus, RunKind

_logger = logging.getLogger(__name__)

_TRUTHY_PG_SETTINGS = {"true", "on", "1", "yes"}

LOAD_PATH_ENV = "ACX_DESCRIBE_LOAD_PATH"
DEFAULT_LOAD_PATH = "/run/acx/describe-load.json"
LOAD_REFRESH_SECONDS_ENV = "ACX_DESCRIBE_LOAD_REFRESH_SECONDS"
DEFAULT_LOAD_REFRESH_SECONDS = 45.0
LOAD_SNAPSHOT_STALE_SECONDS = 120.0
LOAD_REFRESH_TIMEOUT_SECONDS = 30.0
# Preserve two refresh opportunities inside one stale window. The timeout is
# also kept as headroom in case its configured value grows in a later change.
MAX_LOAD_REFRESH_SECONDS = min(
    LOAD_SNAPSHOT_STALE_SECONDS / 2,
    LOAD_SNAPSHOT_STALE_SECONDS - LOAD_REFRESH_TIMEOUT_SECONDS,
)

# ``write_load_snapshot`` is also used by request paths, so serialize the tiny
# write+replace section rather than relying on callers to coordinate. Unique
# temp names make concurrent/multi-process writers safe; this in-process lock
# additionally keeps their replacements ordered and prevents needless overlap.
_LOAD_SNAPSHOT_WRITE_LOCK = threading.Lock()

# A bulk run occupying the GPU. Enumerated as the non-terminal set rather than
# "not in (COMPLETED, ...)" so a newly added status defaults to *not* holding
# the GPU open, instead of silently pinning an A10 forever [sr-007].
_ACTIVE_BULK_RUN_STATUSES = (DescribeRunStatus.PENDING, DescribeRunStatus.RUNNING)


def _open_load_snapshot_fence(target: Path) -> int:
    """Open the persistent lock coordinated with the lifecycle reaper."""
    lock_path = target.with_name(f"{target.name}.lock")
    created = False
    try:
        lock_fd = os.open(
            lock_path,
            os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o660,
        )
        created = True
    except FileExistsError:
        lock_fd = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC)
    if created:
        # Creation mode is filtered through umask. Both deployables use the
        # shared lifecycle group, so restore the provisioned cross-uid mode.
        try:
            os.fchmod(lock_fd, 0o660)
        except BaseException:
            os.close(lock_fd)
            raise
    return lock_fd


def resolve_load_path() -> str:
    """Single source of truth for the idle-reaper load-file path (VLM5-S4A-BR-03).

    Startup snapshot and runtime enqueue/poll writers must resolve through here
    so the reaper can never read a stale file from a drifted literal [rg-008].
    """
    return os.environ.get(LOAD_PATH_ENV, DEFAULT_LOAD_PATH)


def resolve_load_refresh_seconds() -> float:
    """Return a safe refresh cadence below the reaper's 120s stale guard."""
    raw = os.environ.get(LOAD_REFRESH_SECONDS_ENV)
    if raw is None:
        return DEFAULT_LOAD_REFRESH_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 0.0
    # Leave room for a second refresh attempt inside the stale-file window. A
    # value merely below 120s is not sufficient once failures/latency occur.
    if not math.isfinite(seconds) or seconds <= 0 or seconds >= MAX_LOAD_REFRESH_SECONDS:
        _logger.warning(
            "invalid %s=%r; using default %.0fs",
            LOAD_REFRESH_SECONDS_ENV,
            raw,
            DEFAULT_LOAD_REFRESH_SECONDS,
        )
        return DEFAULT_LOAD_REFRESH_SECONDS
    return seconds


async def _require_rls_bypass(session: AsyncSession) -> None:
    """Fail closed unless this session has RLS bypass active (design (c))."""
    if is_sqlite(session):
        return
    result = await session.execute(text("SELECT current_setting('app.bypass_rls', true)"))
    value = result.scalar()
    if value is None or str(value).strip().lower() not in _TRUTHY_PG_SETTINGS:
        raise RuntimeError(
            "load_snapshot requires an RLS-bypassed system session "
            "(current_setting('app.bypass_rls') is not truthy); open a dedicated "
            "session and call enable_rls_bypass(session) first"
        )


async def batch_in_progress(session: AsyncSession) -> bool:
    """True while any tenant holds a non-terminal ``run_kind=bulk`` run (GPUW-1).

    This is the "Describe selected" case. ``queue_depth``/``in_flight`` below
    deliberately count only single runs, so without this flag a bulk run is
    completely invisible to the lifecycle controller: ``run_start_cycle`` sees
    no work and never starts the burst GPU, and ``run_reap_cycle`` sees an idle
    GPU and STOPs it mid-batch. ``reaper.JsonFileJobLoadSource`` already reads
    ``batch_in_progress`` and warns that bulk runs are unprotected until a
    producer writes it -- this is that producer.

    Counted on the run, not its items: a run that has claimed the GPU but whose
    items are momentarily between states must still read as busy.
    """
    result = await session.execute(
        select(func.count())
        .select_from(DescribeRun)
        .where(
            DescribeRun.run_kind == RunKind.BULK,
            DescribeRun.status.in_(_ACTIVE_BULK_RUN_STATUSES),
        )
    )
    return int(result.scalar() or 0) > 0


async def load_snapshot(session: AsyncSession) -> dict[str, int | float | bool]:
    """Count non-terminal work for the GPU lifecycle controller.

    ``queue_depth`` = single-run items with status ``queued``; ``in_flight`` =
    status ``running`` (includes provisional, which stays ``running`` until
    final). Bulk-run *items* stay excluded from both counts -- the wire meaning
    of those two keys is unchanged -- and bulk work is reported separately as
    ``batch_in_progress`` (GPUW-1). Callers must use a bypass session [DIAG-02].
    """
    await _require_rls_bypass(session)
    result = await session.execute(
        select(DescribeRunItem.status, func.count())
        .join(DescribeRun, DescribeRun.id == DescribeRunItem.run_id)
        .where(
            DescribeRun.run_kind == RunKind.SINGLE,
            DescribeRunItem.status.in_([DescribeItemStatus.QUEUED, DescribeItemStatus.RUNNING]),
        )
        .group_by(DescribeRunItem.status)
    )
    counts: dict[str, int] = {str(status): int(n) for status, n in result.all()}
    return {
        "queue_depth": counts.get(DescribeItemStatus.QUEUED, 0),
        "in_flight": counts.get(DescribeItemStatus.RUNNING, 0),
        "batch_in_progress": await batch_in_progress(session),
        "written_at": time.time(),
    }


def write_load_snapshot(snapshot: dict[str, Any], path: str | Path) -> None:
    """Atomically dump load while holding the reaper's process fence."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, separators=(",", ":"))

    with _LOAD_SNAPSHOT_WRITE_LOCK:
        lock_fd = _open_load_snapshot_fence(target)
        fd = -1
        tmp: Path | None = None
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            fd, tmp_name = tempfile.mkstemp(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                text=True,
            )
            tmp = Path(tmp_name)
            with os.fdopen(fd, "w") as tmp_file:
                fd = -1  # owned and closed by ``tmp_file`` from here
                tmp_file.write(payload)
                os.fchmod(tmp_file.fileno(), 0o644)
            os.replace(tmp, target)
            tmp = None  # the temp path no longer exists after replace
        finally:
            if fd >= 0:
                os.close(fd)
            if tmp is not None:
                tmp.unlink(missing_ok=True)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)


async def dump_load_snapshot(
    session_factory,
    path: str | Path | None = None,
    *,
    raise_on_error: bool = False,
) -> None:
    """Best-effort load write on a dedicated RLS-bypassed session (GPUW-1).

    Shared by the single-image router, the bulk-run router and the bulk worker
    so there is exactly one writer implementation; a second copy would drift and
    the reaper would silently read a stale file [rg-008].

    Request/worker callers retain best-effort behavior by default: a failed
    snapshot must not fail the describe operation that triggered it. The
    periodic refresher opts into ``raise_on_error`` so its cycle-level warning
    and timeout supervision can observe failures instead of silently treating
    them as successful refreshes.
    """
    from db.tenant_context import enable_rls_bypass

    if session_factory is None:
        if raise_on_error:
            raise RuntimeError("describe load snapshot session factory is unavailable")
        return
    target = path or resolve_load_path()
    try:
        async with session_factory() as session:
            await enable_rls_bypass(session)
            snap = await load_snapshot(session)
            await session.commit()
        write_load_snapshot(snap, target)
    except Exception:  # noqa: BLE001 - reaper snapshot is best-effort
        if raise_on_error:
            raise
        _logger.debug("describe load snapshot write failed path=%s", target, exc_info=True)


async def refresh_load_snapshot_loop(
    session_factory,
    *,
    refresh_seconds: float | None = None,
    timeout_seconds: float = LOAD_REFRESH_TIMEOUT_SECONDS,
) -> None:
    """Keep the reaper snapshot fresh for as long as the API is running."""
    interval = refresh_seconds if refresh_seconds is not None else resolve_load_refresh_seconds()
    loop = asyncio.get_running_loop()
    next_refresh_at = loop.time() + interval
    while True:
        await asyncio.sleep(max(0.0, next_refresh_at - loop.time()))
        next_refresh_at += interval
        try:
            async with asyncio.timeout(timeout_seconds):
                await dump_load_snapshot(session_factory, raise_on_error=True)
        except TimeoutError:
            _logger.warning(
                "periodic describe load snapshot refresh timed out after %.1fs",
                timeout_seconds,
            )
        except Exception:  # noqa: BLE001 - one failed refresh must not stop later refreshes
            _logger.warning("periodic describe load snapshot refresh failed", exc_info=True)
        finally:
            # Keep cycles on their configured start-to-start cadence so a slow
            # or timed-out DB call does not add another full interval. If one
            # cycle overruns the cadence entirely, retry without a tight-looping
            # backlog of missed ticks.
            if next_refresh_at < loop.time():
                # Skip missed ticks but keep the configured gap; clamping to
                # bare loop.time() would turn a persistently slow dump into a
                # zero-gap DB polling loop.
                next_refresh_at = loop.time() + interval


async def run_startup_load_snapshot(session_factory, path: str | Path | None = None) -> None:
    """VLM-5 design (c): write the initial DB-derived load snapshot at boot.

    Opens a dedicated short-lived RLS-bypassed session (never tenant-scoped).
    Best-effort from the lifespan caller; raises on failure for that try/except.
    """
    await dump_load_snapshot(session_factory, path, raise_on_error=True)
