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

from scripts.mcp import unified_server as mcp_server  # type: ignore[import-untyped] # noqa: E402


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
    }

    # First bootstrap
    with mcp_server._get_db_connection() as conn:
        first_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('handoff_state','decisions','blockers','next_actions','verified_tests','review_findings','task_archives')"
            )
        }

    # Second bootstrap should produce identical schema (no error/no drift)
    with mcp_server._get_db_connection() as conn:
        second_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('handoff_state','decisions','blockers','next_actions','verified_tests','review_findings','task_archives')"
            )
        }
        review_finding_columns = {row[1] for row in conn.execute("PRAGMA table_info(review_findings)").fetchall()}

    assert first_tables == expected_tables
    assert second_tables == expected_tables
    assert {
        "resolution_notes",
        "reopen_count",
        "last_reopen_reason",
        "last_reopened_at",
        "updated_at",
    }.issubset(review_finding_columns)


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

    with pytest.raises(sqlite3.IntegrityError), mcp_server._get_db_connection() as conn:
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
    _parse(mcp_server.update_next_actions(operation="add", action="seed action", priority=1))
    _parse(mcp_server.report_blocker(operation="add", description="seed blocker"))
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

    with mcp_server._get_db_connection() as conn:
        conn.execute("DELETE FROM decisions WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM next_actions WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM blockers WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM verified_tests WHERE task_ref = '4.12.0'")
        conn.execute("DELETE FROM review_findings WHERE task_ref = '4.12.0'")
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
    assert mismatch["error"] == "Finding not found for active task."


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
