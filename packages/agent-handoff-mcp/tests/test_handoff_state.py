"""Unit tests for portable agent handoff MCP state tools."""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp.config import RuntimeConfig


@pytest.fixture()
def isolated_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect handoff sqlite + generated markdown paths into tmp dir."""
    state_dir = tmp_path / ".task-state"
    current_task_path = tmp_path / "CURRENT_TASK.md"
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=state_dir,
        current_task_path=current_task_path,
    )
    mcp_server.configure_runtime(runtime)

    return {
        "state_dir": state_dir,
        "db_path": runtime.db_path,
        "current_task_path": current_task_path,
    }


def test_runtime_config_defaults_to_workspace_task_state() -> None:
    runtime = RuntimeConfig.for_workspace("/tmp/example-workspace")
    workspace_root = Path("/tmp/example-workspace").resolve()

    assert runtime.state_dir == workspace_root / ".task-state"
    assert runtime.db_path == workspace_root / ".task-state" / "handoff.db"
    assert runtime.current_task_path == workspace_root / "CURRENT_TASK.md"
    assert runtime.exports_dir == workspace_root / ".task-state" / "exports"


def _parse(payload: str) -> dict:
    import typing

    return typing.cast(dict, json.loads(payload))


def test_schema_bootstrap_is_idempotent(isolated_handoff: dict) -> None:
    expected_tables = {
        "handoff_state",
        "decisions",
        "blockers",
        "next_actions",
        "verified_tests",
        "review_findings",
        "task_archives",
        "worktree_lanes",
        "worker_reports",
        "lane_messages",
        "plan_cursors",
    }

    # First bootstrap
    with handoff_core._get_db_connection() as conn:
        first_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('handoff_state','decisions','blockers','next_actions','verified_tests','review_findings','task_archives','worktree_lanes','worker_reports','lane_messages','plan_cursors')"
            )
        }

    # Second bootstrap should produce identical schema (no error/no drift)
    with handoff_core._get_db_connection() as conn:
        second_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('handoff_state','decisions','blockers','next_actions','verified_tests','review_findings','task_archives','worktree_lanes','worker_reports','lane_messages','plan_cursors')"
            )
        }
        review_finding_columns = {row[1] for row in conn.execute("PRAGMA table_info(review_findings)").fetchall()}
        decision_columns = {row[1] for row in conn.execute("PRAGMA table_info(decisions)").fetchall()}
        plan_cursor_columns = {row[1] for row in conn.execute("PRAGMA table_info(plan_cursors)").fetchall()}

    assert first_tables == expected_tables
    assert second_tables == expected_tables
    assert "lane_id" in decision_columns
    assert {
        "resolution_notes",
        "reopen_count",
        "last_reopen_reason",
        "last_reopened_at",
        "updated_at",
    }.issubset(review_finding_columns)
    assert {"plan_item_id", "state", "dispatch_count", "summary"}.issubset(plan_cursor_columns)


def test_plan_cursor_crud_round_trip(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-5-task-plan-driven-orchestrator",
            objective="Drive work from a task plan",
            status="in_progress",
        )
    )

    created = _parse(
        mcp_server.upsert_plan_cursor(
            task_ref="daemon-5-task-plan-driven-orchestrator",
            plan_item_id="phase-1::phase-1-backend::checklist_1",
            state="dispatched",
            lane_id="backend-domain",
            summary="Implement backend slice",
            source_heading="Phase 1: Backend",
        )
    )
    assert created["ok"] is True
    assert created["cursor"]["dispatch_count"] == 1

    fetched = _parse(
        mcp_server.get_plan_cursor(
            task_ref="daemon-5-task-plan-driven-orchestrator",
            plan_item_id="phase-1::phase-1-backend::checklist_1",
        )
    )
    assert fetched["cursor"]["state"] == "dispatched"

    updated = _parse(
        mcp_server.upsert_plan_cursor(
            task_ref="daemon-5-task-plan-driven-orchestrator",
            plan_item_id="phase-1::phase-1-backend::checklist_1",
            state="completed",
            lane_id="backend-domain",
            summary="Implement backend slice",
        )
    )
    assert updated["cursor"]["state"] == "completed"
    assert updated["cursor"]["completed_at"] is not None

    listed = _parse(
        mcp_server.list_plan_cursors(
            task_ref="daemon-5-task-plan-driven-orchestrator",
            state="completed",
        )
    )
    assert listed["returned"] == 1


def test_set_handoff_state_revision_conflict(isolated_handoff: dict) -> None:
    inserted = _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Initial objective",
            status="in_progress",
            actor={"agent": "agent-a"},
        )
    )
    assert inserted["ok"] is True
    assert inserted["inserted"] is True
    assert inserted["active"]["revision"] == 0

    updated = _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Revised objective",
            status="review",
            expected_revision=0,
            actor={"agent": "agent-b"},
        )
    )
    assert updated["ok"] is True
    assert updated["updated"] is True
    assert updated["active"]["revision"] == 1

    conflict = _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Stale writer objective",
            status="blocked",
            expected_revision=0,
            actor={"agent": "agent-c"},
        )
    )
    assert conflict["ok"] is False
    assert conflict["error"] == "Revision conflict."
    assert conflict["current_revision"] == 1


def test_blocker_constraints_enforced(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Objective",
            status="in_progress",
        )
    )

    with pytest.raises(sqlite3.IntegrityError), handoff_core._get_db_connection() as conn:
        conn.execute(
            """
                INSERT INTO blockers (task_ref, description, status, resolved_at)
                VALUES (?, ?, 'resolved', NULL)
                """,
            ("4.12.0", "Resolved without timestamp"),
        )

    add_resp = _parse(
        mcp_server.report_blocker(
            operation="add",
            description="Need API key",
            actor={"agent": "agent-a"},
        )
    )
    blocker_id = add_resp["blocker"]["id"]

    resolved = _parse(
        mcp_server.report_blocker(
            operation="resolve",
            blocker_id=blocker_id,
            actor={"agent": "agent-a"},
        )
    )
    assert resolved["ok"] is True
    assert resolved["blocker"]["status"] == "resolved"
    assert resolved["blocker"]["resolved_at"] is not None


def test_get_handoff_state_compact_defaults_enforced(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Objective",
            status="in_progress",
        )
    )

    for idx in range(8):
        _parse(
            mcp_server.report_blocker(
                operation="add",
                description=f"blocker-{idx}",
            )
        )

    for idx in range(9):
        _parse(
            mcp_server.update_next_actions(
                operation="add",
                action=f"action-{idx}",
                priority=idx,
            )
        )

    for idx in range(6):
        _parse(
            mcp_server.record_decision(
                session="s1",
                decision=f"decision-{idx}",
            )
        )

    for idx in range(7):
        _parse(
            mcp_server.record_test_result(
                session="s1",
                command=f"pytest -k t{idx}",
                passed=True,
                result="ok",
            )
        )

    compact = _parse(mcp_server.get_handoff_state())

    assert compact["ok"] is True
    assert compact["limits"] == {"blockers": 5, "actions": 5, "decisions": 3, "tests": 3, "findings": 10}
    assert len(compact["blockers_open"]) == 5
    assert len(compact["actions_pending"]) == 5
    assert len(compact["decisions_recent"]) == 3
    assert len(compact["tests_recent"]) == 3

    verbose = _parse(mcp_server.get_handoff_state(verbose=True))
    assert len(verbose["blockers_open"]) == 8
    assert len(verbose["actions_pending"]) == 9
    assert len(verbose["decisions_recent"]) == 6
    assert len(verbose["tests_recent"]) == 7


def test_new_writes_prefer_current_git_context_over_stale_handoff_state(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "review-branch"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Codex"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    head_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()

    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=tmp_path / ".task-state",
        current_task_path=tmp_path / "CURRENT_TASK.md",
    )
    mcp_server.configure_runtime(runtime)

    _parse(
        mcp_server.set_handoff_state(
            task_ref="review-task",
            objective="review objective",
            actor={"agent": "worker-agent", "branch": "stale-worker-branch", "commit_sha": "deadbeef"},
        )
    )

    finding = _parse(
        mcp_server.record_review_finding(
            session="review-session",
            finding_id="PROV-1",
            severity="medium",
            file_path="Makefile",
            description="provenance check",
        )
    )["finding"]

    assert finding["branch"] == "review-branch"
    assert finding["commit_sha"] == head_sha


def test_worker_worktree_scopes_open_lane_messages_to_its_registered_lane(tmp_path: Path) -> None:
    orchestrator_root = tmp_path / "orchestrator"
    frontend_root = tmp_path / "orchestrator-p5-frontend"
    backend_root = tmp_path / "orchestrator-p5-backend-http"
    orchestrator_root.mkdir()
    frontend_root.mkdir()
    backend_root.mkdir()

    shared_state_dir = orchestrator_root / ".task-state"
    shared_current_task = orchestrator_root / "CURRENT_TASK.md"

    mcp_server.configure_runtime(
        RuntimeConfig.for_workspace(
            orchestrator_root,
            state_dir=shared_state_dir,
            current_task_path=shared_current_task,
        )
    )
    _parse(
        mcp_server.set_handoff_state(
            task_ref="task-lane-inbox",
            objective="Verify worker worktrees see their own lane dispatches",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.upsert_worktree_lane(
            lane_id="frontend",
            worktree_path=str(frontend_root),
            branch="codex/p5-frontend",
            status="active",
        )
    )
    _parse(
        mcp_server.upsert_worktree_lane(
            lane_id="backend-http",
            worktree_path=str(backend_root),
            branch="codex/p5-backend-http",
            status="active",
        )
    )
    _parse(
        mcp_server.record_lane_message(
            lane_id="frontend",
            session="dispatch-frontend",
            direction="orchestrator_to_worker",
            subject="Frontend dispatch",
            message="Frontend lane should see this open dispatch.",
        )
    )
    _parse(
        mcp_server.record_lane_message(
            lane_id="backend-http",
            session="dispatch-backend",
            direction="orchestrator_to_worker",
            subject="Backend dispatch",
            message="Backend lane should keep this dispatch scoped to itself.",
        )
    )

    mcp_server.configure_runtime(
        RuntimeConfig.for_workspace(
            frontend_root,
            state_dir=shared_state_dir,
            current_task_path=shared_current_task,
        )
    )

    worker_state = _parse(mcp_server.get_handoff_state())
    assert worker_state["current_lane"]["lane_id"] == "frontend"
    assert [message["lane_id"] for message in worker_state["lane_messages_open"]] == ["frontend"]
    assert worker_state["lane_messages_open"][0]["subject"] == "Frontend dispatch"

    worker_messages = _parse(mcp_server.list_lane_messages(status="open"))
    assert worker_messages["lane_id"] == "frontend"
    assert worker_messages["current_lane"]["lane_id"] == "frontend"
    assert [message["lane_id"] for message in worker_messages["messages"]] == ["frontend"]

    mcp_server.configure_runtime(
        RuntimeConfig.for_workspace(
            orchestrator_root,
            state_dir=shared_state_dir,
            current_task_path=shared_current_task,
        )
    )
    orchestrator_state = _parse(mcp_server.get_handoff_state())
    assert orchestrator_state["current_lane"] is None
    assert {message["lane_id"] for message in orchestrator_state["lane_messages_open"]} == {"frontend", "backend-http"}


def test_export_and_import_handoff_state_round_trip(isolated_handoff: dict) -> None:
    export_path = isolated_handoff["state_dir"] / "exports" / "roundtrip.json"

    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Round trip objective",
            status="in_progress",
        )
    )
    _parse(mcp_server.record_decision(session="s1", decision="seed decision"))
    _parse(
        mcp_server.upsert_worktree_lane(
            lane_id="backend-http",
            worktree_path="/tmp/backend-http",
            branch="codex/p5-backend-http",
            title="Backend HTTP",
            status="active",
        )
    )
    _parse(mcp_server.update_next_actions(operation="add", action="seed action", priority=1))
    _parse(mcp_server.report_blocker(operation="add", description="seed blocker"))
    _parse(
        mcp_server.record_worker_report(
            lane_id="backend-http",
            session="s1",
            summary="lane summary",
            changed_files=["apps/prototype-description-service/foo.py"],
            test_commands=["pytest -q"],
            merge_ready=True,
        )
    )
    _parse(
        mcp_server.record_lane_message(
            lane_id="backend-http",
            session="s1",
            direction="worker_to_orchestrator",
            subject="Need review",
            message="Ready for merge",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="M-1",
            severity="medium",
            file_path="apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx",
            description="seed finding",
        )
    )
    _parse(
        mcp_server.record_test_result(
            session="s1",
            command="pytest -q",
            passed=True,
            result="1 passed",
        )
    )

    exported = _parse(
        mcp_server.export_handoff_state(
            task_ref="4.12.0",
            output_path=str(export_path),
            include_markdown=True,
        )
    )
    assert exported["ok"] is True
    assert export_path.exists()

    with handoff_core._get_db_connection() as conn:
        conn.execute("DELETE FROM decisions WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM next_actions WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM blockers WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM verified_tests WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM review_findings WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM worktree_lanes WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM worker_reports WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM lane_messages WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM handoff_state WHERE id = 1")

    imported = _parse(
        mcp_server.import_handoff_state(
            input_path=str(export_path),
            mode="replace_task",
            set_active=True,
        )
    )
    assert imported["ok"] is True
    assert imported["task_ref"] == "4.12.0"

    state = _parse(mcp_server.get_handoff_state(task_ref="4.12.0", verbose=True))
    assert state["active"] is not None
    assert len(state["decisions_recent"]) == 1
    assert len(state["actions_pending"]) == 1
    assert len(state["blockers_open"]) == 1
    assert len(state["tests_recent"]) == 1
    assert len(state["findings_open"]) == 1
    assert len(state["worktree_lanes"]) == 1
    assert len(state["worker_reports_recent"]) == 1
    assert len(state["lane_messages_open"]) == 1


def test_worktree_lane_activity_and_reports_are_recorded_by_lane(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="5.0.0",
            objective="Lane tracking",
            status="in_progress",
        )
    )
    lane = _parse(
        mcp_server.upsert_worktree_lane(
            lane_id="frontend",
            worktree_path="/tmp/frontend",
            branch="codex/p5-frontend",
            title="Frontend",
            owner_agent="worker-a",
            status="active",
        )
    )
    assert lane["ok"] is True

    actor = {"agent": "worker-a", "branch": "codex/p5-frontend", "lane_id": "frontend"}
    _parse(mcp_server.record_decision(session="lane", decision="Started frontend slice", actor=actor))
    _parse(mcp_server.record_test_result(session="lane", command="npm run test", passed=True, actor=actor))
    _parse(mcp_server.update_next_actions(operation="add", action="Finish panel", priority=1, actor=actor))
    _parse(mcp_server.report_blocker(operation="add", description="Waiting on copy", actor=actor))
    _parse(
        mcp_server.record_review_finding(
            session="lane",
            finding_id="F-1",
            severity="low",
            file_path="README.md",
            description="lane scoped finding",
            actor=actor,
        )
    )
    report = _parse(
        mcp_server.record_worker_report(
            lane_id="frontend",
            session="lane",
            summary="Frontend ready for review",
            changed_files=["apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx"],
            test_commands=["npm run test"],
            blockers=["Waiting on copy"],
            merge_ready=False,
            actor=actor,
        )
    )
    assert report["ok"] is True
    message = _parse(
        mcp_server.record_lane_message(
            lane_id="frontend",
            session="lane",
            direction="worker_to_orchestrator",
            subject="Review requested",
            message="Please review frontend lane",
            actor=actor,
        )
    )
    assert message["ok"] is True

    activity = _parse(mcp_server.get_lane_activity(lane_id="frontend"))
    assert activity["ok"] is True
    assert activity["lane"]["branch"] == "codex/p5-frontend"
    assert len(activity["decisions"]) == 1
    assert len(activity["tests"]) == 1
    assert len(activity["actions"]) == 1
    assert len(activity["blockers"]) == 1
    assert len(activity["findings"]) == 1
    assert len(activity["reports"]) == 1
    assert len(activity["messages"]) == 1

    listed_reports = _parse(mcp_server.list_worker_reports(lane_id="frontend"))
    assert listed_reports["total_matching"] == 1
    assert listed_reports["reports"][0]["lane_id"] == "frontend"

    listed_messages = _parse(mcp_server.list_lane_messages(lane_id="frontend"))
    assert listed_messages["total_matching"] == 1
    updated_message = _parse(
        mcp_server.update_lane_message(
            message_id=listed_messages["messages"][0]["id"],
            status="acknowledged",
        )
    )
    assert updated_message["message"]["status"] == "acknowledged"


def test_import_handoff_state_rejects_malformed_snapshot_payload(isolated_handoff: dict) -> None:
    malformed_path = isolated_handoff["state_dir"] / "exports" / "malformed.json"
    malformed_path.parent.mkdir(parents=True, exist_ok=True)
    malformed_path.write_text(json.dumps({"task_ref": "4.12.0", "snapshot": []}))

    response = _parse(
        mcp_server.import_handoff_state(
            input_path=str(malformed_path),
            mode="merge",
            set_active=False,
        )
    )

    assert response["ok"] is False
    assert response["error"] == "Invalid import payload: snapshot must be an object."


def test_update_review_finding_status_and_resolved_at(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Review finding updates",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.record_review_finding(
            session="s-review",
            finding_id="M-9",
            severity="medium",
            file_path="scripts/mcp/unified_server.py",
            description="Needs status transition coverage",
            actor={"agent": "reviewer", "branch": "feature/review", "commit_sha": "abc123"},
        )
    )
    finding_id = created["finding"]["id"]

    fixed = _parse(
        mcp_server.update_review_finding(
            finding_db_id=finding_id,
            status="fixed",
            actor={"agent": "tester"},
        )
    )
    assert fixed["ok"] is True
    assert fixed["finding"]["status"] == "fixed"
    assert fixed["finding"]["resolved_at"] is not None
    assert fixed["finding"]["agent"] == "reviewer"
    assert fixed["finding"]["branch"] == "feature/review"
    assert fixed["finding"]["commit_sha"] == "abc123"

    reopen_missing_reason = _parse(
        mcp_server.update_review_finding(
            finding_db_id=finding_id,
            status="open",
        )
    )
    assert reopen_missing_reason["ok"] is False
    assert "reopen_reason is required" in reopen_missing_reason["error"]

    reopened = _parse(
        mcp_server.update_review_finding(
            finding_db_id=finding_id,
            status="open",
            reopen_reason="Regression observed in latest handoff update.",
        )
    )
    assert reopened["ok"] is True
    assert reopened["finding"]["status"] == "open"
    assert reopened["finding"]["resolved_at"] is None
    assert reopened["finding"]["reopen_count"] == 1
    assert reopened["finding"]["last_reopen_reason"] == "Regression observed in latest handoff update."
    assert reopened["finding"]["last_reopened_at"] is not None


def test_update_review_finding_requires_verified_descendant_commit(isolated_handoff: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Review commit guard",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.record_review_finding(
            session="s-review",
            finding_id="GUARD-1",
            severity="high",
            file_path="scripts/mcp/unified_server.py",
            description="Guard descendant fix",
            actor={"agent": "reviewer", "branch": "feature/review", "commit_sha": "abc123"},
        )
    )
    finding_db_id = created["finding"]["id"]

    monkeypatch.setattr(handoff_core, "_detect_git_write_context", lambda: ("feature/review", "def456"))
    monkeypatch.setattr(
        handoff_core,
        "_classify_commit_relation",
        lambda reference_sha, candidate_sha: "descendant" if (reference_sha, candidate_sha) in {("abc123", "def456"), ("abc123", "abc123")} else "unknown",
    )

    missing_verified_commit = _parse(
        mcp_server.update_review_finding(
            finding_db_id=finding_db_id,
            status="fixed",
            resolution_notes="Verified after follow-up changes.",
        )
    )
    assert missing_verified_commit["ok"] is False
    assert "verified_commit_sha is required" in missing_verified_commit["error"]
    assert missing_verified_commit["commit_guard"]["finding_commit_sha"] == "abc123"
    assert missing_verified_commit["commit_guard"]["current_commit_sha"] == "def456"
    assert missing_verified_commit["commit_guard"]["relation"] == "descendant"

    mismatched_verified_commit = _parse(
        mcp_server.update_review_finding(
            finding_db_id=finding_db_id,
            status="fixed",
            resolution_notes="Verified after follow-up changes.",
            verified_commit_sha="zzz999",
        )
    )
    assert mismatched_verified_commit["ok"] is False
    assert "must match the current workspace/actor commit" in mismatched_verified_commit["error"]

    fixed = _parse(
        mcp_server.update_review_finding(
            finding_db_id=finding_db_id,
            status="fixed",
            resolution_notes="Verified on descendant commit def456 after reviewing the newer branch state.",
            verified_commit_sha="def456",
        )
    )
    assert fixed["ok"] is True
    assert fixed["finding"]["status"] == "fixed"
    assert fixed["commit_guard"]["relation"] == "descendant"
    assert fixed["commit_guard"]["verified_commit_sha"] == "def456"


def test_update_review_finding_rejects_non_descendant_verified_commit(isolated_handoff: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Reject divergent verification",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.record_review_finding(
            session="s-review",
            finding_id="GUARD-2",
            severity="medium",
            file_path="scripts/mcp/unified_server.py",
            description="Guard divergent fix",
            actor={"agent": "reviewer", "branch": "feature/review", "commit_sha": "abc123"},
        )
    )
    finding_db_id = created["finding"]["id"]

    monkeypatch.setattr(handoff_core, "_detect_git_write_context", lambda: ("feature/review", "zzz999"))

    def _fake_relation(reference_sha: str | None, candidate_sha: str | None) -> str:
        mapping = {
            ("abc123", "def456"): "descendant",
            ("abc123", "zzz999"): "diverged",
        }
        return mapping.get((reference_sha, candidate_sha), "unknown")

    monkeypatch.setattr(handoff_core, "_classify_commit_relation", _fake_relation)

    divergent = _parse(
        mcp_server.update_review_finding(
            finding_db_id=finding_db_id,
            status="fixed",
            resolution_notes="Attempted verification on unrelated commit.",
            verified_commit_sha="zzz999",
        )
    )
    assert divergent["ok"] is False
    assert "same commit or a newer descendant commit" in divergent["error"]
    assert divergent["commit_guard"]["relation"] == "diverged"


def test_review_list_and_summary_surface_workspace_git_context(isolated_handoff: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Workspace git visibility",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="s-review",
            finding_id="CTX-1",
            severity="medium",
            file_path="scripts/mcp/unified_server.py",
            description="Workspace git visibility finding",
            actor={"agent": "reviewer", "branch": "feature/review", "commit_sha": "abc123"},
        )
    )

    monkeypatch.setattr(handoff_core, "_detect_git_write_context", lambda: ("feature/review", "def456"))
    monkeypatch.setattr(
        handoff_core,
        "_classify_commit_relation",
        lambda reference_sha, candidate_sha: "descendant" if (reference_sha, candidate_sha) == ("abc123", "def456") else "same",
    )

    listed = _parse(mcp_server.list_review_findings())
    assert listed["ok"] is True
    assert listed["workspace_git"]["branch"] == "feature/review"
    assert listed["workspace_git"]["commit_sha"] == "def456"
    assert listed["findings"][0]["workspace_commit_relation"] == "descendant"
    assert listed["findings"][0]["workspace_branch_matches"] is True

    summary = _parse(mcp_server.get_review_findings_summary())
    assert summary["ok"] is True
    assert summary["workspace_git"]["commit_sha"] == "def456"
    assert summary["open_top"][0]["workspace_commit_relation"] == "descendant"


def test_update_review_finding_rejects_invalid_status_and_task_mismatch(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Review finding updates",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.record_review_finding(
            session="s-review",
            finding_id="L-2",
            severity="low",
            file_path="scripts/mcp/unified_server.py",
            description="Task mismatch case",
        )
    )
    finding_id = created["finding"]["id"]

    invalid = _parse(
        mcp_server.update_review_finding(
            finding_db_id=finding_id,
            status="closed",
        )
    )
    assert invalid["ok"] is False
    assert "Invalid status" in invalid["error"]

    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.1",
            objective="Switch active task",
            status="in_progress",
            expected_revision=0,
        )
    )
    mismatch = _parse(mcp_server.update_review_finding(finding_db_id=finding_id, status="fixed"))
    assert mismatch["ok"] is False
    assert mismatch["error"] == "Finding not found for task."


def test_record_review_finding_accepts_structured_details_and_actor_fallback(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Structured finding details",
            status="in_progress",
            actor={"agent": "codex", "branch": "feature/demo"},
        )
    )

    created = _parse(
        mcp_server.record_review_finding(
            session="s-review",
            finding_id="M-10",
            severity="medium",
            file_path="scripts/mcp/unified_server.py",
            description="Structured payload",
            details={"line_start": 10, "line_end": 12, "fix": "Extract helper"},
        )
    )
    finding = created["finding"]
    assert finding["line_start"] == 10
    assert finding["line_end"] == 12
    assert finding["fix"] == "Extract helper"
    assert finding["agent"] == "codex"
    assert finding["branch"] == "feature/demo"


def test_record_review_finding_rerecord_reopens_with_marker_reason(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Re-record reopen behavior",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="s-review",
            finding_id="M-11",
            severity="medium",
            file_path="scripts/mcp/unified_server.py",
            description="Original finding",
        )
    )
    _parse(
        mcp_server.update_review_finding(
            finding_id="M-11",
            status="fixed",
        )
    )

    rerecorded = _parse(
        mcp_server.record_review_finding(
            session="s-review-rerecord",
            finding_id="M-11",
            severity="medium",
            file_path="scripts/mcp/unified_server.py",
            description="Re-recorded after follow-up review",
        )
    )

    assert rerecorded["ok"] is True
    assert rerecorded["reopened"] is True
    assert rerecorded["finding"]["status"] == "open"
    assert rerecorded["finding"]["reopen_count"] == 1
    assert rerecorded["finding"]["last_reopen_reason"] == "Re-recorded via review-record."
    assert rerecorded["finding"]["last_reopened_at"] is not None


def test_list_review_findings_filters_and_pagination(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="List findings",
            status="in_progress",
        )
    )

    finding_ids: list[int] = []
    for finding_id, severity in [("H-1", "high"), ("M-2", "medium"), ("L-3", "low")]:
        created = _parse(
            mcp_server.record_review_finding(
                session="s-list",
                finding_id=finding_id,
                severity=severity,
                file_path="scripts/mcp/unified_server.py",
                description=f"Finding {finding_id}",
            )
        )
        finding_ids.append(int(created["finding"]["id"]))

    _parse(
        mcp_server.update_review_finding(
            finding_db_id=finding_ids[1],
            status="fixed",
        )
    )

    page_one = _parse(mcp_server.list_review_findings(limit=2, offset=0))
    assert page_one["ok"] is True
    assert page_one["total_matching"] == 3
    assert page_one["returned"] == 2
    assert page_one["has_more"] is True
    assert page_one["counts"]["status"]["open"] == 2
    assert page_one["counts"]["status"]["fixed"] == 1

    fixed_only = _parse(mcp_server.list_review_findings(status="fixed"))
    assert fixed_only["ok"] is True
    assert fixed_only["total_matching"] == 1
    assert fixed_only["findings"][0]["status"] == "fixed"

    high_only = _parse(mcp_server.list_review_findings(severity="high"))
    assert high_only["ok"] is True
    assert high_only["total_matching"] == 1
    assert high_only["findings"][0]["severity"] == "high"


def test_get_review_finding_respects_task_scope(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Get finding scope",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.record_review_finding(
            session="s-scope",
            finding_id="M-8",
            severity="medium",
            file_path="scripts/mcp/unified_server.py",
            description="Scoped finding",
        )
    )
    finding_db_id = int(created["finding"]["id"])

    switched = _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.1",
            objective="Different task",
            status="in_progress",
            expected_revision=0,
        )
    )
    assert switched["ok"] is True

    hidden = _parse(mcp_server.get_review_finding(finding_db_id=finding_db_id))
    assert hidden["ok"] is False
    assert hidden["error"] == "Finding not found for task."

    explicit = _parse(mcp_server.get_review_finding(finding_db_id=finding_db_id, task_ref="4.12.0"))
    assert explicit["ok"] is True
    assert explicit["finding"]["finding_id"] == "M-8"


def test_update_review_finding_cross_task(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="cross-update-a",
            objective="Task A",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.record_review_finding(
            session="s-cross",
            finding_id="CU-1",
            severity="medium",
            file_path="core.py",
            description="Cross-task finding",
        )
    )
    assert created["ok"] is True

    # Switch to a different active task
    _parse(
        mcp_server.set_handoff_state(
            task_ref="cross-update-b",
            objective="Task B",
            status="in_progress",
            expected_revision=0,
        )
    )

    # Without task_ref, finding is invisible to the new active task
    hidden = _parse(
        mcp_server.update_review_finding(
            finding_id="CU-1",
            status="fixed",
        )
    )
    assert hidden["ok"] is False

    # With explicit task_ref, update succeeds against the original task
    fixed = _parse(
        mcp_server.update_review_finding(
            finding_id="CU-1",
            status="fixed",
            task_ref="cross-update-a",
        )
    )
    assert fixed["ok"] is True
    assert fixed["finding"]["status"] == "fixed"

    # Reopen also works cross-task
    reopened = _parse(
        mcp_server.reopen_review_finding(
            finding_id="CU-1",
            reason="Needs re-check",
            task_ref="cross-update-a",
        )
    )
    assert reopened["ok"] is True
    assert reopened["reopened"] is True
    assert reopened["finding"]["status"] == "open"


def test_lane_reports_and_messages_accept_explicit_task_ref_cross_task(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="phase-5-a",
            objective="Task A",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.upsert_worktree_lane(
            lane_id="backend-domain",
            worktree_path="/tmp/backend-domain",
            branch="codex/p5-backend-domain",
            status="active",
        )
    )
    _parse(
        mcp_server.set_handoff_state(
            task_ref="phase-5-b",
            objective="Task B",
            status="in_progress",
            expected_revision=0,
        )
    )

    hidden_report = _parse(
        mcp_server.record_worker_report(
            lane_id="backend-domain",
            session="cross-task",
            summary="hidden",
        )
    )
    assert hidden_report["ok"] is False

    explicit_report = _parse(
        mcp_server.record_worker_report(
            task_ref="phase-5-a",
            lane_id="backend-domain",
            session="cross-task",
            summary="reported to original task",
        )
    )
    assert explicit_report["ok"] is True
    assert explicit_report["report"]["task_ref"] == "phase-5-a"

    hidden_message = _parse(
        mcp_server.record_lane_message(
            lane_id="backend-domain",
            session="cross-task",
            direction="worker_to_orchestrator",
            message="hidden",
        )
    )
    assert hidden_message["ok"] is False

    explicit_message = _parse(
        mcp_server.record_lane_message(
            task_ref="phase-5-a",
            lane_id="backend-domain",
            session="cross-task",
            direction="worker_to_orchestrator",
            message="reported to original task",
        )
    )
    assert explicit_message["ok"] is True
    assert explicit_message["message"]["task_ref"] == "phase-5-a"

    hidden_update = _parse(
        mcp_server.update_lane_message(
            message_id=explicit_message["message"]["id"],
            status="acknowledged",
        )
    )
    assert hidden_update["ok"] is False

    explicit_update = _parse(
        mcp_server.update_lane_message(
            message_id=explicit_message["message"]["id"],
            status="acknowledged",
            task_ref="phase-5-a",
        )
    )
    assert explicit_update["ok"] is True
    assert explicit_update["message"]["status"] == "acknowledged"


def test_lane_upsert_accepts_explicit_task_ref_cross_task(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="phase-5-a",
            objective="Task A",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.set_handoff_state(
            task_ref="phase-5-b",
            objective="Task B",
            status="in_progress",
            expected_revision=0,
        )
    )

    explicit_lane = _parse(
        mcp_server.upsert_worktree_lane(
            task_ref="phase-5-a",
            lane_id="backend-domain",
            worktree_path="/tmp/backend-domain",
            branch="codex/p5-backend-domain",
            status="blocked",
        )
    )
    assert explicit_lane["ok"] is True
    assert explicit_lane["lane"]["task_ref"] == "phase-5-a"
    assert explicit_lane["lane"]["status"] == "blocked"


def test_get_review_findings_summary_counts_and_limits(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Summarize findings",
            status="in_progress",
        )
    )
    open_finding = _parse(
        mcp_server.record_review_finding(
            session="s-summary",
            finding_id="H-2",
            severity="high",
            file_path="scripts/mcp/unified_server.py",
            description="Open finding",
        )
    )
    fixed_finding = _parse(
        mcp_server.record_review_finding(
            session="s-summary",
            finding_id="M-3",
            severity="medium",
            file_path="scripts/mcp/unified_server.py",
            description="Will be fixed",
        )
    )
    deferred_finding = _parse(
        mcp_server.record_review_finding(
            session="s-summary",
            finding_id="L-4",
            severity="low",
            file_path="scripts/mcp/unified_server.py",
            description="Will be deferred",
        )
    )

    _parse(
        mcp_server.update_review_finding(
            finding_db_id=int(fixed_finding["finding"]["id"]),
            status="fixed",
        )
    )
    _parse(
        mcp_server.update_review_finding(
            finding_db_id=int(deferred_finding["finding"]["id"]),
            status="deferred",
            resolution_notes="Deferred for summary coverage.",
        )
    )

    summary = _parse(
        mcp_server.get_review_findings_summary(
            top_n_open=1,
            top_n_recent_updates=2,
        )
    )
    assert summary["ok"] is True
    assert summary["counts"]["total"] == 3
    assert summary["counts"]["status"]["open"] == 1
    assert summary["counts"]["status"]["fixed"] == 1
    assert summary["counts"]["status"]["deferred"] == 1
    assert summary["counts"]["severity"]["high"] == 1
    assert summary["counts"]["severity"]["medium"] == 1
    assert summary["counts"]["severity"]["low"] == 1
    assert len(summary["open_top"]) == 1
    assert summary["open_top"][0]["id"] == open_finding["finding"]["id"]
    assert len(summary["recent_updates"]) == 2


def test_archive_and_dashboard_summary(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.99.0",
            objective="Archive me",
            status="done",
        )
    )
    _parse(mcp_server.record_decision(session="s-archive", decision="done"))
    _parse(mcp_server.update_next_actions(operation="add", action="cleanup", priority=1))

    archived = _parse(
        mcp_server.archive_task_state(
            task_ref="4.99.0",
            notes="completed",
            archive_by="agent-z",
            clear_active_if_matches=True,
            prune_working_rows=True,
            allow_destructive_clear=True,
        )
    )
    assert archived["ok"] is True
    assert archived["active_cleared"] is True
    assert archived["pruned_working_rows"] is True

    with handoff_core._get_db_connection() as conn:
        archive_row = conn.execute("SELECT * FROM task_archives WHERE task_ref = '4.99.0'").fetchone()
        assert archive_row is not None
        assert conn.execute("SELECT COUNT(*) FROM decisions WHERE task_ref = '4.99.0'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM next_actions WHERE task_ref = '4.99.0'").fetchone()[0] == 0

    dashboard = _parse(mcp_server.get_handoff_dashboard(include_archived=True))
    matching = [row for row in dashboard["tasks"] if row["task_ref"] == "4.99.0"]
    assert len(matching) == 1
    assert matching[0]["archived_at"] is not None


def test_generate_current_task_md_with_nested_tool_wrapper(
    isolated_handoff: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Nested wrapper objective",
            status="in_progress",
        )
    )

    class NestedWrapper:
        def __init__(self, fn):
            self.fn = fn

    # Simulate a FastMCP wrapper chain where top-level `.fn` is not directly callable.
    monkeypatch.setattr(
        mcp_server,
        "get_handoff_state",
        NestedWrapper(NestedWrapper(mcp_server.get_handoff_state)),
    )

    payload = _parse(mcp_server.generate_current_task_md(task_ref="4.12.0", write_file=False))
    assert payload["ok"] is True
    assert payload["written"] is False
    assert "CURRENT_TASK" in payload["markdown"]
    assert "Nested wrapper objective" in payload["markdown"]


def test_handoff_close_check_allows_no_active_task_when_configured(isolated_handoff: dict) -> None:
    response = _parse(mcp_server.handoff_close_check(allow_no_active_task=True, enforce=True))
    assert response["ok"] is True
    assert response["skipped"] is True
    assert response["ready_to_close"] is True


def test_handoff_close_check_enforce_fails_then_passes(isolated_handoff: dict) -> None:
    initialized = _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Close-check lifecycle",
            status="in_progress",
        )
    )
    assert initialized["ok"] is True

    _parse(
        mcp_server.record_review_finding(
            session="s-close-check",
            finding_id="M-12",
            severity="medium",
            file_path="scripts/mcp/unified_server.py",
            description="Close-check should fail while this is open",
        )
    )

    not_ready = _parse(mcp_server.handoff_close_check(enforce=True))
    assert not_ready["ok"] is False
    assert not_ready["ready_to_close"] is False
    assert not_ready["checks"]["open_review_findings"]["count"] == 1

    _parse(
        mcp_server.update_review_finding(
            finding_id="M-12",
            status="fixed",
        )
    )

    revision = int(initialized["active"]["revision"])
    moved_done = _parse(
        mcp_server.set_handoff_state(
            task_ref="4.12.0",
            objective="Close-check lifecycle",
            status="done",
            expected_revision=revision,
        )
    )
    assert moved_done["ok"] is True
    assert moved_done["active"]["revision"] == revision + 1

    _parse(mcp_server.generate_current_task_md(task_ref="4.12.0", write_file=True))

    ready = _parse(mcp_server.handoff_close_check(enforce=True))
    assert ready["ok"] is True
    assert ready["ready_to_close"] is True
    assert ready["checks"]["current_task_sync"]["is_in_sync"] is True


# ---------------------------------------------------------------------------
# generate_current_task_md -- related_task_refs
# ---------------------------------------------------------------------------


def test_generate_current_task_md_includes_related_findings(isolated_handoff: dict) -> None:
    """Open findings from related tasks appear under a grouped section."""
    # Set up the active task
    _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-3",
            objective="Active task",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            task_ref="daemon-3",
            session="s1",
            finding_id="D3-01",
            file_path="file_c.py",
            description="Daemon 3 finding",
            severity="low",
        )
    )

    # Set up two related tasks with findings
    _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-1",
            objective="Related task 1",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            task_ref="daemon-1",
            session="s1",
            finding_id="D1-01",
            file_path="file_a.py",
            description="Daemon 1 finding",
            severity="medium",
        )
    )
    _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-2",
            objective="Related task 2",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            task_ref="daemon-2",
            session="s1",
            finding_id="D2-01",
            file_path="file_b.py",
            description="Daemon 2 finding",
            severity="high",
        )
    )

    # Switch back to daemon-3 as active
    _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-3",
            objective="Active task",
            status="in_progress",
        )
    )

    payload = _parse(
        mcp_server.generate_current_task_md(
            task_ref="daemon-3",
            write_file=False,
            related_task_refs="daemon-1,daemon-2",
        )
    )
    assert payload["ok"] is True
    md = payload["markdown"]
    assert "## Open Review Findings" in md
    assert "D3-01" in md
    assert "## Related Open Review Findings" in md
    assert "### daemon-1" in md
    assert "D1-01" in md
    assert "### daemon-2" in md
    assert "D2-01" in md


def test_generate_current_task_md_related_excludes_active_task(isolated_handoff: dict) -> None:
    """If the active task_ref appears in related_task_refs, it is deduplicated."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-3",
            objective="Active",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            task_ref="daemon-3",
            session="s1",
            finding_id="D3-01",
            file_path="f.py",
            description="Finding",
            severity="low",
        )
    )

    payload = _parse(
        mcp_server.generate_current_task_md(
            task_ref="daemon-3",
            write_file=False,
            related_task_refs="daemon-3",
        )
    )
    md = payload["markdown"]
    # D3-01 should appear only once (in the main section), not duplicated
    assert md.count("D3-01") == 1
    assert "## Related Open Review Findings" not in md


def test_generate_current_task_md_related_skips_resolved(isolated_handoff: dict) -> None:
    """Resolved findings from related tasks should not appear."""
    # Create daemon-1 task first and resolve a finding while it is active
    init1 = _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-1",
            objective="Related",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            task_ref="daemon-1",
            session="s1",
            finding_id="D1-FIXED",
            file_path="f.py",
            description="Fixed finding",
            severity="medium",
        )
    )
    update_result = _parse(
        mcp_server.update_review_finding(
            finding_id="D1-FIXED",
            status="fixed",
            resolution_notes="Done",
        )
    )
    assert update_result["ok"] is True
    # Now switch to daemon-3 as the active task
    rev = init1["active"]["revision"]
    _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-3",
            objective="Active",
            status="in_progress",
            expected_revision=rev,
        )
    )

    payload = _parse(
        mcp_server.generate_current_task_md(
            task_ref="daemon-3",
            write_file=False,
            related_task_refs="daemon-1",
        )
    )
    md = payload["markdown"]
    assert "D1-FIXED" not in md
    assert "## Related Open Review Findings" not in md


def test_generate_current_task_md_no_related_param(isolated_handoff: dict) -> None:
    """When related_task_refs is not provided, no related section appears."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-3",
            objective="Active",
            status="in_progress",
        )
    )
    payload = _parse(
        mcp_server.generate_current_task_md(
            task_ref="daemon-3",
            write_file=False,
        )
    )
    md = payload["markdown"]
    assert "## Related Open Review Findings" not in md


# ---------------------------------------------------------------------------
# False-fix structural guards
# ---------------------------------------------------------------------------


def _create_and_cycle_finding(finding_id: str, cycles: int = 1) -> int:
    """Create a finding and reopen it `cycles` times (leaving it open)."""
    created = _parse(
        mcp_server.record_review_finding(
            session="s-guard",
            finding_id=finding_id,
            severity="high",
            file_path="core.py",
            description=f"Guard test finding {finding_id}",
        )
    )
    db_id = created["finding"]["id"]
    for i in range(cycles):
        _parse(mcp_server.update_review_finding(finding_db_id=db_id, status="fixed"))
        _parse(
            mcp_server.update_review_finding(
                finding_db_id=db_id,
                status="open",
                reopen_reason=f"Reopen cycle {i + 1}",
            )
        )
    return db_id


def test_reopen_escalation_requires_evidence(isolated_handoff: dict) -> None:
    """After >=2 reopens, closing as fixed requires verification_evidence."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="guard-reopen",
            objective="Reopen escalation guard",
            status="in_progress",
        )
    )
    db_id = _create_and_cycle_finding("RE-1", cycles=2)
    # reopen_count is now 2 -- should require evidence
    rejected = _parse(
        mcp_server.update_review_finding(
            finding_db_id=db_id,
            status="fixed",
        )
    )
    assert rejected["ok"] is False
    assert "verification_evidence is required" in rejected["error"]
    assert rejected["false_fix_guard"]["guard"] == "reopen_escalation"
    assert rejected["false_fix_guard"]["reopen_count"] == 2

    # With evidence, it succeeds
    accepted = _parse(
        mcp_server.update_review_finding(
            finding_db_id=db_id,
            status="fixed",
            verification_evidence="grep -n '_resolve_task_ref' core.py shows function at line 450",
        )
    )
    assert accepted["ok"] is True
    assert accepted["finding"]["status"] == "fixed"
    assert accepted["verification_evidence"] == "grep -n '_resolve_task_ref' core.py shows function at line 450"


def test_reopen_escalation_not_triggered_below_threshold(isolated_handoff: dict) -> None:
    """Findings with reopen_count < 2 can be fixed without evidence."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="guard-reopen-ok",
            objective="Below threshold",
            status="in_progress",
        )
    )
    db_id = _create_and_cycle_finding("RE-2", cycles=1)
    # reopen_count is 1 -- below threshold
    accepted = _parse(
        mcp_server.update_review_finding(
            finding_db_id=db_id,
            status="fixed",
        )
    )
    assert accepted["ok"] is True
    assert accepted["finding"]["status"] == "fixed"


def test_batch_close_detection_requires_evidence(isolated_handoff: dict) -> None:
    """Fixing 3+ findings within 60s window requires verification_evidence."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="guard-batch",
            objective="Batch close guard",
            status="in_progress",
        )
    )
    # Create 4 findings
    db_ids = []
    for i in range(4):
        created = _parse(
            mcp_server.record_review_finding(
                session="s-batch",
                finding_id=f"BC-{i}",
                severity="medium",
                file_path="core.py",
                description=f"Batch test {i}",
            )
        )
        db_ids.append(created["finding"]["id"])

    # Fix the first two -- no guard triggered (0 and 1 recent fixes)
    for db_id in db_ids[:2]:
        resp = _parse(mcp_server.update_review_finding(finding_db_id=db_id, status="fixed"))
        assert resp["ok"] is True

    # Third fix should trigger batch-close guard (2 recent fixes already in window)
    rejected = _parse(
        mcp_server.update_review_finding(finding_db_id=db_ids[2], status="fixed")
    )
    assert rejected["ok"] is False
    assert "Batch-close guard" in rejected["error"]
    assert rejected["false_fix_guard"]["guard"] == "batch_close"

    # With evidence, the third fix succeeds
    accepted = _parse(
        mcp_server.update_review_finding(
            finding_db_id=db_ids[2],
            status="fixed",
            verification_evidence="git diff HEAD~1 -- core.py shows BC-2 fix at line 100",
        )
    )
    assert accepted["ok"] is True


def test_verification_evidence_stored_and_returned(isolated_handoff: dict) -> None:
    """verification_evidence is persisted in DB and included in response."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="guard-store",
            objective="Evidence storage",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.record_review_finding(
            session="s-store",
            finding_id="VS-1",
            severity="low",
            file_path="core.py",
            description="Evidence storage test",
        )
    )
    db_id = created["finding"]["id"]

    fixed = _parse(
        mcp_server.update_review_finding(
            finding_db_id=db_id,
            status="fixed",
            verification_evidence="diff --git a/core.py b/core.py\n+    def new_function():",
        )
    )
    assert fixed["ok"] is True
    assert fixed["verification_evidence"] == "diff --git a/core.py b/core.py\n+    def new_function():"
    assert fixed["finding"]["verification_evidence"] == "diff --git a/core.py b/core.py\n+    def new_function():"


def test_verification_evidence_cleared_on_reopen(isolated_handoff: dict) -> None:
    """When a finding is reopened, verification_evidence is cleared."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="guard-clear",
            objective="Evidence cleared on reopen",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.record_review_finding(
            session="s-clear",
            finding_id="VC-1",
            severity="medium",
            file_path="core.py",
            description="Clear on reopen test",
        )
    )
    db_id = created["finding"]["id"]

    _parse(
        mcp_server.update_review_finding(
            finding_db_id=db_id,
            status="fixed",
            verification_evidence="some evidence",
        )
    )

    reopened = _parse(
        mcp_server.update_review_finding(
            finding_db_id=db_id,
            status="open",
            reopen_reason="Evidence was wrong",
        )
    )
    assert reopened["ok"] is True
    assert reopened["finding"]["verification_evidence"] is None


def test_verification_evidence_rejected_for_non_fixed_status(isolated_handoff: dict) -> None:
    """verification_evidence is only accepted when status='fixed'."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="guard-status",
            objective="Evidence status check",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.record_review_finding(
            session="s-statuscheck",
            finding_id="SC-1",
            severity="low",
            file_path="core.py",
            description="Status check test",
        )
    )
    db_id = created["finding"]["id"]

    rejected = _parse(
        mcp_server.update_review_finding(
            finding_db_id=db_id,
            status="wontfix",
            verification_evidence="this should be rejected",
        )
    )
    assert rejected["ok"] is False
    assert "only supported when status='fixed'" in rejected["error"]


def test_verification_evidence_too_long(isolated_handoff: dict) -> None:
    """verification_evidence exceeding max length is rejected."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="guard-len",
            objective="Evidence length check",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.record_review_finding(
            session="s-len",
            finding_id="LN-1",
            severity="low",
            file_path="core.py",
            description="Length check test",
        )
    )
    db_id = created["finding"]["id"]

    rejected = _parse(
        mcp_server.update_review_finding(
            finding_db_id=db_id,
            status="fixed",
            verification_evidence="x" * 2001,
        )
    )
    assert rejected["ok"] is False
    assert "2000" in rejected["error"]
