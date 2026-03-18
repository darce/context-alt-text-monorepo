"""Lane operations: dispatch, poll, intake, refresh, and cross-lane verification."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _env import pythonpath_env
from orchestrator_helpers import _json_load


# ---------------------------------------------------------------------------
# Dispatch, poll, intake
# ---------------------------------------------------------------------------


def _run_handoff_dispatch(
    orchestrator_root: Path, task_ref: str, *, dry_run: bool = False,
) -> dict[str, Any]:
    """Run ``review_dispatch.py`` and return its JSON output."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "review_dispatch.py"),
        "--orchestrator-root", str(orchestrator_root),
        "--task-ref", task_ref,
    ]
    if dry_run:
        cmd.append("--dry-run")
    env = pythonpath_env(orchestrator_root)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"review_dispatch.py failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return _json_load(result.stdout)


def _lane_has_unmerged_commits(
    orchestrator_root: Path, task_ref: str, lane_id: str,
) -> bool:
    """Return True if the lane branch has commits not yet on the current branch."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from lane_manifest import get_lane_config

    config = get_lane_config(task_ref, lane_id, orchestrator_root=str(orchestrator_root))
    if not config or not config.get("branch"):
        return False
    branch = config["branch"]
    result = subprocess.run(
        ["git", "log", "--oneline", f"HEAD..{branch}"],
        cwd=orchestrator_root, capture_output=True, text=True, check=False,
    )
    return bool(result.returncode == 0 and result.stdout.strip())


def _sort_by_manifest_merge_order(ready: list[str], manifest_order: list[str]) -> list[str]:
    """Sort *ready* lanes by the manifest merge order, unknown lanes last."""
    order_map = {lane: i for i, lane in enumerate(manifest_order)}
    return sorted(ready, key=lambda lane: order_map.get(lane, len(manifest_order)))


def _intake_lane(
    orchestrator_root: Path, task_ref: str, lane_id: str, *, dry_run: bool = False,
) -> bool:
    """Run ``make lane-intake`` for a single lane.  Returns True on success."""
    from agent_handoff_mcp import list_lane_messages, update_lane_message

    cmd = [
        "make", "lane-intake",
        f"TASK={task_ref}",
        f"LANE={lane_id}",
    ]
    if dry_run:
        cmd.append("DRY_RUN=1")
    result = subprocess.run(
        cmd, cwd=orchestrator_root, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return False
    if dry_run:
        return True

    try:
        payload = _json_load(
            list_lane_messages(task_ref=task_ref, lane_id=lane_id, status="open", limit=200)
        )
        if payload.get("ok") is not True:
            raise RuntimeError(f"Failed to list lane messages for {lane_id}.")
        for row in payload.get("messages", []):
            if not isinstance(row, dict) or row.get("direction") != "orchestrator_to_worker":
                continue
            message_id = row.get("id")
            if message_id is None:
                continue
            update = _json_load(update_lane_message(int(message_id), "closed", task_ref=task_ref))
            if update.get("ok") is not True:
                raise RuntimeError(f"Failed to close dispatch message {message_id} for {lane_id}.")
    except RuntimeError as exc:
        print(
            f"warning: lane intake succeeded but dispatch-message cleanup failed for {lane_id}: {exc}",
            file=sys.stderr,
        )
    return True


# ---------------------------------------------------------------------------
# Downstream refresh and cross-lane verification
# ---------------------------------------------------------------------------


def _refresh_downstream(
    orchestrator_root: Path, task_ref: str, lane_id: str, downstream: list[str],
    *, dry_run: bool = False,
) -> list[tuple[str, bool]]:
    """Refresh each downstream lane.  Returns list of (lane, success) pairs."""
    results: list[tuple[str, bool]] = []
    for dep in downstream:
        cmd = [
            "make", "lane-refresh",
            f"TASK={task_ref}",
            f"LANE={dep}",
        ]
        if dry_run:
            cmd.append("DRY_RUN=1")
        r = subprocess.run(
            cmd, cwd=orchestrator_root, capture_output=True, text=True, check=False,
        )
        results.append((dep, r.returncode == 0))
    return results


def _resolve_lane_worktree(orchestrator_root: Path, task_ref: str, lane_id: str) -> Optional[Path]:
    """Resolve the worktree path for a lane from the manifest."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from lane_manifest import get_lane_config

    config = get_lane_config(task_ref, lane_id, orchestrator_root=str(orchestrator_root))
    if config and config.get("worktree_path"):
        return Path(config["worktree_path"])
    return None


def _lane_has_capacity(task_ref: str, lane_id: str) -> bool:
    """Return True when a lane has no open dispatch, no pending lane action, and no open plan cursor."""
    from agent_handoff_mcp import get_lane_activity, list_lane_messages, list_plan_cursors

    messages_payload = _json_load(
        list_lane_messages(task_ref=task_ref, lane_id=lane_id, status="open", limit=200)
    )
    if messages_payload.get("ok") is not True:
        raise RuntimeError(f"Failed to list lane messages for {lane_id}.")
    for row in messages_payload.get("messages", []):
        if isinstance(row, dict) and row.get("direction") == "orchestrator_to_worker":
            return False

    activity_payload = _json_load(get_lane_activity(task_ref=task_ref, lane_id=lane_id, limit_actions=50))
    if activity_payload.get("ok") is not True:
        raise RuntimeError(f"Failed to fetch lane activity for {lane_id}.")
    for row in activity_payload.get("actions", []):
        if isinstance(row, dict) and row.get("status") == "pending":
            return False

    cursor_raw = list_plan_cursors(task_ref=task_ref, state="dispatched", lane_id=lane_id, limit=20)
    if not isinstance(cursor_raw, str):
        return True
    cursor_payload = _json_load(cursor_raw)
    if cursor_payload.get("ok") is not True:
        raise RuntimeError(f"Failed to list plan cursors for {lane_id}.")
    return not bool(cursor_payload.get("cursors"))


def _complete_lane_plan_cursor(task_ref: str, lane_id: str, *, worker_message_id: Optional[int] = None) -> Optional[dict[str, Any]]:
    """Mark the newest dispatched plan cursor for a lane complete."""
    from agent_handoff_mcp import list_plan_cursors, upsert_plan_cursor

    payload_raw = list_plan_cursors(task_ref=task_ref, state="dispatched", lane_id=lane_id, limit=20)
    if not isinstance(payload_raw, str):
        return None
    payload = _json_load(payload_raw)
    if payload.get("ok") is not True:
        raise RuntimeError(f"Failed to list plan cursors for {lane_id}.")
    rows = payload.get("cursors", [])
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    if not isinstance(row, dict):
        return None
    update = _json_load(
        upsert_plan_cursor(
            task_ref=task_ref,
            plan_item_id=str(row.get("plan_item_id") or ""),
            state="completed",
            lane_id=lane_id,
            worker_message_id=worker_message_id,
            summary=str(row.get("summary") or ""),
            source_heading=str(row.get("source_heading") or "") or None,
        )
    )
    if update.get("ok") is not True:
        raise RuntimeError(f"Failed to complete plan cursor for {lane_id}.")
    cursor = update.get("cursor")
    return cursor if isinstance(cursor, dict) else None
