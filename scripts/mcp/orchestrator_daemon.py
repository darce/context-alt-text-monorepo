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

    from agent_handoff_mcp import RuntimeConfig, configure_runtime, record_decision, record_test_result
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
            log("INFO", "dispatch_complete", result=dispatch_result)
        except RuntimeError as exc:
            log("ERROR", "dispatch_failed", error=str(exc))

        # Step 2: Poll for merge-ready lanes
        ready_lanes = _poll_merge_ready_lanes(orchestrator_root, task_ref, m_order)
        ordered_ready = _sort_by_manifest_merge_order(ready_lanes, m_order)
        log("INFO", "poll_complete", ready_lanes=ordered_ready)

        # Step 3: Intake and refresh
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

            # Downstream refresh
            deps = downstream_lanes(task_ref, lane_id)
            if deps:
                log("INFO", "refresh_start", lane=lane_id, downstream=deps)
                refresh_results = _refresh_downstream(
                    orchestrator_root, task_ref, lane_id, deps, dry_run=dry_run,
                )
                log("INFO", "refresh_complete", lane=lane_id, results=refresh_results)

            # Cross-lane verification
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

        log("INFO", "cycle_end", intaked=ordered_ready)

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
