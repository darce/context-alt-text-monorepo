"""Tests for scripts/mcp/orchestrator_lanes.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_handoff_mcp" / "orchestration"
SCRIPT_PATH = ORCHESTRATION_DIR / "orchestrator_lanes.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("orchestrator_lanes", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load orchestrator_lanes module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lane_has_capacity_false_when_open_dispatch_exists() -> None:
    mod = _load_module()

    with (
        mock.patch("agent_handoff_mcp.list_lane_messages", return_value=json.dumps({
            "ok": True,
            "messages": [{"id": 1, "direction": "orchestrator_to_worker", "status": "open"}],
        })),
        mock.patch("agent_handoff_mcp.get_lane_activity") as mock_activity,
        mock.patch("agent_handoff_mcp.list_plan_cursors") as mock_cursors,
    ):
        assert mod._lane_has_capacity("daemon-9", "frontend") is False

    mock_activity.assert_not_called()
    mock_cursors.assert_not_called()


def test_lane_has_capacity_false_when_pending_action_exists() -> None:
    mod = _load_module()

    with (
        mock.patch("agent_handoff_mcp.list_lane_messages", return_value=json.dumps({"ok": True, "messages": []})),
        mock.patch("agent_handoff_mcp.get_lane_activity", return_value=json.dumps({
            "ok": True,
            "actions": [{"id": 2, "status": "pending"}],
        })),
        mock.patch("agent_handoff_mcp.list_plan_cursors") as mock_cursors,
    ):
        assert mod._lane_has_capacity("daemon-9", "frontend") is False

    mock_cursors.assert_not_called()


def test_lane_has_capacity_false_when_dispatched_plan_cursor_exists() -> None:
    mod = _load_module()

    with (
        mock.patch("agent_handoff_mcp.list_lane_messages", return_value=json.dumps({"ok": True, "messages": []})),
        mock.patch("agent_handoff_mcp.get_lane_activity", return_value=json.dumps({"ok": True, "actions": []})),
        mock.patch("agent_handoff_mcp.list_plan_cursors", return_value=json.dumps({
            "ok": True,
            "cursors": [{"id": 7, "state": "dispatched"}],
        })),
    ):
        assert mod._lane_has_capacity("daemon-9", "frontend") is False


def test_lane_has_capacity_true_when_lane_has_no_open_work() -> None:
    mod = _load_module()

    with (
        mock.patch("agent_handoff_mcp.list_lane_messages", return_value=json.dumps({"ok": True, "messages": []})),
        mock.patch("agent_handoff_mcp.get_lane_activity", return_value=json.dumps({"ok": True, "actions": []})),
        mock.patch("agent_handoff_mcp.list_plan_cursors", return_value=json.dumps({"ok": True, "cursors": []})),
    ):
        assert mod._lane_has_capacity("daemon-9", "frontend") is True


