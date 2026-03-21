#!/usr/bin/env python3
"""Polling live dashboard for lane worker health.

Usage:
    python3 scripts/mcp/dashboard_live.py \\
        --orchestrator-root . \\
        --task-ref <task-ref> \\
        [--lanes frontend backend-domain] \\
        [--interval 10] \\
        [--once]

Prints a compact status table for each lane on each poll cycle.
Press Ctrl-C or pass --once to exit after the first render.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


# ---------------------------------------------------------------------------
# MCP helpers
# ---------------------------------------------------------------------------


def _mcp_worker_status(
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
) -> dict[str, Any]:
    """Return daemon_status dict for a lane by calling worker_daemon_ctl.py."""
    state_dir = orchestrator_root / ".task-state"
    log_dir = orchestrator_root / "logs" / "worker-daemon"
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "worker_daemon_ctl.py"),
        "status",
        "--state-dir", str(state_dir),
        "--log-dir", str(log_dir),
        "--lane-id", lane_id,
        "--task-ref", task_ref,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return {"lane_id": lane_id, "worker_state": "unknown", "state_summary": "Could not retrieve status."}


# ---------------------------------------------------------------------------
# Lane discovery
# ---------------------------------------------------------------------------


def _resolve_lane_ids(
    orchestrator_root: Path,
    task_ref: str,
    requested: list[str] | None,
) -> list[str]:
    """Return the lane IDs to display: explicit list, or all from manifest."""
    if requested:
        return list(requested)
    try:
        from lane_manifest import load_manifest
        manifest = load_manifest(task_ref)
        lanes = manifest.get("lanes", {})
        if isinstance(lanes, dict):
            return sorted(lanes.keys())
    except Exception:  # noqa: BLE001
        pass
    return []


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_STATE_SYMBOLS: dict[str, str] = {
    "executing": "[EXEC]",
    "reviewing": "[REVW]",
    "verifying": "[VRFY]",
    "handoff": "[HNDOFF]",
    "waiting_for_orchestrator": "[WAIT]",
    "idle": "[IDLE]",
    "starting": "[START]",
    "stopped": "[STOP]",
    "handoff_failed": "[FAIL]",
    "paused": "[PAUSE]",
    "unknown": "[???]",
}


def _summarize(status: dict[str, Any]) -> dict[str, Any]:
    """Extract the display-relevant fields from a daemon_status dict."""
    state = str(status.get("worker_state") or "unknown")
    attention = bool(status.get("attention_required"))
    summary = str(status.get("state_summary") or "")[:80]
    process = status.get("process")
    pid = process.get("pid") if isinstance(process, dict) else None
    obs = status.get("observability")
    history = (obs.get("history") or []) if isinstance(obs, dict) else []
    cumulative_tokens = sum(
        int((e.get("token_usage_totals") or {}).get("total_tokens") or 0)
        for e in history
        if isinstance(e, dict)
    )
    # Model and effort from latest observability entry
    latest_obs = (obs.get("latest") or {}) if isinstance(obs, dict) else {}
    model = str(latest_obs.get("model") or "") or "-"
    effort = str(latest_obs.get("effective_reasoning_effort") or "") or "-"
    last_event = status.get("last_event")
    last_ts = (
        str(last_event.get("ts") or "")[:19].replace("T", " ")
        if isinstance(last_event, dict)
        else ""
    )
    streak_info = None
    status_record = status.get("status_record")
    if isinstance(status_record, dict):
        streak_info = status_record.get("exhaustion_streak")
    streak = (
        int(streak_info.get("count") or 0) if isinstance(streak_info, dict) else 0
    )
    # Context pressure from context_utilization_latest or latest observability
    ctx_util = status.get("context_utilization_latest")
    if not isinstance(ctx_util, dict):
        ctx_util = latest_obs.get("context_utilization")
    pressure = str((ctx_util or {}).get("pressure") or "normal")
    # Stale-lock: lock file exists but process is not running
    lock_path = status.get("lock_path")
    stale_lock = False
    if lock_path and not status.get("running"):
        try:
            stale_lock = Path(lock_path).exists()
        except Exception:  # noqa: BLE001
            pass
    # Composite health: unhealthy > attention > pressure > normal
    if state == "unhealthy" or stale_lock:
        health = "UNHEALTHY"
    elif attention or streak >= 2:
        health = "ATTENTION"
    elif pressure in ("elevated", "high"):
        health = "DEGRADED"
    else:
        health = "ok"
    return {
        "state": state,
        "symbol": _STATE_SYMBOLS.get(state, f"[{state[:5].upper()}]"),
        "attention": attention,
        "pid": pid,
        "summary": summary,
        "cumulative_tokens": cumulative_tokens,
        "last_ts": last_ts,
        "exhaustion_streak": streak,
        "model": model,
        "effort": effort,
        "pressure": pressure,
        "stale_lock": stale_lock,
        "health": health,
        "cycle": int(status_record.get("cycle") or 0) if isinstance(status_record, dict) else 0,
    }


def _format_table(
    task_ref: str,
    rows: list[tuple[str, dict[str, Any]]],
    ts: str,
) -> str:
    """Format lanes as a compact status table."""
    col_lane = max((len(lane_id) for lane_id, _ in rows), default=8)
    col_state = 9
    col_health = 9
    col_model = max((len(str(info.get("model") or "-")) for _, info in rows), default=5)
    col_model = max(col_model, 5)
    # header
    lines: list[str] = [
        f"--- dashboard-live  task={task_ref}  {ts} ---",
        f"{'LANE':<{col_lane}}  {'STATE':<{col_state}}  {'HEALTH':<{col_health}}  "
        f"{'PID':>6}  {'TOKENS':>8}  {'STK':>3}  {'CYC':>3}  {'PRES':<8}  "
        f"{'EFFORT':<8}  {'MODEL':<{col_model}}  SUMMARY",
        "-" * (col_lane + col_state + col_health + col_model + 64),
    ]
    for lane_id, info in rows:
        attn = "!" if info["attention"] else " "
        pid_str = str(info["pid"]) if info["pid"] else "-"
        tok_str = f"{info['cumulative_tokens']:,}" if info["cumulative_tokens"] else "-"
        streak_str = str(info["exhaustion_streak"]) if info["exhaustion_streak"] > 0 else "-"
        cycle_str = str(info.get("cycle") or 0)
        stale_mark = "[STALE-LOCK]" if info.get("stale_lock") else ""
        pressure_display = str(info.get("pressure") or "normal")
        effort_display = str(info.get("effort") or "-")[:8]
        health_display = str(info.get("health") or "ok")
        model_display = str(info.get("model") or "-")[:col_model]
        lines.append(
            f"{lane_id:<{col_lane}}{attn} {info['symbol']:<{col_state}}  "
            f"{health_display:<{col_health}}  "
            f"{pid_str:>6}  {tok_str:>8}  {streak_str:>3}  {cycle_str:>3}  "
            f"{pressure_display:<8}  {effort_display:<8}  "
            f"{model_display:<{col_model}}  "
            f"{stale_mark}{info['summary']}"
        )
    if not rows:
        lines.append("  (no lanes found)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------


def poll_lane_status(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_ids: list[str],
    interval: int,
    once: bool,
) -> None:
    """Continuously poll and display lane worker status."""
    while True:
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows: list[tuple[str, dict[str, Any]]] = []
        for lane_id in lane_ids:
            status = _mcp_worker_status(orchestrator_root, task_ref, lane_id)
            rows.append((lane_id, _summarize(status)))
        table = _format_table(task_ref, rows, now)
        # Clear screen (ANSI) then print
        print("\033[2J\033[H" + table, flush=True)
        if once:
            break
        time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live polling dashboard for lane worker health."
    )
    parser.add_argument(
        "--orchestrator-root", default=".",
        help="Path to the monorepo root (default: current directory).",
    )
    parser.add_argument("--task-ref", required=True, help="MCP task reference.")
    parser.add_argument(
        "--lanes", nargs="*", help="Lane IDs to display (default: all manifest lanes)."
    )
    parser.add_argument(
        "--interval", type=int, default=10,
        help="Poll interval in seconds (default: 10).",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Print once and exit instead of polling continuously.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    orchestrator_root = Path(args.orchestrator_root).expanduser().resolve()

    task_ref = str(
        args.task_ref or (orchestrator_root.parent.name if not args.task_ref else "")
    ).strip()
    if not task_ref:
        print("ERROR: --task-ref is required.", file=sys.stderr)
        return 1

    lane_ids = _resolve_lane_ids(orchestrator_root, task_ref, args.lanes or [])
    if not lane_ids:
        print(
            f"WARNING: No lanes found for task '{task_ref}'. Pass --lanes to specify explicitly.",
            file=sys.stderr,
        )
        # Carry on; the table will show "(no lanes found)"

    interval = max(1, int(args.interval or 10))

    try:
        poll_lane_status(
            orchestrator_root=orchestrator_root,
            task_ref=task_ref,
            lane_ids=lane_ids,
            interval=interval,
            once=args.once,
        )
    except KeyboardInterrupt:
        print("\ndashboard-live interrupted.", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
