#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent_handoff_mcp import RuntimeConfig
from agent_handoff_mcp import configure_runtime
from agent_handoff_mcp import get_lane_activity


NO_WORK_MESSAGE = "No actionable lane inbox items."
ANSI = {
    "reset": "\033[0m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "green": "\033[32m",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render an actionable worker prompt from lane MCP state.")
    parser.add_argument("--orchestrator-root", required=True)
    parser.add_argument("--task-ref", required=True)
    parser.add_argument("--lane-id", required=True)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--check", action="store_true", help="Exit 0 if actionable work exists, 3 if not.")
    parser.add_argument("--summary", action="store_true", help="Print a color-coded one-line-per-item summary.")
    return parser.parse_args()


def _json_load(payload: str) -> dict[str, Any]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError("Expected JSON object payload from handoff tool.")
    return data


def _as_dicts(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _line(text: str) -> str:
    return " ".join(text.split())


def _bullet_lines(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]


def _format_message(message: dict[str, Any]) -> str:
    subject = str(message.get("subject") or "lane message").strip()
    body = _line(str(message.get("message") or ""))
    return f"[#{message.get('id')}] {subject}: {body}"


def _format_action(action: dict[str, Any]) -> str:
    priority = action.get("priority")
    priority_label = f" [P{priority}]" if isinstance(priority, int) else ""
    return f"[#{action.get('id')}{priority_label}] {_line(str(action.get('action') or ''))}"


def _format_blocker(blocker: dict[str, Any]) -> str:
    return f"[#{blocker.get('id')}] {_line(str(blocker.get('description') or ''))}"


def _format_finding(finding: dict[str, Any]) -> str:
    location = str(finding.get("file_path") or "")
    line_start = finding.get("line_start")
    if isinstance(line_start, int):
        location = f"{location}:{line_start}"
    severity = str(finding.get("severity") or "unknown")
    description = _line(str(finding.get("description") or ""))
    return f"[{finding.get('finding_id')}] [{severity}] {location} - {description}"


def _summary_color(kind: str, *, severity: str = "", priority: int | None = None) -> str:
    if kind == "blocker":
        return ANSI["red"]
    if kind == "action":
        if priority == 1:
            return ANSI["red"]
        return ANSI["yellow"]
    if kind == "finding":
        if severity == "high":
            return ANSI["red"]
        if severity == "medium":
            return ANSI["yellow"]
        return ANSI["blue"]
    if kind == "message":
        return ANSI["cyan"]
    return ANSI["green"]


def _build_summary_lines(activity: dict[str, Any]) -> list[str]:
    messages = [
        message
        for message in _as_dicts(activity.get("messages"))
        if message.get("direction") == "orchestrator_to_worker" and message.get("status") == "open"
    ]
    actions = sorted(
        [action for action in _as_dicts(activity.get("actions")) if action.get("status") == "pending"],
        key=lambda action: action.get("priority", 99),
    )
    blockers = [blocker for blocker in _as_dicts(activity.get("blockers")) if blocker.get("status") == "open"]
    findings = [finding for finding in _as_dicts(activity.get("findings")) if finding.get("status") == "open"]

    lines: list[str] = []
    for blocker in blockers:
        color = _summary_color("blocker")
        lines.append(f"{color}[BLOCKER]{ANSI['reset']} {_line(str(blocker.get('description') or ''))}")
    for action in actions:
        priority = action.get("priority")
        color = _summary_color("action", priority=priority if isinstance(priority, int) else None)
        label = f"[ACTION P{priority}]" if isinstance(priority, int) else "[ACTION]"
        lines.append(f"{color}{label}{ANSI['reset']} {_line(str(action.get('action') or ''))}")
    for finding in findings:
        severity = str(finding.get("severity") or "unknown")
        color = _summary_color("finding", severity=severity)
        location = str(finding.get("file_path") or "").strip()
        if isinstance(finding.get("line_start"), int):
            location = f"{location}:{finding['line_start']}"
        suffix = f" ({location})" if location else ""
        lines.append(f"{color}[REVIEW {severity.upper()}]{ANSI['reset']} {_line(str(finding.get('description') or ''))}{suffix}")
    for message in messages:
        color = _summary_color("message")
        subject = _line(str(message.get("subject") or "lane message"))
        body = _line(str(message.get("message") or ""))
        compact = f"{subject}: {body}" if body else subject
        lines.append(f"{color}[MESSAGE]{ANSI['reset']} {compact}")
    if not lines:
        return [f"{ANSI['green']}[IDLE]{ANSI['reset']} {NO_WORK_MESSAGE}"]
    return lines


def _build_prompt(activity: dict[str, Any], task_ref: str, lane_id: str, worktree_path: str) -> str:
    lane = activity.get("lane") if isinstance(activity.get("lane"), dict) else {}
    branch = str(lane.get("branch") or "")
    objective = str(lane.get("objective") or "").strip()

    messages = [
        message
        for message in _as_dicts(activity.get("messages"))
        if message.get("direction") == "orchestrator_to_worker" and message.get("status") == "open"
    ]
    actions = [action for action in _as_dicts(activity.get("actions")) if action.get("status") == "pending"]
    blockers = [blocker for blocker in _as_dicts(activity.get("blockers")) if blocker.get("status") == "open"]
    findings = [finding for finding in _as_dicts(activity.get("findings")) if finding.get("status") == "open"]
    latest_report = _as_dicts(activity.get("reports"))[:1]

    actionable = bool(messages or actions or blockers or findings)
    if not actionable:
        return NO_WORK_MESSAGE

    lines = [
        f"You are the worker agent for lane `{lane_id}` on task `{task_ref}`.",
        f"Worktree: `{worktree_path}`",
    ]
    if branch:
        lines.append(f"Branch: `{branch}`")
    if objective:
        lines.append(f"Objective: {objective}")

    lines.extend(
        [
            "",
            "Operate only within this lane's owned files and do not edit sibling-lane paths.",
        ]
    )

    if messages:
        lines.extend(["", "Open orchestrator messages:"])
        lines.extend(_bullet_lines([_format_message(message) for message in messages]))

    if actions:
        lines.extend(["", "Pending lane actions:"])
        lines.extend(_bullet_lines([_format_action(action) for action in actions]))

    if findings:
        lines.extend(["", "Open lane review findings:"])
        lines.extend(_bullet_lines([_format_finding(finding) for finding in findings]))

    if blockers:
        lines.extend(["", "Open lane blockers already assigned to this lane:"])
        lines.extend(_bullet_lines([_format_blocker(blocker) for blocker in blockers]))

    if latest_report:
        report = latest_report[0]
        lines.extend(
            [
                "",
                "Latest worker report:",
                f"- [{report.get('status')}] {_line(str(report.get('summary') or ''))}",
            ]
        )

    lines.extend(
        [
            "",
            "Next steps:",
            "- Inspect the referenced files and implement the highest-priority open work in this lane.",
            "- Run the lane-local tests before handoff.",
            "- When merge-ready, run `make lane-handoff`.",
            "- If you need clarification or are blocked, submit a blocked worker report so the orchestrator sees it in `make handoff-inbox`.",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    orchestrator_root = Path(args.orchestrator_root).expanduser().resolve()
    runtime = RuntimeConfig.for_workspace(
        orchestrator_root,
        state_dir=orchestrator_root / ".task-state",
        current_task_path=orchestrator_root / "CURRENT_TASK.md",
        exports_dir=orchestrator_root / ".task-state" / "exports",
    )
    configure_runtime(runtime)

    activity = _json_load(get_lane_activity(lane_id=args.lane_id, task_ref=args.task_ref, limit_findings=50, limit_actions=50, limit_blockers=50))
    if activity.get("ok") is not True:
        raise RuntimeError(f"Unable to load lane activity: {activity}")

    prompt = _build_prompt(activity, task_ref=args.task_ref, lane_id=args.lane_id, worktree_path=args.worktree_path)
    if args.check:
        return 0 if prompt != NO_WORK_MESSAGE else 3
    if args.summary:
        print("\n".join(_build_summary_lines(activity)))
        return 0
    print(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
