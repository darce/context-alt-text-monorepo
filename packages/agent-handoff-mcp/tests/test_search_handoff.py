"""Tests for structured FTS/BM25 handoff search.

Covers:
- FTS5 schema bootstrap (all virtual tables created on first connection)
- INSERT trigger maintenance for all four record types
- UPDATE and DELETE trigger maintenance
- Scope filters (task_ref, lane_id, record_types)
- Error handling (empty queries, invalid types)
- Backfill for pre-existing rows
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp.config import RuntimeConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Isolated handoff DB per test; seeds an active task so _resolve_task_ref works."""
    state_dir = tmp_path / ".task-state"
    runtime = RuntimeConfig.for_workspace(tmp_path, state_dir=state_dir)
    mcp_server.configure_runtime(runtime)
    handoff_core.set_handoff_state(
        task_ref="test-task",
        objective="Search implementation test",
        status="in_progress",
    )
    return {"state_dir": state_dir, "task_ref": "test-task"}


def _parse(payload: str | dict) -> dict:
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


# ---------------------------------------------------------------------------
# FTS5 schema bootstrap
# ---------------------------------------------------------------------------


def test_fts_tables_exist_after_connection(isolated_env: dict) -> None:
    """All four FTS5 virtual tables must exist after first _get_db_connection()."""
    with handoff_core._get_db_connection() as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%_fts'"
            ).fetchall()
        }
    for expected in ("decisions_fts", "findings_fts", "blockers_fts", "actions_fts"):
        assert expected in names, f"Expected FTS table {expected!r} not found; got {names}."


# ---------------------------------------------------------------------------
# INSERT trigger tests
# ---------------------------------------------------------------------------


def test_insert_trigger_decision(isolated_env: dict) -> None:
    """Inserting a decision must index it in decisions_fts via trigger."""
    handoff_core.record_decision(
        session="s1",
        decision="exponential backoff retry policy",
        rationale="avoids thundering herd",
    )
    result = _parse(
        handoff_core.search_handoff(
            queries=["exponential backoff"],
            record_types=["decision"],
        )
    )
    assert result["ok"] is True
    assert any(r["record_type"] == "decision" for r in result["results"])


def test_insert_trigger_finding(isolated_env: dict) -> None:
    """Inserting a review finding must index it in findings_fts via trigger."""
    handoff_core.record_review_finding(
        session="s1",
        finding_id="F-001",
        severity="high",
        file_path="src/core.py",
        description="missing input validation on the webhook endpoint",
        details={"fix": "validate required fields before processing"},
    )
    result = _parse(
        handoff_core.search_handoff(
            queries=["input validation"],  # adjacent words in description
            record_types=["finding"],
        )
    )
    assert result["ok"] is True
    assert any(r["record_type"] == "finding" for r in result["results"])


def test_insert_trigger_blocker(isolated_env: dict) -> None:
    """Inserting a blocker must index it in blockers_fts via trigger."""
    handoff_core.report_blocker(
        operation="add",
        description="database migration blocked pending architecture approval",
    )
    result = _parse(
        handoff_core.search_handoff(
            queries=["migration blocked"],  # adjacent words in description
            record_types=["blocker"],
        )
    )
    assert result["ok"] is True
    assert any(r["record_type"] == "blocker" for r in result["results"])


def test_insert_trigger_action(isolated_env: dict) -> None:
    """Inserting a next action must index it in actions_fts via trigger."""
    handoff_core.update_next_actions(
        operation="add",
        action="implement rate limiter for outbound requests",
    )
    result = _parse(
        handoff_core.search_handoff(
            queries=["rate limiter"],
            record_types=["action"],
        )
    )
    assert result["ok"] is True
    assert any(r["record_type"] == "action" for r in result["results"])


# ---------------------------------------------------------------------------
# UPDATE and DELETE trigger tests  (direct DB manipulation to cover triggers)
# ---------------------------------------------------------------------------


def test_update_trigger_decision(isolated_env: dict) -> None:
    """Updating a decision row via SQL must update its FTS body."""
    res = _parse(
        handoff_core.record_decision(
            session="s1",
            decision="initial circuit breaker design pattern",
        )
    )
    row_id = res["decision"]["id"]

    # Update the row directly to exercise the UPDATE trigger.
    with handoff_core._get_db_connection() as conn:
        conn.execute(
            "UPDATE decisions SET decision = ? WHERE id = ?",
            ("updated bulkhead isolation strategy", row_id),
        )

    # Old text must no longer match.
    old_result = _parse(
        handoff_core.search_handoff(queries=["circuit breaker design"], record_types=["decision"])
    )
    assert old_result["ok"] is True
    assert all(r.get("record_id") != row_id for r in old_result["results"])

    # New text must match.
    new_result = _parse(
        handoff_core.search_handoff(queries=["bulkhead isolation"], record_types=["decision"])
    )
    assert new_result["ok"] is True
    assert any(r["record_id"] == row_id for r in new_result["results"])


def test_delete_trigger_decision(isolated_env: dict) -> None:
    """Deleting a decisions row must remove its FTS entry."""
    res = _parse(
        handoff_core.record_decision(
            session="s1",
            decision="ephemeral canary deployment token scheme",
        )
    )
    row_id = res["decision"]["id"]

    # Verify indexed before deletion.
    pre_search = _parse(
        handoff_core.search_handoff(queries=["canary deployment"], record_types=["decision"])
    )
    assert any(r["record_id"] == row_id for r in pre_search["results"])

    # Delete the row directly to exercise the DELETE trigger.
    with handoff_core._get_db_connection() as conn:
        conn.execute("DELETE FROM decisions WHERE id = ?", (row_id,))

    post_search = _parse(
        handoff_core.search_handoff(queries=["canary deployment"], record_types=["decision"])
    )
    assert all(r.get("record_id") != row_id for r in post_search["results"])


# ---------------------------------------------------------------------------
# Scope filter tests
# ---------------------------------------------------------------------------


def test_search_scoped_by_task_ref_returns_matching_task(isolated_env: dict) -> None:
    """Scoping by task_ref must return only records from that task."""
    handoff_core.record_decision(
        session="s1",
        decision="telemetry pipeline aggregation configuration",
    )

    # Scoped to the correct task returns a result.
    result = _parse(
        handoff_core.search_handoff(
            queries=["telemetry pipeline"],
            task_ref="test-task",
            record_types=["decision"],
        )
    )
    assert result["ok"] is True
    assert result["results"]
    assert all(r["task_ref"] == "test-task" for r in result["results"])


def test_search_scoped_by_task_ref_excludes_other_tasks(isolated_env: dict) -> None:
    """Scoping by a nonexistent task_ref must return empty results."""
    handoff_core.record_decision(
        session="s1",
        decision="telemetry pipeline aggregation configuration",
    )

    empty = _parse(
        handoff_core.search_handoff(
            queries=["telemetry pipeline"],
            task_ref="nonexistent-task-xyz",
            record_types=["decision"],
        )
    )
    assert empty["ok"] is True
    assert empty["results"] == []


def test_search_scoped_by_lane_id(isolated_env: dict) -> None:
    """Scoping by lane_id must return only records with that lane."""
    handoff_core.record_decision(
        session="s1",
        decision="quorum consensus ledger protocol design",
        actor={"lane_id": "backend-domain"},
    )
    # Record a second decision without a lane_id.
    handoff_core.record_decision(
        session="s1",
        decision="quorum consensus ledger protocol design",
    )

    result = _parse(
        handoff_core.search_handoff(
            queries=["quorum consensus"],
            lane_id="backend-domain",
            record_types=["decision"],
        )
    )
    assert result["ok"] is True
    assert result["results"]
    assert all(r["lane_id"] == "backend-domain" for r in result["results"])


def test_search_scoped_by_record_types_excludes_other_types(isolated_env: dict) -> None:
    """record_types filter must exclude non-requested record types."""
    handoff_core.record_decision(session="s1", decision="zephyr unique filterkeyword test")
    handoff_core.report_blocker(operation="add", description="zephyr unique filterkeyword test")

    result = _parse(
        handoff_core.search_handoff(
            queries=["filterkeyword"],  # single unique word present in both records
            record_types=["decision"],
        )
    )
    assert result["ok"] is True
    assert result["results"]
    assert all(r["record_type"] == "decision" for r in result["results"])


def test_search_all_record_types_by_default(isolated_env: dict) -> None:
    """Omitting record_types must search across all four record types."""
    handoff_core.record_decision(session="s1", decision="omniquery alpha unique designword")
    handoff_core.report_blocker(operation="add", description="omniquery beta unique designword")

    result = _parse(
        handoff_core.search_handoff(queries=["omniquery"])
    )
    assert result["ok"] is True
    assert len(result["record_types_searched"]) == 4
    types_in_results = {r["record_type"] for r in result["results"]}
    assert "decision" in types_in_results
    assert "blocker" in types_in_results


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_search_handoff_none_queries_returns_error(isolated_env: dict) -> None:
    result = _parse(handoff_core.search_handoff(queries=None))
    assert result["ok"] is False
    assert "queries" in result["error"].lower()


def test_search_handoff_all_blank_queries_returns_error(isolated_env: dict) -> None:
    result = _parse(handoff_core.search_handoff(queries=["   ", ""]))
    assert result["ok"] is False
    assert "empty" in result["error"].lower()


def test_search_handoff_invalid_record_type_returns_error(isolated_env: dict) -> None:
    result = _parse(
        handoff_core.search_handoff(
            queries=["anything"],
            record_types=["not_a_type"],
        )
    )
    assert result["ok"] is False
    assert "invalid" in result["error"].lower()


def test_search_handoff_no_match_returns_empty_list(isolated_env: dict) -> None:
    result = _parse(
        handoff_core.search_handoff(queries=["zxqjfnoexistsanywhere99999"])
    )
    assert result["ok"] is True
    assert result["results"] == []
    assert result["total"] == 0


def test_search_handoff_multi_word_query_phrase(isolated_env: dict) -> None:
    """Multi-word queries must be phrase-quoted for accurate FTS matching."""
    handoff_core.record_decision(
        session="s1",
        decision="strict distributed consensus protocol with leader election",
    )
    result = _parse(
        handoff_core.search_handoff(queries=["leader election"], record_types=["decision"])
    )
    assert result["ok"] is True
    assert result["results"]


# ---------------------------------------------------------------------------
# Backfill test
# ---------------------------------------------------------------------------


def test_backfill_indexes_pre_trigger_rows(isolated_env: dict) -> None:
    """Rows pre-existing before FTS initialization are indexed by backfill."""
    handoff_core.record_decision(
        session="s1",
        decision="pre-existing backfill uniqueterm archival test",
    )

    # Simulate a cold-start scenario: manually clear the FTS table.
    # After clearing, source_count > 0 but fts_count == 0, so _backfill_handoff_fts fires.
    with handoff_core._get_db_connection() as conn:
        conn.execute("DELETE FROM decisions_fts")

    # On the next connection, _ensure_handoff_fts calls _backfill_handoff_fts.
    result = _parse(
        handoff_core.search_handoff(
            queries=["backfill uniqueterm archival"],
            record_types=["decision"],
        )
    )
    assert result["ok"] is True
    assert result["results"], "Backfill must have re-indexed the pre-existing decision row."
    assert any(r["record_type"] == "decision" for r in result["results"])
