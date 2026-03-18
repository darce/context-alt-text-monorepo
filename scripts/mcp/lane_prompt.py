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

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lane_manifest import get_lane_config
from _env import extract_pyenv_version


NO_WORK_MESSAGE = "No actionable lane inbox items."
WAITING_MESSAGE = "Open worker handoff already sent; waiting for orchestrator response."
NO_WORK_EXIT = 3
WAITING_EXIT = 4
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
    parser.add_argument("--check", action="store_true", help="Exit 0 if actionable work exists, 3 if idle, 4 if waiting for orchestrator.")
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
    state = _actionable_state(activity)
    if state["awaiting_orchestrator"]:
        return [f"{ANSI['yellow']}[WAITING]{ANSI['reset']} {WAITING_MESSAGE}"]
    if not state["actionable"]:
        return [f"{ANSI['green']}[IDLE]{ANSI['reset']} {NO_WORK_MESSAGE}"]

    messages = state["messages"]
    actions = state["actions"]
    blockers = state["blockers"]
    findings = state["findings"]

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
    return lines


def _timestamp_text(row: dict[str, Any]) -> str:
    for key in ("updated_at", "created_at"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _latest_timestamp(rows: list[dict[str, Any]]) -> str:
    values = [_timestamp_text(row) for row in rows]
    values = [value for value in values if value]
    return max(values) if values else ""


def _actionable_state(activity: dict[str, Any]) -> dict[str, Any]:
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
    worker_messages = [
        message
        for message in _as_dicts(activity.get("messages"))
        if message.get("direction") == "worker_to_orchestrator" and message.get("status") == "open"
    ]

    actionable_rows: list[dict[str, Any]] = [*messages, *actions, *blockers, *findings]
    actionable = bool(actionable_rows)
    latest_worker_ts = _latest_timestamp(worker_messages)
    latest_action_ts = _latest_timestamp(actionable_rows)
    awaiting_orchestrator = bool(
        actionable
        and latest_worker_ts
        and latest_action_ts
        and latest_worker_ts >= latest_action_ts
    )
    return {
        "messages": messages,
        "actions": actions,
        "blockers": blockers,
        "findings": findings,
        "worker_messages": worker_messages,
        "actionable": actionable and not awaiting_orchestrator,
        "awaiting_orchestrator": awaiting_orchestrator,
    }


def _runtime_guidance(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
) -> list[str]:
    lane_config = get_lane_config(task_ref, lane_id, orchestrator_root=str(orchestrator_root)) or {}
    test_commands = [str(item).strip() for item in lane_config.get("test_commands", []) if str(item).strip()]
    app_root = str(lane_config.get("app_root") or "").strip()
    non_goals = [str(item).strip() for item in lane_config.get("non_goals", []) if str(item).strip()]
    owned_paths = [str(item).strip() for item in lane_config.get("owned_paths", []) if str(item).strip()]
    capability_tags = [str(item).strip() for item in lane_config.get("capability_tags", []) if str(item).strip()]
    preflight_commands = [str(item).strip() for item in lane_config.get("preflight_commands", []) if str(item).strip()]

    lines: list[str] = []

    if app_root:
        lines.extend(
            [
                "",
                "Working directory:",
                f"- Your primary application directory is `{app_root}/`. Run all test and build commands from there.",
                f"- `cd {app_root}` before running any lane verification commands.",
            ]
        )

    if owned_paths:
        lines.extend(["", "Owned paths (only edit files within these):"])
        lines.extend(_bullet_lines([f"`{path}`" for path in owned_paths]))

    if non_goals:
        lines.extend(["", "Constraints:"])
        lines.extend(_bullet_lines(non_goals))

    if test_commands:
        lines.extend(["", "Verification commands for this lane:"])
        lines.extend(_bullet_lines([f"`{command}`" for command in test_commands]))

    pyenv_version = extract_pyenv_version(test_commands)
    if pyenv_version:
        app_dir = app_root or "the application directory"
        lines.extend(
            [
                "",
                "Backend runtime notes:",
                f"- Your environment already has `PYENV_VERSION={pyenv_version}` exported with the virtualenv `bin/` directory on `PATH`.",
                f"- Use `python`, `pytest`, and `mypy` directly (they resolve to the `{pyenv_version}` virtualenv). Do NOT use bare `python3` or probe the system Python.",
                f"- Always `cd {app_dir}` first so imports resolve correctly.",
                "- A writable lane temp dir is provided under `.task-state/tmp/<lane>`; temp-file failures usually mean the command escaped the managed worker environment.",
                "- Local reset/bootstrap work depends on backend resources outside the worker sandbox. If PostgreSQL or other local services are unavailable, report `needs_guidance` instead of treating that as a code defect.",
            ]
        )
    if capability_tags or preflight_commands:
        labels = ", ".join(f"`{tag}`" for tag in capability_tags) if capability_tags else "configured lane requirements"
        lines.extend(
            [
                "",
                "Lane capability gate:",
                f"- `make lane-run` and the worker daemon run a preflight before any subagent turn for {labels}.",
                "- If the preflight fails, the lane auto-handoffs `needs_guidance` instead of spending tokens on a backend run that cannot succeed.",
            ]
        )
    return lines


def _build_prompt(
    activity: dict[str, Any],
    task_ref: str,
    lane_id: str,
    worktree_path: str,
    *,
    orchestrator_root: Path,
) -> str:
    lane = activity.get("lane") if isinstance(activity.get("lane"), dict) else {}
    branch = str(lane.get("branch") or "")
    objective = str(lane.get("objective") or "").strip()
    state = _actionable_state(activity)
    messages = state["messages"]
    actions = state["actions"]
    blockers = state["blockers"]
    findings = state["findings"]
    latest_report = _as_dicts(activity.get("reports"))[:1]
    if state["awaiting_orchestrator"]:
        return WAITING_MESSAGE
    if not state["actionable"]:
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

    lines.extend(_runtime_guidance(orchestrator_root=orchestrator_root, task_ref=task_ref, lane_id=lane_id))

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

    state = _actionable_state(activity)
    prompt = _build_prompt(
        activity,
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        worktree_path=args.worktree_path,
        orchestrator_root=orchestrator_root,
    )
    if args.check:
        if state["actionable"]:
            return 0
        if state["awaiting_orchestrator"]:
            return WAITING_EXIT
        return NO_WORK_EXIT
    if args.summary:
        print("\n".join(_build_summary_lines(activity)))
        return 0
    print(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
