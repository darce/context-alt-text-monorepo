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
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
PACKAGE_SRC = SCRIPT_DIR.parents[1]
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from _env import WORKER_REASONING_EFFORT_CHOICES
from _env import pythonpath_env
from backend_registry import get_backend_choices
from agent_handoff_mcp.enums import WorkerEventName
from orchestrator_helpers import rotate_jsonl_if_needed, _combined_text, _json_load, _normalize_text

_MAX_LOG_BYTES = 1_000_000
_STATUS_FILE_VERSION = 1
_OBSERVABILITY_HISTORY_LIMIT = 20
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
    rotate_jsonl_if_needed(path, _MAX_LOG_BYTES)
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
# Graceful shutdown flag (set by SIGTERM handler)
# ---------------------------------------------------------------------------

_shutdown_requested: bool = False


def _handle_sigterm(signum: int, frame: object) -> None:
    global _shutdown_requested
    _shutdown_requested = True


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
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass


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


def _fetch_mcp_lane_params(orchestrator_root: Path, task_ref: str, lane_id: str) -> dict[str, Any]:
    """Fetch dynamic lane parameters (model, backend, reasoning_effort) from MCP."""
    try:
        # Avoid circular or heavy imports at module level
        from agent_handoff_mcp import api
        from agent_handoff_mcp.config import RuntimeConfig
        
        config = RuntimeConfig(workspace_root=orchestrator_root)
        api.configure_runtime(config)
        
        res = api.list_worktree_lanes(task_ref=task_ref)
        data = json.loads(res)
        if not data.get("ok"):
            return {}
            
        lanes = data.get("lanes", [])
        for lane in lanes:
            if lane.get("lane_id") == lane_id:
                return {
                    "model": lane.get("model"),
                    "backend": lane.get("backend"),
                    "reasoning_effort": lane.get("reasoning_effort"),
                }
    except Exception:
        pass
    return {}


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
    run_id: str | None = None,
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
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-500:]
        stdout_tail = (result.stdout or "")[-500:]
        log_dir = orchestrator_root / "logs" / "worker-daemon"
        _log(lane_id, log_dir, "ERROR", WorkerEventName.HANDOFF_SUBPROCESS_FAILED,
             exit_code=result.returncode,
             run_id=run_id,
             stderr_tail=stderr_tail,
             stdout_tail=stdout_tail)
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
    observability: dict[str, Any] | None = None,
    context_utilization: dict[str, Any] | None = None,
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
    if observability is not None:
        payload["observability"] = observability
    elif isinstance(previous.get("observability"), dict):
        payload["observability"] = previous["observability"]
    if context_utilization is not None:
        payload["context_utilization_latest"] = context_utilization
    elif isinstance(previous.get("context_utilization_latest"), dict):
        payload["context_utilization_latest"] = previous["context_utilization_latest"]
    _status_path(state_dir, lane_id).write_text(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def _observability_entry(
    *,
    task_ref: str,
    lane_id: str,
    cycle: int,
    phase: str,
    backend: str,
    model: str | None = None,
    requested_reasoning_effort: str,
    effective_reasoning_effort: str,
    telemetry: dict[str, Any],
    context_utilization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    token_usage = telemetry.get("token_usage")
    total_usage = token_usage.get("total") if isinstance(token_usage, dict) else None
    entry: dict[str, Any] = {
        "recorded_at": _utcnow_iso(),
        "task_ref": task_ref,
        "lane_id": lane_id,
        "cycle": cycle,
        "phase": phase,
        "backend": backend,
        "model": model,
        "requested_reasoning_effort": requested_reasoning_effort,
        "effective_reasoning_effort": effective_reasoning_effort,
        "thread_id": telemetry.get("thread_id"),
        "turn_id": telemetry.get("turn_id"),
        "token_usage": token_usage,
        "token_usage_totals": {
            "total_tokens": total_usage.get("total_tokens") if isinstance(total_usage, dict) else None,
            "reasoning_output_tokens": (
                total_usage.get("reasoning_output_tokens") if isinstance(total_usage, dict) else None
            ),
        },
    }
    if context_utilization is not None:
        entry["context_utilization"] = context_utilization
    return entry


def _merge_observability(
    existing: dict[str, Any] | None,
    *,
    entry: dict[str, Any],
) -> dict[str, Any]:
    history = list(existing.get("history", [])) if isinstance(existing, dict) and isinstance(existing.get("history"), list) else []
    history.append(entry)
    if len(history) > _OBSERVABILITY_HISTORY_LIMIT:
        history = history[-_OBSERVABILITY_HISTORY_LIMIT:]
    by_phase = dict(existing.get("by_phase", {})) if isinstance(existing, dict) and isinstance(existing.get("by_phase"), dict) else {}
    phase = str(entry.get("phase") or "").strip()
    if phase:
        by_phase[phase] = entry
    return {
        "latest": entry,
        "by_phase": by_phase,
        "history": history,
    }


def _record_observability(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
    session: str,
    cycle: int,
    phase: str,
    backend: str,
    model: str | None = None,
    requested_reasoning_effort: str,
    effective_reasoning_effort: str,
    telemetry: dict[str, Any],
    state: str,
    summary: str,
    result_path: Path | None = None,
    handoff_action: str | None = None,
    attention_required: bool = False,
    context_utilization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_dir = orchestrator_root / ".task-state"
    log_dir = orchestrator_root / "logs" / "worker-daemon"
    previous = _read_worker_status(state_dir, lane_id) or {}
    entry = _observability_entry(
        task_ref=task_ref,
        lane_id=lane_id,
        cycle=cycle,
        phase=phase,
        backend=backend,
        model=model,
        requested_reasoning_effort=requested_reasoning_effort,
        effective_reasoning_effort=effective_reasoning_effort,
        telemetry=telemetry,
        context_utilization=context_utilization,
    )
    observability = _merge_observability(previous.get("observability"), entry=entry)
    _write_worker_status(
        state_dir,
        lane_id,
        task_ref=task_ref,
        session=session,
        state=state,
        summary=summary,
        result_path=result_path,
        cycle=cycle,
        handoff_action=handoff_action,
        attention_required=attention_required,
        observability=observability,
    )
    _log(
        lane_id,
        log_dir,
        "INFO",
        WorkerEventName.SUBAGENT_TURN_OBSERVED,
        cycle=cycle,
        phase=phase,
        backend=backend,
        model=model,
        requested_reasoning_effort=requested_reasoning_effort,
        effective_reasoning_effort=effective_reasoning_effort,
        token_usage=entry["token_usage"],
        token_usage_totals=entry["token_usage_totals"],
        total_tokens=entry["token_usage_totals"]["total_tokens"],
        reasoning_output_tokens=entry["token_usage_totals"]["reasoning_output_tokens"],
        thread_id=entry.get("thread_id"),
        turn_id=entry.get("turn_id"),
    )
    _record_token_usage_to_handoff(
        orchestrator_root=orchestrator_root,
        task_ref=task_ref,
        lane_id=lane_id,
        session=session,
        cycle=cycle,
        phase=phase,
        backend=backend,
        model=model,
        entry=entry,
    )
    return entry


def _record_token_usage_to_handoff(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
    session: str,
    cycle: int,
    phase: str,
    backend: str,
    model: str | None,
    entry: dict[str, Any],
) -> None:
    """Best-effort recording of token usage to MCP handoff as a decision."""
    totals = entry.get("token_usage_totals") or {}
    total_tokens = totals.get("total_tokens")
    if not total_tokens:
        return
    try:
        from agent_handoff_mcp import api  # noqa: PLC0415
        from agent_handoff_mcp.config import RuntimeConfig  # noqa: PLC0415

        config = RuntimeConfig(workspace_root=orchestrator_root)
        api.configure_runtime(config)

        reasoning_tokens = totals.get("reasoning_output_tokens") or 0
        token_usage = entry.get("token_usage") or {}
        last = token_usage.get("last") or {}

        rationale = (
            f"cycle={cycle} phase={phase} backend={backend} model={model or 'default'} "
            f"total_tokens={total_tokens} "
            f"input={last.get('input_tokens', 'n/a')} "
            f"output={last.get('output_tokens', 'n/a')} "
            f"cached={last.get('cached_input_tokens', 'n/a')} "
            f"reasoning={reasoning_tokens} "
            f"context_window={token_usage.get('model_context_window', 'n/a')}"
        )
        api.record_decision(
            session=session,
            decision=f"token_usage_c{cycle}_{phase}",
            rationale=rationale,
            actor=api.build_write_actor(agent=f"worker-{lane_id}"),
        )
    except Exception:
        # Best-effort; do not break the execution pipeline for telemetry logging
        pass


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
# Per-session hardening helpers
# ---------------------------------------------------------------------------


def _finding_stable_id(finding: dict[str, Any]) -> str:
    """Derive a stable ID for a review finding to track recurrence across cycles."""
    return (
        f"{finding.get('severity', '')}:"
        f"{finding.get('category', '')}:"
        f"{finding.get('file_path', '')}:"
        f"{finding.get('line_start', 0)}"
    )


def _compute_finding_diff(
    prev_finding_ids: set[str],
    current_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare current findings against a previous set of stable IDs.

    Returns a dict with three keys:
    - ``new``: findings not present in ``prev_finding_ids``
    - ``recurring``: findings that were already in ``prev_finding_ids``
    - ``resolved_count``: number of IDs from ``prev_finding_ids`` not re-found
    """
    current_ids = {_finding_stable_id(f) for f in current_findings}
    new_findings = [f for f in current_findings if _finding_stable_id(f) not in prev_finding_ids]
    recurring = [f for f in current_findings if _finding_stable_id(f) in prev_finding_ids]
    resolved_count = len(prev_finding_ids - current_ids)
    return {
        "new": new_findings,
        "recurring": recurring,
        "resolved_count": resolved_count,
    }


def _update_exhaustion_streak(state_dir: Path, lane_id: str, run_id: str) -> int:
    """Increment and return the exhaustion streak counter for the current daemon session.

    The counter is scoped to ``run_id`` so a fresh daemon session always
    starts from zero even if the status file persists from a previous run.
    """
    status = _read_worker_status(state_dir, lane_id) or {}
    streak_info = status.get("exhaustion_streak")
    if not isinstance(streak_info, dict) or streak_info.get("run_id") != run_id:
        streak_info = {"run_id": run_id, "count": 0}
    streak_info["count"] = int(streak_info.get("count") or 0) + 1
    status["exhaustion_streak"] = streak_info
    _status_path(state_dir, lane_id).parent.mkdir(parents=True, exist_ok=True)
    _status_path(state_dir, lane_id).write_text(json.dumps(status, indent=2, sort_keys=True))
    return streak_info["count"]


def _reset_exhaustion_streak(state_dir: Path, lane_id: str, run_id: str) -> None:
    """Reset exhaustion streak to zero after successful review convergence."""
    status = _read_worker_status(state_dir, lane_id) or {}
    status["exhaustion_streak"] = {"run_id": run_id, "count": 0}
    _status_path(state_dir, lane_id).parent.mkdir(parents=True, exist_ok=True)
    _status_path(state_dir, lane_id).write_text(json.dumps(status, indent=2, sort_keys=True))


def _check_token_burn(
    *,
    state_dir: Path,
    lane_id: str,
    run_id: str,
    threshold: int,
    log_dir: Path,
) -> bool:
    """Emit a ``token_burn_warning`` event if cumulative token usage exceeds threshold.

    Returns True if the threshold was exceeded.
    """
    status = _read_worker_status(state_dir, lane_id) or {}
    obs = status.get("observability") or {}
    history = obs.get("history") if isinstance(obs, dict) else None
    if not isinstance(history, list):
        return False
    cumulative = sum(
        int((entry.get("token_usage_totals") or {}).get("total_tokens") or 0)
        for entry in history
        if isinstance(entry, dict)
    )
    if cumulative < threshold:
        return False
    entry: dict[str, Any] = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "lane": lane_id,
        "level": "WARNING",
        "event": "token_burn_warning",
        "run_id": run_id,
        "cumulative_tokens": cumulative,
        "threshold": threshold,
    }
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"worker-{lane_id}.jsonl"
    rotate_jsonl_if_needed(path, _MAX_LOG_BYTES)
    with path.open("a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    print(
        f"[WARNING] token_burn_warning cumulative_tokens={cumulative} threshold={threshold}",
        flush=True,
    )
    return True


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
    reasoning_effort: str = "inherit",
    model: str | None = None,
    codex_bin: str | None = None,
    codex_args: list[str] | None = None,
    dry_run: bool = False,
) -> int:
    """Main daemon loop.  Returns 0 on clean handoff, 1 on failure."""
    # Lazy-import lane_exec and review_runner to keep module importable
    # without heavy deps at test time.
    from lane_exec import build_fix_prompt, run_lane_exec
    from review_runner import run_review

    log_dir = orchestrator_root / "logs" / "worker-daemon"
    state_dir = orchestrator_root / ".task-state"
    run_id = str(uuid.uuid4())
    def log(level: str, event: str, **kw: Any) -> None:
        _log(lane_id, log_dir, level, event, run_id=run_id, **kw)
    existing_status = _read_worker_status(state_dir, lane_id) or {}

    # Load daemon-level config once (token burn gate, etc.)
    try:
        from lane_manifest import get_lane_config as _get_lane_config
        _lane_cfg = _get_lane_config(task_ref, lane_id, orchestrator_root=str(orchestrator_root)) or {}
    except Exception:
        _lane_cfg = {}
    token_burn_threshold = int(_lane_cfg.get("token_burn_threshold") or 2_000_000)

    previous_run_exhausted = False

    log("INFO", WorkerEventName.DAEMON_START, task_ref=task_ref, single_pass=single_pass,
        max_review_cycles=max_review_cycles, backend=backend, session_mode=session_mode,
        reasoning_effort=reasoning_effort, model=model)
    if existing_status.get("state") != "handoff_failed":
        _write_worker_status(
            state_dir,
            lane_id,
            task_ref=task_ref,
            session=session,
            state="starting",
            summary="Worker daemon started and is preparing its lane-scoped runtime.",
        )

    # Note: codex_bin discovery is now handled by the BackendAdapter.
    # We pass codex_bin through to run_lane_exec if provided.
    dormant_state: str | None = None
    MAX_HANDOFF_RETRIES = 3
    handoff_retry_count = 0

    while True:
        if _shutdown_requested:
            log("INFO", WorkerEventName.DAEMON_STOP, reason="sigterm")
            return 0
        persisted_status = _read_worker_status(state_dir, lane_id) or {}
        if persisted_status.get("state") == "handoff_failed":
            result_path_raw = str(persisted_status.get("result_path") or "").strip()
            result_path = Path(result_path_raw) if result_path_raw else None
            if result_path is not None and result_path.exists() and handoff_retry_count < MAX_HANDOFF_RETRIES:
                backoff = min(poll_interval * (2 ** handoff_retry_count), 300)
                if handoff_retry_count > 0:
                    time.sleep(backoff)
                log("INFO", WorkerEventName.HANDOFF_RETRY_START, result_path=str(result_path), retry=handoff_retry_count + 1)
                retry_exit = _run_final_handoff(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    worktree_path=worktree_path,
                    result_path=result_path,
                    dry_run=dry_run,
                    run_id=run_id,
                )
                handoff_retry_count += 1
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
                    log("INFO", WorkerEventName.HANDOFF_RETRY_COMPLETE, result_path=str(result_path))
                    if single_pass:
                        return 0
                    time.sleep(poll_interval)
                    continue
                log("ERROR", WorkerEventName.HANDOFF_RETRY_FAILED, result_path=str(result_path))
            if dormant_state != "handoff_failed":
                log("ERROR", WorkerEventName.DORMANT_ENTERED, state="handoff_failed", interval=poll_interval, retry_count=handoff_retry_count)
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
            log("ERROR", WorkerEventName.POLL_ERROR, error=str(exc))
            if single_pass:
                return 1
            time.sleep(poll_interval)
            continue

        if lane_state != "actionable":
            if dormant_state != lane_state:
                if lane_state == "waiting":
                    log("INFO", WorkerEventName.DORMANT_ENTERED, state="waiting_for_orchestrator", interval=poll_interval)
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="waiting_for_orchestrator",
                        summary="Worker already handed off this lane and is waiting for orchestrator follow-up.",
                    )
                else:
                    log("INFO", WorkerEventName.DORMANT_ENTERED, state="idle", interval=poll_interval)
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
            log("INFO", WorkerEventName.DORMANT_EXITED, previous_state=dormant_state, reason=wake_reason)
            dormant_state = None

        final_result_path = None
        handoff_exit = 1
        last_findings: list[dict[str, Any]] = []
        prev_finding_ids: set[str] = set()

        for cycle in range(max_review_cycles):
            # M-3: Fetch dynamic overrides from MCP at the START of each cycle
            mcp_params = _fetch_mcp_lane_params(orchestrator_root, task_ref, lane_id)
            if mcp_params.get("backend"):
                log("INFO", WorkerEventName.MCP_BACKEND_OVERRIDE, old=backend, new=mcp_params["backend"])
                backend = str(mcp_params["backend"])
            if mcp_params.get("model"):
                log("INFO", WorkerEventName.MCP_MODEL_OVERRIDE, old=model, new=mcp_params["model"])
                model = str(mcp_params["model"])
            if mcp_params.get("reasoning_effort"):
                log("INFO", WorkerEventName.MCP_EFFORT_OVERRIDE, old=reasoning_effort, new=mcp_params["reasoning_effort"])
                reasoning_effort = str(mcp_params["reasoning_effort"])

            log("INFO", WorkerEventName.CYCLE_START, cycle=cycle)
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
                        WorkerEventName.FIX_PROMPT_FAILED,
                        cycle=cycle,
                        error=(base_result.stderr or base_result.stdout or "").strip()[:200],
                    )

            # M-4: Use adapter to resolve reasoning effort (backend-agnostic)
            from backend_registry import get_adapter
            adapter_kwargs = {}
            if backend == "codex-cli":
                adapter_kwargs = {"codex_bin": codex_bin, "codex_args": codex_args}
            
            adapter = get_adapter(backend, **adapter_kwargs)
            cycle_reasoning_effort, effort_reasons = adapter.resolve_reasoning_effort(
                orchestrator_root=orchestrator_root,
                task_ref=task_ref,
                lane_id=lane_id,
                requested=reasoning_effort,
                cycle=cycle,
                prompt_override=prompt_override,
                previous_run_exhausted=previous_run_exhausted,
            )
            log(
                "INFO",
                WorkerEventName.REASONING_EFFORT_SELECTED,
                cycle=cycle,
                requested_reasoning_effort=reasoning_effort,
                effective_reasoning_effort=cycle_reasoning_effort or "inherit",
                reasons="; ".join(effort_reasons),
            )
            execution_requested_effort = str(reasoning_effort or "inherit")
            execution_effective_effort = cycle_reasoning_effort or "inherit"

            def _worker_progress(event: str, **kw: Any) -> None:
                if event == WorkerEventName.SUBAGENT_TURN_COMPLETE:
                    phase = str(kw.get("phase") or "execution")
                    phase_state = "reviewing" if phase == "review" else "executing"
                    _record_observability(
                        orchestrator_root=orchestrator_root,
                        task_ref=task_ref,
                        lane_id=lane_id,
                        session=session,
                        cycle=cycle,
                        phase=phase,
                        backend=str(kw.get("backend") or backend),
                        model=model,
                        requested_reasoning_effort=execution_requested_effort,
                        effective_reasoning_effort=execution_effective_effort,
                        telemetry=kw,
                        state=phase_state,
                        summary=f"Worker {phase} telemetry captured for cycle {cycle + 1}.",
                        result_path=final_result_path,
                    )
                    exceeded = _check_token_burn(
                        state_dir=state_dir,
                        lane_id=lane_id,
                        run_id=run_id,
                        threshold=token_burn_threshold,
                        log_dir=log_dir,
                    )
                    if exceeded:
                        _write_worker_status(
                            state_dir,
                            lane_id,
                            task_ref=task_ref,
                            session=session,
                            state=phase_state,
                            summary=(
                                f"Token burn threshold ({token_burn_threshold:,} tokens) exceeded;"
                                " manual attention may be required."
                            ),
                            result_path=final_result_path,
                            cycle=cycle,
                            attention_required=True,
                        )
                else:
                    log("INFO", event, cycle=cycle, **kw)

            _exec_start = time.monotonic()
            try:
                log("INFO", WorkerEventName.EXEC_START, cycle=cycle, worktree_path=str(worktree_path))
                final_result_path = run_lane_exec(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    worktree_path=worktree_path,
                    backend=backend,
                    session_mode=session_mode,
                    reasoning_effort=cycle_reasoning_effort,
                    model=model,
                    codex_bin=codex_bin,
                    codex_args=codex_args,
                    prompt_override=prompt_override,
                    progress_callback=_worker_progress,
                    dry_run=dry_run,
                )
            except Exception as exc:
                log("ERROR", WorkerEventName.EXEC_FAILED, error=str(exc), cycle=cycle)
                break

            exec_seconds = round(time.monotonic() - _exec_start, 2)
            log("INFO", WorkerEventName.EXEC_COMPLETE, result_path=str(final_result_path), cycle=cycle, exec_seconds=exec_seconds)

            # Emit artifact_indexed event when lane_exec compressed a large details field
            result = _load_result(final_result_path)
            _details_ref = result.get("details_artifact_ref")
            if _details_ref is not None:
                log("INFO", WorkerEventName.ARTIFACT_INDEXED,
                    cycle=cycle,
                    details_artifact_ref=_details_ref,
                    lane_id=lane_id,
                    task_ref=task_ref,
                )

            # Emit context_pressure event when the prompt was under elevated or high pressure
            _ctx_util = result.get("context_utilization")
            if isinstance(_ctx_util, dict):
                _pressure = str(_ctx_util.get("pressure") or "normal")
                if _pressure in ("elevated", "high"):
                    log("WARNING", WorkerEventName.CONTEXT_PRESSURE,
                        cycle=cycle,
                        pressure=_pressure,
                        utilization_ratio=_ctx_util.get("utilization_ratio"),
                        domain_signal_ratio=_ctx_util.get("domain_signal_ratio"),
                        prompt_tokens_approx=_ctx_util.get("prompt_tokens_approx"),
                    )
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="executing",
                        summary=f"Context pressure is {_pressure}; utilization={_ctx_util.get('utilization_ratio')}.",
                        cycle=cycle,
                        context_utilization=_ctx_util,
                    )
                # Record context_utilization in the observability entry so it appears
                # in observability.latest and history regardless of pressure level.
                _record_observability(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    cycle=cycle,
                    phase="context_freshness",
                    backend=backend,
                    model=model,
                    requested_reasoning_effort=execution_requested_effort,
                    effective_reasoning_effort=execution_effective_effort,
                    telemetry={},
                    state="executing",
                    summary=f"Context-freshness metrics recorded for cycle {cycle + 1}.",
                    result_path=final_result_path,
                    context_utilization=_ctx_util,
                )

            # Check for needs_guidance
            if result.get("handoff_action") == "needs_guidance":
                log("INFO", WorkerEventName.NEEDS_GUIDANCE, cycle=cycle)
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
                    run_id=run_id,
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
                    log("ERROR", WorkerEventName.HANDOFF_FAILED, cycle=cycle, result_path=str(final_result_path))
                if single_pass:
                    return handoff_exit
                break

            # --- Scope violation gate ---
            if result.get("scope_violation"):
                scope_violations = result.get("scope_violations", [])
                log("WARNING", WorkerEventName.SCOPE_VIOLATION, cycle=cycle, violations=scope_violations)
                _record_observability(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    cycle=cycle,
                    phase="scope_check",
                    backend=backend,
                    model=model or "unknown",
                    requested_reasoning_effort=execution_requested_effort,
                    effective_reasoning_effort=execution_effective_effort,
                    telemetry={"scope_violations": scope_violations},
                    state="scope_violation",
                    summary=f"Scope violation: {len(scope_violations)} file(s) outside owned_paths.",
                    result_path=final_result_path,
                )
                _patch_result(final_result_path, {
                    "handoff_action": "needs_guidance",
                    "blockers": [
                        f"Scope violation: {len(scope_violations)} file(s) modified outside owned_paths: "
                        + str(scope_violations[:5])
                    ],
                })
                _write_worker_status(
                    state_dir,
                    lane_id,
                    task_ref=task_ref,
                    session=session,
                    state="handoff",
                    summary=(
                        f"Scope violation detected ({len(scope_violations)} file(s));"
                        " handing blocked result back to orchestrator."
                    ),
                    result_path=final_result_path,
                    cycle=cycle,
                    handoff_action="needs_guidance",
                    attention_required=True,
                )
                handoff_exit = _run_final_handoff(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    worktree_path=worktree_path,
                    result_path=final_result_path,
                    dry_run=dry_run,
                    run_id=run_id,
                )
                if handoff_exit == 0:
                    _cleanup_result_file(final_result_path)
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="waiting_for_orchestrator",
                        summary="Scope-violation blocked handoff submitted; waiting for orchestrator guidance.",
                        handoff_action="needs_guidance",
                        clear_result_path=True,
                    )
                else:
                    _write_worker_status(
                        state_dir,
                        lane_id,
                        task_ref=task_ref,
                        session=session,
                        state="handoff_failed",
                        summary="Scope-violation handoff failed; saved result must be retried.",
                        result_path=final_result_path,
                        failure_stage="final_handoff",
                        cycle=cycle,
                        handoff_action="needs_guidance",
                        attention_required=True,
                    )
                    log("ERROR", WorkerEventName.HANDOFF_FAILED, cycle=cycle, result_path=str(final_result_path))
                if single_pass:
                    return handoff_exit
                break

            # --- Self-review pass ---
            log("INFO", WorkerEventName.REVIEW_START, cycle=cycle)
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
            _review_start = time.monotonic()
            try:
                review_output = run_review(
                    worktree_path=worktree_path,
                    lane_id=lane_id,
                    task_ref=task_ref,
                    session=session,
                    orchestrator_root=orchestrator_root,
                    backend=backend,
                    reasoning_effort=cycle_reasoning_effort,
                    model=model,
                    record_findings=True,
                    dry_run=dry_run,
                    progress_callback=_worker_progress,
                )
            except Exception as exc:
                log("ERROR", WorkerEventName.REVIEW_FAILED, error=str(exc), cycle=cycle)
                break

            review_seconds = round(time.monotonic() - _review_start, 2)
            findings = review_output.get("findings", [])
            converged = review_output.get("converged", False)
            log(
                "INFO",
                WorkerEventName.REVIEW_COMPLETE,
                cycle=cycle,
                converged=converged,
                finding_count=len(findings),
                review_seconds=review_seconds,
                review_kind=review_output.get("review_kind"),
                scope_source=review_output.get("scope_source"),
                scope_reason=review_output.get("scope_reason"),
            )

            # ACE reflection hook: scan new findings for rule references and
            # append detection records to the shared ace_reflect_log.jsonl.
            # Counter writes are intentionally deferred to 'make ace-reflect'
            # so instruction-file edits never happen inside a daemon cycle.
            if findings:
                try:
                    import datetime as _dt  # noqa: PLC0415
                    from agent_handoff_mcp.orchestration.ace_reflect import (  # noqa: PLC0415
                        ace_reflect_on_findings,
                    )

                    _workspace_root = state_dir.parent
                    # CLAUDE.md and GEMINI.md are symlinks to instructions.md;
                    # only pass the canonical path to avoid triple-counting.
                    _instruction_files = [
                        _workspace_root / "docs/agentic/instructions.md",
                    ]
                    _records = ace_reflect_on_findings(findings, _instruction_files)
                    if _records:
                        _reflect_log = state_dir / "ace_reflect_log.jsonl"
                        with _reflect_log.open("a", encoding="utf-8") as _fh:
                            for _rec in _records:
                                _rec["cycle"] = cycle
                                _rec["timestamp"] = _dt.datetime.utcnow().isoformat() + "Z"
                                _fh.write(json.dumps(_rec) + "\n")
                        log(
                            "INFO",
                            WorkerEventName.ACE_REFLECT_DETECTED,
                            cycle=cycle,
                            records=len(_records),
                        )
                except Exception as _ace_exc:  # noqa: BLE001
                    log("WARNING", WorkerEventName.ACE_REFLECT_ERROR, error=str(_ace_exc))

            # Compute finding diff before updating prev_finding_ids
            if prev_finding_ids or findings:
                diff = _compute_finding_diff(prev_finding_ids, findings)
                log("INFO", WorkerEventName.FINDING_DIFF, cycle=cycle,
                    new_count=len(diff["new"]),
                    recurring_count=len(diff["recurring"]),
                    resolved_count=diff["resolved_count"])

            # Stash findings for next fix cycle
            last_findings = findings
            prev_finding_ids = {_finding_stable_id(f) for f in findings}

            if converged:
                # --- Verification ---
                _reset_exhaustion_streak(state_dir, lane_id, run_id)
                previous_run_exhausted = False
                log("INFO", WorkerEventName.VERIFICATION_START)
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
                log("INFO", WorkerEventName.VERIFICATION_COMPLETE, passed=check_ok)

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
                    run_id=run_id,
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
                    log("ERROR", WorkerEventName.HANDOFF_FAILED, cycle=cycle, result_path=str(final_result_path))
                if single_pass:
                    return handoff_exit
                break

            log("INFO", WorkerEventName.FIX_CYCLE_NEEDED, cycle=cycle)
            # Loop continues with next cycle
        else:
            # Exhausted review cycles
            log("WARNING", WorkerEventName.REVIEW_EXHAUSTED, max_cycles=max_review_cycles)
            previous_run_exhausted = True
            exhaustion_streak = _update_exhaustion_streak(state_dir, lane_id, run_id)
            log("WARNING", WorkerEventName.EXHAUSTION_STREAK, streak=exhaustion_streak, lane=lane_id)
            if exhaustion_streak >= 3:
                log("WARNING", WorkerEventName.LANE_EXHAUSTION_FORCED_STOP, streak=exhaustion_streak)
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
                    attention_required=exhaustion_streak >= 2,
                )
                handoff_exit = _run_final_handoff(
                    orchestrator_root=orchestrator_root,
                    task_ref=task_ref,
                    lane_id=lane_id,
                    session=session,
                    worktree_path=worktree_path,
                    result_path=final_result_path,
                    dry_run=dry_run,
                    run_id=run_id,
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
                    log("ERROR", WorkerEventName.HANDOFF_FAILED, result_path=str(final_result_path))

        if single_pass:
            return handoff_exit

        log("INFO", WorkerEventName.POLL_SLEEP, interval=poll_interval)
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
    parser.add_argument("--reasoning-effort", default="inherit",
                        choices=WORKER_REASONING_EFFORT_CHOICES,
                        help="Worker reasoning mode: inherit existing defaults, auto-tune per cycle, or force a specific effort.")
    parser.add_argument("--codex-bin", default=None,
                        help="Explicit path to the codex binary.")
    parser.add_argument("--codex-args", default=None,
                        help="Extra args for codex exec (space-separated).")
    parser.add_argument("--model", default=None,
                        help="Explicit model to use (e.g. gpt-5.4-mini).")
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

    signal.signal(signal.SIGTERM, _handle_sigterm)
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
            reasoning_effort=args.reasoning_effort,
            model=args.model,
            codex_bin=args.codex_bin,
            codex_args=codex_args,
            dry_run=args.dry_run,
        )
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
