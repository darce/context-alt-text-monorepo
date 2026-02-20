"""Unit tests for MCP handoff state tools in scripts/mcp/unified_server.py."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure monorepo root is importable when tests run from app-local cwd.
REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mcp import unified_server as mcp_server


@pytest.fixture()
def isolated_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect handoff sqlite + generated markdown paths into tmp dir."""
    state_dir = tmp_path / ".task-state"
    db_path = state_dir / "handoff.db"
    current_task_path = tmp_path / "CURRENT_TASK.md"

    monkeypatch.setattr(mcp_server, "TASK_STATE_DIR", state_dir)
    monkeypatch.setattr(mcp_server, "TASK_EXPORTS_DIR", state_dir / "exports")
    monkeypatch.setattr(mcp_server, "HANDOFF_DB_PATH", db_path)
    monkeypatch.setattr(mcp_server, "CURRENT_TASK_PATH", current_task_path)

    return {
        "state_dir": state_dir,
        "db_path": db_path,
        "current_task_path": current_task_path,
    }


def _parse(payload: str) -> dict:
    return json.loads(payload)


def test_schema_bootstrap_is_idempotent(isolated_handoff: dict) -> None:
    expected_tables = {
        "handoff_state",
        "decisions",
        "blockers",
        "next_actions",
        "verified_tests",
        "task_archives",
    }

    # First bootstrap
    with mcp_server._get_db_connection() as conn:
        first_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('handoff_state','decisions','blockers','next_actions','verified_tests','task_archives')"
            )
        }

    # Second bootstrap should produce identical schema (no error/no drift)
    with mcp_server._get_db_connection() as conn:
        second_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('handoff_state','decisions','blockers','next_actions','verified_tests','task_archives')"
            )
        }

    assert first_tables == expected_tables
    assert second_tables == expected_tables


def test_set_handoff_state_revision_conflict(isolated_handoff: dict) -> None:
    inserted = _parse(
        mcp_server.set_handoff_state.fn(
            task_ref="4.12.0",
            objective="Initial objective",
            status="in_progress",
            agent="agent-a",
        )
    )
    assert inserted["ok"] is True
    assert inserted["inserted"] is True
    assert inserted["active"]["revision"] == 0

    updated = _parse(
        mcp_server.set_handoff_state.fn(
            task_ref="4.12.0",
            objective="Revised objective",
            status="review",
            expected_revision=0,
            agent="agent-b",
        )
    )
    assert updated["ok"] is True
    assert updated["updated"] is True
    assert updated["active"]["revision"] == 1

    conflict = _parse(
        mcp_server.set_handoff_state.fn(
            task_ref="4.12.0",
            objective="Stale writer objective",
            status="blocked",
            expected_revision=0,
            agent="agent-c",
        )
    )
    assert conflict["ok"] is False
    assert conflict["error"] == "Revision conflict."
    assert conflict["current_revision"] == 1


def test_blocker_constraints_enforced(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state.fn(
            task_ref="4.12.0",
            objective="Objective",
            status="in_progress",
        )
    )

    with pytest.raises(sqlite3.IntegrityError):
        with mcp_server._get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO blockers (task_ref, description, status, resolved_at)
                VALUES (?, ?, 'resolved', NULL)
                """,
                ("4.12.0", "Resolved without timestamp"),
            )

    add_resp = _parse(
        mcp_server.report_blocker.fn(
            operation="add",
            description="Need API key",
            agent="agent-a",
        )
    )
    blocker_id = add_resp["blocker"]["id"]

    resolved = _parse(
        mcp_server.report_blocker.fn(
            operation="resolve",
            blocker_id=blocker_id,
            agent="agent-a",
        )
    )
    assert resolved["ok"] is True
    assert resolved["blocker"]["status"] == "resolved"
    assert resolved["blocker"]["resolved_at"] is not None


def test_get_handoff_state_compact_defaults_enforced(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state.fn(
            task_ref="4.12.0",
            objective="Objective",
            status="in_progress",
        )
    )

    for idx in range(8):
        _parse(
            mcp_server.report_blocker.fn(
                operation="add",
                description=f"blocker-{idx}",
            )
        )

    for idx in range(9):
        _parse(
            mcp_server.update_next_actions.fn(
                operation="add",
                action=f"action-{idx}",
                priority=idx,
            )
        )

    for idx in range(6):
        _parse(
            mcp_server.record_decision.fn(
                session="s1",
                decision=f"decision-{idx}",
            )
        )

    for idx in range(7):
        _parse(
            mcp_server.record_test_result.fn(
                session="s1",
                command=f"pytest -k t{idx}",
                passed=True,
                result="ok",
            )
        )

    compact = _parse(mcp_server.get_handoff_state.fn())

    assert compact["ok"] is True
    assert compact["limits"] == {"blockers": 5, "actions": 5, "decisions": 3, "tests": 3}
    assert len(compact["blockers_open"]) == 5
    assert len(compact["actions_pending"]) == 5
    assert len(compact["decisions_recent"]) == 3
    assert len(compact["tests_recent"]) == 3

    verbose = _parse(mcp_server.get_handoff_state.fn(verbose=True))
    assert len(verbose["blockers_open"]) == 8
    assert len(verbose["actions_pending"]) == 9
    assert len(verbose["decisions_recent"]) == 6
    assert len(verbose["tests_recent"]) == 7


def test_export_and_import_handoff_state_round_trip(isolated_handoff: dict) -> None:
    export_path = isolated_handoff["state_dir"] / "exports" / "roundtrip.json"

    _parse(
        mcp_server.set_handoff_state.fn(
            task_ref="4.12.0",
            objective="Round trip objective",
            status="in_progress",
        )
    )
    _parse(mcp_server.record_decision.fn(session="s1", decision="seed decision"))
    _parse(mcp_server.update_next_actions.fn(operation="add", action="seed action", priority=1))
    _parse(mcp_server.report_blocker.fn(operation="add", description="seed blocker"))
    _parse(
        mcp_server.record_test_result.fn(
            session="s1",
            command="pytest -q",
            passed=True,
            result="1 passed",
        )
    )

    exported = _parse(
        mcp_server.export_handoff_state.fn(
            task_ref="4.12.0",
            output_path=str(export_path),
            include_markdown=True,
        )
    )
    assert exported["ok"] is True
    assert export_path.exists()

    with mcp_server._get_db_connection() as conn:
        conn.execute("DELETE FROM decisions WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM next_actions WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM blockers WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM verified_tests WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM handoff_state WHERE id = 1")

    imported = _parse(
        mcp_server.import_handoff_state.fn(
            input_path=str(export_path),
            mode="replace_task",
            set_active=True,
        )
    )
    assert imported["ok"] is True
    assert imported["task_ref"] == "4.12.0"

    state = _parse(mcp_server.get_handoff_state.fn(task_ref="4.12.0", verbose=True))
    assert state["active"] is not None
    assert len(state["decisions_recent"]) == 1
    assert len(state["actions_pending"]) == 1
    assert len(state["blockers_open"]) == 1
    assert len(state["tests_recent"]) == 1


def test_archive_and_dashboard_summary(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state.fn(
            task_ref="4.99.0",
            objective="Archive me",
            status="done",
        )
    )
    _parse(mcp_server.record_decision.fn(session="s-archive", decision="done"))
    _parse(mcp_server.update_next_actions.fn(operation="add", action="cleanup", priority=1))

    archived = _parse(
        mcp_server.archive_task_state.fn(
            task_ref="4.99.0",
            notes="completed",
            archive_by="agent-z",
            clear_active_if_matches=True,
            prune_working_rows=True,
        )
    )
    assert archived["ok"] is True
    assert archived["active_cleared"] is True
    assert archived["pruned_working_rows"] is True

    with mcp_server._get_db_connection() as conn:
        archive_row = conn.execute("SELECT * FROM task_archives WHERE task_ref = '4.99.0'").fetchone()
        assert archive_row is not None
        assert conn.execute("SELECT COUNT(*) FROM decisions WHERE task_ref = '4.99.0'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM next_actions WHERE task_ref = '4.99.0'").fetchone()[0] == 0

    dashboard = _parse(mcp_server.get_handoff_dashboard.fn(include_archived=True))
    matching = [row for row in dashboard["tasks"] if row["task_ref"] == "4.99.0"]
    assert len(matching) == 1
    assert matching[0]["archived_at"] is not None
