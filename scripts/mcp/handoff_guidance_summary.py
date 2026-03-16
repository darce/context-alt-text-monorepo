#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_handoff_mcp import RuntimeConfig, configure_runtime, list_lane_messages, list_worker_reports


def _json_load(payload: str) -> dict[str, Any]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError("Expected JSON object payload.")
    return data


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _summary_level(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("read-only", "sandbox", "writable temp", "postgresql", "permissionerror")):
        return "BLOCKED"
    if any(token in lowered for token in ("already resolved", "already covered", "already present", "no code changes were warranted")):
        return "REVIEW"
    return "GUIDANCE"


def _load_open_guidance(task_ref: str, lane_id: str | None = None) -> list[dict[str, Any]]:
    payload = _json_load(list_lane_messages(task_ref=task_ref, lane_id=lane_id, status="open", limit=200))
    rows = payload.get("messages", [])
    if not isinstance(rows, list):
        return []
    return [
        row for row in rows
        if isinstance(row, dict) and row.get("direction") == "worker_to_orchestrator"
    ]


def _load_recent_reports(task_ref: str, lane_id: str | None = None) -> dict[str, dict[str, Any]]:
    payload = _json_load(list_worker_reports(task_ref=task_ref, lane_id=lane_id, limit=50))
    rows = payload.get("reports", [])
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_lane = _normalize(row.get("lane_id"))
        if row_lane and row_lane not in result:
            result[row_lane] = row
    return result


def render_summary(task_ref: str, lane_id: str | None = None) -> str:
    messages = _load_open_guidance(task_ref, lane_id=lane_id)
    if not messages:
        return "[CLEAR] No open worker guidance messages."

    recent_reports = _load_recent_reports(task_ref, lane_id=lane_id)
    lines: list[str] = []
    for message in messages:
        lane = _normalize(message.get("lane_id")) or "unknown-lane"
        body = _normalize(message.get("message"))
        subject = _normalize(message.get("subject"))
        latest_report = recent_reports.get(lane, {})
        summary = _normalize(latest_report.get("summary"))
        level = _summary_level(f"{subject} {body} {summary}")
        detail = subject or summary or "Worker requested orchestrator guidance."
        lines.append(f"[{level}] {lane}: {detail}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a compact orchestrator guidance summary.")
    parser.add_argument("--orchestrator-root", required=True)
    parser.add_argument("--task-ref", required=True)
    parser.add_argument("--lane-id")
    args = parser.parse_args()

    orchestrator_root = Path(args.orchestrator_root).resolve()
    runtime = RuntimeConfig.for_workspace(
        orchestrator_root,
        state_dir=orchestrator_root / ".task-state",
        current_task_path=orchestrator_root / "CURRENT_TASK.md",
        exports_dir=orchestrator_root / ".task-state" / "exports",
    )
    configure_runtime(runtime)
    print(render_summary(args.task_ref, lane_id=args.lane_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
