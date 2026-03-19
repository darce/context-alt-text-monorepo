"""Tests for scripts/mcp/orchestrator_lanes.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "orchestrator_lanes.py"


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


def test_refresh_downstream_reports_success_per_lane(tmp_path: Path) -> None:
    mod = _load_module()

    def _run(cmd, cwd, capture_output, text, check):  # type: ignore[no-untyped-def]
        lane = next(part.split("=", 1)[1] for part in cmd if part.startswith("LANE="))
        return mock.Mock(returncode=0 if lane == "frontend" else 1)

    with mock.patch.object(mod.subprocess, "run", side_effect=_run):
        result = mod._refresh_downstream(
            tmp_path,
            "daemon-9",
            "backend-http",
            ["frontend", "wp-proxy"],
        )

    assert result == [("frontend", True), ("wp-proxy", False)]


def test_record_downstream_briefs_creates_one_brief_per_dependency() -> None:
    mod = _load_module()

    with (
        mock.patch("agent_handoff_mcp.list_worker_reports", return_value=json.dumps({
            "ok": True,
            "reports": [
                {
                    "summary": "Backend domain changes were intaken.",
                    "changed_files": ["apps/prototype-description-service/export_service.py"],
                    "test_commands": ["pytest recognition/tests/unit/test_export_service.py"],
                }
            ],
        })),
        mock.patch("agent_handoff_mcp.record_lane_brief", side_effect=[
            json.dumps({"ok": True}),
            json.dumps({"ok": True}),
        ]) as mock_record,
    ):
        result = mod._record_downstream_briefs(
            "daemon-10",
            "backend-domain",
            ["frontend", "wp-proxy"],
        )

    assert result == [("frontend", True), ("wp-proxy", True)]
    first_call = mock_record.call_args_list[0].kwargs
    assert first_call["source_lane"] == "backend-domain"
    assert first_call["lane_id"] == "frontend"
    assert first_call["reason"] == "upstream-lane-intake"
    assert "Refresh your lane" in first_call["required_actions"][0]


def test_record_downstream_briefs_returns_false_when_no_report_exists() -> None:
    mod = _load_module()

    with mock.patch("agent_handoff_mcp.list_worker_reports", return_value=json.dumps({"ok": True, "reports": []})):
        result = mod._record_downstream_briefs(
            "daemon-10",
            "backend-domain",
            ["frontend"],
        )

    assert result == [("frontend", False)]
