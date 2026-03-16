#!/usr/bin/env python3
"""Orchestrator daemon: dispatch open issues, intake merge-ready lanes, refresh dependents.

Usage:
    python3 scripts/mcp/orchestrator_daemon.py \
        --orchestrator-root . --task-ref <task> \
        [--single-pass] [--poll-interval 60] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _env import pythonpath_env

# ---------------------------------------------------------------------------
# JSONL logger
# ---------------------------------------------------------------------------


def _log(log_dir: Path, level: str, event: str, **extra: Any) -> None:
    """Append one JSONL record to ``<log_dir>/orchestrator.jsonl``."""
    log_dir.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "level": level,
        "event": event,
        **extra,
    }
    path = log_dir / "orchestrator.jsonl"
    with path.open("a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    print(f"[{level}] {event}", flush=True)


# ---------------------------------------------------------------------------
# Exclusive orchestrator lock
# ---------------------------------------------------------------------------


class OrchestratorLock:
    """flock-based exclusive lock so only one orchestrator daemon runs at a time."""

    def __init__(self, state_dir: Path) -> None:
        self._lock_path = state_dir / "orchestrator.lock"
        self._fh: Any = None

    def acquire(self) -> bool:
        """Try to acquire the lock.  Returns True on success."""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._lock_path.open("w")
        try:
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fh.write(json.dumps({"pid": os.getpid()}))
            self._fh.flush()
            return True
        except OSError:
            self._fh.close()
            self._fh = None
            return False

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()
        except Exception:
            pass
        self._fh = None


# ---------------------------------------------------------------------------
# Pause/resume surface
# ---------------------------------------------------------------------------


def _pause_path(state_dir: Path) -> Path:
    return state_dir / "daemon-paused"


def _is_paused(state_dir: Path) -> bool:
    return _pause_path(state_dir).exists()


def daemon_pause(state_dir: Path) -> None:
    """Create the pause sentinel."""
    state_dir.mkdir(parents=True, exist_ok=True)
    _pause_path(state_dir).write_text(
        json.dumps({"paused_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    )


def daemon_resume(state_dir: Path) -> None:
    """Remove the pause sentinel."""
    p = _pause_path(state_dir)
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_load(payload: str) -> dict[str, Any]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError("Expected JSON object payload from handoff tool.")
    return data


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _combined_text(*parts: Any) -> str:
    return " ".join(_normalize_text(part) for part in parts if _normalize_text(part)).lower()


def _json_list_text(raw_value: Any) -> str:
    if isinstance(raw_value, list):
        return " ".join(str(item) for item in raw_value)
    if not isinstance(raw_value, str) or not raw_value.strip():
        return ""
    try:
        data = json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value
    if isinstance(data, list):
        return " ".join(str(item) for item in data)
    return raw_value


def _message_timestamp(message: dict[str, Any]) -> str:
    return str(message.get("updated_at") or message.get("created_at") or "")


def _report_timestamp(report: dict[str, Any]) -> str:
    return str(report.get("created_at") or "")


_RESOLVED_MARKERS = (
    "already resolved",
    "already covered",
    "already present",
    "already correct",
    "already appears",
    "already wired",
    "no code changes were warranted",
    "no lane-owned code changes were warranted",
    "no stale fallback wiring was found",
    "appears already resolved",
    "work appears present already",
    "existing coverage",
    "substantially covered",
)

_REMAINING_WORK_MARKERS = (
    "remaining backend-domain implementation target",
    "highest-priority open lane-owned gap",
    "open backend-domain work still appears",
    "remaining open frontend slice",
    "remaining slice",
    "next slice",
    "still appears to be",
)

_ENV_BLOCKER_MARKERS = (
    "read-only",
    "sandbox",
    "writable temp directory",
    "no usable temporary directory",
    "mypy is not available",
    "mypy was unavailable",
    "postgresql is not running",
    "permissionerror",
    "vendor is a symlink",
    "duplicate altcontext",
)

GUIDANCE_STALL_THRESHOLD = 3


class GuidanceResolution:
    def __init__(
        self,
        *,
        kind: str,
        lane_id: str,
        worker_message_id: int,
        latest_report_id: int | None = None,
        decision: str = "",
        rationale: str | None = None,
        lane_status: str = "review",
        lane_notes: str | None = None,
        dispatch_subject: str | None = None,
        dispatch_message: str | None = None,
        close_dispatch_ids: tuple[int, ...] = (),
        error: str | None = None,
    ) -> None:
        self.kind = kind
        self.lane_id = lane_id
        self.worker_message_id = worker_message_id
        self.latest_report_id = latest_report_id
        self.decision = decision
        self.rationale = rationale
        self.lane_status = lane_status
        self.lane_notes = lane_notes
        self.dispatch_subject = dispatch_subject
        self.dispatch_message = dispatch_message
        self.close_dispatch_ids = close_dispatch_ids
        self.error = error


def _list_open_worker_guidance(task_ref: str) -> list[dict[str, Any]]:
    from agent_handoff_mcp import list_lane_messages

    payload = _json_load(list_lane_messages(task_ref=task_ref, status="open", limit=200))
    if payload.get("ok") is not True:
        raise RuntimeError("Failed to list lane messages.")
    rows = payload.get("messages", [])
    if not isinstance(rows, list):
        return []
    return [
        row for row in rows
        if isinstance(row, dict) and row.get("direction") == "worker_to_orchestrator"
    ]


def _list_open_dispatch_messages(task_ref: str, lane_id: str) -> list[dict[str, Any]]:
    from agent_handoff_mcp import list_lane_messages

    payload = _json_load(list_lane_messages(task_ref=task_ref, lane_id=lane_id, status="open", limit=200))
    if payload.get("ok") is not True:
        raise RuntimeError(f"Failed to list lane messages for {lane_id}.")
    rows = payload.get("messages", [])
    if not isinstance(rows, list):
        return []
    return [
        row for row in rows
        if isinstance(row, dict) and row.get("direction") == "orchestrator_to_worker"
    ]


def _latest_lane_report(task_ref: str, lane_id: str, *, session: str | None = None) -> dict[str, Any] | None:
    from agent_handoff_mcp import list_worker_reports

    payload = _json_load(list_worker_reports(task_ref=task_ref, lane_id=lane_id, limit=20))
    if payload.get("ok") is not True:
        raise RuntimeError(f"Failed to list worker reports for {lane_id}.")
    reports = payload.get("reports", [])
    if not isinstance(reports, list):
        return None
    if session:
        for report in reports:
            if isinstance(report, dict) and report.get("session") == session:
                return report
    for report in reports:
        if isinstance(report, dict):
            return report
    return None


def _lane_row(task_ref: str, lane_id: str) -> dict[str, Any]:
    from agent_handoff_mcp import list_worktree_lanes

    payload = _json_load(list_worktree_lanes(task_ref=task_ref, status="all", limit=200))
    if payload.get("ok") is not True:
        raise RuntimeError(f"Failed to list lanes for {task_ref}.")
    for lane in payload.get("lanes", []):
        if isinstance(lane, dict) and lane.get("lane_id") == lane_id:
            return lane
    raise RuntimeError(f"Lane {lane_id} not found for task {task_ref}.")


def _lane_activity(task_ref: str, lane_id: str) -> dict[str, Any]:
    from agent_handoff_mcp import get_lane_activity

    payload = _json_load(get_lane_activity(lane_id=lane_id, task_ref=task_ref, limit_actions=50))
    if payload.get("ok") is not True:
        raise RuntimeError(f"Failed to fetch lane activity for {lane_id}.")
    return payload


def _pending_lane_actions(activity: dict[str, Any]) -> list[dict[str, Any]]:
    rows = activity.get("actions", [])
    if not isinstance(rows, list):
        return []
    pending = [
        row for row in rows
        if isinstance(row, dict) and row.get("status") == "pending"
    ]
    return sorted(pending, key=lambda row: (int(row.get("priority", 100)), int(row.get("id", 0))))


def _resolve_next_assignment(task_ref: str, lane_id: str, activity: dict[str, Any], text: str) -> tuple[str, str] | None:
    pending_actions = _pending_lane_actions(activity)
    if pending_actions:
        action = pending_actions[0]
        return (
            f"{lane_id} next assignment",
            _normalize_text(action.get("action")),
        )

    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from orchestrator_guidance_policy import resolve_assignment as resolve_policy_assignment

    policy_assignment = resolve_policy_assignment(task_ref, lane_id, text, activity)
    if policy_assignment is not None:
        return policy_assignment

    lane = activity.get("lane", {})
    if any(marker in text for marker in _REMAINING_WORK_MARKERS):
        objective = _normalize_text(lane.get("objective"))
        if objective:
            return (f"{lane_id} next assignment", objective)
    return None


def _classify_guidance(
    *,
    task_ref: str,
    worker_message: dict[str, Any],
    latest_report: dict[str, Any] | None,
    activity: dict[str, Any],
    open_dispatches: list[dict[str, Any]],
) -> GuidanceResolution:
    lane_id = _normalize_text(worker_message.get("lane_id"))
    worker_message_id = int(worker_message.get("id"))
    latest_report_id = int(latest_report["id"]) if isinstance(latest_report, dict) and latest_report.get("id") is not None else None
    combined = _combined_text(
        worker_message.get("subject"),
        worker_message.get("message"),
        latest_report.get("summary") if isinstance(latest_report, dict) else "",
        _json_list_text(latest_report.get("blockers_json")) if isinstance(latest_report, dict) else "",
    )
    close_dispatch_ids = tuple(
        int(row["id"])
        for row in open_dispatches
        if isinstance(row, dict) and row.get("id") is not None
    )

    pending_actions = _pending_lane_actions(activity)
    has_resolved_marker = any(marker in combined for marker in _RESOLVED_MARKERS)
    has_env_blocker = any(marker in combined for marker in _ENV_BLOCKER_MARKERS)

    if has_resolved_marker and not pending_actions:
        return GuidanceResolution(
            kind="review",
            lane_id=lane_id,
            worker_message_id=worker_message_id,
            latest_report_id=latest_report_id,
            decision=f"Resolved worker guidance for {lane_id} by closing stale work and marking the lane ready for review.",
            rationale="Worker report indicates the assigned lane slice is already satisfied in the current branch state.",
            lane_status="review",
            lane_notes="Orchestrator confirmed the worker guidance reflected already-satisfied lane work.",
            close_dispatch_ids=close_dispatch_ids,
        )

    next_assignment = _resolve_next_assignment(task_ref, lane_id, activity, combined)

    if next_assignment is not None:
        subject, message = next_assignment
        return GuidanceResolution(
            kind="redispatch",
            lane_id=lane_id,
            worker_message_id=worker_message_id,
            latest_report_id=latest_report_id,
            decision=f"Resolved worker guidance for {lane_id} by dispatching the next lane assignment.",
            rationale="Worker reported the prior slice as satisfied or blocked and identified a concrete remaining lane-owned target.",
            lane_status="active",
            lane_notes="Orchestrator resolved worker guidance and dispatched the next lane-owned slice.",
            dispatch_subject=subject,
            dispatch_message=message,
            close_dispatch_ids=close_dispatch_ids,
        )

    if has_env_blocker:
        return GuidanceResolution(
            kind="blocked",
            lane_id=lane_id,
            worker_message_id=worker_message_id,
            latest_report_id=latest_report_id,
            decision=f"Resolved worker guidance for {lane_id} by marking the lane blocked for operator/environment follow-up.",
            rationale="Worker report indicates an environment or sandbox blocker without a safe automatic redispatch target.",
            lane_status="blocked",
            lane_notes="Worker needs a writable or better-provisioned environment before the next lane step can continue.",
            close_dispatch_ids=close_dispatch_ids,
        )

    return GuidanceResolution(
        kind="fatal_error",
        lane_id=lane_id,
        worker_message_id=worker_message_id,
        latest_report_id=latest_report_id,
        error=f"Unable to classify worker guidance for lane {lane_id}.",
        decision=f"Failed to resolve worker guidance for {lane_id}.",
        rationale="Guidance message did not match a known resolved, redispatchable, or environment-blocked pattern.",
        close_dispatch_ids=close_dispatch_ids,
    )


def _apply_guidance_resolution(
    *,
    task_ref: str,
    orchestrator_root: Path,
    resolution: GuidanceResolution,
    dry_run: bool = False,
) -> GuidanceResolution:
    from agent_handoff_mcp import (
        get_lane_activity,
        record_decision,
        record_lane_message,
        update_lane_message,
        update_next_actions,
        upsert_worktree_lane,
    )

    lane = _lane_row(task_ref, resolution.lane_id)
    if dry_run:
        return resolution

    update_lane_message(resolution.worker_message_id, "closed")
    for message_id in resolution.close_dispatch_ids:
        update_lane_message(message_id, "closed")

    upsert_worktree_lane(
        lane_id=resolution.lane_id,
        worktree_path=str(lane.get("worktree_path") or ""),
        branch=str(lane.get("branch") or ""),
        title=_normalize_text(lane.get("title")) or None,
        objective=_normalize_text(lane.get("objective")) or None,
        owner_agent=_normalize_text(lane.get("owner_agent")) or "codex",
        status=resolution.lane_status,
        notes=resolution.lane_notes,
    )

    if resolution.kind == "redispatch" and resolution.dispatch_message:
        record_lane_message(
            lane_id=resolution.lane_id,
            session=f"{task_ref}-orchestrator-guidance",
            direction="orchestrator_to_worker",
            subject=resolution.dispatch_subject,
            message=resolution.dispatch_message,
            status="open",
        )
    elif resolution.kind == "review":
        activity = _json_load(get_lane_activity(lane_id=resolution.lane_id, task_ref=task_ref, limit_actions=50))
        for action in _pending_lane_actions(activity):
            action_id = action.get("id")
            if action_id is None:
                continue
            update_next_actions(operation="complete", action_id=int(action_id))

    record_decision(
        session=f"{task_ref}-orchestrator-daemon",
        decision=resolution.decision,
        rationale=resolution.rationale,
    )
    return resolution


def _resolve_guidance_cycle(
    orchestrator_root: Path,
    task_ref: str,
    *,
    dry_run: bool = False,
    log: Any | None = None,
) -> list[GuidanceResolution]:
    from agent_handoff_mcp import record_decision

    results: list[GuidanceResolution] = []
    for worker_message in _list_open_worker_guidance(task_ref):
        lane_id = _normalize_text(worker_message.get("lane_id"))
        if not lane_id:
            continue
        if callable(log):
            log(
                "INFO",
                "guidance_detected",
                lane=lane_id,
                worker_message_id=int(worker_message.get("id") or 0),
            )
        latest_report = _latest_lane_report(
            task_ref,
            lane_id,
            session=_normalize_text(worker_message.get("session")) or None,
        )
        activity = _lane_activity(task_ref, lane_id)
        open_dispatches = _list_open_dispatch_messages(task_ref, lane_id)
        resolution = _classify_guidance(
            task_ref=task_ref,
            worker_message=worker_message,
            latest_report=latest_report,
            activity=activity,
            open_dispatches=open_dispatches,
        )
        if resolution.kind == "fatal_error":
            if not dry_run:
                record_decision(
                    session=f"{task_ref}-orchestrator-daemon",
                    decision=resolution.decision,
                    rationale=resolution.rationale,
                )
            results.append(resolution)
            continue
        results.append(
            _apply_guidance_resolution(
                task_ref=task_ref,
                orchestrator_root=orchestrator_root,
                resolution=resolution,
                dry_run=dry_run,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Phase 2: Dispatch, poll, intake
# ---------------------------------------------------------------------------


def _run_handoff_dispatch(
    orchestrator_root: Path, task_ref: str, *, dry_run: bool = False,
) -> dict[str, Any]:
    """Run ``review_dispatch.py`` and return its JSON output."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "review_dispatch.py"),
        "--orchestrator-root", str(orchestrator_root),
        "--task-ref", task_ref,
    ]
    if dry_run:
        cmd.append("--dry-run")
    env = pythonpath_env(orchestrator_root)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"review_dispatch.py failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return _json_load(result.stdout)


def _lane_has_unmerged_commits(
    orchestrator_root: Path, task_ref: str, lane_id: str,
) -> bool:
    """Return True if the lane branch has commits not yet on the current branch."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from lane_manifest import get_lane_config

    config = get_lane_config(task_ref, lane_id, orchestrator_root=str(orchestrator_root))
    if not config or not config.get("branch"):
        return False
    branch = config["branch"]
    result = subprocess.run(
        ["git", "log", "--oneline", f"HEAD..{branch}"],
        cwd=orchestrator_root, capture_output=True, text=True, check=False,
    )
    return bool(result.returncode == 0 and result.stdout.strip())


def _poll_merge_ready_lanes(
    orchestrator_root: Path, task_ref: str, lane_ids: list[str],
) -> list[str]:
    """Return lane IDs that have a merge-ready worker report and unmerged commits."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    from agent_handoff_mcp import list_worker_reports

    ready: list[str] = []
    for lane_id in lane_ids:
        payload = _json_load(
            list_worker_reports(task_ref=task_ref, lane_id=lane_id, limit=1)
        )
        if payload.get("ok") is not True:
            continue
        reports = payload.get("reports", [])
        if reports and isinstance(reports[0], dict) and reports[0].get("merge_ready"):
            if _lane_has_unmerged_commits(orchestrator_root, task_ref, lane_id):
                ready.append(lane_id)
    return ready


def _sort_by_manifest_merge_order(ready: list[str], manifest_order: list[str]) -> list[str]:
    """Sort *ready* lanes by the manifest merge order, unknown lanes last."""
    order_map = {lane: i for i, lane in enumerate(manifest_order)}
    return sorted(ready, key=lambda lane: order_map.get(lane, len(manifest_order)))


def _intake_lane(
    orchestrator_root: Path, task_ref: str, lane_id: str, *, dry_run: bool = False,
) -> bool:
    """Run ``make lane-intake`` for a single lane.  Returns True on success."""
    cmd = [
        "make", "lane-intake",
        f"TASK={task_ref}",
        f"LANE={lane_id}",
    ]
    if dry_run:
        cmd.append("DRY_RUN=1")
    result = subprocess.run(
        cmd, cwd=orchestrator_root, capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Phase 3: Downstream refresh and cross-lane verification
# ---------------------------------------------------------------------------


def _refresh_downstream(
    orchestrator_root: Path, task_ref: str, lane_id: str, downstream: list[str],
    *, dry_run: bool = False,
) -> list[tuple[str, bool]]:
    """Refresh each downstream lane.  Returns list of (lane, success) pairs."""
    results: list[tuple[str, bool]] = []
    for dep in downstream:
        cmd = [
            "make", "lane-refresh",
            f"TASK={task_ref}",
            f"LANE={dep}",
        ]
        if dry_run:
            cmd.append("DRY_RUN=1")
        r = subprocess.run(
            cmd, cwd=orchestrator_root, capture_output=True, text=True, check=False,
        )
        results.append((dep, r.returncode == 0))
    return results


def _resolve_lane_worktree(orchestrator_root: Path, task_ref: str, lane_id: str) -> Path | None:
    """Resolve the worktree path for a lane from the manifest."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from lane_manifest import get_lane_config

    config = get_lane_config(task_ref, lane_id, orchestrator_root=str(orchestrator_root))
    if config and config.get("worktree_path"):
        return Path(config["worktree_path"])
    return None


def _run_cross_lane_verify(
    orchestrator_root: Path, task_ref: str, lane_id: str, *, dry_run: bool = False,
) -> bool:
    """Run ``make lane-check`` from the lane worktree for the intaken lane."""
    if dry_run:
        return True
    lane_worktree = _resolve_lane_worktree(orchestrator_root, task_ref, lane_id)
    if lane_worktree is None or not lane_worktree.is_dir():
        return False
    cmd = [
        "make", "lane-check",
        f"TASK={task_ref}",
        f"LANE={lane_id}",
    ]
    result = subprocess.run(
        cmd, cwd=lane_worktree, capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Status query
# ---------------------------------------------------------------------------


def daemon_status(state_dir: Path, log_dir: Path) -> dict[str, Any]:
    """Return a status dict for the daemon-status target."""
    lock_path = state_dir / "orchestrator.lock"
    lock_info: dict[str, Any] = {"held": False}
    if lock_path.exists():
        try:
            lock_info = {**json.loads(lock_path.read_text()), "held": True}
        except (json.JSONDecodeError, OSError):
            lock_info = {"held": True, "pid": "unknown"}

    paused = _is_paused(state_dir)

    log_path = log_dir / "orchestrator.jsonl"
    last_cycle: dict[str, Any] | None = None
    last_verify: dict[str, Any] | None = None
    if log_path.exists():
        for line in reversed(log_path.read_text().splitlines()):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if last_cycle is None and entry.get("event") == "cycle_end":
                last_cycle = entry
            if last_verify is None and entry.get("event") == "verify_complete":
                last_verify = entry
            if last_cycle and last_verify:
                break

    return {
        "lock": lock_info,
        "paused": paused,
        "last_cycle": last_cycle,
        "last_verify": last_verify,
    }


# ---------------------------------------------------------------------------
# Main orchestrator loop
# ---------------------------------------------------------------------------


def orchestrator_loop(
    *,
    orchestrator_root: Path,
    task_ref: str,
    poll_interval: int = 60,
    single_pass: bool = False,
    dry_run: bool = False,
) -> int:
    """Main daemon loop.  Returns 0 on clean exit, 1 on failure."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    from agent_handoff_mcp import (
        RuntimeConfig,
        configure_runtime,
        handoff_close_check,
        record_decision,
        record_test_result,
    )
    from lane_manifest import downstream_lanes, merge_order as manifest_merge_order

    state_dir = orchestrator_root / ".task-state"
    log_dir = orchestrator_root / "logs" / "daemon"
    log = lambda level, event, **kw: _log(log_dir, level, event, **kw)

    # Configure MCP runtime
    runtime = RuntimeConfig.for_workspace(
        orchestrator_root,
        state_dir=state_dir,
        current_task_path=orchestrator_root / "CURRENT_TASK.md",
        exports_dir=state_dir / "exports",
    )
    configure_runtime(runtime)

    log("INFO", "daemon_start", task_ref=task_ref, single_pass=single_pass)

    m_order = manifest_merge_order(task_ref)
    log("INFO", "manifest_loaded", merge_order=m_order)
    dispatch_failure_count = 0
    runtime_failure_count = 0
    guidance_stalls: dict[str, tuple[int, int]] = {}

    while True:
        if _is_paused(state_dir):
            log("INFO", "daemon_paused")
            if single_pass:
                return 0
            time.sleep(poll_interval)
            continue

        log("INFO", "cycle_start")

        # Step 1: Dispatch open issues to lanes
        try:
            dispatch_result = _run_handoff_dispatch(
                orchestrator_root, task_ref, dry_run=dry_run,
            )
            dispatch_failure_count = 0
            log("INFO", "dispatch_complete", result=dispatch_result)
        except RuntimeError as exc:
            dispatch_failure_count += 1
            log("ERROR", "dispatch_failed", error=str(exc))
            if single_pass or dispatch_failure_count >= 3:
                return 1

        try:
            # Step 2: Resolve worker guidance handoffs
            guidance_results = _resolve_guidance_cycle(
                orchestrator_root,
                task_ref,
                dry_run=dry_run,
                log=log,
            )
            for resolution in guidance_results:
                if resolution.kind == "fatal_error":
                    previous = guidance_stalls.get(resolution.lane_id)
                    if previous and previous[0] == resolution.worker_message_id:
                        guidance_stalls[resolution.lane_id] = (resolution.worker_message_id, previous[1] + 1)
                    else:
                        guidance_stalls[resolution.lane_id] = (resolution.worker_message_id, 1)
                    stall_count = guidance_stalls[resolution.lane_id][1]
                    log(
                        "ERROR",
                        "guidance_failed",
                        lane=resolution.lane_id,
                        error=resolution.error,
                        stall_count=stall_count,
                    )
                    if single_pass or stall_count >= GUIDANCE_STALL_THRESHOLD:
                        log("ERROR", "terminal_error", lane=resolution.lane_id, reason="guidance_stall")
                        return 1
                    continue
                guidance_stalls.pop(resolution.lane_id, None)
                event_name = "guidance_resolved"
                if resolution.kind == "redispatch":
                    event_name = "guidance_redispatched"
                elif resolution.kind == "blocked":
                    event_name = "guidance_escalated"
                log("INFO", event_name, lane=resolution.lane_id, kind=resolution.kind, latest_report_id=resolution.latest_report_id)

            # Step 3: Poll for merge-ready lanes
            ready_lanes = _poll_merge_ready_lanes(orchestrator_root, task_ref, m_order)
            ordered_ready = _sort_by_manifest_merge_order(ready_lanes, m_order)
            log("INFO", "poll_complete", ready_lanes=ordered_ready)

            # Step 4: Intake and refresh
            for lane_id in ordered_ready:
                log("INFO", "intake_start", lane=lane_id)
                intake_ok = _intake_lane(
                    orchestrator_root, task_ref, lane_id, dry_run=dry_run,
                )
                decision_text = (
                    f"Orchestrator daemon intaked lane {lane_id} successfully."
                    if intake_ok
                    else f"Orchestrator daemon failed to intake lane {lane_id}."
                )
                if not dry_run:
                    record_decision(
                        session=f"{task_ref}-orchestrator-daemon",
                        decision=decision_text,
                        rationale=f"Automated intake cycle for merge-ready lane {lane_id}.",
                    )
                log("INFO", "intake_complete", lane=lane_id, success=intake_ok)

                if not intake_ok:
                    continue

                deps = downstream_lanes(task_ref, lane_id)
                if deps:
                    log("INFO", "refresh_start", lane=lane_id, downstream=deps)
                    refresh_results = _refresh_downstream(
                        orchestrator_root, task_ref, lane_id, deps, dry_run=dry_run,
                    )
                    log("INFO", "refresh_complete", lane=lane_id, results=refresh_results)

                log("INFO", "verify_start", lane=lane_id)
                verify_ok = _run_cross_lane_verify(
                    orchestrator_root, task_ref, lane_id, dry_run=dry_run,
                )
                if not dry_run:
                    record_test_result(
                        session=f"{task_ref}-orchestrator-daemon",
                        command=f"make lane-check TASK={task_ref} LANE={lane_id}",
                        passed=verify_ok,
                        result="Cross-lane verification passed." if verify_ok else "Cross-lane verification failed.",
                    )
                log("INFO", "verify_complete", lane=lane_id, passed=verify_ok)

            close_check = _json_load(handoff_close_check(task_ref=task_ref))
            ready_to_close = bool(close_check.get("ready_to_close"))
            runtime_failure_count = 0
            log("INFO", "close_check_complete", ready_to_close=ready_to_close)
            log("INFO", "cycle_end", intaked=ordered_ready, guidance=len(guidance_results))
        except RuntimeError as exc:
            runtime_failure_count += 1
            log("ERROR", "runtime_phase_failed", error=str(exc), failure_count=runtime_failure_count)
            if single_pass or runtime_failure_count >= 3:
                log("ERROR", "terminal_error", reason="runtime_failure")
                return 1
            log("INFO", "poll_sleep", interval=poll_interval)
            time.sleep(poll_interval)
            continue

        if ready_to_close:
            log("INFO", "task_complete", task_ref=task_ref)
            return 0

        if single_pass:
            return 0

        log("INFO", "poll_sleep", interval=poll_interval)
        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Orchestrator daemon: dispatch, intake, refresh, verify."
    )
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="Run the orchestrator loop.")
    run_parser.add_argument("--orchestrator-root", required=True,
                            help="Absolute path to the monorepo root.")
    run_parser.add_argument("--task-ref", required=True,
                            help="MCP task reference.")
    run_parser.add_argument("--poll-interval", type=int, default=60,
                            help="Seconds between poll cycles (default: 60).")
    run_parser.add_argument("--single-pass", action="store_true",
                            help="Run one cycle and exit.")
    run_parser.add_argument("--dry-run", action="store_true",
                            help="Skip mutating operations.")

    pause_parser = sub.add_parser("pause", help="Pause the daemon.")
    pause_parser.add_argument("--state-dir", required=True)

    resume_parser = sub.add_parser("resume", help="Resume the daemon.")
    resume_parser.add_argument("--state-dir", required=True)

    status_parser = sub.add_parser("status", help="Show daemon status.")
    status_parser.add_argument("--state-dir", required=True)
    status_parser.add_argument("--log-dir", default=None,
                               help="Log directory. Defaults to <state-dir>/../logs/daemon.")

    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.command == "pause":
        state_dir = Path(args.state_dir).expanduser().resolve()
        daemon_pause(state_dir)
        print("Daemon paused.")
        return 0

    if args.command == "resume":
        state_dir = Path(args.state_dir).expanduser().resolve()
        daemon_resume(state_dir)
        print("Daemon resumed.")
        return 0

    if args.command == "status":
        state_dir = Path(args.state_dir).expanduser().resolve()
        log_dir = (
            Path(args.log_dir).expanduser().resolve()
            if args.log_dir
            else state_dir.parent / "logs" / "daemon"
        )
        status = daemon_status(state_dir, log_dir)
        print(json.dumps(status, indent=2, default=str))
        return 0

    if args.command == "run":
        orchestrator_root = Path(args.orchestrator_root).expanduser().resolve()
        state_dir = orchestrator_root / ".task-state"

        # Ensure SCRIPT_DIR is on sys.path
        if str(SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR))

        lock = OrchestratorLock(state_dir)
        if not lock.acquire():
            print("Another orchestrator daemon is already running.", file=sys.stderr)
            return 1

        try:
            return orchestrator_loop(
                orchestrator_root=orchestrator_root,
                task_ref=args.task_ref,
                poll_interval=args.poll_interval,
                single_pass=args.single_pass,
                dry_run=args.dry_run,
            )
        finally:
            lock.release()

    # No subcommand -- print help
    _parse_args()
    return 1


if __name__ == "__main__":
    sys.exit(main())
