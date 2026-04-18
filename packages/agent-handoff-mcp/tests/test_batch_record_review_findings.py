"""Tests for batch_record_review_findings: atomic write, validation, upsert semantics."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp.config import RuntimeConfig
from agent_handoff_mcp.shared_schema import _get_db_connection


def _parse(raw: str | dict) -> dict:
    """Convenience accessor (AHMCP-10): handlers now return dicts directly."""
    result = raw if isinstance(raw, dict) else json.loads(raw)
    if isinstance(result, dict) and result.get("schema_version") == 2:
        data = result.get("data", {})
        scope = result.get("scope", {})
        flat = {**result, **data}
        if "task_ref" not in flat and scope.get("task_ref"):
            flat["task_ref"] = scope["task_ref"]
        return flat
    return result


@pytest.fixture()
def isolated_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_dir = tmp_path / ".task-state"
    current_task_path = tmp_path / "CURRENT_TASK.json"
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


# ---------------------------------------------------------------------------
# Basic contracts
# ---------------------------------------------------------------------------


def test_batch_empty_returns_ok_written_zero(isolated_handoff: dict) -> None:
    """Empty findings list succeeds with written=0."""
    result = _parse(mcp_server.batch_record_review_findings(session="s1", findings=[]))
    assert result["ok"] is True
    assert result["written"] == 0
    assert result["results"] == []


def test_batch_single_item_round_trip(isolated_handoff: dict) -> None:
    """Single-item batch inserts one finding and returns action='inserted'."""
    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))
    result = _parse(
        mcp_server.batch_record_review_findings(
            session="s1",
            task_ref="T1",
            findings=[{"finding_id": "B-001", "severity": "high", "file_path": "core.py", "description": "Single"}],
        )
    )
    assert result["ok"] is True
    assert result["written"] == 1
    assert result["results"][0]["finding_id"] == "B-001"
    assert result["results"][0]["action"] == "inserted"


def test_batch_twelve_items_written_atomically(isolated_handoff: dict) -> None:
    """12 items are all written; DB row count and FTS row count both equal 12."""
    _parse(mcp_server.set_handoff_state(task_ref="T2", objective="obj", status="in_progress"))
    findings = [
        {"finding_id": f"B12-{i:03d}", "severity": "low", "file_path": f"f{i}.py", "description": f"desc {i}"}
        for i in range(12)
    ]
    result = _parse(mcp_server.batch_record_review_findings(session="s1", task_ref="T2", findings=findings))
    assert result["ok"] is True
    assert result["written"] == 12
    assert len(result["results"]) == 12

    with _get_db_connection() as conn:
        db_count = conn.execute("SELECT COUNT(*) FROM review_findings WHERE task_ref = 'T2'").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM findings_fts WHERE task_ref = 'T2'").fetchone()[0]
    assert db_count == 12
    assert fts_count == 12


def test_batch_invalid_severity_rejects_entire_batch(isolated_handoff: dict) -> None:
    """Invalid severity on item 2 rejects the batch before any write."""
    _parse(mcp_server.set_handoff_state(task_ref="T3", objective="obj", status="in_progress"))
    findings = [
        {"finding_id": "BSEV-001", "severity": "high", "file_path": "a.py", "description": "ok"},
        {"finding_id": "BSEV-002", "severity": "high", "file_path": "b.py", "description": "ok"},
        {"finding_id": "BSEV-003", "severity": "INVALID", "file_path": "c.py", "description": "bad"},
    ]
    result = _parse(mcp_server.batch_record_review_findings(session="s1", task_ref="T3", findings=findings))
    assert result["ok"] is False
    assert "BSEV-003" in result["error"]
    assert "Invalid severity" in result["error"]

    with _get_db_connection() as conn:
        db_count = conn.execute("SELECT COUNT(*) FROM review_findings WHERE task_ref = 'T3'").fetchone()[0]
    assert db_count == 0


def test_batch_101_items_rejected(isolated_handoff: dict) -> None:
    """Batch of 101 items returns ok=False without writing."""
    _parse(mcp_server.set_handoff_state(task_ref="T4", objective="obj", status="in_progress"))
    findings = [
        {"finding_id": f"BMAX-{i:03d}", "severity": "low", "file_path": "f.py", "description": "d"} for i in range(101)
    ]
    result = _parse(mcp_server.batch_record_review_findings(session="s1", task_ref="T4", findings=findings))
    assert result["ok"] is False
    assert "maximum" in result["error"].lower() or "100" in result["error"]

    with _get_db_connection() as conn:
        db_count = conn.execute("SELECT COUNT(*) FROM review_findings WHERE task_ref = 'T4'").fetchone()[0]
    assert db_count == 0


def test_batch_duplicate_finding_id_upserts(isolated_handoff: dict) -> None:
    """Duplicate finding_id in same batch: second occurrence upserts the first."""
    _parse(mcp_server.set_handoff_state(task_ref="T5", objective="obj", status="in_progress"))
    findings = [
        {"finding_id": "BDUP-001", "severity": "low", "file_path": "a.py", "description": "first"},
        {"finding_id": "BDUP-001", "severity": "high", "file_path": "b.py", "description": "second"},
    ]
    result = _parse(mcp_server.batch_record_review_findings(session="s1", task_ref="T5", findings=findings))
    assert result["ok"] is True
    assert result["written"] == 2

    with _get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM review_findings WHERE task_ref = 'T5' AND finding_id = 'BDUP-001'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["severity"] == "high"
    assert rows[0]["file_path"] == "b.py"


def test_batch_reopen_detected(isolated_handoff: dict) -> None:
    """Re-recording a non-open finding sets action='updated' and reopened=True."""
    _parse(mcp_server.set_handoff_state(task_ref="T6", objective="obj", status="in_progress"))
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="BROP-001",
            severity="low",
            file_path="a.py",
            description="orig",
            task_ref="T6",
        )
    )
    _parse(
        mcp_server.update_review_finding(
            finding_id="BROP-001", status="fixed", task_ref="T6", resolution_notes="fixed it"
        )
    )

    result = _parse(
        mcp_server.batch_record_review_findings(
            session="s1",
            task_ref="T6",
            findings=[{"finding_id": "BROP-001", "severity": "low", "file_path": "a.py", "description": "reopened"}],
        )
    )
    assert result["ok"] is True
    assert result["results"][0]["action"] == "updated"
    assert result["results"][0].get("reopened") is True


def test_batch_actor_and_task_ref_forwarding(isolated_handoff: dict) -> None:
    """actor.lane_id is propagated to inserted rows."""
    _parse(mcp_server.set_handoff_state(task_ref="T7", objective="obj", status="in_progress"))
    result = _parse(
        mcp_server.batch_record_review_findings(
            session="s1",
            task_ref="T7",
            actor={"lane_id": "lane-42"},
            findings=[
                {"finding_id": "BACT-001", "severity": "medium", "file_path": "x.py", "description": "with actor"}
            ],
        )
    )
    assert result["ok"] is True

    with _get_db_connection() as conn:
        row = conn.execute("SELECT lane_id FROM review_findings WHERE finding_id = 'BACT-001'").fetchone()
    assert str(row["lane_id"]) == "lane-42"


def test_batch_review_mode_preserved_on_upsert(isolated_handoff: dict) -> None:
    """review_mode set on insert is preserved when re-recorded with review_mode=None."""
    _parse(mcp_server.set_handoff_state(task_ref="T8", objective="obj", status="in_progress"))
    _parse(
        mcp_server.batch_record_review_findings(
            session="s1",
            task_ref="T8",
            findings=[
                {
                    "finding_id": "BRM-001",
                    "severity": "low",
                    "file_path": "f.py",
                    "description": "d",
                    "review_mode": "planning",
                }
            ],
        )
    )
    # Re-record without review_mode
    _parse(
        mcp_server.batch_record_review_findings(
            session="s1",
            task_ref="T8",
            findings=[{"finding_id": "BRM-001", "severity": "low", "file_path": "f.py", "description": "d"}],
        )
    )

    with _get_db_connection() as conn:
        row = conn.execute("SELECT review_mode FROM review_findings WHERE finding_id = 'BRM-001'").fetchone()
    assert str(row["review_mode"]) == "planning"


def test_batch_write_current_task_md_called_once(isolated_handoff: dict) -> None:
    """_write_current_task_md_for_task is called exactly once per batch, regardless of batch size."""
    _parse(mcp_server.set_handoff_state(task_ref="T9", objective="obj", status="in_progress"))
    findings = [
        {"finding_id": f"BONCE-{i:02d}", "severity": "low", "file_path": "f.py", "description": "d"} for i in range(5)
    ]
    with patch("agent_handoff_mcp.review_findings_support._write_current_task_md_for_task") as mock_write:
        _parse(mcp_server.batch_record_review_findings(session="s1", task_ref="T9", findings=findings))
    mock_write.assert_called_once()


def test_batch_missing_file_path_rejected(isolated_handoff: dict) -> None:
    """Batch item missing file_path returns ok=False before any write."""
    _parse(mcp_server.set_handoff_state(task_ref="T11", objective="obj", status="in_progress"))
    result = _parse(
        mcp_server.batch_record_review_findings(
            session="s1",
            task_ref="T11",
            findings=[{"finding_id": "BMFP-001", "severity": "low", "description": "no path"}],
        )
    )
    assert result["ok"] is False
    assert "file_path" in result["error"]

    with _get_db_connection() as conn:
        db_count = conn.execute("SELECT COUNT(*) FROM review_findings WHERE task_ref = 'T11'").fetchone()[0]
    assert db_count == 0


def test_batch_missing_description_rejected(isolated_handoff: dict) -> None:
    """Batch item missing description returns ok=False before any write."""
    _parse(mcp_server.set_handoff_state(task_ref="T12", objective="obj", status="in_progress"))
    result = _parse(
        mcp_server.batch_record_review_findings(
            session="s1",
            task_ref="T12",
            findings=[{"finding_id": "BMDE-001", "severity": "low", "file_path": "f.py"}],
        )
    )
    assert result["ok"] is False
    assert "description" in result["error"]

    with _get_db_connection() as conn:
        db_count = conn.execute("SELECT COUNT(*) FROM review_findings WHERE task_ref = 'T12'").fetchone()[0]
    assert db_count == 0


def test_batch_review_mode_queryable_via_list(isolated_handoff: dict) -> None:
    """review_mode written through batch is queryable via list_review_findings(review_mode=...)."""
    _parse(mcp_server.set_handoff_state(task_ref="T10", objective="obj", status="in_progress"))
    _parse(
        mcp_server.batch_record_review_findings(
            session="s1",
            task_ref="T10",
            findings=[
                {
                    "finding_id": "BRQ-001",
                    "severity": "high",
                    "file_path": "a.py",
                    "description": "planning gap",
                    "review_mode": "planning",
                },
                {
                    "finding_id": "BRQ-002",
                    "severity": "low",
                    "file_path": "b.py",
                    "description": "branch issue",
                    "review_mode": "branch",
                },
            ],
        )
    )

    planning = _parse(mcp_server.list_review_findings(task_ref="T10", review_mode="planning"))
    assert planning["ok"] is True
    assert len(planning["findings"]) == 1
    assert planning["findings"][0]["finding_id"] == "BRQ-001"
