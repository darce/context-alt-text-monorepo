#!/usr/bin/env python3
"""Worker daemon: poll for lane work, run implementation/review/fix cycles, emit one final handoff.

Usage:
    python3 scripts/mcp/worker_daemon.py \
        --orchestrator-root . --task-ref <task> --lane-id <lane> \
        --worktree-path ../context-alt-text-monorepo-<lane> \
        [--single-pass] [--max-review-cycles 3] [--poll-interval 30] [--dry-run]
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
from backend_registry import get_backend_choices

_MAX_LOG_BYTES = 1_000_000
_STATUS_FILE_VERSION = 1
BACKEND_CHOICES = get_backend_choices()
SESSION_MODE_CHOICES = ("fresh_turn", "shared_lane")


# ---------------------------------------------------------------------------
# JSONL logger
# ---------------------------------------------------------------------------


def _log(lane_id: str, log_dir: Path, level: str, event: str, **extra: Any) -> None:
    """Append one JSONL record to ``<log_dir>/worker-<lane_id>.jsonl``."""
    log_dir.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "lane": lane_id,
        "level": level,
        "event": event,
        **extra,
    }
    path = log_dir / f"worker-{lane_id}.jsonl"
    if path.exists():
        try:
            if path.stat().st_size >= _MAX_LOG_BYTES:
                rotated = path.with_suffix(path.suffix + ".1")
                if rotated.exists():
                    rotated.unlink()
                path.replace(rotated)
        except OSError:
            pass
    with path.open("a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    # Also print for interactive visibility.
    preview_parts: list[str] = []
    for key in ("cycle", "elapsed_seconds", "finding_count", "passed", "interval", "pid"):
        if key in extra:
            preview_parts.append(f"{key}={extra[key]}")
    for key in ("result_path", "error", "stderr_tail", "stdout_tail"):
        value = extra.get(key)
        if not value:
            continue
        text = str(value).replace("\n", " ")
        if len(text) > 160:
            text = text[:157] + "..."
        preview_parts.append(f"{key}={text}")
    suffix = f" {' '.join(preview_parts)}" if preview_parts else ""
    print(f"[{level}] {event}{suffix}", flush=True)


# ---------------------------------------------------------------------------
# Exclusive per-lane lock
# ---------------------------------------------------------------------------


class WorkerLock:
    """flock-based exclusive lock so only one daemon runs per lane."""

    def __init__(self, lane_id: str, state_dir: Path) -> None:
        self._lock_path = state_dir / f"worker-{lane_id}.lock"
        self._fh: Any = None

    def acquire(self) -> bool:
        """Try to acquire the lock.  Returns True on success."""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._lock_path.open("w")
        try:
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fh.write(str(json.dumps({"pid": __import__("os").getpid()})))
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
# Actionable-work detection
# ---------------------------------------------------------------------------


_NO_WORK_EXIT = 3
_WAITING_EXIT = 4


def poll_lane_state(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
    worktree_path: Path,
) -> str:
    """Return one of ``actionable``, ``idle``, or ``waiting``.

    Exit code 3 means the lane is idle. Exit code 4 means the worker
    already handed control back to the orchestrator and should remain
    dormant until a new dispatch arrives. Any other non-zero exit
    indicates a runtime/config error and raises ``RuntimeError`` so the
    caller can surface it instead of silently sleeping.
    """
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "lane_prompt.py"),
        "--orchestrator-root", str(orchestrator_root),
        "--task-ref", task_ref,
        "--lane-id", lane_id,
        "--worktree-path", str(worktree_path),
        "--check",
    ]
    env = pythonpath_env(orchestrator_root, task_ref=task_ref, lane_id=lane_id)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if result.returncode == 0:
        return "actionable"
    if result.returncode == _NO_WORK_EXIT:
        return "idle"
    if result.returncode == _WAITING_EXIT:
        return "waiting"
    raise RuntimeError(
        f"lane_prompt.py --check failed (exit {result.returncode}):\n"
        f"{result.stderr.strip()}"
    )


def has_actionable_work(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
    worktree_path: Path,
) -> bool:
    """Backwards-compatible bool wrapper used by older callers/tests."""
    return poll_lane_state(
        orchestrator_root=orchestrator_root,
        task_ref=task_ref,
        lane_id=lane_id,
        worktree_path=worktree_path,
    ) == "actionable"


# ---------------------------------------------------------------------------
# Verification (make lane-check)
# ---------------------------------------------------------------------------


def _run_lane_check(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
    worktree_path: Path,
) -> bool:
    """Run ``make lane-check`` and return True on success."""
    cmd = [
        "make",
        "-f", str(orchestrator_root / "Makefile"),
        "-C", str(worktree_path),
        "lane-check",
        f"TASK={task_ref}",
        f"LANE={lane_id}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Final handoff (lane_result.py handoff)
# ---------------------------------------------------------------------------


def _run_final_handoff(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
    session: str,
    worktree_path: Path,
    result_path: Path,
    dry_run: bool = False,
) -> int:
    """Call ``lane_result.py handoff`` for the one final report."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "lane_result.py"),
        "handoff",
        "--orchestrator-root", str(orchestrator_root),
        "--task-ref", task_ref,
        "--lane-id", lane_id,
        "--session", session,
        "--worktree-path", str(worktree_path),
        "--result-file", str(result_path),
    ]
    if dry_run:
        cmd.append("--dry-run")
    result = subprocess.run(cmd, check=False)
    return result.returncode


def _cleanup_result_file(path: Path | None) -> None:
    """Delete a consumed lane result artifact if it still exists."""
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


# ---------------------------------------------------------------------------
# Durable worker status
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _status_path(state_dir: Path, lane_id: str) -> Path:
    return state_dir / f"worker-{lane_id}.status.json"


def _read_worker_status(state_dir: Path, lane_id: str) -> dict[str, Any] | None:
    path = _status_path(state_dir, lane_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_worker_status(
    state_dir: Path,
    lane_id: str,
    *,
    task_ref: str | None = None,
    session: str | None = None,
    state: str,
    summary: str,
    result_path: Path | None = None,
    clear_result_path: bool = False,
    failure_stage: str | None = None,
    cycle: int | None = None,
    handoff_action: str | None = None,
    attention_required: bool = False,
) -> dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    previous = _read_worker_status(state_dir, lane_id) or {}
    payload: dict[str, Any] = {
        "version": _STATUS_FILE_VERSION,
        "lane_id": lane_id,
        "task_ref": task_ref or previous.get("task_ref"),
        "session": session or previous.get("session"),
        "state": state,
        "summary": summary,
        "attention_required": attention_required,
        "updated_at": _utcnow_iso(),
        "pid": os.getpid(),
    }
    if result_path is not None:
        payload["result_path"] = str(result_path)
    elif clear_result_path:
        payload.pop("result_path", None)
    elif "result_path" in previous and state != "handoff_failed":
        payload["result_path"] = previous["result_path"]
    if failure_stage is not None:
        payload["failure_stage"] = failure_stage
    if cycle is not None:
        payload["cycle"] = cycle
    if handoff_action is not None:
        payload["handoff_action"] = handoff_action
    _status_path(state_dir, lane_id).write_text(json.dumps(payload, indent=2, sort_keys=True))
    return payload


# ---------------------------------------------------------------------------
# Result file helpers
# ---------------------------------------------------------------------------


def _load_result(path: Path) -> dict[str, Any]:
    raw = path.read_text()
    return json.loads(raw)


def _patch_result(path: Path, overrides: dict[str, Any]) -> None:
    """Merge overrides into the result file on disk."""
    data = _load_result(path)
    data.update(overrides)
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------


def worker_loop(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
    session: str,
    worktree_path: Path,
    max_review_cycles: int = 3,
    poll_interval: int = 30,
    single_pass: bool = False,
    backend: str = "codex-cli",
    session_mode: str = "fresh_turn",
    codex_bin: str | None = None,
    codex_args: list[str] | None = None,
    dry_run: bool = False,
) -> int:
    """Main daemon loop.  Returns 0 on clean handoff, 1 on failure."""
    # Lazy-import lane_exec and review_runner to keep module importable
    # without heavy deps at test time.
    from lane_exec import build_fix_prompt, find_codex, run_lane_exec
    from review_runner import run_review

    log_dir = orchestrator_root / "logs" / "worker-daemon"
    state_dir = orchestrator_root / ".task-state"
    log = lambda level, event, **kw: _log(lane_id, log_dir, level, event, **kw)
    existing_status = _read_worker_status(state_dir, lane_id) or {}

    log("INFO", "daemon_start", task_ref=task_ref, single_pass=single_pass,
        max_review_cycles=max_review_cycles, backend=backend, session_mode=session_mode)
    if existing_status.get("state") != "handoff_failed":
        _write_worker_status(
            state_dir,
            lane_id,
            task_ref=task_ref,
            session=session,
            state="starting",
            summary="Worker daemon started and is preparing its lane-scoped runtime.",
        )

    codex = None
    if backend == "codex-cli":
        codex = find_codex(codex_bin)
        log("INFO", "codex_found", codex_bin=codex)
    dormant_state: str | None = None
    handoff_failure_seen_in_process = False

    while True:
        persisted_status = _read_worker_status(state_dir, lane_id) or {}
        if persisted_status.get("state") == "handoff_failed":
            result_path_raw = str(persisted_status.get("result_path") or "").strip()
            result_path = Path(result_path_raw) if result_path_raw else None
            if result_path is not None and result_path.exists() and not handoff_failure_seen_in_process:
                log("INFO", "handoff_retry_start", result_path=str(result_path))
                retry_exit = _run_final_handoff(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    worktree_path=worktree_path,
                    result_path=result_path,
                    dry_run=dry_run,
                )
                handoff_failure_seen_in_process = True
                if retry_exit == 0:
                    _cleanup_result_file(result_path)
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="waiting_for_orchestrator",
                        summary="Worker handoff submitted successfully; waiting for orchestrator follow-up.",
                        clear_result_path=True,
                    )
                    log("INFO", "handoff_retry_complete", result_path=str(result_path))
                    if single_pass:
                        return 0
                    time.sleep(poll_interval)
                    continue
                log("ERROR", "handoff_retry_failed", result_path=str(result_path))
            if dormant_state != "handoff_failed":
                log("ERROR", "dormant_entered", state="handoff_failed", interval=poll_interval)
                dormant_state = "handoff_failed"
            if single_pass:
                return 1
            time.sleep(poll_interval)
            continue

        try:
            lane_state = poll_lane_state(
                orchestrator_root=orchestrator_root,
                task_ref=task_ref,
                lane_id=lane_id,
                worktree_path=worktree_path,
            )
        except RuntimeError as exc:
            log("ERROR", "poll_error", error=str(exc))
            if single_pass:
                return 1
            time.sleep(poll_interval)
            continue

        if lane_state != "actionable":
            if dormant_state != lane_state:
                if lane_state == "waiting":
                    log("INFO", "dormant_entered", state="waiting_for_orchestrator", interval=poll_interval)
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="waiting_for_orchestrator",
                        summary="Worker already handed off this lane and is waiting for orchestrator follow-up.",
                    )
                else:
                    log("INFO", "dormant_entered", state="idle", interval=poll_interval)
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="idle",
                        summary="No actionable lane inbox items are currently assigned to this worker.",
                    )
                dormant_state = lane_state
            if single_pass:
                return 0
            time.sleep(poll_interval)
            continue

        if dormant_state is not None:
            wake_reason = "orchestrator_dispatch" if dormant_state == "waiting" else "new_lane_work"
            log("INFO", "dormant_exited", previous_state=dormant_state, reason=wake_reason)
            dormant_state = None

        log("INFO", "work_detected")
        _write_worker_status(
            state_dir,
            lane_id,
            task_ref=task_ref,
            session=session,
            state="executing",
            summary="Worker accepted actionable lane work and is preparing execution.",
        )

        final_result_path = None
        handoff_exit = 1
        last_findings: list[dict[str, Any]] = []

        for cycle in range(max_review_cycles):
            log("INFO", "cycle_start", cycle=cycle)
            _write_worker_status(
                state_dir,
                lane_id,
                task_ref=task_ref,
                session=session,
                state="executing",
                summary=f"Worker execution cycle {cycle + 1} is running.",
                cycle=cycle,
            )

            # --- Implementation pass ---
            prompt_override = None
            if cycle > 0 and final_result_path and last_findings:
                base_prompt_cmd = [
                    sys.executable,
                    str(SCRIPT_DIR / "lane_prompt.py"),
                    "--orchestrator-root", str(orchestrator_root),
                    "--task-ref", task_ref,
                    "--lane-id", lane_id,
                    "--worktree-path", str(worktree_path),
                ]
                env = pythonpath_env(orchestrator_root, task_ref=task_ref, lane_id=lane_id)
                base_result = subprocess.run(
                    base_prompt_cmd, capture_output=True, text=True, check=False, env=env
                )
                if base_result.returncode == 0:
                    prompt_override = build_fix_prompt(
                        base_result.stdout, last_findings
                    )
                else:
                    log(
                        "WARNING",
                        "fix_prompt_failed",
                        cycle=cycle,
                        error=(base_result.stderr or base_result.stdout or "").strip()[:200],
                    )

            try:
                log("INFO", "exec_start", cycle=cycle, worktree_path=str(worktree_path))
                final_result_path = run_lane_exec(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    worktree_path=worktree_path,
                    backend=backend,
                    session_mode=session_mode,
                    codex_bin=codex,
                    codex_args=codex_args,
                    prompt_override=prompt_override,
                    progress_callback=lambda event, **kw: log("INFO", event, cycle=cycle, **kw),
                    dry_run=dry_run,
                )
            except RuntimeError as exc:
                log("ERROR", "exec_failed", error=str(exc), cycle=cycle)
                break

            log("INFO", "exec_complete", result_path=str(final_result_path), cycle=cycle)

            # Check for needs_guidance
            result = _load_result(final_result_path)
            if result.get("handoff_action") == "needs_guidance":
                log("INFO", "needs_guidance", cycle=cycle)
                _write_worker_status(
                    state_dir,
                    lane_id,
                    task_ref=task_ref,
                    session=session,
                    state="handoff",
                    summary="Worker is handing a blocked/needs-guidance result back to the orchestrator.",
                    result_path=final_result_path,
                    cycle=cycle,
                    handoff_action="needs_guidance",
                )
                handoff_exit = _run_final_handoff(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    worktree_path=worktree_path,
                    result_path=final_result_path,
                    dry_run=dry_run,
                )
                if handoff_exit == 0:
                    _cleanup_result_file(final_result_path)
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="waiting_for_orchestrator",
                        summary="Blocked worker handoff submitted; waiting for orchestrator guidance.",
                        handoff_action="needs_guidance",
                        clear_result_path=True,
                    )
                else:
                    handoff_failure_seen_in_process = True
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="handoff_failed",
                        summary="The final worker handoff failed; the saved lane result must be retried without re-running execution.",
                        result_path=final_result_path,
                        failure_stage="final_handoff",
                        cycle=cycle,
                        handoff_action="needs_guidance",
                        attention_required=True,
                    )
                    log("ERROR", "handoff_failed", cycle=cycle, result_path=str(final_result_path))
                if single_pass:
                    return handoff_exit
                break

            # --- Self-review pass ---
            log("INFO", "review_start", cycle=cycle)
            _write_worker_status(
                state_dir,
                lane_id,
                task_ref=task_ref,
                session=session,
                state="reviewing",
                summary=f"Worker review cycle {cycle + 1} is checking the latest lane changes.",
                result_path=final_result_path,
                cycle=cycle,
            )
            try:
                review_output = run_review(
                    worktree_path=worktree_path,
                    lane_id=lane_id,
                    task_ref=task_ref,
                    session=session,
                    orchestrator_root=orchestrator_root,
                    backend=backend,
                    record_findings=True,
                    dry_run=dry_run,
                )
            except RuntimeError as exc:
                log("ERROR", "review_failed", error=str(exc), cycle=cycle)
                break

            findings = review_output.get("findings", [])
            converged = review_output.get("converged", False)
            log("INFO", "review_complete", cycle=cycle, converged=converged,
                finding_count=len(findings))

            # Stash findings for next fix cycle
            last_findings = findings

            if converged:
                # --- Verification ---
                log("INFO", "verification_start")
                _write_worker_status(
                    state_dir,
                    lane_id,
                    task_ref=task_ref,
                    session=session,
                    state="verifying",
                    summary="Worker review converged; lane-local verification is running.",
                    result_path=final_result_path,
                    cycle=cycle,
                )
                if dry_run:
                    check_ok = True
                else:
                    check_ok = _run_lane_check(
                        orchestrator_root=orchestrator_root,
                        task_ref=task_ref,
                        lane_id=lane_id,
                        worktree_path=worktree_path,
                    )
                log("INFO", "verification_complete", passed=check_ok)

                if not check_ok:
                    _patch_result(final_result_path, {
                        "handoff_action": "needs_guidance",
                        "blockers": ["Lane verification failed after review convergence."],
                    })

                handoff_action = "needs_guidance" if not check_ok else "merge_ready"
                _write_worker_status(
                    state_dir,
                    lane_id,
                    task_ref=task_ref,
                    session=session,
                    state="handoff",
                    summary="Worker verification finished; final handoff is being submitted.",
                    result_path=final_result_path,
                    cycle=cycle,
                    handoff_action=handoff_action,
                )
                handoff_exit = _run_final_handoff(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    worktree_path=worktree_path,
                    result_path=final_result_path,
                    dry_run=dry_run,
                )
                if handoff_exit == 0:
                    _cleanup_result_file(final_result_path)
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="waiting_for_orchestrator",
                        summary="Worker handoff submitted successfully; waiting for orchestrator follow-up.",
                        handoff_action=handoff_action,
                        clear_result_path=True,
                    )
                else:
                    handoff_failure_seen_in_process = True
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="handoff_failed",
                        summary="The final worker handoff failed after verification; the saved lane result must be retried without re-running execution.",
                        result_path=final_result_path,
                        failure_stage="final_handoff",
                        cycle=cycle,
                        handoff_action=handoff_action,
                        attention_required=True,
                    )
                    log("ERROR", "handoff_failed", cycle=cycle, result_path=str(final_result_path))
                if single_pass:
                    return handoff_exit
                break

            log("INFO", "fix_cycle_needed", cycle=cycle)
            # Loop continues with next cycle
        else:
            # Exhausted review cycles
            log("WARNING", "review_exhausted", max_cycles=max_review_cycles)
            if final_result_path:
                _patch_result(final_result_path, {
                    "handoff_action": "needs_guidance",
                    "blockers": [
                        f"Review did not converge after {max_review_cycles} cycles."
                    ],
                })
                _write_worker_status(
                    state_dir,
                    lane_id,
                    task_ref=task_ref,
                    session=session,
                    state="handoff",
                    summary="Worker review did not converge; handing the blocked result back to the orchestrator.",
                    result_path=final_result_path,
                    handoff_action="needs_guidance",
                )
                handoff_exit = _run_final_handoff(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    worktree_path=worktree_path,
                    result_path=final_result_path,
                    dry_run=dry_run,
                )
                if handoff_exit == 0:
                    _cleanup_result_file(final_result_path)
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="waiting_for_orchestrator",
                        summary="Non-converged worker handoff submitted; waiting for orchestrator follow-up.",
                        handoff_action="needs_guidance",
                        clear_result_path=True,
                    )
                else:
                    handoff_failure_seen_in_process = True
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="handoff_failed",
                        summary="The blocked worker handoff failed; the saved lane result must be retried without re-running execution.",
                        result_path=final_result_path,
                        failure_stage="final_handoff",
                        handoff_action="needs_guidance",
                        attention_required=True,
                    )
                    log("ERROR", "handoff_failed", result_path=str(final_result_path))

        if single_pass:
            return handoff_exit

        log("INFO", "poll_sleep", interval=poll_interval)
        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Worker daemon: poll, implement, review, verify, handoff."
    )
    parser.add_argument("--orchestrator-root", required=True,
                        help="Absolute path to the monorepo root.")
    parser.add_argument("--task-ref", required=True,
                        help="MCP task reference (e.g. phase-5-retention-export-and-audit-controls).")
    parser.add_argument("--lane-id", required=True,
                        help="Lane identifier (e.g. backend-domain).")
    parser.add_argument("--session", default=None,
                        help="MCP session. Defaults to <task>-<lane>.")
    parser.add_argument("--worktree-path", required=True,
                        help="Absolute path to the lane worktree.")
    parser.add_argument("--max-review-cycles", type=int, default=3,
                        help="Max review/fix cycles before declaring blocked (default: 3).")
    parser.add_argument("--poll-interval", type=int, default=30,
                        help="Seconds between poll cycles (default: 30).")
    parser.add_argument("--single-pass", action="store_true",
                        help="Run one cycle and exit instead of looping.")
    parser.add_argument("--backend", default="codex-cli",
                        choices=BACKEND_CHOICES,
                        help="Execution backend to use (default: codex-cli).")
    parser.add_argument("--session-mode", default="fresh_turn",
                        choices=SESSION_MODE_CHOICES,
                        help="Use a fresh backend session per turn, or preserve continuity within this lane only.")
    parser.add_argument("--codex-bin", default=None,
                        help="Explicit path to the codex binary.")
    parser.add_argument("--codex-args", default=None,
                        help="Extra args for codex exec (space-separated).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Codex execution and simulate results.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    orchestrator_root = Path(args.orchestrator_root).expanduser().resolve()
    worktree_path = Path(args.worktree_path).expanduser().resolve()
    session = args.session or f"{args.task_ref}-{args.lane_id}"
    state_dir = orchestrator_root / ".task-state"
    codex_args = args.codex_args.split() if args.codex_args else None

    # Ensure SCRIPT_DIR is on sys.path so lazy imports work
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    # Per-lane exclusive lock
    lock = WorkerLock(args.lane_id, state_dir)
    if not lock.acquire():
        print(f"Another worker daemon is already running for lane '{args.lane_id}'.", file=sys.stderr)
        return 1

    try:
        return worker_loop(
            orchestrator_root=orchestrator_root,
            task_ref=args.task_ref,
            lane_id=args.lane_id,
            session=session,
            worktree_path=worktree_path,
            max_review_cycles=args.max_review_cycles,
            poll_interval=args.poll_interval,
            single_pass=args.single_pass,
            backend=args.backend,
            session_mode=args.session_mode,
            codex_bin=args.codex_bin,
            codex_args=codex_args,
            dry_run=args.dry_run,
        )
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
