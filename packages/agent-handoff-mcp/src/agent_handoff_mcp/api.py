from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.client import Client, PythonStdioTransport

from .config import RuntimeConfig
from . import core
from .runtime import configure_runtime, get_runtime_config, reset_runtime_config


record_decision = core.record_decision
build_write_actor = core.build_write_actor
update_next_actions = core.update_next_actions
record_test_result = core.record_test_result
report_blocker = core.report_blocker
record_review_finding = core.record_review_finding
update_review_finding = core.update_review_finding
reopen_review_finding = core.reopen_review_finding
list_review_findings = core.list_review_findings
get_review_finding = core.get_review_finding
get_review_findings_summary = core.get_review_findings_summary
reconcile_review_findings = core.reconcile_review_findings
handoff_close_check = core.handoff_close_check
export_handoff_state = core.export_handoff_state
import_handoff_state = core.import_handoff_state
archive_task_state = core.archive_task_state
switch_task = core.switch_task
get_handoff_dashboard = core.get_handoff_dashboard
set_handoff_state = core.set_handoff_state
get_handoff_state = core.get_handoff_state
get_lane_activity = core.get_lane_activity
list_lane_messages = core.list_lane_messages
list_lane_briefs = core.list_lane_briefs
get_plan_cursor = core.get_plan_cursor
list_next_actions = core.list_next_actions
list_plan_cursors = core.list_plan_cursors
upsert_plan_cursor = core.upsert_plan_cursor
list_worker_reports = core.list_worker_reports
list_worktree_lanes = core.list_worktree_lanes
record_lane_message = core.record_lane_message
record_lane_brief = core.record_lane_brief
record_worker_report = core.record_worker_report
update_lane_message = core.update_lane_message
upsert_worktree_lane = core.upsert_worktree_lane
close_worktree_lane = core.close_worktree_lane

record_artifact = core.record_artifact
search_artifacts = core.search_artifacts
get_artifact_source = core.get_artifact_source
get_artifact_terms = core.get_artifact_terms
list_artifact_sources = core.list_artifact_sources
purge_artifacts = core.purge_artifacts
search_handoff = core.search_handoff


TOOL_DESCRIPTIONS: dict[str, str] = {
    "set_handoff_state": "Set or update the active handoff task state with optimistic revision protection.",
    "get_handoff_state": "Read the active or requested task handoff summary, including blockers, actions, tests, and findings.",
    "upsert_worktree_lane": "Create or update worktree lane metadata for a task, including branch, status, and worktree path.",
    "close_worktree_lane": "Transition a worktree lane to merged or closed status. Accepts lane_id, optional status (merged|closed, default closed), optional notes, and optional task_ref.",
    "list_worktree_lanes": "List registered worktree lanes for the active or requested task.",
    "get_lane_activity": "Read the current activity summary for a lane, including blockers, actions, findings, messages, and tests.",
    "list_next_actions": "List next-action rows for the active or requested task, optionally filtered by lane or status.",
    "record_decision": "Record an orchestrator or worker decision in the handoff ledger for the active task.",
    "update_next_actions": "Add, update, complete, or skip next-action items for the active task.",
    "record_test_result": "Record the result of a verification command for the active task.",
    "report_blocker": "Add, resolve, or reopen a blocker for the active task.",
    "record_worker_report": "Record a structured worker report for a lane, including summary, changed files, blockers, and merge readiness.",
    "list_worker_reports": "List recent worker reports for the active or requested task, optionally scoped to a lane.",
    "record_lane_message": "Create a lane message between orchestrator and worker for the active or requested task.",
    "record_lane_brief": "Create a structured orchestrator-to-worker brief on top of the lane_messages surface.",
    "update_lane_message": "Update the status of a lane message, such as closing or acknowledging it.",
    "list_lane_messages": "List lane messages for the active or requested task, optionally filtered by lane, direction, or status.",
    "list_lane_briefs": "List structured orchestrator-to-worker brief messages for the active or requested task.",
    "get_plan_cursor": "Fetch the durable plan-dispatch cursor for a specific task-plan item.",
    "list_plan_cursors": "List durable plan-dispatch cursor rows for the active or requested task, optionally filtered by state or lane.",
    "upsert_plan_cursor": "Create or update a durable task-plan cursor row recording dispatch, completion, skip, or escalation state; optionally enforce a clean-slice gate before the update.",
    "record_review_finding": "Record or reopen a review finding for a task with stable finding IDs, optional line metadata, and optional review_mode classification.",
    "update_review_finding": "Mark a review finding fixed, deferred, wontfix, or reopen it with notes.",
    "reopen_review_finding": "Reopen a previously closed review finding with a reopen reason.",
    "list_review_findings": "List review findings for the active or requested task, optionally filtered by status, severity, or review_mode.",
    "get_review_finding": "Fetch a single review finding by stable finding ID or database ID.",
    "get_review_findings_summary": "Return aggregate counts of review findings by status and severity for the active or requested task, optionally scoped by review_mode.",
    "reconcile_review_findings": "Compare open findings against current files and return a reconciliation summary for review workflows.",
    "handoff_close_check": "Evaluate whether a task is ready to close based on open blockers, pending actions, open findings, lane state, and optional fresh-test requirements for the current commit.",
    "generate_current_task_md": "Generate CURRENT_TASK.md from handoff state for the active or requested task.",
    "export_handoff_state": "Export the task handoff state to a portable JSON snapshot.",
    "import_handoff_state": "Import a previously exported handoff state snapshot into the local database.",
    "archive_task_state": "Archive completed task state from the live handoff tables into archive storage.",
    "switch_task": "Switch the active task in one step: auto-archives the outgoing task and activates the target, restoring its objective from the archive if available.",
    "get_handoff_dashboard": "Return a broader handoff dashboard view across task state, lanes, findings, blockers, and reports.",
    "orchestrator_start": "Start the orchestrator daemon for the authoritative checkout and return its PID and lock path.",
    "orchestrator_status": "Return orchestrator daemon runtime status, including pause state, PID, last event, and cycle count.",
    "orchestrator_stop": "Stop the orchestrator daemon with SIGTERM, or SIGKILL when force=true.",
    "orchestrator_pause": "Pause the orchestrator daemon by creating the standard pause sentinel on the authoritative host.",
    "orchestrator_resume": "Resume the orchestrator daemon by clearing the standard pause sentinel on the authoritative host.",
    "worker_start": "Start a lane worker daemon for a specific task and lane, returning PID, lock path, and log path.",
    "worker_status": "Return runtime status for a lane worker daemon, including lock/process/log metadata.",
    "worker_event_history": "Return recent worker-daemon JSONL events for a lane, with optional event-name filtering.",
    "worker_stop": "Stop a lane worker daemon with SIGTERM, or SIGKILL when force=true.",
    "worker_resume": "Resume a stopped lane worker daemon with SIGCONT.",
    "worker_start_all": "Start worker daemons for all lanes declared in the task manifest and return per-lane results.",
    "run_structured_turn": "Execute one synchronous structured bridge turn through a registered non-CLI backend.",
    "orchestrator_single_cycle": "Run one complete orchestrator cycle synchronously (dispatch, poll, intake, verify) and return the result.",
    "dispatch_lane_work": "Update lane dispatch parameters (model, backend, effort) for the next execution cycle.",
    "list_available_backends": "List supported execution backends and their capabilities.",
    "record_artifact": "Index a large artifact (log, doc, payload, output) in the sidecar FTS5 database for later scoped retrieval.",
    "search_artifacts": "Search indexed artifact chunks by relevance with optional task/lane/app/source filters and BM25 ranking.",
    "get_artifact_source": "Return the full artifact source record for exact inspection by source_id or task_ref+source_label.",
    "get_artifact_terms": "Return suggested retrieval query terms for a freshly indexed artifact source by extracting its most distinctive words.",
    "list_artifact_sources": "List indexed artifact sources so operators and prompts can discover available evidence without reading raw content.",
    "purge_artifacts": "Delete artifact sources and their FTS chunks to keep the sidecar database bounded after task archival, lane closure, or age-based expiry.",
    "search_handoff": "Search canonical handoff records (decisions, findings, blockers, actions) by keyword with BM25 ranking and optional task/lane/type scope filters.",
    "get_metrics_summary": "Return an ACE metrics snapshot for the active task covering token burn, context pressure, FTS5 retrieval, lane health, phase timing, and documentation fitness.",
}


def _apply_tool_descriptions() -> None:
    for name, description in TOOL_DESCRIPTIONS.items():
        tool = globals().get(name)
        if tool is None:
            continue
        existing = getattr(tool, "__doc__", None)
        if existing and existing.strip():
            continue
        tool.__doc__ = description


def generate_current_task_md(
    task_ref: str | None = None,
    write_file: bool = True,
    related_task_refs: str | None = None,
) -> str:
    """Generate CURRENT_TASK.md for the active task.

    Args:
        task_ref: The task to render. Defaults to the active task.
        write_file: Write the markdown to disk.
        related_task_refs: Comma-separated task_ref values whose open review
            findings should also appear in the output, grouped under
            "Related Open Review Findings".
    """
    raw_state = core._invoke_tool(
        get_handoff_state,
        task_ref=task_ref,
        top_n_blockers=50,
        top_n_actions=50,
        top_n_decisions=50,
        top_n_tests=50,
        top_n_findings=100,
        verbose=True,
    )
    state = json.loads(raw_state)

    if related_task_refs:
        refs = [r.strip() for r in related_task_refs.split(",") if r.strip()]
        active_ref = state.get("task_ref", "")
        refs = [r for r in refs if r != active_ref]
        if refs:
            state["related_findings_open"] = core._fetch_related_open_findings(refs)

    markdown = core._render_current_task_md(state)
    current_task_path = get_runtime_config().current_task_path

    if write_file:
        current_task_path.write_text(markdown)

    return core._json_response(
        {
            "ok": True,
            "task_ref": state.get("task_ref"),
            "path": str(current_task_path),
            "written": write_file,
            "markdown": markdown if not write_file else None,
        }
    )


def _scripts_mcp_dir() -> Path:
    return Path(__file__).resolve().parent / "orchestration"


def _import_scripts_mcp_module(name: str) -> Any:
    scripts_dir = _scripts_mcp_dir()
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    return importlib.import_module(name)


def _handoff_pythonpath() -> str:
    package_root = Path(__file__).resolve().parents[4]
    pythonpath_parts = [
        str(package_root / "packages" / "agent-handoff-mcp" / "src"),
        str(package_root / "packages" / "codex-subagent-bridge" / "src"),
    ]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        pythonpath_parts.append(existing)
    return ":".join(part for part in pythonpath_parts if part)


def _orchestrator_paths() -> dict[str, Path]:
    config = get_runtime_config()
    state_dir = config.workspace_root / ".task-state"
    return {
        "workspace_root": config.workspace_root,
        "state_dir": state_dir,
        "lock_path": state_dir / "orchestrator.lock",
        "pause_path": state_dir / "daemon-paused",
        "log_dir": config.workspace_root / "logs" / "daemon",
        "log_path": config.workspace_root / "logs" / "daemon" / "orchestrator.jsonl",
        "script_path": Path(__file__).resolve().parent / "orchestration" / "orchestrator_daemon.py",
    }


def _worker_paths() -> dict[str, Path]:
    config = get_runtime_config()
    state_dir = config.workspace_root / ".task-state"
    log_dir = config.workspace_root / "logs" / "worker-daemon"
    return {
        "workspace_root": config.workspace_root,
        "state_dir": state_dir,
        "log_dir": log_dir,
        "script_path": Path(__file__).resolve().parent / "orchestration" / "worker_daemon.py",
    }


def _worker_lane_config(task_ref: str, lane_id: str) -> dict[str, Any]:
    lane_manifest = _import_scripts_mcp_module("lane_manifest")
    lane = lane_manifest.get_lane_config(task_ref, lane_id, orchestrator_root=str(get_runtime_config().workspace_root))
    if not isinstance(lane, dict):
        raise RuntimeError(f"Lane '{lane_id}' is not defined in the manifest for task '{task_ref}'.")
    return lane


def _read_lock_pid(lock_path: Path) -> int | None:
    if not lock_path.exists():
        return None
    try:
        payload = json.loads(lock_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    pid = payload.get("pid")
    return int(pid) if isinstance(pid, int) or isinstance(pid, str) and str(pid).isdigit() else None


def _pid_is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _last_log_event(log_path: Path) -> dict[str, Any] | None:
    if not log_path.exists():
        return None
    try:
        for line in reversed(log_path.read_text().splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
    except OSError:
        return None
    return None


def _count_log_events(log_path: Path, event_name: str) -> int:
    if not log_path.exists():
        return 0
    try:
        count = 0
        for line in log_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("event") == event_name:
                count += 1
        return count
    except OSError:
        return 0


def orchestrator_start(
    task_ref: str,
    backend: str = "codex-cli",
    poll_interval: int = 60,
    single_pass: bool = False,
    worker_start_mode: str = "mcp",
    worker_reasoning_effort: str = "auto",
    model: str | None = None,
) -> str:
    paths = _orchestrator_paths()
    try:
        backend_registry = _import_scripts_mcp_module("backend_registry")
        backend_name = backend_registry.validate_backend(backend)
    except RuntimeError as exc:
        return core._json_response({"ok": False, "error": str(exc)})

    existing_pid = _read_lock_pid(paths["lock_path"])
    if _pid_is_running(existing_pid):
        return core._json_response(
            {
                "ok": False,
                "error": "Orchestrator daemon is already running.",
                "pid": existing_pid,
                "lock_path": str(paths["lock_path"]),
            }
        )

    env = dict(os.environ)
    env["PYTHONPATH"] = _handoff_pythonpath()
    cmd = [
        sys.executable,
        str(paths["script_path"]),
        "run",
        "--orchestrator-root",
        str(paths["workspace_root"]),
        "--task-ref",
        task_ref,
        "--backend",
        backend_name,
        "--poll-interval",
        str(poll_interval),
        "--worker-start-mode",
        worker_start_mode,
        "--worker-reasoning-effort",
        worker_reasoning_effort,
    ]
    if model:
        cmd.extend(["--model", model])
    if single_pass:
        cmd.append("--single-pass")
    log_dir = paths["log_dir"]
    log_dir.mkdir(parents=True, exist_ok=True)
    stderr_fh = (log_dir / "orchestrator.stderr").open("a")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(paths["workspace_root"]),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_fh,
            start_new_session=True,
        )
    finally:
        stderr_fh.close()
    return core._json_response(
        {
            "ok": True,
            "pid": proc.pid,
            "lock_path": str(paths["lock_path"]),
            "backend": backend_name,
            "single_pass": single_pass,
            "worker_start_mode": worker_start_mode,
            "worker_reasoning_effort": worker_reasoning_effort,
        }
    )


def orchestrator_status() -> str:
    paths = _orchestrator_paths()
    orchestrator_daemon = _import_scripts_mcp_module("orchestrator_daemon")
    status = orchestrator_daemon.daemon_status(paths["state_dir"], paths["log_dir"])
    pid = None
    lock_info = status.get("lock")
    if isinstance(lock_info, dict):
        raw_pid = lock_info.get("pid")
        if isinstance(raw_pid, int) or isinstance(raw_pid, str) and str(raw_pid).isdigit():
            pid = int(raw_pid)
    running = _pid_is_running(pid)
    last_event = _last_log_event(paths["log_path"])
    task_ref = None
    if isinstance(last_event, dict):
        raw_task_ref = last_event.get("task_ref")
        if isinstance(raw_task_ref, str) and raw_task_ref.strip():
            task_ref = raw_task_ref
    return core._json_response(
        {
            "ok": True,
            "running": running,
            "pid": pid,
            "task_ref": task_ref,
            "cycle_count": _count_log_events(paths["log_path"], "cycle_end"),
            "last_event": last_event,
            "paused": bool(status.get("paused")),
            "lock_path": str(paths["lock_path"]),
            "status": status,
        }
    )


def orchestrator_pause() -> str:
    paths = _orchestrator_paths()
    orchestrator_daemon = _import_scripts_mcp_module("orchestrator_daemon")
    orchestrator_daemon.daemon_pause(paths["state_dir"])
    return core._json_response(
        {
            "ok": True,
            "paused": True,
            "pause_path": str(paths["pause_path"]),
        }
    )


def orchestrator_resume() -> str:
    paths = _orchestrator_paths()
    orchestrator_daemon = _import_scripts_mcp_module("orchestrator_daemon")
    orchestrator_daemon.daemon_resume(paths["state_dir"])
    return core._json_response(
        {
            "ok": True,
            "paused": False,
            "pause_path": str(paths["pause_path"]),
        }
    )


def orchestrator_stop(force: bool = False, wait_seconds: float = 5.0) -> str:
    paths = _orchestrator_paths()
    pid = _read_lock_pid(paths["lock_path"])
    if not _pid_is_running(pid):
        return core._json_response(
            {
                "ok": True,
                "running": False,
                "pid": pid,
                "exit_code": None,
            }
        )

    sig = signal.SIGKILL if force else signal.SIGTERM
    os.kill(pid, sig)
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            return core._json_response(
                {
                    "ok": True,
                    "running": False,
                    "pid": pid,
                    "exit_code": -int(sig),
                }
            )
        time.sleep(0.05)
    return core._json_response(
        {
            "ok": False,
            "error": f"Orchestrator daemon did not exit after {signal.Signals(sig).name}.",
            "running": True,
            "pid": pid,
        }
    )


def orchestrator_single_cycle(
    task_ref: str,
    backend: str = "codex-cli",
    dry_run: bool = False,
    timeout_seconds: float = 300.0,
    worker_start_mode: str = "mcp",
    worker_reasoning_effort: str = "auto",
    model: str | None = None,
) -> str:
    """Run one orchestrator cycle synchronously (dispatch, poll, intake, verify)."""
    paths = _orchestrator_paths()
    try:
        backend_registry = _import_scripts_mcp_module("backend_registry")
        backend_name = backend_registry.validate_backend(backend)
    except RuntimeError as exc:
        return core._json_response({"ok": False, "error": str(exc)})

    env = dict(os.environ)
    env["PYTHONPATH"] = _handoff_pythonpath()
    cmd = [
        sys.executable,
        str(paths["script_path"]),
        "run",
        "--orchestrator-root",
        str(paths["workspace_root"]),
        "--task-ref",
        task_ref,
        "--backend",
        backend_name,
        "--worker-start-mode",
        worker_start_mode,
        "--worker-reasoning-effort",
        worker_reasoning_effort,
        "--single-pass",
    ]
    if model:
        cmd.extend(["--model", model])
    if dry_run:
        cmd.append("--dry-run")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(paths["workspace_root"]),
            env=env,
            capture_output=True,
            text=True,
            timeout=max(timeout_seconds, 1.0),
        )
    except subprocess.TimeoutExpired:
        return core._json_response(
            {
                "ok": False,
                "error": f"Orchestrator single cycle timed out after {timeout_seconds} seconds.",
            }
        )
    return core._json_response(
        {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "backend": backend_name,
            "dry_run": dry_run,
            "worker_start_mode": worker_start_mode,
            "worker_reasoning_effort": worker_reasoning_effort,
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }
    )


def worker_start(
    task_ref: str,
    lane_id: str,
    backend: str = "codex-subagent",
    poll_interval: int = 30,
    single_pass: bool = False,
    session: str | None = None,
    session_mode: str = "fresh_turn",
    reasoning_effort: str = "inherit",
    model: str | None = None,
) -> str:
    paths = _worker_paths()
    try:
        backend_registry = _import_scripts_mcp_module("backend_registry")
        backend_name = backend_registry.validate_backend(backend)
        lane = _worker_lane_config(task_ref, lane_id)
        worker_daemon_ctl = _import_scripts_mcp_module("worker_daemon_ctl")
    except RuntimeError as exc:
        return core._json_response({"ok": False, "error": str(exc)})

    worktree_path = Path(str(lane.get("worktree_path") or "")).expanduser().resolve()
    if not worktree_path.exists():
        return core._json_response(
            {
                "ok": False,
                "error": f"Lane worktree does not exist for lane '{lane_id}': {worktree_path}",
            }
        )

    payload = worker_daemon_ctl.daemon_start(
        orchestrator_root=paths["workspace_root"],
        state_dir=paths["state_dir"],
        log_dir=paths["log_dir"],
        task_ref=task_ref,
        lane_id=lane_id,
        worktree_path=worktree_path,
        session=session or f"{task_ref}-{lane_id}",
        python_executable=sys.executable,
        pythonpath=_handoff_pythonpath(),
        backend=backend_name,
        session_mode=session_mode,
        reasoning_effort=reasoning_effort,
        model=model,
        poll_interval=poll_interval,
        single_pass=single_pass,
    )
    return core._json_response(payload)


def worker_status(task_ref: str, lane_id: str) -> str:
    paths = _worker_paths()
    worker_daemon_ctl = _import_scripts_mcp_module("worker_daemon_ctl")
    payload = worker_daemon_ctl.daemon_status(
        state_dir=paths["state_dir"],
        log_dir=paths["log_dir"],
        lane_id=lane_id,
        task_ref=task_ref,
    )
    process = payload.get("process")
    running = isinstance(process, dict) and isinstance(process.get("pid"), int)
    payload["running"] = running
    payload["ok"] = True
    return core._json_response(payload)


def worker_event_history(
    task_ref: str,
    lane_id: str,
    limit: int = 50,
    event_name: str | None = None,
) -> str:
    paths = _worker_paths()
    worker_daemon_ctl = _import_scripts_mcp_module("worker_daemon_ctl")
    payload = worker_daemon_ctl.daemon_event_history(
        state_dir=paths["state_dir"],
        log_dir=paths["log_dir"],
        lane_id=lane_id,
        task_ref=task_ref,
        limit=limit,
        event_name=event_name,
    )
    process = payload.get("process")
    payload["running"] = isinstance(process, dict) and isinstance(process.get("pid"), int)
    payload["ok"] = True
    return core._json_response(payload)


def worker_stop(task_ref: str, lane_id: str, force: bool = False) -> str:
    paths = _worker_paths()
    worker_daemon_ctl = _import_scripts_mcp_module("worker_daemon_ctl")
    payload = worker_daemon_ctl.daemon_stop(
        state_dir=paths["state_dir"],
        log_dir=paths["log_dir"],
        lane_id=lane_id,
        task_ref=task_ref,
        force=force,
    )
    return core._json_response(payload)


def worker_resume(task_ref: str, lane_id: str) -> str:
    paths = _worker_paths()
    worker_daemon_ctl = _import_scripts_mcp_module("worker_daemon_ctl")
    payload = worker_daemon_ctl.daemon_resume(
        state_dir=paths["state_dir"],
        log_dir=paths["log_dir"],
        lane_id=lane_id,
        task_ref=task_ref,
    )
    return core._json_response(payload)


def worker_start_all(
    task_ref: str,
    backend: str = "codex-subagent",
    poll_interval: int = 30,
    single_pass: bool = False,
    session_mode: str = "fresh_turn",
    reasoning_effort: str = "inherit",
    model: str | None = None,
) -> str:
    try:
        lane_manifest = _import_scripts_mcp_module("lane_manifest")
        orchestrator_lanes = _import_scripts_mcp_module("orchestrator_lanes")
        merge_order_fn = getattr(lane_manifest, "merge_order", None)
        manifest_order = merge_order_fn(task_ref) if callable(merge_order_fn) else []
        lane_ids = manifest_order or lane_manifest.list_lanes(task_ref)
    except RuntimeError as exc:
        return core._json_response({"ok": False, "error": str(exc)})

    results: list[dict[str, Any]] = []
    for lane_id in lane_ids:
        blocked_by: list[str] = []
        if lane_id in manifest_order:
            lane_index = manifest_order.index(lane_id)
            dependency_error: dict[str, Any] | None = None
            for upstream_lane in manifest_order[:lane_index]:
                try:
                    has_capacity = bool(orchestrator_lanes._lane_has_capacity(task_ref, upstream_lane))
                except RuntimeError as exc:
                    dependency_error = {
                        "ok": False,
                        "lane_id": lane_id,
                        "error": f"dependency check failed for upstream lane '{upstream_lane}': {exc}",
                    }
                    break
                if not has_capacity:
                    blocked_by.append(upstream_lane)
            if dependency_error is not None:
                results.append(dependency_error)
                continue
        if blocked_by:
            results.append(
                {
                    "ok": True,
                    "lane_id": lane_id,
                    "started": False,
                    "skipped": True,
                    "reason": "unresolved_upstream_dependencies",
                    "blocked_by": blocked_by,
                }
            )
            continue
        try:
            result = json.loads(
                worker_start(
                    task_ref=task_ref,
                    lane_id=lane_id,
                    backend=backend,
                    poll_interval=poll_interval,
                    single_pass=single_pass,
                    session_mode=session_mode,
                    reasoning_effort=reasoning_effort,
                    model=model,
                )
            )
        except Exception as exc:
            result = {
                "ok": False,
                "lane_id": lane_id,
                "error": f"worker_start raised {type(exc).__name__}: {exc}",
            }
        results.append(result)
    return core._json_response(
        {
            "ok": all(bool(item.get("ok")) for item in results),
            "task_ref": task_ref,
            "backend": backend,
            "session_mode": session_mode,
            "reasoning_effort": reasoning_effort,
            "results": results,
        }
    )


def run_structured_turn(
    prompt: str,
    schema: dict[str, Any],
    cwd: str,
    backend: str = "codex-subagent",
    env: dict[str, str] | None = None,
    timeout_seconds: float = 120.0,
) -> str:
    try:
        backend_registry = _import_scripts_mcp_module("backend_registry")
        backend_name = backend_registry.validate_backend(backend)
        spec = backend_registry.get_backend_spec(backend_name)
        if spec.kind == "cli":
            return core._json_response(
                {
                    "ok": False,
                    "error": "CLI backends are not supported for synchronous MCP turns. Use orchestrator_start or a worker daemon instead.",
                }
            )
        runner = backend_registry.resolve_bridge(backend_name)
    except RuntimeError as exc:
        return core._json_response({"ok": False, "error": str(exc)})

    runner_kwargs: dict[str, Any] = {
        "prompt": prompt,
        "schema": schema,
        "cwd": cwd,
    }
    if env is not None:
        runner_kwargs["env"] = env

    def _invoke_runner() -> Any:
        try:
            return runner(**runner_kwargs)
        except TypeError as exc:
            if env is None or "env" not in str(exc):
                raise
            retry_kwargs = dict(runner_kwargs)
            retry_kwargs.pop("env", None)
            return runner(**retry_kwargs)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_invoke_runner)
            payload = future.result(timeout=max(timeout_seconds, 0.0))
    except concurrent.futures.TimeoutError:
        return core._json_response(
            {
                "ok": False,
                "error": f"Structured turn timed out after {timeout_seconds} seconds.",
                "backend": backend,
            }
        )
    except RuntimeError as exc:
        return core._json_response({"ok": False, "error": str(exc), "backend": backend})
    except TypeError as exc:
        return core._json_response({"ok": False, "error": str(exc), "backend": backend})

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            return core._json_response(
                {
                    "ok": False,
                    "error": f"{backend_name} backend returned invalid JSON: {exc}",
                    "backend": backend_name,
                }
            )
    if not isinstance(payload, dict):
        return core._json_response(
            {
                "ok": False,
                "error": f"{backend_name} backend returned non-object payload: {type(payload).__name__}",
                "backend": backend_name,
            }
        )
    return core._json_response({"ok": True, "backend": backend_name, "result": payload})


def dispatch_lane_work(
    lane_id: str,
    model: str | None = None,
    backend: str | None = None,
    reasoning_effort: str | None = None,
    task_ref: str | None = None,
    start_worker: bool = False,
) -> str:
    with core._get_db_connection() as conn:
        resolved_task_ref = core._resolve_task_ref(conn, task_ref)
        lane_row = core._get_lane_row(conn, resolved_task_ref, lane_id)
        if lane_row is None:
            return core._json_response({"ok": False, "error": f"Lane '{lane_id}' not found."})

        result = core.upsert_worktree_lane(
            lane_id=lane_id,
            worktree_path=lane_row["worktree_path"],
            branch=lane_row["branch"],
            title=lane_row["title"],
            objective=lane_row["objective"],
            owner_agent=lane_row["owner_agent"],
            model=model,
            backend=backend,
            reasoning_effort=reasoning_effort,
            status=lane_row["status"],
            notes=lane_row["notes"],
            task_ref=resolved_task_ref,
        )
        if start_worker:
            worker_start(
                task_ref=resolved_task_ref,
                lane_id=lane_id,
                backend=backend or lane_row["backend"] or "codex-subagent",
                model=model or lane_row["model"],
                reasoning_effort=reasoning_effort or lane_row["reasoning_effort"] or "inherit",
            )
        return result


def list_available_backends() -> str:
    try:
        backend_registry = _import_scripts_mcp_module("backend_registry")
        backends = {}
        for name, spec in backend_registry.BACKENDS.items():
            backends[name] = {
                "kind": spec.kind,
                "description": spec.description,
                "supports_reasoning_effort": spec.capabilities.supports_reasoning_effort,
                "supports_sync_turn": spec.capabilities.supports_sync_turn,
            }
        return core._json_response({"ok": True, "backends": backends})
    except Exception as exc:
        return core._json_response({"ok": False, "error": str(exc)})


def get_metrics_summary(
    task_ref: str | None = None,
    output_format: str = "markdown",
) -> str:
    """Return an ACE metrics snapshot for the active task."""
    try:
        from agent_handoff_mcp.orchestration.ace_metrics import (  # noqa: PLC0415
            build_snapshot,
            render_markdown,
        )
    except ImportError as exc:
        return core._json_response({"ok": False, "error": f"ace_metrics module unavailable: {exc}"})

    paths = _orchestrator_paths()
    workspace_root = paths["workspace_root"]
    state_dir = paths["state_dir"]
    logs_dir = workspace_root / "logs"

    resolved_task_ref = task_ref
    if not resolved_task_ref:
        try:
            with core._get_db_connection() as conn:
                resolved_task_ref = core._resolve_task_ref(conn, None)
        except Exception:
            resolved_task_ref = "unknown"

    instruction_files = [workspace_root / "docs/agentic/instructions.md"]

    try:
        snapshot = build_snapshot(
            task_ref=resolved_task_ref,
            state_dir=state_dir,
            logs_dir=logs_dir,
            instruction_files=instruction_files,
        )
        if output_format == "json":
            return core._json_response({"ok": True, "snapshot": snapshot})
        return render_markdown(snapshot)
    except Exception as exc:
        return core._json_response({"ok": False, "error": str(exc)})


def build_handoff_mcp(config: RuntimeConfig) -> FastMCP:
    configure_runtime(config)
    mcp = FastMCP(
        "Agent Handoff MCP",
        instructions=(
            "You are connected to the Agent Handoff MCP server. "
            "Use these tools for task state, review findings, exports, and close checks."
        ),
    )
    _apply_tool_descriptions()
    for tool in [
        set_handoff_state,
        get_handoff_state,
        upsert_worktree_lane,
        close_worktree_lane,
        list_worktree_lanes,
        get_lane_activity,
        list_next_actions,
        record_decision,
        update_next_actions,
        record_test_result,
        report_blocker,
        record_worker_report,
        record_lane_brief,
        list_worker_reports,
        record_lane_message,
        update_lane_message,
        list_lane_messages,
        list_lane_briefs,
        get_plan_cursor,
        list_plan_cursors,
        upsert_plan_cursor,
        record_review_finding,
        update_review_finding,
        reopen_review_finding,
        list_review_findings,
        get_review_finding,
        get_review_findings_summary,
        reconcile_review_findings,
        handoff_close_check,
        generate_current_task_md,
        export_handoff_state,
        import_handoff_state,
        archive_task_state,
        switch_task,
        get_handoff_dashboard,
        orchestrator_start,
        orchestrator_status,
        orchestrator_stop,
        orchestrator_pause,
        orchestrator_resume,
        orchestrator_single_cycle,
        worker_start,
        worker_status,
        worker_event_history,
        worker_stop,
        worker_resume,
        worker_start_all,
        run_structured_turn,
        dispatch_lane_work,
        list_available_backends,
        record_artifact,
        search_artifacts,
        get_artifact_source,
        get_artifact_terms,
        list_artifact_sources,
        purge_artifacts,
        search_handoff,
        get_metrics_summary,
    ]:
        mcp.add_tool(tool)
    return mcp


def run_doctor(config: RuntimeConfig) -> dict[str, Any]:
    configure_runtime(config)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    config.exports_dir.mkdir(parents=True, exist_ok=True)

    # FTS5 availability check - hard requirement for artifact indexing
    import sqlite3 as _sqlite3
    with _sqlite3.connect(":memory:") as _fts5_probe:
        try:
            _fts5_probe.execute(
                "CREATE VIRTUAL TABLE _fts5_test USING fts5(body)"
            )
            _fts5_probe.execute("DROP TABLE IF EXISTS _fts5_test")
            fts5_available = True
        except _sqlite3.OperationalError:
            fts5_available = False
    if not fts5_available:
        raise RuntimeError(
            "SQLite FTS5 extension is not available on this system. "
            "agent-handoff-mcp artifact indexing requires FTS5. "
            "Rebuild SQLite with SQLITE_ENABLE_FTS5 or use a Python distribution "
            "that bundles FTS5 (e.g. system Python on macOS 10.15+ or major Linux distros)."
        )

    writable_probe = config.state_dir / ".write-test"
    writable_probe.write_text("ok")
    writable_probe.unlink()
    _FTS_TABLES = ("decisions_fts", "findings_fts", "blockers_fts", "actions_fts")
    handoff_fts_check: dict[str, Any] = {}
    with core._get_db_connection() as conn:
        conn.execute("SELECT 1").fetchone()
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?,?)",
                _FTS_TABLES,
            ).fetchall()
        }
        table_counts: dict[str, int] = {}
        for tbl in _FTS_TABLES:
            if tbl in existing:
                count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]  # noqa: S608
                table_counts[tbl] = count
            else:
                table_counts[tbl] = -1  # -1 signals table missing

        handoff_fts_check = {
            "ok": all(v >= 0 for v in table_counts.values()),
            "tables": table_counts,
        }

    package_src = Path(__file__).resolve().parents[1]
    launcher = package_src / "agent_handoff_mcp_launcher.py"
    stdio_tools: list[str] = []
    with tempfile.TemporaryDirectory() as temp_dir:

        async def _list_tools() -> list[str]:
            transport = PythonStdioTransport(
                script_path=launcher,
                args=["--workspace-root", str(config.workspace_root), "serve-stdio"],
                cwd=str(config.workspace_root),
                python_cmd=sys.executable,
                log_file=Path(temp_dir) / "doctor-stdio.log",
            )
            async with Client(transport) as client:
                tools = await client.list_tools()
                return sorted(tool.name for tool in tools)

        stdio_tools = asyncio.run(_list_tools())

        cli_env = dict(**os.environ)
        cli_env["PYTHONPATH"] = _handoff_pythonpath()
        cli_probe = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_handoff_mcp",
                "--workspace-root",
                str(config.workspace_root),
                "state",
            ],
            cwd=str(config.workspace_root),
            env=cli_env,
            capture_output=True,
            text=True,
            check=True,
        )
        json.loads(cli_probe.stdout)

    return {
        "ok": True,
        "workspace_root": str(config.workspace_root),
        "state_dir": str(config.state_dir),
        "db_path": str(config.db_path),
        "artifact_db_path": str(config.artifact_db_path),
        "current_task_path": str(config.current_task_path),
        "exports_dir": str(config.exports_dir),
        "checks": {
            "sqlite": True,
            "fts5_available": True,
            "state_dir_writable": True,
            "handoff_fts_index": handoff_fts_check,
            "stdio_startup": {
                "ok": True,
                "tool_count": len(stdio_tools),
            },
            "cli_fallback_startup": True,
        },
    }
