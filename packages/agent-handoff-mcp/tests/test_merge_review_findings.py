"""Slice 5: review_findings(operation="merge") + idx_review_findings_lane_status.

Coordinator-centric additive backend groundwork. Tests:
- happy path: two source task_refs × 3 findings each → 6 rows under coordinator
- merged_from provenance: each merged row names its source (task_ref, session, finding_id)
- source rows remain intact (additive, not destructive)
- empty-source merge is a validated error, not a silent no-op
- second idempotent merge against overlapping sources succeeds via upsert
- EXPLAIN QUERY PLAN confirms idx_review_findings_lane_status for (lane_id, status)
- non-merged findings emit no merged_from in list response (envelope unchanged)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp.config import RuntimeConfig
from agent_handoff_mcp.shared_schema import _get_db_connection


def _parse(raw: str | dict) -> dict:
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
def isolated_handoff(tmp_path: Path) -> dict:
    state_dir = tmp_path / ".task-state"
    current_task_path = tmp_path / "CURRENT_TASK.json"
    runtime = RuntimeConfig.for_workspace(tmp_path, state_dir=state_dir, current_task_path=current_task_path)
    mcp_server.configure_runtime(runtime)
    return {
        "state_dir": state_dir,
        "db_path": runtime.db_path,
        "current_task_path": current_task_path,
    }


def _seed_source_findings(task_ref: str, session: str, ids: list[str]) -> None:
    _parse(mcp_server.set_handoff_state(task_ref=task_ref, objective="obj", status="in_progress"))
    _parse(
        mcp_server.batch_record_review_findings(
            session=session,
            task_ref=task_ref,
            findings=[
                {
                    "finding_id": fid,
                    "severity": "medium",
                    "file_path": f"{task_ref}/{fid}.py",
                    "description": f"{task_ref} finding {fid}",
                }
                for fid in ids
            ],
        )
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_merge_two_sources_appends_six_rows_with_provenance(isolated_handoff: dict) -> None:
    _seed_source_findings("SRC-A", "rev-a-sess", ["A-1", "A-2", "A-3"])
    _seed_source_findings("SRC-B", "rev-b-sess", ["B-1", "B-2", "B-3"])
    _parse(mcp_server.set_handoff_state(task_ref="COORD", objective="obj", status="in_progress"))

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "merge",
                "source_task_refs": ["SRC-A", "SRC-B"],
                "target_task_ref": "COORD",
            }
        )
    )
    assert result["ok"] is True, result
    assert result["written"] == 6
    assert result["task_ref"] == "COORD"
    assert result["session"].startswith("merge-COORD-"), result["session"]

    listed = _parse(mcp_server.review_findings(review={"operation": "list", "task_ref": "COORD", "limit": 50}))
    assert listed["total_matching"] == 6
    ids_on_coord = sorted(f["finding_id"] for f in listed["findings"])
    assert ids_on_coord == ["A-1", "A-2", "A-3", "B-1", "B-2", "B-3"]

    merged_from_map = {f["finding_id"]: f["merged_from"] for f in listed["findings"]}
    assert merged_from_map["A-1"] == {"task_ref": "SRC-A", "session": "rev-a-sess", "finding_id": "A-1"}
    assert merged_from_map["B-3"] == {"task_ref": "SRC-B", "session": "rev-b-sess", "finding_id": "B-3"}

    src_a = _parse(mcp_server.review_findings(review={"operation": "list", "task_ref": "SRC-A"}))
    src_b = _parse(mcp_server.review_findings(review={"operation": "list", "task_ref": "SRC-B"}))
    assert src_a["total_matching"] == 3
    assert src_b["total_matching"] == 3
    for f in src_a["findings"] + src_b["findings"]:
        assert "merged_from" not in f


def test_merge_with_explicit_session_prefix_uses_it(isolated_handoff: dict) -> None:
    _seed_source_findings("SRC-X", "sess-x", ["X-1"])
    _parse(mcp_server.set_handoff_state(task_ref="COORD-X", objective="obj", status="in_progress"))
    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "merge",
                "source_task_refs": ["SRC-X"],
                "target_task_ref": "COORD-X",
                "session": "coord-X-pass1",
            }
        )
    )
    assert result["ok"] is True
    assert result["session"] == "coord-X-pass1"
    listed = _parse(mcp_server.review_findings(review={"operation": "list", "task_ref": "COORD-X"}))
    assert listed["findings"][0]["session"] == "coord-X-pass1"


# ---------------------------------------------------------------------------
# Validation / guards
# ---------------------------------------------------------------------------


def test_merge_empty_source_refs_is_validated_error(isolated_handoff: dict) -> None:
    _parse(mcp_server.set_handoff_state(task_ref="COORD-E", objective="obj", status="in_progress"))
    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "merge",
                "source_task_refs": [],
                "target_task_ref": "COORD-E",
            }
        )
    )
    assert result["ok"] is False
    assert "source_task_refs" in result.get("error", "")


def test_merge_with_no_matching_findings_is_validated_error(isolated_handoff: dict) -> None:
    _parse(mcp_server.set_handoff_state(task_ref="SRC-EMPTY", objective="obj", status="in_progress"))
    _parse(mcp_server.set_handoff_state(task_ref="COORD-NE", objective="obj", status="in_progress"))
    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "merge",
                "source_task_refs": ["SRC-EMPTY"],
                "target_task_ref": "COORD-NE",
            }
        )
    )
    assert result["ok"] is False
    assert "no findings" in result.get("error", "").lower()


# ---------------------------------------------------------------------------
# Idempotency: second merge over overlapping sources upserts, not destroys
# ---------------------------------------------------------------------------


def test_second_merge_overlapping_sources_is_idempotent_upsert(isolated_handoff: dict) -> None:
    _seed_source_findings("SRC-O", "o-sess", ["O-1", "O-2"])
    _parse(mcp_server.set_handoff_state(task_ref="COORD-O", objective="obj", status="in_progress"))

    first = _parse(
        mcp_server.review_findings(
            review={
                "operation": "merge",
                "source_task_refs": ["SRC-O"],
                "target_task_ref": "COORD-O",
            }
        )
    )
    assert first["ok"] is True
    assert first["written"] == 2

    second = _parse(
        mcp_server.review_findings(
            review={
                "operation": "merge",
                "source_task_refs": ["SRC-O"],
                "target_task_ref": "COORD-O",
            }
        )
    )
    assert second["ok"] is True
    assert second["written"] == 2

    listed = _parse(mcp_server.review_findings(review={"operation": "list", "task_ref": "COORD-O"}))
    assert listed["total_matching"] == 2


# ---------------------------------------------------------------------------
# Schema / index invariants
# ---------------------------------------------------------------------------


def test_lane_status_index_exists_and_is_used(isolated_handoff: dict) -> None:
    with _get_db_connection() as conn:
        indexes = {row[1] for row in conn.execute("PRAGMA index_list('review_findings')").fetchall()}
        assert "idx_review_findings_lane_status" in indexes
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM review_findings WHERE lane_id = ? AND status = 'open'",
            ("lane-A",),
        ).fetchall()
        plan_text = "\n".join(str(row[3]) for row in plan)
        assert "idx_review_findings_lane_status" in plan_text, plan_text


def test_merged_from_json_column_present(isolated_handoff: dict) -> None:
    with _get_db_connection() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(review_findings)").fetchall()}
        assert "merged_from_json" in cols


# ---------------------------------------------------------------------------
# Response envelope stability: no merged_from emitted when absent
# ---------------------------------------------------------------------------


def test_non_merged_finding_omits_merged_from(isolated_handoff: dict) -> None:
    _seed_source_findings("SRC-P", "p-sess", ["P-1"])
    listed = _parse(mcp_server.review_findings(review={"operation": "list", "task_ref": "SRC-P"}))
    assert listed["total_matching"] == 1
    assert "merged_from" not in listed["findings"][0]
    assert "merged_from_json" not in listed["findings"][0]
