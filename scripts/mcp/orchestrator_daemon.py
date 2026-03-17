#!/usr/bin/env python3
"""Orchestrator daemon: dispatch open issues, intake merge-ready lanes, refresh dependents.

Usage:
    python3 scripts/mcp/orchestrator_daemon.py \
        --orchestrator-root . --task-ref <task> \
        [--single-pass] [--poll-interval 60] [--dry-run]
"""
from __future__ import annotations

import argparse
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

# ---------------------------------------------------------------------------
# Re-export submodule symbols for backward compatibility (tests load this
# module via importlib and access everything through ``mod.X``).
# ---------------------------------------------------------------------------
from orchestrator_helpers import (  # noqa: F401
    _combined_text,
    _json_list_text,
    _json_load,
    _log,
    _message_timestamp,
    _normalize_text,
    _report_timestamp,
)
from orchestrator_guidance import (  # noqa: F401
    GUIDANCE_STALL_THRESHOLD,
    GuidanceResolution,
    _apply_guidance_resolution,
    _classify_guidance,
    _dedupe_worker_guidance_messages,
    _lane_activity,
    _lane_row,
    _latest_lane_report,
    _list_open_dispatch_messages,
    _list_open_worker_guidance,
    _pending_lane_actions,
    _resolve_guidance_cycle,
    _resolve_next_assignment,
)
from orchestrator_guidance import (
    _ENV_BLOCKER_MARKERS,
    _REMAINING_WORK_MARKERS,
    _RESOLVED_MARKERS,
)
from orchestrator_lanes import (  # noqa: F401
    _complete_lane_plan_cursor,
    _intake_lane,
    _lane_has_capacity,
    _lane_has_unmerged_commits,
    _refresh_downstream,
    _resolve_lane_worktree,
    _run_handoff_dispatch,
    _sort_by_manifest_merge_order,
)


# ---------------------------------------------------------------------------
# Orchestration-level lane queries (stay here so tests can patch siblings)
# ---------------------------------------------------------------------------


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


def _has_open_plan_action(task_ref: str, plan_item_id: str) -> bool:
    from agent_handoff_mcp import list_next_actions

    marker = f"[plan:{plan_item_id}]"
    payload = _json_load(list_next_actions(task_ref=task_ref, status="pending", limit=200))
    if payload.get("ok") is not True:
        raise RuntimeError(f"Failed to list next actions for {task_ref}.")
    for row in payload.get("actions", []):
        if isinstance(row, dict) and marker in str(row.get("action") or ""):
            return True
    return False


def _has_open_plan_message(task_ref: str, plan_item_id: str) -> bool:
    from agent_handoff_mcp import list_lane_messages

    marker = f"[plan:{plan_item_id}]"
    payload = _json_load(list_lane_messages(task_ref=task_ref, status="open", limit=200))
    if payload.get("ok") is not True:
        raise RuntimeError(f"Failed to list lane messages for {task_ref}.")
    for row in payload.get("messages", []):
        if not isinstance(row, dict):
            continue
        haystack = f"{row.get('subject') or ''} {row.get('message') or ''}"
        if marker in haystack:
            return True
    return False


def _escalate_plan_item(
    task_ref: str,
    *,
    plan_item_id: str,
    summary: str,
    heading: str,
    dry_run: bool = False,
    log: Any | None = None,
) -> None:
    from agent_handoff_mcp import record_decision, upsert_plan_cursor

    if dry_run:
        return
    _json_load(
        upsert_plan_cursor(
            task_ref=task_ref,
            plan_item_id=plan_item_id,
            state="escalated",
            summary=summary,
            source_heading=heading or None,
        )
    )
    record_decision(
        session=f"{task_ref}-orchestrator-daemon",
        decision=f"Escalated plan item {plan_item_id} for human review.",
        rationale="Task plan item could not be mapped to a single lane from explicit annotations or manifest routing metadata.",
    )
    if callable(log):
        log("WARN", "task_plan_item_escalated", plan_item_id=plan_item_id, heading=heading)


def _dispatch_plan_item(
    task_ref: str,
    *,
    lane_id: str,
    plan_item_id: str,
    summary: str,
    heading: str,
    resolved_plan: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    from agent_handoff_mcp import record_decision, record_lane_message, update_next_actions, upsert_plan_cursor

    marker = f"[plan:{plan_item_id}]"
    result = {
        "plan_item_id": plan_item_id,
        "lane_id": lane_id,
        "lane": lane_id,
        "summary": summary,
        "heading": heading,
    }
    if dry_run:
        return result

    action_payload = _json_load(
        update_next_actions(
            operation="add",
            action=f"{marker} {summary}",
            priority=100,
            actor={"lane_id": lane_id},
        )
    )
    if action_payload.get("ok") is not True:
        raise RuntimeError(f"Failed to create next action for {plan_item_id}.")
    action = action_payload.get("action", {})
    action_id = int(action.get("id")) if isinstance(action, dict) and action.get("id") is not None else None

    message_payload = _json_load(
        record_lane_message(
            lane_id=lane_id,
            session=f"{task_ref}-orchestrator-plan",
            direction="orchestrator_to_worker",
            subject=f"{lane_id} plan assignment",
            message=f"{marker} {summary}",
            status="open",
        )
    )
    if message_payload.get("ok") is not True:
        raise RuntimeError(f"Failed to create lane message for {plan_item_id}.")

    cursor_update = _json_load(
        upsert_plan_cursor(
            task_ref=task_ref,
            plan_item_id=plan_item_id,
            state="dispatched",
            lane_id=lane_id,
            mcp_action_id=action_id,
            summary=summary,
            source_heading=heading or None,
        )
    )
    if cursor_update.get("ok") is not True:
        raise RuntimeError(f"Failed to persist plan cursor for {plan_item_id}.")

    record_decision(
        session=f"{task_ref}-orchestrator-daemon",
        decision=f"Dispatched plan item {plan_item_id} to {lane_id}.",
        rationale=f"Selected the next unchecked task-plan item from {resolved_plan.name} and routed it via manifest-owned lane metadata.",
    )
    return result


def _dispatch_from_task_plan(
    orchestrator_root: Path,
    task_ref: str,
    *,
    dry_run: bool = False,
    log: Any | None = None,
) -> dict[str, Any] | None:
    from agent_handoff_mcp import get_plan_cursor
    from lane_manifest import load_manifest, task_plan_path
    from task_plan_parser import map_plan_item_to_lane, normalize_plan_item, parse_task_plan

    plan_path = task_plan_path(task_ref, orchestrator_root=str(orchestrator_root))
    if not isinstance(plan_path, str) or not plan_path.strip():
        return None
    resolved_plan = Path(plan_path)
    if not resolved_plan.exists():
        raise RuntimeError(f"Task plan path does not exist for {task_ref}: {resolved_plan}")

    manifest = load_manifest(task_ref)
    if not isinstance(manifest, dict):
        return None
    items = parse_task_plan(resolved_plan)
    unchecked: list[dict[str, Any]] = []
    for item in items:
        if item.checked:
            continue
        normalized = normalize_plan_item(item)
        cursor_payload = _json_load(get_plan_cursor(task_ref=task_ref, plan_item_id=normalized.plan_item_id))
        if cursor_payload.get("ok") is not True:
            raise RuntimeError(f"Failed to read plan cursor for {normalized.plan_item_id}.")
        cursor = cursor_payload.get("cursor")
        cursor_state = str(cursor.get("state") or "") if isinstance(cursor, dict) else ""
        unchecked.append(
            {
                "normalized": normalized,
                "lane_id": map_plan_item_to_lane(normalized, manifest=manifest),
                "cursor_state": cursor_state,
            }
        )

    merge_order = [lane for lane in manifest.get("merge_order", []) if isinstance(lane, str)]
    terminal_states = {"completed", "skipped", "escalated"}
    for entry in unchecked:
        normalized = entry["normalized"]
        cursor_state = entry["cursor_state"]
        if cursor_state in {"dispatched", *terminal_states}:
            continue

        lane_id = entry["lane_id"]
        if lane_id is None:
            _escalate_plan_item(
                task_ref,
                plan_item_id=normalized.plan_item_id,
                summary=normalized.summary,
                heading=normalized.heading,
                dry_run=dry_run,
                log=log,
            )
            continue

        if lane_id in merge_order:
            lane_index = merge_order.index(lane_id)
            upstream_lanes = set(merge_order[:lane_index])
            blocked_by_upstream = any(
                candidate["lane_id"] in upstream_lanes
                and candidate["cursor_state"] not in terminal_states
                for candidate in unchecked
            )
            if blocked_by_upstream:
                continue

        if _has_open_plan_action(task_ref, normalized.plan_item_id) or _has_open_plan_message(task_ref, normalized.plan_item_id):
            continue
        if not _lane_has_capacity(task_ref, lane_id):
            continue

        result = _dispatch_plan_item(
            task_ref,
            lane_id=lane_id,
            plan_item_id=normalized.plan_item_id,
            summary=normalized.summary,
            heading=normalized.heading,
            resolved_plan=resolved_plan,
            dry_run=dry_run,
        )
        result["line_start"] = normalized.line_start
        return result
    return None


def _remaining_plan_work(
    orchestrator_root: Path,
    task_ref: str,
) -> list[dict[str, Any]]:
    from agent_handoff_mcp import get_plan_cursor
    from lane_manifest import load_manifest, task_plan_path
    from task_plan_parser import map_plan_item_to_lane, normalize_plan_item, parse_task_plan

    plan_path = task_plan_path(task_ref, orchestrator_root=str(orchestrator_root))
    if not isinstance(plan_path, str) or not plan_path.strip():
        return []
    resolved_plan = Path(plan_path)
    if not resolved_plan.exists():
        raise RuntimeError(f"Task plan path does not exist for {task_ref}: {resolved_plan}")

    manifest = load_manifest(task_ref)
    if not isinstance(manifest, dict):
        return []

    remaining: list[dict[str, Any]] = []
    for item in parse_task_plan(resolved_plan):
        if item.checked:
            continue
        normalized = normalize_plan_item(item)
        cursor_payload = _json_load(get_plan_cursor(task_ref=task_ref, plan_item_id=normalized.plan_item_id))
        if cursor_payload.get("ok") is not True:
            raise RuntimeError(f"Failed to read plan cursor for {normalized.plan_item_id}.")
        cursor = cursor_payload.get("cursor")
        cursor_state = str(cursor.get("state") or "") if isinstance(cursor, dict) else ""
        if cursor_state in {"completed", "skipped", "escalated"}:
            continue
        remaining.append(
            {
                "plan_item_id": normalized.plan_item_id,
                "lane_id": map_plan_item_to_lane(normalized, manifest=manifest),
                "cursor_state": cursor_state,
            }
        )
    return remaining


def _resolve_task_ref(orchestrator_root: Path, explicit_task_ref: str | None) -> str:
    """Resolve the orchestrator task from CLI, MCP state, or a sole manifest."""
    if explicit_task_ref and explicit_task_ref.strip():
        return explicit_task_ref.strip()

    from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state
    from lane_manifest import list_task_refs

    state_dir = orchestrator_root / ".task-state"
    runtime = RuntimeConfig.for_workspace(
        orchestrator_root,
        state_dir=state_dir,
        current_task_path=orchestrator_root / "CURRENT_TASK.md",
        exports_dir=state_dir / "exports",
    )
    configure_runtime(runtime)

    payload = _json_load(get_handoff_state())
    active_task = str(payload.get("task_ref") or "").strip()
    if active_task:
        return active_task

    task_refs = list_task_refs()
    if len(task_refs) == 1:
        return task_refs[0]
    if task_refs:
        raise RuntimeError(
            "Unable to infer orchestrator task. Set --task-ref or activate a handoff task. "
            f"Available manifests: {', '.join(task_refs)}"
        )
    raise RuntimeError(
        "Unable to infer orchestrator task. Set --task-ref or add a lane manifest under config/lane-orchestration/."
    )


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
    import datetime

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
        "mode": "singleton",
        "state_dir": str(state_dir),
        "log_dir": str(log_dir),
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
    backend: str = "codex-cli",
    dry_run: bool = False,
) -> int:
    """Main daemon loop.  Returns 0 on clean exit, 1 on failure."""
    # Backend is currently surfaced for future orchestrator-invoked execution.
    # The loop itself still coordinates via MCP + Make targets only.
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

    log("INFO", "daemon_start", task_ref=task_ref, single_pass=single_pass, backend=backend)

    m_order = manifest_merge_order(task_ref)
    log("INFO", "manifest_loaded", merge_order=m_order)
    log("INFO", "lanes_discovered", lanes=m_order)
    dispatch_failure_count = 0
    runtime_failure_count = 0
    plan_stall_count = 0
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

            # Step 3: Derive new work from the task plan when backlog is otherwise empty
            plan_dispatch = _dispatch_from_task_plan(
                orchestrator_root,
                task_ref,
                dry_run=dry_run,
                log=log,
            )
            if plan_dispatch is not None:
                log("INFO", "task_plan_dispatch", **plan_dispatch)

            # Step 4: Poll for merge-ready lanes
            ready_lanes = _poll_merge_ready_lanes(orchestrator_root, task_ref, m_order)
            ordered_ready = _sort_by_manifest_merge_order(ready_lanes, m_order)
            log("INFO", "poll_complete", ready_lanes=ordered_ready)

            # Step 5: Intake and refresh
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
                if not dry_run:
                    cursor = _complete_lane_plan_cursor(task_ref, lane_id)
                    if cursor is not None:
                        log("INFO", "plan_cursor_completed", lane=lane_id, plan_item_id=cursor.get("plan_item_id"))

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
            remaining_plan_items = _remaining_plan_work(orchestrator_root, task_ref)
            active_plan_dispatches = any(
                str(row.get("cursor_state") or "") == "dispatched"
                for row in remaining_plan_items
            )
            if remaining_plan_items:
                log(
                    "INFO",
                    "task_plan_remaining",
                    remaining=len(remaining_plan_items),
                    dispatched=sum(1 for row in remaining_plan_items if str(row.get("cursor_state") or "") == "dispatched"),
                )
            plan_stalled = (
                bool(remaining_plan_items)
                and plan_dispatch is None
                and not active_plan_dispatches
                and not ordered_ready
                and not guidance_results
            )
            if plan_stalled:
                plan_stall_count += 1
                log("ERROR", "task_plan_stalled", remaining=len(remaining_plan_items), stall_count=plan_stall_count)
                if single_pass or plan_stall_count >= 3:
                    log("ERROR", "terminal_error", reason="task_plan_stall")
                    return 1
            else:
                plan_stall_count = 0
            runtime_failure_count = 0
            log("INFO", "close_check_complete", ready_to_close=ready_to_close, remaining_plan_items=len(remaining_plan_items))
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

        if ready_to_close and not remaining_plan_items:
            log("INFO", "task_complete", task_ref=task_ref)
            return 0
        if ready_to_close and remaining_plan_items:
            log("INFO", "task_close_blocked_by_plan", remaining=len(remaining_plan_items))

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
    run_parser.add_argument("--task-ref",
                            help="MCP task reference.")
    run_parser.add_argument("--poll-interval", type=int, default=60,
                            help="Seconds between poll cycles (default: 60).")
    run_parser.add_argument("--single-pass", action="store_true",
                            help="Run one cycle and exit.")
    run_parser.add_argument("--backend", default="codex-cli",
                            choices=("codex-cli", "codex-subagent"),
                            help="Execution backend to use for orchestrator-invoked operations (default: codex-cli).")
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
        try:
            task_ref = _resolve_task_ref(orchestrator_root, args.task_ref)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        lock = OrchestratorLock(state_dir)
        if not lock.acquire():
            print("Another orchestrator daemon is already running.", file=sys.stderr)
            return 1

        try:
            return orchestrator_loop(
                orchestrator_root=orchestrator_root,
                task_ref=task_ref,
                poll_interval=args.poll_interval,
                single_pass=args.single_pass,
                backend=args.backend,
                dry_run=args.dry_run,
            )
        finally:
            lock.release()

    # No subcommand -- print help
    _parse_args()
    return 1


if __name__ == "__main__":
    sys.exit(main())
