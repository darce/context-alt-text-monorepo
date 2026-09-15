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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.scene import DescribeDemandLease, DescribeOperation, DescribeRun, DescribeRunItem
from recognition.shared.db.dialect import is_sqlite
from scene.application.describe_operation_repository import DescribeOperationRepository
from scene.domain.describe_run import (
    DEFAULT_ASYNC_JOB_RETENTION_HOURS,
    DemandLeaseState,
    DescribeItemStatus,
    DescribeRunStatus,
    RunKind,
    as_utc,
    utc_observation,
)

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

# Counting-only repository construction; lease lifetime is stored on each row.
_COUNTING_LEASE_SECONDS = 1.0
_SNAPSHOT_REVISION_TABLE = "describe_load_snapshot_revisions"
_MAX_LEASE_REASON = "lease_cap"
# Deployed demand-lease lifetime L. accept() callers must use this same bound.
DEMAND_LEASE_SECONDS = 180.0
# acx-gpu-start.timer default OnUnitActiveSec (START_INTERVAL=30s).
CONTROLLER_POLL_PERIOD_SECONDS = 30.0
# Bounded worst-case timer drift; no other in-process jitter source.
SCHEDULING_JITTER_SECONDS = 15.0
PUBLICATION_DELAY_SECONDS = LOAD_REFRESH_TIMEOUT_SECONDS
PUBLIC_RETRY_AFTER_CEILING_SECONDS = 120.0
# Bounded extra client delay after honouring Retry-After.
CLIENT_RETRY_GAP_SECONDS = 15.0
_DEMAND_BOUND_NAMES = (
    "lease_seconds",
    "poll_period_seconds",
    "jitter_seconds",
    "publication_delay_seconds",
    "retry_after_seconds",
    "client_retry_gap_seconds",
    "refresh_seconds",
    "freshness_seconds",
    "retention_seconds",
)

# A bulk run occupying the GPU. Enumerated as the non-terminal set rather than
# "not in (COMPLETED, ...)" so a newly added status defaults to *not* holding
# the GPU open, instead of silently pinning an A10 forever [sr-007].
_ACTIVE_BULK_RUN_STATUSES = (DescribeRunStatus.PENDING, DescribeRunStatus.RUNNING)


@dataclass(frozen=True)
class DemandLeaseBounds:
    """Fail-closed deployment bounds for demand-lease publication (rg-008)."""

    lease_seconds: float
    poll_period_seconds: float
    jitter_seconds: float
    publication_delay_seconds: float
    retry_after_seconds: float
    client_retry_gap_seconds: float
    refresh_seconds: float
    freshness_seconds: float
    retention_seconds: float

    def validate(self) -> None:
        """Raise ValueError when any bound is missing, non-finite, or illegal."""
        for name in _DEMAND_BOUND_NAMES:
            value = getattr(self, name)
            if (
                value is None
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"demand lease bound {name} must be a finite number; got {value!r}")
            if value < 0:
                raise ValueError(f"demand lease bound {name} must be non-negative; got {value!r}")
        poll_budget = self.poll_period_seconds + self.jitter_seconds + self.publication_delay_seconds
        if self.lease_seconds <= poll_budget:
            raise ValueError(f"demand lease L must exceed P+J+D ({self.lease_seconds} <= {poll_budget})")
        retry_budget = self.retry_after_seconds + self.client_retry_gap_seconds
        if self.lease_seconds <= retry_budget:
            raise ValueError(
                f"demand lease L must exceed Retry-After + client retry gap ({self.lease_seconds} <= {retry_budget})"
            )
        refresh_span = self.refresh_seconds + self.publication_delay_seconds
        if refresh_span >= self.freshness_seconds:
            raise ValueError(
                f"demand refresh R+D must stay below freshness F ({refresh_span} >= {self.freshness_seconds})"
            )
        if self.lease_seconds > self.retention_seconds:
            raise ValueError(
                f"demand lease L must fit within async retention ({self.lease_seconds} > {self.retention_seconds})"
            )


def deployed_demand_lease_bounds() -> DemandLeaseBounds:
    """Build bounds from in-process constants and the live refresh cadence."""
    return DemandLeaseBounds(
        lease_seconds=DEMAND_LEASE_SECONDS,
        poll_period_seconds=CONTROLLER_POLL_PERIOD_SECONDS,
        jitter_seconds=SCHEDULING_JITTER_SECONDS,
        publication_delay_seconds=PUBLICATION_DELAY_SECONDS,
        retry_after_seconds=PUBLIC_RETRY_AFTER_CEILING_SECONDS,
        client_retry_gap_seconds=CLIENT_RETRY_GAP_SECONDS,
        refresh_seconds=resolve_load_refresh_seconds(),
        freshness_seconds=LOAD_SNAPSHOT_STALE_SECONDS,
        retention_seconds=float(DEFAULT_ASYNC_JOB_RETENTION_HOURS * 3600),
    )


def validate_demand_lease_bounds(bounds: DemandLeaseBounds | None = None) -> DemandLeaseBounds:
    """Fail closed on illegal demand-lease bounds before any publication."""
    resolved = deployed_demand_lease_bounds() if bounds is None else bounds
    resolved.validate()
    return resolved


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


async def _allocate_snapshot_revision(session: AsyncSession) -> int:
    """Allocate the next publication revision under the demand-read transaction.

    A singleton row lock serializes allocation with the subsequent demand read
    so an older database view cannot receive a newer revision. The table is the
    publication sequence declared by the identity schema; this path never
    creates it at runtime.
    """
    if is_sqlite(session):
        await session.execute(
            text(f"INSERT OR IGNORE INTO {_SNAPSHOT_REVISION_TABLE} (singleton, revision) VALUES (1, 0)")
        )
    else:
        await session.execute(
            text(
                f"INSERT INTO {_SNAPSHOT_REVISION_TABLE} (singleton, revision) VALUES (1, 0) "
                "ON CONFLICT (singleton) DO NOTHING"
            )
        )
    result = await session.execute(
        text(f"UPDATE {_SNAPSHOT_REVISION_TABLE} SET revision = revision + 1 WHERE singleton = 1 RETURNING revision")
    )
    revision = result.scalar()
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise RuntimeError("failed to allocate load snapshot revision")
    return revision


def _published_revision(payload: object) -> int:
    """Return the currently published revision; a missing key is revision 0."""
    if not isinstance(payload, dict):
        raise RuntimeError("published load snapshot is not an object")
    if "revision" not in payload:
        return 0
    revision = payload["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise RuntimeError("malformed published load snapshot revision")
    return revision


def _max_lease_reached() -> bool:
    from scene.application.gpu_state import resolve_gpu_state_path

    path = Path(resolve_gpu_state_path())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return True
    if not isinstance(payload, dict):
        return True
    return payload.get("last_transition_reason") == _MAX_LEASE_REASON


def _gpu_excludes_lease_demand(*, now: datetime) -> bool:
    from scene.application.gpu_state import GpuState, read_gpu_state

    state = read_gpu_state(now=now.timestamp())
    return state not in {
        GpuState.STOPPED,
        GpuState.STARTING,
        GpuState.WARMING,
        GpuState.READY,
        GpuState.DEGRADED,
    }


def _demand_policy_flags(*, now: datetime) -> tuple[bool, bool]:
    from scene.application.gpu_intent import IntentAction, read_gpu_intent, resolve_gpu_intent_path

    stop_requested = False
    intent = read_gpu_intent(resolve_gpu_intent_path())
    if intent is not None and intent.action is IntentAction.STOP and utc_observation(intent.expires_at) > now:
        stop_requested = True
    return stop_requested, _max_lease_reached()


def _lease_demand_blocked(
    *,
    now: datetime,
    stop_requested: bool | None,
    max_lease_reached: bool | None,
) -> bool:
    policy_stop, policy_max_lease = _demand_policy_flags(now=now)
    blocked_by_stop = policy_stop if stop_requested is None else stop_requested
    blocked_by_max_lease = policy_max_lease if max_lease_reached is None else max_lease_reached
    return blocked_by_stop or blocked_by_max_lease or _gpu_excludes_lease_demand(now=now)


async def _persist_first_ready(session: AsyncSession, *, now: datetime) -> None:
    from scene.application.gpu_state import GpuState, read_gpu_state

    if read_gpu_state(now=now.timestamp()) is not GpuState.READY:
        return
    rows = (
        await session.execute(
            select(DescribeOperation.tenant_id, DescribeOperation.operation_id)
            .join(
                DescribeDemandLease,
                (DescribeDemandLease.tenant_id == DescribeOperation.tenant_id)
                & (DescribeDemandLease.operation_id == DescribeOperation.operation_id),
            )
            .where(
                DescribeDemandLease.state == DemandLeaseState.ACTIVE,
                DescribeDemandLease.expires_at > now,
                DescribeOperation.first_ready_at.is_(None),
            )
        )
    ).all()
    if not rows:
        return
    repo = DescribeOperationRepository(session, lease_seconds=_COUNTING_LEASE_SECONDS)
    for tenant_id, operation_id in rows:
        await repo.observe_ready(tenant_id=tenant_id, operation_id=operation_id, now=now)


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


async def load_snapshot(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    stop_requested: bool | None = None,
    max_lease_reached: bool | None = None,
) -> dict[str, int | float | bool]:
    """Count non-terminal work for the GPU lifecycle controller.

    ``queue_depth`` = single-run items with status ``queued``; ``in_flight`` =
    status ``running`` (includes provisional, which stays ``running`` until
    final) plus eligible demand leases. Bulk-run *items* stay excluded from
    both counts -- the wire meaning of those two keys is unchanged -- and bulk
    work is reported separately as ``batch_in_progress`` (GPUW-1). Eligible
    leases are also reported as additive ``lease_demand``. Callers must use a
    bypass session [DIAG-02].

    STOP and lease-cap are resolved from the same policy files the periodic
    publisher uses unless a caller passes an explicit override. The demand
    transaction (revision allocation, expiry, first-ready) commits before this
    returns so a later file write cannot publish an undurable revision.
    """
    await _require_rls_bypass(session)
    observed_at = as_utc(now or datetime.now(UTC))
    demand_blocked = _lease_demand_blocked(
        now=observed_at,
        stop_requested=stop_requested,
        max_lease_reached=max_lease_reached,
    )
    revision = await _allocate_snapshot_revision(session)
    await _persist_first_ready(session, now=observed_at)
    lease_demand = await DescribeOperationRepository(
        session, lease_seconds=_COUNTING_LEASE_SECONDS
    ).active_demand_count(
        now=observed_at,
        stop_requested=demand_blocked,
        max_lease_reached=False,
    )
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
    running = counts.get(DescribeItemStatus.RUNNING, 0)
    snapshot: dict[str, int | float | bool] = {
        "queue_depth": counts.get(DescribeItemStatus.QUEUED, 0),
        "in_flight": running + lease_demand,
        "batch_in_progress": await batch_in_progress(session),
        "lease_demand": lease_demand,
        "revision": revision,
        "written_at": observed_at.timestamp(),
    }
    await session.commit()
    return snapshot


def write_load_snapshot(snapshot: dict[str, Any], path: str | Path) -> None:
    """Atomically dump load while holding the reaper's process fence.

    Snapshots that carry ``revision`` use write-if-newer: equal or older
    candidates are dropped without refreshing ``written_at``. Payloads without
    ``revision`` keep the legacy unconditional replace used by unit writers.
    Unreadable or malformed published revisions fail closed and never bypass
    the fence.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_if_newer = "revision" in snapshot
    candidate_revision: int | None = None
    if write_if_newer:
        raw_revision = snapshot["revision"]
        if isinstance(raw_revision, bool) or not isinstance(raw_revision, int) or raw_revision < 1:
            raise RuntimeError("load snapshot revision must be a positive integer")
        candidate_revision = raw_revision
    payload = json.dumps(snapshot, separators=(",", ":"))

    with _LOAD_SNAPSHOT_WRITE_LOCK:
        lock_fd = _open_load_snapshot_fence(target)
        fd = -1
        tmp: Path | None = None
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if write_if_newer:
                published = 0
                if target.exists():
                    try:
                        published = _published_revision(json.loads(target.read_text(encoding="utf-8")))
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise RuntimeError("unreadable published load snapshot") from exc
                if candidate_revision is not None and candidate_revision <= published:
                    return
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
    now: datetime | None = None,
    stop_requested: bool | None = None,
    max_lease_reached: bool | None = None,
) -> None:
    """Best-effort load write on a dedicated RLS-bypassed session (GPUW-1).

    Shared by the single-image router, the bulk-run router and the bulk worker
    so there is exactly one writer implementation; a second copy would drift and
    the reaper would silently read a stale file [rg-008].

    Request/worker callers retain best-effort behavior by default: a failed
    snapshot must not fail the describe operation that triggered it. The
    periodic refresher opts into ``raise_on_error`` so its cycle-level warning
    and timeout supervision can observe failures instead of silently treating
    them as successful refreshes. The demand transaction commits before the
    write-if-newer publication.
    """
    from db.tenant_context import enable_rls_bypass

    if session_factory is None:
        if raise_on_error:
            raise RuntimeError("describe load snapshot session factory is unavailable")
        return
    target = path or resolve_load_path()
    observed_at = as_utc(now or datetime.now(UTC))
    try:
        async with session_factory() as session:
            await enable_rls_bypass(session)
            snap = await load_snapshot(
                session,
                now=observed_at,
                stop_requested=stop_requested,
                max_lease_reached=max_lease_reached,
            )
            await session.commit()
        write_load_snapshot(snap, target)
    except Exception:  # noqa: BLE001 - reaper snapshot is best-effort
        if raise_on_error:
            raise
        _logger.warning("describe load snapshot write failed path=%s", target, exc_info=True)


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
    Fail-closed bound checks run before the first publication.
    """
    validate_demand_lease_bounds()
    await dump_load_snapshot(session_factory, path, raise_on_error=True)
