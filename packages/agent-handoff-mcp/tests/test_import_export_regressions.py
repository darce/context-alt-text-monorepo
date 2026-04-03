"""Regression tests for import/export and task switching semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp.config import RuntimeConfig


def _parse(payload: str) -> dict:
    raw = json.loads(payload)
    if isinstance(raw, dict) and raw.get("schema_version") == 2:
        data = raw.get("data", {})
        scope = raw.get("scope", {})
        flat = {**raw, **data}
        if "task_ref" not in flat and scope.get("task_ref"):
            flat["task_ref"] = scope["task_ref"]
        return flat
    return raw


def _configure_runtime(workspace_root: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.for_workspace(
        workspace_root,
        state_dir=workspace_root / ".task-state",
        current_task_path=workspace_root / "CURRENT_TASK.md",
    )
    mcp_server.configure_runtime(runtime)
    return runtime


@pytest.fixture()
def workspace_pair(tmp_path: Path) -> dict[str, Path]:
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source_root.mkdir()
    target_root.mkdir()
    _configure_runtime(source_root)
    return {"source": source_root, "target": target_root}


def test_export_and_import_handoff_state_round_trip(workspace_pair: dict[str, Path]) -> None:
    export_path = workspace_pair["source"] / ".task-state" / "exports" / "round-trip.json"

    _parse(
        mcp_server.set_handoff_state(task_ref="round-trip", objective="Round trip export/import", status="in_progress")
    )
    _parse(mcp_server.record_decision(session="s1", decision="round_trip_decision", rationale="kept"))
    _parse(mcp_server.record_test_result(session="s1", command="pytest", passed=True, result="1 passed in 0.01s"))
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="ROUND-TRIP-001",
            severity="medium",
            file_path="pkg/mod.py",
            description="Round trip finding",
        )
    )

    exported = _parse(mcp_server.export_handoff_state(task_ref="round-trip", output_path=str(export_path)))
    assert exported["ok"] is True

    _configure_runtime(workspace_pair["target"])
    imported = _parse(
        mcp_server.import_handoff_state(
            input_path=str(export_path),
            mode="merge",
            set_active=True,
        )
    )
    assert imported["ok"] is True

    state = _parse(mcp_server.get_handoff_state(task_ref="round-trip"))
    assert state["ok"] is True
    assert state["active"]["task_ref"] == "round-trip"
    assert state["decisions_recent"][0]["decision"] == "round_trip_decision"
    assert state["findings_open"][0]["finding_id"] == "ROUND-TRIP-001"


def test_export_defaults_to_no_markdown(workspace_pair: dict[str, Path]) -> None:
    """OC-007: export_handoff_state defaults to include_markdown=False."""
    _configure_runtime(workspace_pair["source"])
    _parse(
        mcp_server.set_handoff_state(task_ref="export-default", objective="Test export default", status="in_progress")
    )
    exported = _parse(mcp_server.export_handoff_state(task_ref="export-default"))
    assert exported["ok"] is True
    payload = exported.get("data") or exported
    assert "current_task_markdown" not in payload


def test_switch_task_clears_focus_on_restore(workspace_pair: dict[str, Path]) -> None:
    _configure_runtime(workspace_pair["source"])

    first = _parse(
        mcp_server.set_handoff_state(
            task_ref="task-a",
            objective="Restore me",
            focus="stale focus",
            status="in_progress",
        )
    )
    assert first["ok"] is True

    switched = _parse(handoff_core.switch_task(task_ref="task-b", objective="Task B objective"))
    assert switched["ok"] is True

    restored = _parse(handoff_core.switch_task(task_ref="task-a"))
    assert restored["ok"] is True
    assert restored["active"]["task_ref"] == "task-a"
    assert restored["active"]["objective"] == "Restore me"
    assert restored["active"]["focus"] is None


def test_update_task_status_updates_archived_snapshot_and_dashboard(workspace_pair: dict[str, Path]) -> None:
    _configure_runtime(workspace_pair["source"])

    _parse(
        mcp_server.set_handoff_state(
            task_ref="task-a",
            objective="Archive me",
            status="in_progress",
        )
    )
    _parse(mcp_server.record_decision(session="archive-status", decision="task_a_decision", rationale="note"))
    _parse(mcp_server.archive_task_state(task_ref="task-a"))
    _parse(mcp_server.set_handoff_state(task_ref="task-b", objective="Keep current", status="in_progress"))

    updated = _parse(mcp_server.update_task_status(task_ref="task-a", status="done"))

    assert updated["ok"] is True
    assert updated["updated_scope"] == "archived"

    payload = _parse(mcp_server.generate_current_task_md(task_ref="task-b", write_file=False))
    assert payload["ok"] is True
    assert "> task-b" in payload["markdown"]
    assert "task-a" in payload["markdown"]
    assert "done" in payload["markdown"]


def test_switch_task_preserves_target_branch_on_restore(workspace_pair: dict[str, Path]) -> None:
    """target_branch survives switch-away / switch-back lifecycle."""
    _configure_runtime(workspace_pair["source"])

    init = _parse(
        mcp_server.set_handoff_state(
            task_ref="task-a",
            objective="Branch-bound task",
            target_branch="feature/task-a-work",
        )
    )
    assert init["ok"] is True
    assert init["active"]["target_branch"] == "feature/task-a-work"

    switched = _parse(handoff_core.switch_task(task_ref="task-b", objective="Task B"))
    assert switched["ok"] is True

    restored = _parse(handoff_core.switch_task(task_ref="task-a"))
    assert restored["ok"] is True
    assert restored["active"]["task_ref"] == "task-a"
    assert restored["active"]["target_branch"] == "feature/task-a-work"


def test_import_handoff_state_prefers_decoded_lane_message_payload(workspace_pair: dict[str, Path]) -> None:
    payload_path = workspace_pair["source"] / "decoded-payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "task_ref": "decoded-payload",
                "snapshot": {
                    "active": {
                        "task_ref": "decoded-payload",
                        "objective": "decoded payload import",
                        "status": "in_progress",
                    },
                    "blockers": [],
                    "next_actions": [],
                    "decisions": [],
                    "verified_tests": [],
                    "review_findings": [],
                    "worktree_lanes": [],
                    "worker_reports": [],
                    "lane_messages": [
                        {
                            "lane_id": "frontend",
                            "session": "s1",
                            "direction": "orchestrator_to_worker",
                            "subject": "payload",
                            "message": "decoded wins",
                            "status": "open",
                            "payload_json": '{"source": "stale"}',
                            "payload": {"source": "decoded", "count": 2},
                        }
                    ],
                    "plan_cursors": [],
                    "turn_metrics": [],
                },
            }
        )
    )

    imported = _parse(mcp_server.import_handoff_state(input_path=str(payload_path), set_active=True))
    assert imported["ok"] is True

    state = _parse(mcp_server.get_handoff_state(task_ref="decoded-payload"))
    assert state["ok"] is True
    message = state["lane_messages_open"][0]
    assert message["payload"]["source"] == "decoded"
    assert message["payload"]["count"] == 2


def test_get_review_findings_summary_counts_and_limits(workspace_pair: dict[str, Path]) -> None:
    _configure_runtime(workspace_pair["source"])
    _parse(mcp_server.set_handoff_state(task_ref="summary-task", objective="summary", status="in_progress"))

    for finding_id, severity in (("SUM-001", "high"), ("SUM-002", "medium"), ("SUM-003", "low")):
        _parse(
            mcp_server.record_review_finding(
                session="s1",
                finding_id=finding_id,
                severity=severity,
                file_path="docs/summary.md",
                description=finding_id,
            )
        )
    _parse(mcp_server.update_review_finding(finding_id="SUM-003", status="fixed"))

    summary = _parse(handoff_core.get_review_findings_summary(top_n_open=2, top_n_recent_updates=2))

    assert summary["ok"] is True
    assert summary["counts"]["total"] == 3
    assert summary["counts"]["status"]["open"] == 2
    assert summary["counts"]["status"]["fixed"] == 1
    assert len(summary["open_top"]) == 2
    assert len(summary["recent_updates"]) == 2


def test_review_list_and_summary_surface_workspace_git_context(workspace_pair: dict[str, Path]) -> None:
    _configure_runtime(workspace_pair["source"])
    _parse(mcp_server.set_handoff_state(task_ref="workspace-git", objective="git context", status="in_progress"))
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="GIT-CTX-001",
            severity="medium",
            file_path="docs/git.md",
            description="workspace git context",
        )
    )

    listed = _parse(mcp_server.list_review_findings())
    summary = _parse(handoff_core.get_review_findings_summary())

    assert listed["ok"] is True
    assert isinstance(listed["workspace_git"], dict)
    assert "branch" in listed["workspace_git"]
    assert "commit_sha" in listed["workspace_git"]

    assert summary["ok"] is True
    assert isinstance(summary["workspace_git"], dict)
    assert "branch" in summary["workspace_git"]
    assert "commit_sha" in summary["workspace_git"]
