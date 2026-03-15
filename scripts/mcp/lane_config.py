#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lane_manifest import get_lane_config
from lane_manifest import infer_lane_from_branch
from lane_manifest import list_lanes
from lane_manifest import list_task_refs
from lane_manifest import load_manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit lane/task configuration for Makefile helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-tasks")

    list_lanes_parser = subparsers.add_parser("list-lanes")
    list_lanes_parser.add_argument("--task-ref", required=True)

    infer_parser = subparsers.add_parser("infer-lane")
    infer_parser.add_argument("--branch", required=True)
    infer_parser.add_argument("--task-ref")

    field_parser = subparsers.add_parser("field")
    field_parser.add_argument("--task-ref", required=True)
    field_parser.add_argument("--lane-id", required=True)
    field_parser.add_argument("--field", required=True)
    field_parser.add_argument("--orchestrator-root")

    return parser.parse_args()


def _quote_args(flag: str, values: list[str]) -> str:
    if not values:
        return ""
    return " ".join(f"{flag} {shlex.quote(value)}" for value in values)


def _escape_make(value: str) -> str:
    return value.replace("$", "$$")


def _print_make_var(name: str, value: str) -> None:
    print(f"{name} := {_escape_make(value)}")


def _field_value(task_ref: str, lane_id: str, field: str, orchestrator_root: str | None) -> str:
    manifest = load_manifest(task_ref)
    lane = get_lane_config(task_ref, lane_id, orchestrator_root=orchestrator_root)
    if lane is None:
        return ""

    test_commands = [str(item) for item in lane.get("test_commands", []) if str(item).strip()]
    owned_paths = [str(item) for item in lane.get("owned_paths", []) if str(item).strip()]
    required_docs = [str(item) for item in lane.get("required_docs", []) if str(item).strip()]
    non_goals = [str(item) for item in lane.get("non_goals", []) if str(item).strip()]
    commit_paths = [str(item) for item in lane.get("commit_paths", []) if str(item).strip()]
    tooling_paths = [str(item) for item in lane.get("tooling_paths", []) if str(item).strip()]
    default_done = str(manifest.get("default_done_definition", ""))
    values = {
        "branch": str(lane.get("branch", "")),
        "worktree_path": str(lane.get("worktree_path", "")),
        "title": str(lane.get("title", "")),
        "objective": str(lane.get("objective", "")),
        "owned_args": _quote_args("--owned-path", owned_paths),
        "doc_args": _quote_args("--required-doc", required_docs),
        "test_args": _quote_args("--test-command", test_commands),
        "test_command_1": test_commands[0] if len(test_commands) >= 1 else "",
        "test_command_2": test_commands[1] if len(test_commands) >= 2 else "",
        "non_goal_args": _quote_args("--non-goal", non_goals),
        "commit_paths": " ".join(commit_paths),
        "commit_subject": str(lane.get("commit_subject", "")),
        "done_definition": str(lane.get("done_definition", lane.get("definition", default_done))),
        "tooling_paths": " ".join(tooling_paths),
    }
    return values.get(field, "")


def main() -> int:
    args = _parse_args()
    if args.command == "list-tasks":
        print(" ".join(list_task_refs()))
        return 0
    if args.command == "list-lanes":
        print(" ".join(list_lanes(args.task_ref)))
        return 0
    if args.command == "infer-lane":
        print(infer_lane_from_branch(args.branch, args.task_ref))
        return 0
    if args.command == "field":
        print(_field_value(args.task_ref, args.lane_id, args.field, args.orchestrator_root))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
