"""DB-derived GPU idle-reaper load snapshot for async single-run jobs (VLM-5).

Preserves the atomic tmp+rename write and ``{queue_depth,in_flight,written_at}``
wire contract from the deleted in-memory store (VLMFIX-S2-01). Counts are
global (cross-tenant) and MUST run on a dedicated short-lived RLS-bypassed
session — never a tenant-scoped request/worker session [DIAG-02], [SEC-01].
"""

from __future__ import annotations

import json
import logging
import os
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

# A bulk run occupying the GPU. Enumerated as the non-terminal set rather than
# "not in (COMPLETED, ...)" so a newly added status defaults to *not* holding
# the GPU open, instead of silently pinning an A10 forever [sr-007].
_ACTIVE_BULK_RUN_STATUSES = (DescribeRunStatus.PENDING, DescribeRunStatus.RUNNING)


def resolve_load_path() -> str:
    """Single source of truth for the idle-reaper load-file path (VLM5-S4A-BR-03).

    Startup snapshot and runtime enqueue/poll writers must resolve through here
    so the reaper can never read a stale file from a drifted literal [rg-008].
    """
    return os.environ.get(LOAD_PATH_ENV, DEFAULT_LOAD_PATH)


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
    """Atomically dump a load snapshot for the GPU idle reaper (VLMFIX-S2-01)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, separators=(",", ":")))
    os.replace(tmp, target)


async def dump_load_snapshot(session_factory, path: str | Path | None = None) -> None:
    """Best-effort load write on a dedicated RLS-bypassed session (GPUW-1).

    Shared by the single-image router, the bulk-run router and the bulk worker
    so there is exactly one writer implementation; a second copy would drift and
    the reaper would silently read a stale file [rg-008].

    Never raises: a failed snapshot must not fail the describe request that
    triggered it. The consumer fails closed on a stale file, so the cost of a
    missed write is a GPU that stays up until the max-lease cap, not a batch
    that dies.
    """
    from db.tenant_context import enable_rls_bypass

    if session_factory is None:
        return
    target = path or resolve_load_path()
    try:
        async with session_factory() as session:
            await enable_rls_bypass(session)
            snap = await load_snapshot(session)
            await session.commit()
        write_load_snapshot(snap, target)
    except Exception:  # noqa: BLE001 - reaper snapshot is best-effort
        _logger.debug("describe load snapshot write failed path=%s", target, exc_info=True)


async def run_startup_load_snapshot(session_factory, path: str | Path | None = None) -> None:
    """VLM-5 design (c): write the initial DB-derived load snapshot at boot.

    Opens a dedicated short-lived RLS-bypassed session (never tenant-scoped).
    Best-effort from the lifespan caller; raises on failure for that try/except.
    """
    from db.tenant_context import enable_rls_bypass

    target = path or resolve_load_path()
    async with session_factory() as session:
        await enable_rls_bypass(session)
        snap = await load_snapshot(session)
        await session.commit()
    write_load_snapshot(snap, target)
