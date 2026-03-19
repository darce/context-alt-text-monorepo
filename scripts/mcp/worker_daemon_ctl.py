#!/usr/bin/env python3
"""Control helpers for lane-scoped worker daemons."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any


def _lock_path(state_dir: Path, lane_id: str) -> Path:
    return state_dir / f"worker-{lane_id}.lock"


def _log_path(log_dir: Path, lane_id: str) -> Path:
    return log_dir / f"worker-{lane_id}.jsonl"


def _read_lock_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"held": False, "path": str(path)}
    if not path.exists():
        return info
    info["held"] = True
    raw = path.read_text(errors="replace").strip()
    if raw:
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                info.update(payload)
            else:
                info["raw"] = raw
        except json.JSONDecodeError:
            info["raw"] = raw
    return info


def _ps_info(pid: int) -> dict[str, Any] | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "pid=,ppid=,stat=,etime=,command="],
        capture_output=True,
        text=True,
        check=False,
    )
    line = result.stdout.strip()
    if result.returncode != 0 or not line:
        return None
    parts = line.split(None, 4)
    if len(parts) < 4:
        return {"pid": pid, "raw": line}
    info: dict[str, Any] = {
        "pid": int(parts[0]),
        "ppid": int(parts[1]),
        "stat": parts[2],
        "etime": parts[3],
        "command": parts[4] if len(parts) > 4 else "",
    }
    info["stopped"] = "T" in info["stat"]
    return info


def _find_worker_process(*, task_ref: str | None, lane_id: str) -> dict[str, Any] | None:
    pattern = f"worker_daemon.py.*--lane-id {lane_id}"
    if task_ref:
        pattern = f"worker_daemon.py.*--task-ref {task_ref}.*--lane-id {lane_id}"
    result = subprocess.run(
        ["pgrep", "-af", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    candidates: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if not parts or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        command = parts[1] if len(parts) == 2 else ""
        candidates.append({"pid": pid, "command": command})

    if not candidates:
        return None

    candidates.sort(key=lambda item: 1 if item["command"].startswith("/bin/sh -c") else 0)
    chosen = candidates[0]
    info = _ps_info(int(chosen["pid"]))
    if info is not None:
        info["pid_source"] = "process_scan"
    return info


def _child_pids(pid: int) -> list[int]:
    result = subprocess.run(
        ["pgrep", "-P", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]


def _process_tree(pid: int) -> list[int]:
    tree: list[int] = []
    for child in _child_pids(pid):
        tree.extend(_process_tree(child))
        tree.append(child)
    tree.append(pid)
    return tree


def _signal_tree(pid: int, sig: signal.Signals) -> list[int]:
    signaled: list[int] = []
    for target in _process_tree(pid):
        try:
            os.kill(target, sig)
        except ProcessLookupError:
            continue
        signaled.append(target)
    return signaled


def _last_log_event(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    for line in reversed(path.read_text(errors="replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def daemon_status(*, state_dir: Path, log_dir: Path, lane_id: str, task_ref: str | None = None) -> dict[str, Any]:
    lock = _read_lock_info(_lock_path(state_dir, lane_id))
    pid = lock.get("pid")
    process = _ps_info(int(pid)) if isinstance(pid, int) else None
    if process is not None:
        process["pid_source"] = "lock"
    if process is None:
        process = _find_worker_process(task_ref=task_ref, lane_id=lane_id)
    return {
        "lane_id": lane_id,
        "task_ref": task_ref,
        "lock": lock,
        "process": process,
        "stale_lock": bool(lock.get("held") and isinstance(pid, int) and process is None),
        "log_path": str(_log_path(log_dir, lane_id)),
        "last_event": _last_log_event(_log_path(log_dir, lane_id)),
    }


def daemon_start(
    *,
    orchestrator_root: Path,
    state_dir: Path,
    log_dir: Path,
    task_ref: str,
    lane_id: str,
    worktree_path: Path,
    session: str,
    python_executable: str,
    pythonpath: str | None = None,
    backend: str = "codex-cli",
    poll_interval: int = 30,
    single_pass: bool = False,
) -> dict[str, Any]:
    status = daemon_status(state_dir=state_dir, log_dir=log_dir, lane_id=lane_id, task_ref=task_ref)
    process = status.get("process")
    pid = process.get("pid") if isinstance(process, dict) else None
    if isinstance(pid, int):
        return {
            "ok": False,
            "message": f"Worker daemon is already running for lane '{lane_id}'.",
            "pid": pid,
            "lock_path": str(_lock_path(state_dir, lane_id)),
            "log_path": str(_log_path(log_dir, lane_id)),
            "status": status,
        }

    cmd = [
        python_executable,
        str(orchestrator_root / "scripts" / "mcp" / "worker_daemon.py"),
        "--orchestrator-root",
        str(orchestrator_root),
        "--task-ref",
        task_ref,
        "--lane-id",
        lane_id,
        "--session",
        session,
        "--worktree-path",
        str(worktree_path),
        "--backend",
        backend,
        "--poll-interval",
        str(poll_interval),
    ]
    if single_pass:
        cmd.append("--single-pass")

    env = dict(os.environ)
    if pythonpath:
        env["PYTHONPATH"] = pythonpath

    proc = subprocess.Popen(
        cmd,
        cwd=str(orchestrator_root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "ok": True,
        "pid": proc.pid,
        "lane_id": lane_id,
        "task_ref": task_ref,
        "session": session,
        "backend": backend,
        "poll_interval": poll_interval,
        "single_pass": single_pass,
        "worktree_path": str(worktree_path),
        "lock_path": str(_lock_path(state_dir, lane_id)),
        "log_path": str(_log_path(log_dir, lane_id)),
    }


def daemon_stop(*, state_dir: Path, log_dir: Path, lane_id: str, task_ref: str | None = None, force: bool = False) -> dict[str, Any]:
    status = daemon_status(state_dir=state_dir, log_dir=log_dir, lane_id=lane_id, task_ref=task_ref)
    process = status.get("process")
    pid = process.get("pid") if isinstance(process, dict) else None
    if not isinstance(pid, int):
        return {"ok": False, "message": f"No running worker daemon recorded for lane '{lane_id}'.", "signaled": []}
    sig = signal.SIGKILL if force else signal.SIGTERM
    signaled = _signal_tree(pid, sig)
    return {"ok": True, "message": f"Sent {sig.name} to worker daemon lane '{lane_id}'.", "signaled": signaled}


def daemon_resume(*, state_dir: Path, log_dir: Path, lane_id: str, task_ref: str | None = None) -> dict[str, Any]:
    status = daemon_status(state_dir=state_dir, log_dir=log_dir, lane_id=lane_id, task_ref=task_ref)
    process = status.get("process")
    pid = process.get("pid") if isinstance(process, dict) else None
    if not isinstance(pid, int):
        return {"ok": False, "message": f"No running worker daemon recorded for lane '{lane_id}'.", "signaled": []}
    signaled = _signal_tree(pid, signal.SIGCONT)
    return {"ok": True, "message": f"Sent SIGCONT to worker daemon lane '{lane_id}'.", "signaled": signaled}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect and control lane worker daemons.")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state-dir", required=True)
    common.add_argument("--log-dir", required=False)
    common.add_argument("--lane-id", required=True)
    common.add_argument("--task-ref")

    sub.add_parser("status", parents=[common])
    stop = sub.add_parser("stop", parents=[common])
    stop.add_argument("--force", action="store_true")
    sub.add_parser("resume", parents=[common])
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    state_dir = Path(args.state_dir).expanduser().resolve()
    log_dir = Path(args.log_dir).expanduser().resolve() if args.log_dir else state_dir.parent / "logs" / "worker-daemon"

    if args.command == "status":
        print(json.dumps(daemon_status(state_dir=state_dir, log_dir=log_dir, lane_id=args.lane_id, task_ref=args.task_ref), indent=2))
        return 0
    if args.command == "stop":
        result = daemon_stop(state_dir=state_dir, log_dir=log_dir, lane_id=args.lane_id, task_ref=args.task_ref, force=args.force)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.command == "resume":
        result = daemon_resume(state_dir=state_dir, log_dir=log_dir, lane_id=args.lane_id, task_ref=args.task_ref)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
