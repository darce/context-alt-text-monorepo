#!/usr/bin/env python3
"""Inline Python implementation for scripts/maint-start.sh.

Registers a MAINT-* task against the primary worktree without creating a
feature branch or linked worktree. This is the main-branch counterpart to
task-start.sh for permitted docs/config maintenance slices.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from workstate_handoff_mcp import (
    RuntimeConfig,
    configure_runtime,
    get_handoff_state,
    render_handoff,
    set_handoff_state,
    switch_task,
)


def build_maint_task_ref(slug: str, *, today: date | None = None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", slug.strip().lower()).strip("-")
    if not normalized:
        raise ValueError("slug must contain at least one alphanumeric character")
    task_day = today or datetime.now(tz=timezone.utc).date()
    return f"MAINT-{normalized}-{task_day.strftime('%Y%m%d')}"


def main() -> int:
    repo_root = Path(os.environ["REPO_ROOT"])
    runtime = RuntimeConfig.for_repo(repo_root)
    configure_runtime(runtime)

    target_task = build_maint_task_ref(os.environ["SLUG"])
    target_objective = os.environ["OBJECTIVE"]

    identity = get_handoff_state(sections="identity")
    if isinstance(identity, str):
        identity = json.loads(identity)
    identity_data = identity.get("data") if isinstance(identity, dict) else None
    active_row = identity_data.get("active") if isinstance(identity_data, dict) else None
    expected_revision = active_row.get("revision") if isinstance(active_row, dict) else None

    if isinstance(active_row, dict) and active_row.get("task_ref") != target_task:
        switch_result = switch_task(
            task_ref=target_task,
            objective=target_objective,
            status="in_progress",
            target_branch="main",
        )
        parsed_switch = json.loads(switch_result) if isinstance(switch_result, str) else switch_result
        if not parsed_switch.get("ok"):
            print(f"\u26a0 switch_task failed: {parsed_switch}", file=sys.stderr)
            return 1
        switch_data = parsed_switch.get("data") if isinstance(parsed_switch, dict) else None
        switch_active = switch_data.get("active") if isinstance(switch_data, dict) else None
        expected_revision = switch_active.get("revision") if isinstance(switch_active, dict) else None

    result = set_handoff_state(
        task_ref=target_task,
        objective=target_objective,
        status="in_progress",
        target_branch="main",
        target_worktree_path=str(repo_root),
        expected_revision=expected_revision,
    )
    parsed = json.loads(result) if isinstance(result, str) else result
    if not parsed.get("ok"):
        print(f"\u26a0 set_handoff_state failed: {parsed}", file=sys.stderr)
        return 1

    current_task = render_handoff(kind="current_task", task_ref=target_task)
    if not current_task.get("ok"):
        print(f"\u26a0 render_handoff(kind='current_task') failed: {current_task}", file=sys.stderr)
        return 1

    dashboard = render_handoff(kind="dashboard")
    if not dashboard.get("ok"):
        print(f"\u26a0 render_handoff(kind='dashboard') failed: {dashboard}", file=sys.stderr)
        return 1

    revision = parsed.get("data", {}).get("active", {}).get("revision", "?")
    print(f"  OK task={target_task} rev={revision}")
    return 0


if __name__ == "__main__":
    sys.exit(main())