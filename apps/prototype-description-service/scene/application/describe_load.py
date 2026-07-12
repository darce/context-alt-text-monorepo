"""DB-derived GPU idle-reaper load snapshot for async single-run jobs (VLM-5).

Preserves the atomic tmp+rename write and ``{queue_depth,in_flight,written_at}``
wire contract from the deleted in-memory store (VLMFIX-S2-01). Counts are
global (cross-tenant) and MUST run on a dedicated short-lived RLS-bypassed
session — never a tenant-scoped request/worker session [DIAG-02], [SEC-01].
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.scene import DescribeRun, DescribeRunItem
from recognition.shared.db.dialect import is_sqlite
from scene.domain.describe_run import DescribeItemStatus, RunKind

_TRUTHY_PG_SETTINGS = {"true", "on", "1", "yes"}


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


async def load_snapshot(session: AsyncSession) -> dict[str, int | float]:
    """Count non-terminal ``run_kind=single`` items for the GPU idle reaper.

    ``queue_depth`` = items with status ``queued``; ``in_flight`` = status
    ``running`` (includes provisional, which stays ``running`` until final).
    Bulk-run items are excluded. Callers must use a bypass session [DIAG-02].
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
        "written_at": time.time(),
    }


def write_load_snapshot(snapshot: dict[str, Any], path: str | Path) -> None:
    """Atomically dump a load snapshot for the GPU idle reaper (VLMFIX-S2-01)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, separators=(",", ":")))
    os.replace(tmp, target)
