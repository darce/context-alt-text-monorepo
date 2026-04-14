"""Unit tests for portable agent handoff MCP state tools."""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from agent_handoff_mcp import PromptMetrics, TokenUsage
from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp import import_export as handoff_import_export
from agent_handoff_mcp import shared_schema as handoff_schema
from agent_handoff_mcp.config import RuntimeConfig


@pytest.fixture()
def isolated_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect handoff sqlite + generated markdown paths into tmp dir."""
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    current_task_path = tmp_path / "CURRENT_TASK.md"
    dashboard_path = tmp_path / "DASHBOARD.md"
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=state_dir,
        current_task_path=current_task_path,
        dashboard_path=dashboard_path,
    )
    mcp_server.configure_runtime(runtime)

    return {
        "state_dir": state_dir,
        "db_path": runtime.db_path,
        "current_task_path": current_task_path,
        "dashboard_path": dashboard_path,
    }


def test_runtime_config_defaults_to_workspace_task_state() -> None:
    runtime = RuntimeConfig.for_workspace("/tmp/example-workspace")
    workspace_root = Path("/tmp/example-workspace").resolve()

    assert runtime.state_dir == workspace_root / ".task-state"
    assert runtime.db_path == workspace_root / ".task-state" / "handoff.db"
    assert runtime.current_task_path == workspace_root / "CURRENT_TASK.md"
    assert runtime.dashboard_path == workspace_root / "DASHBOARD.md"
    assert runtime.exports_dir == workspace_root / ".task-state" / "exports"


def test_mandatory_slice_decision_headings_constant_is_stable() -> None:
    assert handoff_core.MANDATORY_SLICE_DECISION_HEADINGS == (
        "## Changes",
        "## Verification",
        "## Schema / Contract Changes",
        "## Open Threads",
    )


def test_record_event_domain_tool_dispatches_all_variants(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="record-event-task",
            objective="Exercise record_event domain tool",
            status="in_progress",
        )
    )

    decision_result = _parse(
        mcp_server.record_event(
            event={
                "event_kind": "decision",
                "session": "record-event",
                "decision": "record_event_dispatch_decision",
                "rationale": "Domain tool decision dispatch proof.",
                "task_ref": "record-event-task",
                "changed_files": ["packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py"],
            }
        )
    )
    assert decision_result["ok"] is True
    assert decision_result["decision"]["decision"] == "record_event_dispatch_decision"

    test_result = _parse(
        mcp_server.record_event(
            event={
                "event_kind": "test_result",
                "session": "record-event",
                "command": "pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q",
                "passed": True,
                "result": "1 passed in 0.01s",
                "task_ref": "record-event-task",
            }
        )
    )
    assert test_result["ok"] is True
    assert test_result["test"]["command"] == "pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q"

    blocker_result = _parse(
        mcp_server.record_event(
            event={
                "event_kind": "blocker",
                "operation": "add",
                "description": "record_event blocker dispatch proof",
                "task_ref": "record-event-task",
            }
        )
    )
    assert blocker_result["ok"] is True
    assert blocker_result["blocker"]["description"] == "record_event blocker dispatch proof"

    with handoff_core._get_db_connection() as conn:
        decision_row = conn.execute(
            "SELECT decision FROM decisions WHERE task_ref = ? ORDER BY id DESC LIMIT 1",
            ("record-event-task",),
        ).fetchone()
        test_row = conn.execute(
            "SELECT command FROM verified_tests WHERE task_ref = ? ORDER BY id DESC LIMIT 1",
            ("record-event-task",),
        ).fetchone()
        blocker_row = conn.execute(
            "SELECT description FROM blockers WHERE task_ref = ? ORDER BY id DESC LIMIT 1",
            ("record-event-task",),
        ).fetchone()

    assert decision_row is not None
    assert decision_row["decision"] == "record_event_dispatch_decision"
    assert test_row is not None
    assert test_row["command"] == "pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q"
    assert blocker_row is not None
    assert blocker_row["description"] == "record_event blocker dispatch proof"


def test_summarize_test_result_falls_back_to_last_line() -> None:
    result = (
        "============================= test session starts =============================\n"
        "platform darwin -- Python 3.12.0\n"
        "collected 3 items\n"
        "3 passed in 0.12s\n"
    )

    assert handoff_core._summarize_test_result(result) == "3 passed in 0.12s"


def _parse(payload: str | dict) -> dict:
    """Convenience accessor for test assertions.

    Post-AHMCP-10, handlers return dicts directly. This helper merges
    ``data`` and ``scope.task_ref`` into the top level so existing test
    assertions like ``result["active"]`` keep working without rewriting
    every test body to use ``result["data"]["active"]``. The string
    branch survives only for the rare callers that capture serialised
    CLI output (the CLI still prints JSON to stdout).
    """
    raw = payload if isinstance(payload, dict) else json.loads(payload)
    if isinstance(raw, dict) and raw.get("schema_version") == 2:
        data = raw.get("data", {})
        scope = raw.get("scope", {})
        flat = {**raw, **data}
        if "task_ref" not in flat and scope.get("task_ref"):
            flat["task_ref"] = scope["task_ref"]
        return flat
    return raw


def _assert_dashboard_row(
    md: str,
    task_ref: str,
    *,
    status: str,
    open_findings: int,
    open_blockers: int,
    pending_actions: int,
    active: bool,
) -> None:
    row = next(
        line
        for line in md.splitlines()
        if (line.startswith("> ") or line.startswith("  ")) and line[2:46].rstrip() == task_ref
    )
    assert row.startswith("> " if active else "  ")
    task_cell = row[2:46].rstrip()
    cells = row[46:].split()
    assert task_cell == task_ref
    assert cells[0] == status
    assert cells[1] == str(open_findings)
    assert cells[2] == str(open_blockers)
    assert cells[3] == str(pending_actions)


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
        "turn_metrics",
    }

    # First bootstrap
    with handoff_core._get_db_connection() as conn:
        first_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('handoff_state','decisions','blockers','next_actions','verified_tests','review_findings','task_archives','worktree_lanes','worker_reports','lane_messages','plan_cursors','turn_metrics')"
            )
        }

    # Second bootstrap should produce identical schema (no error/no drift)
    with handoff_core._get_db_connection() as conn:
        second_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('handoff_state','decisions','blockers','next_actions','verified_tests','review_findings','task_archives','worktree_lanes','worker_reports','lane_messages','plan_cursors','turn_metrics')"
            )
        }

    assert first_tables == expected_tables
    assert second_tables == expected_tables


def test_schema_bootstrap_migrates_decisions_changed_files_column(isolated_handoff: dict) -> None:
    """Warm databases from the prior schema gain decisions.changed_files_json on reopen."""
    legacy_schema_sql = handoff_core.HANDOFF_SCHEMA_SQL.replace("    changed_files_json TEXT,\n", "")

    with sqlite3.connect(isolated_handoff["db_path"]) as conn:
        conn.executescript(legacy_schema_sql)
        conn.execute(f"PRAGMA user_version = {handoff_schema.HANDOFF_SCHEMA_VERSION - 1}")

    with handoff_core._get_db_connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(decisions)").fetchall()}
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert "changed_files_json" in columns
    assert user_version == handoff_schema.HANDOFF_SCHEMA_VERSION


def test_record_decision_persists_unified_model_identity_fields(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="decision-model-identity",
            objective="Persist decision actor model identity",
            status="in_progress",
        )
    )

    recorded = _parse(
        mcp_server.record_decision(
            task_ref="decision-model-identity",
            session="codex",
            decision="cdx_slice_complete_test_model_identity",
            rationale=(
                "## Changes\n- added unified model identity.\n"
                "## Verification\n- unit tests updated.\n"
                "## Schema / Contract Changes\n- decisions store model provenance.\n"
                "## Open Threads\n- none.\n"
            ),
            actor={
                "model": "claude-opus-4-0520",
                "reasoning_level": "high",
            },
        )
    )

    assert recorded["ok"] is True
    decision = recorded["decision"]
    assert decision["agent"] == "Claude Opus 4 high"
    assert decision["model"] == "claude-opus-4-0520"
    assert decision["model_label"] == "Claude Opus 4"
    assert decision["reasoning_level"] == "high"


def test_record_decision_persists_changed_files(isolated_handoff: dict) -> None:
    """changed_files parameter is stored as JSON on the decision row."""
    _parse(mcp_server.set_handoff_state(task_ref="cf-test", objective="Changed files test", status="in_progress"))

    files = ["src/api.py", "tests/test_api.py", "docs/contract.md"]
    recorded = _parse(
        mcp_server.record_decision(
            session="s1",
            decision="cdx_slice_complete_test_changed_files",
            rationale=(
                "## Changes\n- added changed_files.\n"
                "## Verification\n- tested.\n"
                "## Schema / Contract Changes\n- none.\n"
                "## Open Threads\n- none.\n"
            ),
            changed_files=files,
        )
    )
    assert recorded["ok"] is True
    assert json.loads(recorded["decision"]["changed_files_json"]) == files
    assert recorded["mutation"]["entity"] == "decision"
    assert recorded["mutation"]["operation"] == "insert"
    assert recorded["mutation"]["affected_ids"]
    assert isinstance(recorded["mutation"]["task_revision"], int)


def test_record_decision_warns_when_rationale_is_verbose(isolated_handoff: dict) -> None:
    _parse(mcp_server.set_handoff_state(task_ref="cf-warn", objective="Verbose rationale", status="in_progress"))

    recorded = _parse(
        mcp_server.record_decision(
            session="s1",
            decision="cdx_decision_verbose_rationale",
            rationale="x" * 1600,
        )
    )

    assert recorded["ok"] is True
    warnings = recorded.get("warnings", [])
    assert any("1,500 chars" in warning for warning in warnings)


def test_record_decision_rejects_oversize_rationale(isolated_handoff: dict) -> None:
    _parse(mcp_server.set_handoff_state(task_ref="cf-too-long", objective="Oversize rationale", status="in_progress"))

    recorded = _parse(
        mcp_server.record_decision(
            session="s1",
            decision="cdx_decision_oversize_rationale",
            rationale="x" * 3500,
        )
    )

    assert recorded["ok"] is False
    assert "3,000-char limit" in recorded["error"]


def test_record_decision_rejects_non_relative_changed_files(isolated_handoff: dict) -> None:
    """changed_files rejects malformed or non-relative path entries."""
    _parse(mcp_server.set_handoff_state(task_ref="cf-invalid", objective="Invalid files test", status="in_progress"))

    recorded = _parse(
        mcp_server.record_decision(
            session="s1",
            decision="cdx_slice_complete_test_invalid_files",
            rationale=(
                "## Changes\n- invalid files.\n"
                "## Verification\n- tested.\n"
                "## Schema / Contract Changes\n- none.\n"
                "## Open Threads\n- none.\n"
            ),
            changed_files=["/absolute/path.py", "../escape.py"],
        )
    )

    assert recorded["ok"] is False
    assert "monorepo-relative paths" in recorded["error"]


def test_record_decision_changed_files_none_by_default(isolated_handoff: dict) -> None:
    """When changed_files is not passed, the column is null."""
    _parse(mcp_server.set_handoff_state(task_ref="cf-none", objective="No files test", status="in_progress"))
    recorded = _parse(
        mcp_server.record_decision(
            session="s1",
            decision="cdx_slice_complete_test_no_files",
            rationale=(
                "## Changes\n- no files.\n"
                "## Verification\n- tested.\n"
                "## Schema / Contract Changes\n- none.\n"
                "## Open Threads\n- none.\n"
            ),
        )
    )
    assert recorded["ok"] is True
    assert recorded["decision"]["changed_files_json"] == "[]"


def test_record_decision_preserves_legacy_agent_fallback(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="decision-legacy-agent",
            objective="Keep legacy actors working",
            status="in_progress",
        )
    )

    recorded = _parse(
        mcp_server.record_decision(
            task_ref="decision-legacy-agent",
            session="legacy",
            decision="cdx_slice_complete_test_legacy_actor",
            rationale=(
                "## Changes\n- kept legacy agent fallback.\n"
                "## Verification\n- unit tests updated.\n"
                "## Schema / Contract Changes\n- none.\n"
                "## Open Threads\n- none.\n"
            ),
            actor={"agent": "copilot-chat"},
        )
    )

    assert recorded["ok"] is True
    assert recorded["decision"]["agent"] == "copilot-chat"
    assert recorded["decision"]["model"] is None


def test_record_decision_with_token_counts(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="token-annotation-test",
            objective="Test token annotation on decisions",
            status="in_progress",
        )
    )

    recorded = _parse(
        mcp_server.record_decision(
            task_ref="token-annotation-test",
            session="copilot",
            decision="cdx_slice_complete_test_token_test",
            rationale=(
                "## Changes\n- tested token fields.\n"
                "## Verification\n- unit tests.\n"
                "## Schema / Contract Changes\n- none.\n"
                "## Open Threads\n- none.\n"
            ),
            actor={"model": "claude-opus-4-0520", "reasoning_level": "high"},
            input_tokens=8500,
            output_tokens=3200,
            total_tokens=11700,
        )
    )

    assert recorded["ok"] is True
    decision = recorded["decision"]
    assert decision["input_tokens"] == 8500
    assert decision["output_tokens"] == 3200
    assert decision["total_tokens"] == 11700
    assert decision["agent"] == "Claude Opus 4 high"


def test_record_decision_without_tokens_leaves_nulls(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="token-null-test",
            objective="No token fields",
            status="in_progress",
        )
    )

    recorded = _parse(
        mcp_server.record_decision(
            task_ref="token-null-test",
            session="copilot",
            decision="cdx_slice_complete_test_no_tokens",
            rationale=(
                "## Changes\n- no tokens.\n"
                "## Verification\n- unit tests.\n"
                "## Schema / Contract Changes\n- none.\n"
                "## Open Threads\n- none.\n"
            ),
        )
    )

    assert recorded["ok"] is True
    decision = recorded["decision"]
    assert decision["input_tokens"] is None
    assert decision["output_tokens"] is None
    assert decision["total_tokens"] is None


def test_current_task_md_shows_token_summary(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="token-render-test",
            objective="Token summary rendering",
            status="in_progress",
        )
    )

    for i, tokens in enumerate([(5000, 2000, 7000), (10000, 4000, 14000)]):
        _parse(
            mcp_server.record_decision(
                task_ref="token-render-test",
                session="copilot",
                decision=f"cdx_slice_complete_test_render_{i}",
                rationale=(
                    "## Changes\n- render test.\n"
                    "## Verification\n- unit tests.\n"
                    "## Schema / Contract Changes\n- none.\n"
                    "## Open Threads\n- none.\n"
                ),
                actor={"model": "claude-opus-4-0520", "reasoning_level": "high"},
                input_tokens=tokens[0],
                output_tokens=tokens[1],
                total_tokens=tokens[2],
            )
        )

    _parse(mcp_server.generate_current_task_md(task_ref="token-render-test"))

    ct_data = json.loads(isolated_handoff["current_task_path"].read_text())
    decisions = ct_data["decisions_recent"]
    total_tokens = sum(d.get("total_tokens", 0) or 0 for d in decisions)
    assert total_tokens == 21000  # 7000 + 14000
    assert any(d.get("model") == "claude-opus-4-0520" for d in decisions)


def test_current_task_md_omits_token_summary_when_no_tokens(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="no-token-render-test",
            objective="No token summary",
            status="in_progress",
        )
    )

    _parse(
        mcp_server.record_decision(
            task_ref="no-token-render-test",
            session="copilot",
            decision="cdx_slice_complete_test_no_tok_render",
            rationale=(
                "## Changes\n- no tokens.\n"
                "## Verification\n- unit tests.\n"
                "## Schema / Contract Changes\n- none.\n"
                "## Open Threads\n- none.\n"
            ),
        )
    )

    _parse(mcp_server.generate_current_task_md(task_ref="no-token-render-test"))

    md = isolated_handoff["current_task_path"].read_text()
    assert "## Token Summary" not in md


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


def test_set_handoff_state_preserves_objective_when_omitted(isolated_handoff: dict) -> None:
    """When objective is None on update, the existing value is preserved."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="obj-preserve",
            objective="Original objective",
            status="in_progress",
        )
    )
    updated = _parse(
        mcp_server.set_handoff_state(
            task_ref="obj-preserve",
            status="review",
            expected_revision=0,
        )
    )
    assert updated["ok"] is True
    assert updated["active"]["objective"] == "Original objective"
    assert updated["active"]["status"] == "review"


def test_set_handoff_state_requires_objective_on_insert(isolated_handoff: dict) -> None:
    """Creating a new handoff state without objective returns an error."""
    result = _parse(
        mcp_server.set_handoff_state(
            task_ref="no-obj",
            status="in_progress",
        )
    )
    assert result["ok"] is False
    assert "objective is required" in result["error"]


def test_set_handoff_state_explicit_objective_overrides(isolated_handoff: dict) -> None:
    """When objective is explicitly passed on update, it overrides the stored value."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="obj-override",
            objective="Original",
            status="in_progress",
        )
    )
    updated = _parse(
        mcp_server.set_handoff_state(
            task_ref="obj-override",
            objective="Deliberately changed",
            status="in_progress",
            expected_revision=0,
        )
    )
    assert updated["ok"] is True
    assert updated["active"]["objective"] == "Deliberately changed"


def test_record_decision_warns_when_model_identity_missing(isolated_handoff: dict) -> None:
    """Decisions without model/model_label get a warning in the response."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="warn-test",
            objective="Test warnings",
            status="in_progress",
        )
    )
    result = _parse(
        mcp_server.record_decision(
            session="copilot",
            decision="cdx_slice_complete_warn_test_model_warning",
            rationale=(
                "## Changes\n- none.\n"
                "## Verification\n- none.\n"
                "## Schema / Contract Changes\n- none.\n"
                "## Open Threads\n- none.\n"
            ),
            actor={"agent": "codex"},
        )
    )
    assert result["ok"] is True
    assert "warnings" in result
    assert any("model" in w for w in result["warnings"])


def test_record_decision_no_warning_with_model(isolated_handoff: dict) -> None:
    """Decisions with model identity do not produce warnings."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="no-warn-test",
            objective="No warnings",
            status="in_progress",
        )
    )
    result = _parse(
        mcp_server.record_decision(
            session="copilot",
            decision="cdx_slice_complete_warn_test_no_warning",
            rationale=(
                "## Changes\n- none.\n"
                "## Verification\n- none.\n"
                "## Schema / Contract Changes\n- none.\n"
                "## Open Threads\n- none.\n"
            ),
            actor={"model": "claude-opus-4-0520", "model_label": "Claude Opus 4", "reasoning_level": "high"},
        )
    )
    assert result["ok"] is True
    assert not result.get("warnings")
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
    assert compact["limits"]["blockers"] == 5
    assert compact["limits"]["actions"] == 5
    assert compact["limits"]["decisions"] == 3
    assert compact["limits"]["tests"] == 3
    assert compact["limits"]["findings"] == 10
    write = compact["limits"]["write"]
    assert write["rationale_soft_chars"] == 1500
    assert write["rationale_hard_chars"] == 3000
    assert write["slice_complete_hard_chars"] == 4000
    assert "## Changes" in write["slice_complete_required_sections"]
    assert len(compact["blockers_open"]) == 5
    assert len(compact["actions_pending"]) == 5
    assert len(compact["decisions_recent"]) == 3
    assert len(compact["tests_recent"]) == 3

    verbose = _parse(mcp_server.get_handoff_state(verbose=True))
    assert len(verbose["blockers_open"]) == 8
    assert len(verbose["actions_pending"]) == 9
    assert len(verbose["decisions_recent"]) == 6
    assert len(verbose["tests_recent"]) == 7


def test_v2_envelope_shape_on_read_surfaces(isolated_handoff: dict) -> None:
    """Read surfaces return the v2 envelope with schema_version, tool, scope, data."""
    _parse(mcp_server.set_handoff_state(task_ref="env-test", objective="Envelope shape", status="in_progress"))

    # get_handoff_state — handlers return dicts natively (AHMCP-10)
    raw_state = mcp_server.get_handoff_state(task_ref="env-test")
    assert raw_state["schema_version"] == 2
    assert raw_state["tool"] == "get_handoff_state"
    assert raw_state["scope"]["task_ref"] == "env-test"
    assert "data" in raw_state
    assert "active" in raw_state["data"]
    assert "limits" in raw_state["data"]

    # generate_current_task_md
    raw_gen = mcp_server.generate_current_task_md(task_ref="env-test", write_file=False)
    assert raw_gen["schema_version"] == 2
    assert raw_gen["tool"] == "generate_current_task_md"
    assert raw_gen["scope"]["task_ref"] == "env-test"
    assert "current_task_json" in raw_gen["data"]


def test_v2_envelope_no_legacy_mirroring(isolated_handoff: dict) -> None:
    """Compact envelope puts data in the ``data`` block only — no top-level mirrors."""
    _parse(mcp_server.set_handoff_state(task_ref="compact-env", objective="Compact envelope", status="in_progress"))

    raw_state = mcp_server.get_handoff_state(task_ref="compact-env")
    assert raw_state["schema_version"] == 2
    assert raw_state["task_ref"] == "compact-env"
    # Canonical data block contains the payload
    assert "active" in raw_state["data"]
    assert "limits" in raw_state["data"]
    # No legacy mirroring at top level
    assert "active" not in raw_state
    assert "limits" not in raw_state

    raw_error = mcp_server.handoff_close_check(require_fresh_tests=True)
    assert raw_error["ok"] is False
    assert "error" in raw_error["data"]
    assert "error" not in raw_error  # no legacy mirror


def test_get_handoff_state_sections_filter(isolated_handoff: dict) -> None:
    """sections parameter limits which keys appear in the response."""
    _parse(mcp_server.set_handoff_state(task_ref="sec-test", objective="Sections test", status="in_progress"))
    _parse(mcp_server.record_decision(session="s1", decision="d1"))
    _parse(mcp_server.report_blocker(operation="add", description="b1"))

    # Request only decisions_recent
    result = _parse(mcp_server.get_handoff_state(sections="decisions_recent"))
    assert result["ok"] is True
    assert result["task_ref"] == "sec-test"
    assert "active" in result  # Always present
    assert "limits" in result  # Always present
    assert "decisions_recent" in result
    assert len(result["decisions_recent"]) >= 1
    # Unrequested sections should be absent
    assert "blockers_open" not in result
    assert "actions_pending" not in result
    assert "tests_recent" not in result
    assert "findings_open" not in result
    assert "worktree_lanes" not in result

    # Request multiple sections
    result2 = _parse(mcp_server.get_handoff_state(sections="blockers_open,decisions_recent"))
    assert "blockers_open" in result2
    assert "decisions_recent" in result2
    assert "tests_recent" not in result2


def test_get_handoff_state_sections_invalid_stripped(isolated_handoff: dict) -> None:
    """Invalid section names are stripped; remaining valid ones still work."""
    _parse(mcp_server.set_handoff_state(task_ref="strip-test", objective="Strip test", status="in_progress"))
    _parse(mcp_server.report_blocker(operation="add", description="b1"))

    # Mix of valid and invalid — valid one still returned
    result = _parse(mcp_server.get_handoff_state(sections="blockers_open,typo_name"))
    assert "blockers_open" in result
    assert "decisions_recent" not in result

    # All invalid — identity-only response (active + limits, no data sections)
    result2 = _parse(mcp_server.get_handoff_state(sections="bogus,nope"))
    assert result2["ok"] is True
    assert "active" in result2
    assert "limits" in result2
    assert "blockers_open" not in result2
    assert "decisions_recent" not in result2
    assert "findings_open" not in result2


def test_get_handoff_state_sections_identity_token(isolated_handoff: dict) -> None:
    """The reserved 'identity' token explicitly requests identity-only (active + limits)."""
    _parse(mcp_server.set_handoff_state(task_ref="id-tok", objective="Identity token test", status="in_progress"))
    _parse(mcp_server.report_blocker(operation="add", description="b1"))
    _parse(
        mcp_server.record_decision(
            session="s",
            decision="d_test_identity",
            rationale=(
                "## Changes\n- identity token.\n## Verification\n- tested.\n"
                "## Schema / Contract Changes\n- none.\n## Open Threads\n- none.\n"
            ),
        )
    )

    # Explicit identity token — only active + limits returned
    result = _parse(mcp_server.get_handoff_state(sections="identity"))
    assert result["ok"] is True
    assert "active" in result
    assert "limits" in result
    assert "blockers_open" not in result
    assert "decisions_recent" not in result
    assert "findings_open" not in result

    # Identity token takes precedence over other section names
    result2 = _parse(mcp_server.get_handoff_state(sections="identity,blockers_open,decisions_recent"))
    assert result2["ok"] is True
    assert "active" in result2
    assert "blockers_open" not in result2
    assert "decisions_recent" not in result2

    # Case-insensitive
    result3 = _parse(mcp_server.get_handoff_state(sections="IDENTITY"))
    assert result3["ok"] is True
    assert "active" in result3
    assert "blockers_open" not in result3


def test_get_handoff_state_sections_lane_messages_resolves_lane(isolated_handoff: dict) -> None:
    """Requesting lane_messages_open without current_lane still scopes to active lane."""
    _parse(
        mcp_server.set_handoff_state(task_ref="lm-test", objective="Lane messages scoping test", status="in_progress")
    )
    # The key assertion: lane_messages_open is returned without error
    # even when current_lane is not in the sections filter.
    result = _parse(mcp_server.get_handoff_state(sections="lane_messages_open"))
    assert result["ok"] is True
    assert "lane_messages_open" in result
    assert "current_lane" not in result  # Not requested
    assert isinstance(result["lane_messages_open"], list)


def test_get_handoff_state_sections_none_returns_all(isolated_handoff: dict) -> None:
    """sections=None (default) returns all sections."""
    _parse(mcp_server.set_handoff_state(task_ref="all-test", objective="All sections test", status="in_progress"))
    result = _parse(mcp_server.get_handoff_state())
    assert "blockers_open" in result
    assert "actions_pending" in result
    assert "decisions_recent" in result
    assert "tests_recent" in result
    assert "findings_open" in result
    assert "worktree_lanes" in result
    assert "worker_reports_recent" in result
    assert "lane_messages_open" in result
    assert "current_lane" in result


def test_get_handoff_state_detail_summary_truncates(isolated_handoff: dict) -> None:
    """detail='summary' truncates long rationale text."""
    _parse(mcp_server.set_handoff_state(task_ref="det-test", objective="Detail test", status="in_progress"))
    long_rationale = "A" * 500
    _parse(mcp_server.record_decision(session="s1", decision="d1", rationale=long_rationale))

    # Full detail preserves the full text
    full = _parse(mcp_server.get_handoff_state(detail="full"))
    assert len(full["decisions_recent"][0]["rationale"]) == 500

    # Summary truncates
    summary = _parse(mcp_server.get_handoff_state(detail="summary"))
    rationale = summary["decisions_recent"][0]["rationale"]
    assert rationale.endswith("...")
    assert len(rationale) == 203  # 200 chars + "..."


def test_get_handoff_state_detail_summary_preserves_short_text(isolated_handoff: dict) -> None:
    """detail='summary' does not truncate text shorter than the threshold."""
    _parse(mcp_server.set_handoff_state(task_ref="short-test", objective="Short text test", status="in_progress"))
    _parse(mcp_server.record_decision(session="s1", decision="d1", rationale="Short rationale"))

    summary = _parse(mcp_server.get_handoff_state(detail="summary"))
    assert summary["decisions_recent"][0]["rationale"] == "Short rationale"


def test_get_handoff_state_invalid_detail_falls_back_to_full(isolated_handoff: dict) -> None:
    """Invalid detail value falls back to 'full'."""
    _parse(mcp_server.set_handoff_state(task_ref="inv-test", objective="Invalid detail test", status="in_progress"))
    long_rationale = "B" * 500
    _parse(mcp_server.record_decision(session="s1", decision="d1", rationale=long_rationale))

    result = _parse(mcp_server.get_handoff_state(detail="bogus"))
    assert len(result["decisions_recent"][0]["rationale"]) == 500


def test_new_writes_prefer_current_git_context_over_stale_handoff_state(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "review-branch"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Codex"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "codex@example.com"], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()

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


def test_record_test_result_summarizes_multiline_output(isolated_handoff: dict) -> None:
    initialized = _parse(
        mcp_server.set_handoff_state(
            task_ref="test-results",
            objective="Summarize verification output",
            status="in_progress",
        )
    )
    assert initialized["ok"] is True

    recorded = _parse(
        mcp_server.record_test_result(
            session="s-test-summary",
            command="python3 -m pytest",
            passed=True,
            result=(
                "============================= test session starts =============================\n"
                "collected 55 items\n"
                "packages/agent-handoff-mcp/tests/test_handoff_state.py .....\n"
                "============================== 55 passed in 7.02s =============================="
            ),
            actor={"agent": "codex", "branch": "tooling/review-hardening", "commit_sha": "abc123"},
        )
    )

    assert (
        recorded["test"]["result"] == "============================== 55 passed in 7.02s =============================="
    )


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


def test_update_review_finding_requires_verified_descendant_commit(
    isolated_handoff: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        lambda reference_sha, candidate_sha: (
            "descendant"
            if (reference_sha, candidate_sha) in {("abc123", "def456"), ("abc123", "abc123")}
            else "unknown"
        ),
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


def test_update_review_finding_rejects_non_descendant_verified_commit(
    isolated_handoff: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    # Global lookup: finding_db_id is a unique PK, so omitting task_ref succeeds via global lookup
    found = _parse(mcp_server.update_review_finding(finding_db_id=finding_id, status="fixed"))
    assert found["ok"] is True
    assert found["finding"]["status"] == "fixed"


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
    assert created["mutation"]["entity"] == "finding"
    assert created["mutation"]["operation"] == "upsert"
    assert created["mutation"]["affected_ids"] == ["M-10"]
    assert isinstance(created["mutation"]["task_revision"], int)


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

    # Global lookup: omitting task_ref finds the finding by db_id regardless of active task
    found = _parse(mcp_server.list_review_findings(finding_db_id=finding_db_id))
    assert found["ok"] is True
    assert found["findings"][0]["finding_id"] == "M-8"

    # Explicit task_ref still scopes correctly
    explicit = _parse(mcp_server.list_review_findings(finding_db_id=finding_db_id, task_ref="4.12.0"))
    assert explicit["ok"] is True
    assert explicit["findings"][0]["finding_id"] == "M-8"

    # Explicit task_ref for wrong task returns not-found
    wrong_task = _parse(mcp_server.list_review_findings(finding_db_id=finding_db_id, task_ref="4.12.1"))
    assert wrong_task["ok"] is False
    assert "Finding not found for task." in wrong_task["error"]


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

    # Global lookup: omitting task_ref finds unique finding_id across all tasks
    global_fixed = _parse(
        mcp_server.update_review_finding(
            finding_id="CU-1",
            status="fixed",
        )
    )
    assert global_fixed["ok"] is True
    assert global_fixed["finding"]["status"] == "fixed"

    # With explicit task_ref, update also succeeds against the original task
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
        mcp_server.update_review_finding(
            finding_id="CU-1",
            status="open",
            reopen_reason="Needs re-check",
            task_ref="cross-update-a",
        )
    )
    assert reopened["ok"] is True
    assert reopened["reopened"] is True
    assert reopened["finding"]["status"] == "open"


def test_core_write_tools_accept_explicit_task_ref_cross_task(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="cross-write-a",
            objective="Task A",
            status="in_progress",
        )
    )

    decision = _parse(
        mcp_server.record_decision(
            session="s-cross",
            decision="cdx_slice_complete_cross_write_cross_write_a",
            rationale="## Changes\n- none.\n\n## Verification\n- none.\n\n## Schema / Contract Changes\n- none.\n\n## Open Threads\n- none.",
            task_ref="cross-write-a",
        )
    )
    assert decision["ok"] is True
    assert decision["task_ref"] == "cross-write-a"

    action = _parse(
        mcp_server.update_next_actions(
            operation="add",
            action="Cross-task action",
            priority=1,
            task_ref="cross-write-a",
        )
    )
    assert action["ok"] is True
    assert action["task_ref"] == "cross-write-a"

    blocker = _parse(
        mcp_server.report_blocker(
            operation="add",
            description="Cross-task blocker",
            task_ref="cross-write-a",
        )
    )
    assert blocker["ok"] is True
    assert blocker["task_ref"] == "cross-write-a"

    test = _parse(
        mcp_server.record_test_result(
            session="s-cross",
            command="pytest -q",
            passed=True,
            result="1 passed in 0.01s",
            task_ref="cross-write-a",
        )
    )
    assert test["ok"] is True
    assert test["task_ref"] == "cross-write-a"

    _parse(
        mcp_server.set_handoff_state(
            task_ref="cross-write-b",
            objective="Task B",
            status="in_progress",
            expected_revision=0,
        )
    )

    hidden = _parse(mcp_server.get_handoff_state(verbose=True))
    assert hidden["task_ref"] == "cross-write-b"
    assert hidden["decisions_recent"] == []
    assert hidden["actions_pending"] == []
    assert hidden["blockers_open"] == []
    assert hidden["tests_recent"] == []

    explicit = _parse(mcp_server.get_handoff_state(task_ref="cross-write-a", verbose=True))
    assert explicit["task_ref"] == "cross-write-a"
    assert [row["decision"] for row in explicit["decisions_recent"]] == ["cdx_slice_complete_cross_write_cross_write_a"]
    assert [row["action"] for row in explicit["actions_pending"]] == ["Cross-task action"]
    assert [row["description"] for row in explicit["blockers_open"]] == ["Cross-task blocker"]
    assert [row["command"] for row in explicit["tests_recent"]] == ["pytest -q"]


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

    # Archived task must appear in DASHBOARD.md (generate_dashboard_md replaces view="dashboard").
    dash_result = _parse(mcp_server.generate_dashboard_md(write_file=False))
    dash_md = dash_result["markdown"]
    assert "4.99.0" in dash_md

    # (a) Status is recovered from archived snapshot JSON; task was archived with status="done".
    # The All Tasks table in DASHBOARD.md renders the status column.
    assert "done" in dash_md

    # (b) CURRENT_TASK.md no longer renders the All Tasks table (moved to DASHBOARD.md).
    _parse(mcp_server.set_handoff_state(task_ref="post-archive", objective="post-archive placeholder", status="active"))
    rendered = _parse(mcp_server.generate_current_task_md(task_ref="post-archive", write_file=False))
    current_task_data = json.loads(rendered["current_task_json"])
    assert current_task_data["task_ref"] == "post-archive"  # cross-task data moved to DASHBOARD.md
    assert "4.99.0" not in rendered["current_task_json"]


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
    _parse(
        mcp_server.record_decision(
            session="nested-wrapper",
            decision="cdx_slice_complete_nested_nested_wrapper",
            rationale="## Changes\n- none.\n\n## Verification\n- none.\n\n## Schema / Contract Changes\n- none.\n\n## Open Threads\n- none.",
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
    data = json.loads(payload["current_task_json"])
    assert data["active"]["objective"] == "Nested wrapper objective"
    assert any("cdx_slice_complete_nested_nested_wrapper" in d.get("decision", "") for d in data["decisions_recent"])


def test_generate_current_task_md_prefers_live_status_over_archived_snapshot(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="reactivated-task",
            objective="Original objective",
            status="in_progress",
        )
    )
    _parse(mcp_server.archive_task_state(task_ref="reactivated-task"))

    switched = _parse(
        handoff_import_export.switch_task(
            task_ref="reactivated-task",
            status="done",
        )
    )
    assert switched["ok"] is True
    assert switched["active"]["status"] == "done"

    payload = _parse(mcp_server.generate_current_task_md(task_ref="reactivated-task", write_file=False))
    data = json.loads(payload["current_task_json"])

    # CURRENT_TASK.md shows active-task status only; All Tasks table is in DASHBOARD.md.
    assert data["task_ref"] == "reactivated-task"
    assert data["active"]["status"] == "done"


def test_generate_current_task_md_includes_dashboard_header(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="E12-11",
            objective="Dashboard active task",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_decision(
            session="dash-1",
            task_ref="E12-11",
            decision="cop_slice_complete_E12-11_dashboard_header",
            rationale=(
                "## Changes\n- CURRENT_TASK.md header.\n\n"
                "## Verification\n- unit tests.\n\n"
                "## Schema / Contract Changes\n- none.\n\n"
                "## Open Threads\n- none."
            ),
        )
    )
    _parse(
        mcp_server.record_review_finding(
            task_ref="E12-10",
            session="dash-2",
            finding_id="E12-10-OPEN",
            severity="medium",
            file_path="docs/task.md",
            description="Second task stays visible in dashboard",
        )
    )

    payload = _parse(mcp_server.generate_current_task_md(task_ref="E12-11", write_file=False))
    data = json.loads(payload["current_task_json"])

    # CURRENT_TASK.md is now active-task-only; All Tasks table moved to DASHBOARD.md.
    assert data["task_ref"] == "E12-11"
    assert data["active"]["objective"] == "Dashboard active task"
    # Cross-task finding (E12-10) must not appear in active-task JSON
    assert all(f["finding_id"] != "E12-10-OPEN" for f in data["findings_open"])


def test_internal_write_path_writes_current_task_json(isolated_handoff: dict) -> None:
    from agent_handoff_mcp._shared import _write_current_task_md_from_state

    _parse(
        mcp_server.set_handoff_state(
            task_ref="iw-dashboard",
            objective="Internal write path dashboard",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            task_ref="other-task",
            session="iw-dash",
            finding_id="IW-DASH-01",
            severity="low",
            file_path="docs/x.md",
            description="Visible in dashboard table",
        )
    )

    _write_current_task_md_from_state("iw-dashboard")

    # CURRENT_TASK.md is machine-readable JSON (active-task only).
    # Cross-task sections (All Tasks table, other-task findings) live in DASHBOARD.md.
    current_task_payload = json.loads(isolated_handoff["current_task_path"].read_text())
    assert current_task_payload["task_ref"] == "iw-dashboard"
    assert current_task_payload["active"]["status"] == "in_progress"


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


def test_handoff_close_check_requires_structured_slice_summary_for_current_commit(
    isolated_handoff: dict,
) -> None:
    initialized = _parse(
        mcp_server.set_handoff_state(
            task_ref="docs-audit",
            objective="Audit docs and record handoff",
            status="in_progress",
        )
    )
    assert initialized["ok"] is True

    actor = {"agent": "codex", "branch": "tooling/review-hardening", "commit_sha": "abc123"}
    _parse(
        mcp_server.record_decision(
            session="s-docs",
            decision="note_only",
            rationale="unstructured note",
            actor=actor,
        )
    )

    revision = int(initialized["active"]["revision"])
    done = _parse(
        mcp_server.set_handoff_state(
            task_ref="docs-audit",
            objective="Audit docs and record handoff",
            status="done",
            expected_revision=revision,
        )
    )
    assert done["ok"] is True

    _parse(mcp_server.generate_current_task_md(task_ref="docs-audit", write_file=True))

    missing = _parse(mcp_server.handoff_close_check(enforce=True, current_commit_sha="abc123"))
    assert missing["ok"] is False
    assert missing["ready_to_close"] is False
    assert missing["checks"]["current_commit_handoff"]["is_violation"] is True

    _parse(
        mcp_server.record_decision(
            session="s-docs",
            decision="cdx_slice_complete_docs_docs_audit",
            rationale=(
                "## Changes\n"
                "- docs/agentic/rules/development-workflow.md: handoff policy ; required handoff for docs-only slices.\n\n"
                "## Verification\n"
                "- rg docs/agentic: 1 matched policy update.\n\n"
                "## Schema / Contract Changes\n"
                "- none.\n\n"
                "## Open Threads\n"
                "- none."
            ),
            actor=actor,
        )
    )
    _parse(mcp_server.generate_current_task_md(task_ref="docs-audit", write_file=True))

    passing = _parse(mcp_server.handoff_close_check(enforce=True, current_commit_sha="abc123"))
    assert passing["ok"] is True
    assert passing["ready_to_close"] is True
    assert passing["checks"]["current_commit_handoff"]["structured_slice_decision_count"] == 1


def test_handoff_close_check_rejects_empty_structured_slice_sections_for_current_commit(
    isolated_handoff: dict,
) -> None:
    initialized = _parse(
        mcp_server.set_handoff_state(
            task_ref="docs-audit-empty",
            objective="Audit docs and record handoff",
            status="done",
        )
    )
    assert initialized["ok"] is True

    actor = {"agent": "codex", "branch": "tooling/review-hardening", "commit_sha": "abc123"}
    _parse(
        mcp_server.record_decision(
            session="s-docs-empty",
            decision="cdx_slice_complete_docs_docs_audit_empty",
            rationale=("## Changes\n## Verification\n## Schema / Contract Changes\n## Open Threads\n"),
            actor=actor,
        )
    )

    response = _parse(mcp_server.handoff_close_check(enforce=True, current_commit_sha="abc123"))

    assert response["ok"] is False
    assert response["ready_to_close"] is False
    assert response["checks"]["current_commit_handoff"]["is_violation"] is True
    assert response["checks"]["current_commit_handoff"]["structured_slice_decision_count"] == 0


def test_record_decision_rejects_unstructured_slice_completion_rationale(isolated_handoff: dict) -> None:
    initialized = _parse(
        mcp_server.set_handoff_state(
            task_ref="slice-summary-validation",
            objective="Require structured slice summaries at write time",
            status="in_progress",
        )
    )
    assert initialized["ok"] is True

    actor = {"agent": "codex", "branch": "tooling/review-hardening", "commit_sha": "abc123"}
    response = _parse(
        mcp_server.record_decision(
            session="slice-invalid",
            decision="cdx_slice_complete_docs_invalid_summary",
            rationale="single line summary only",
            actor=actor,
        )
    )

    assert response["ok"] is False
    assert "slice_complete_* decisions require a structured rationale" in response["error"]

    handoff = _parse(mcp_server.get_handoff_state(task_ref="slice-summary-validation"))
    assert handoff["decisions_recent"] == []


def test_record_decision_rejects_legacy_slice_completion_id_for_new_writes(
    isolated_handoff: dict,
) -> None:
    initialized = _parse(
        mcp_server.set_handoff_state(
            task_ref="slice-summary-legacy",
            objective="Reject legacy ids for new writes",
            status="in_progress",
        )
    )
    assert initialized["ok"] is True

    actor = {"agent": "codex", "branch": "tooling/review-hardening", "commit_sha": "abc123"}
    response = _parse(
        mcp_server.record_decision(
            session="slice-legacy",
            decision="slice_complete_legacy_summary",
            rationale=(
                "## Changes\n"
                "- docs/README.md: updated navigation hub.\n\n"
                "## Verification\n"
                "- python3 docs audit: TOTAL 0.\n\n"
                "## Schema / Contract Changes\n"
                "- none.\n\n"
                "## Open Threads\n"
                "- none."
            ),
            actor=actor,
        )
    )

    assert response["ok"] is False
    assert "Legacy slice-complete ids are grandfathered" in response["error"]

    handoff = _parse(mcp_server.get_handoff_state(task_ref="slice-summary-legacy"))
    assert handoff["decisions_recent"] == []


def test_record_decision_accepts_structured_slice_completion_rationale(isolated_handoff: dict) -> None:
    initialized = _parse(
        mcp_server.set_handoff_state(
            task_ref="slice-summary-validation-ok",
            objective="Allow valid slice completion summaries",
            status="in_progress",
        )
    )
    assert initialized["ok"] is True

    actor = {"agent": "codex", "branch": "tooling/review-hardening", "commit_sha": "abc123"}
    response = _parse(
        mcp_server.record_decision(
            session="slice-valid",
            decision="cdx_slice_complete_docs_valid_summary",
            rationale=(
                "## Changes\n"
                "- docs/README.md: updated navigation hub.\n\n"
                "## Verification\n"
                "- python3 docs audit: TOTAL 0.\n\n"
                "## Schema / Contract Changes\n"
                "- none.\n\n"
                "## Open Threads\n"
                "- none."
            ),
            actor=actor,
        )
    )

    assert response["ok"] is True
    assert response["decision"]["decision"] == "cdx_slice_complete_docs_valid_summary"


# ---------------------------------------------------------------------------
# generate_current_task_md -- related_task_refs
# ---------------------------------------------------------------------------


def test_generate_current_task_md_excludes_cross_task_findings(isolated_handoff: dict) -> None:
    """CURRENT_TASK.md only shows the active task's own findings; cross-task data is in DASHBOARD.md."""
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

    payload = _parse(
        mcp_server.generate_current_task_md(
            task_ref="daemon-3",
            write_file=False,
        )
    )
    assert payload["ok"] is True
    data = json.loads(payload["current_task_json"])
    # Active task's own finding present
    assert any(f["finding_id"] == "D3-01" for f in data["findings_open"])
    # Cross-task finding absent from CURRENT_TASK.md
    assert all(f["finding_id"] != "D1-01" for f in data["findings_open"])


def test_generate_current_task_md_related_excludes_active_task(isolated_handoff: dict) -> None:
    """Active task findings are never duplicated in the cross-task section."""
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
        )
    )
    data = json.loads(payload["current_task_json"])
    # D3-01 should appear exactly once in findings_open (not duplicated)
    d3_findings = [f for f in data["findings_open"] if f["finding_id"] == "D3-01"]
    assert len(d3_findings) == 1
    # No cross-task related findings section in JSON
    assert "related_findings_open" not in data or len(data.get("related_findings_open", [])) == 0


def test_generate_current_task_md_excludes_all_cross_task_findings(isolated_handoff: dict) -> None:
    """Cross-task findings never appear in CURRENT_TASK.md; they belong in DASHBOARD.md."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-active",
            objective="Active",
            status="in_progress",
        )
    )

    for task_ref, finding_ids in {
        "daemon-a": ["DA-01", "DA-02"],
        "daemon-b": ["DB-01", "DB-02"],
    }.items():
        for finding_id in finding_ids:
            _parse(
                mcp_server.record_review_finding(
                    task_ref=task_ref,
                    session=f"{task_ref}-{finding_id}",
                    finding_id=finding_id,
                    file_path=f"{task_ref}.py",
                    description=f"Finding {finding_id}",
                    severity="low",
                )
            )

    payload = _parse(
        mcp_server.generate_current_task_md(
            task_ref="daemon-active",
            write_file=False,
        )
    )

    assert payload["ok"] is True
    data = json.loads(payload["current_task_json"])
    finding_ids = {f["finding_id"] for f in data["findings_open"]}
    assert "DA-01" not in finding_ids
    assert "DA-02" not in finding_ids
    assert "DB-01" not in finding_ids
    assert "DB-02" not in finding_ids


def test_generate_current_task_md_related_skips_resolved(isolated_handoff: dict) -> None:
    """Resolved findings from other tasks do not appear in the output."""
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
        )
    )
    data = json.loads(payload["current_task_json"])
    # OC-001: All Review Findings History section removed; fixed findings
    # are no longer in the default render. They remain queryable via
    # list_review_findings(status="all").
    finding_ids = {f["finding_id"] for f in data["findings_open"]}
    assert "D1-FIXED" not in finding_ids
    # No related findings section in JSON for daemon-3 (has no own findings)
    assert len(data["findings_open"]) == 0


def test_generate_current_task_md_includes_all_findings_history_for_resolved_cross_task_findings(
    isolated_handoff: dict,
) -> None:
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
            finding_id="D1-HISTORY",
            file_path="f.py",
            description="Fixed finding retained in history",
            severity="medium",
        )
    )
    _parse(
        mcp_server.update_review_finding(
            finding_id="D1-HISTORY",
            status="fixed",
            resolution_notes="Done",
        )
    )
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
        )
    )
    data = json.loads(payload["current_task_json"])
    # OC-001: All Review Findings History section removed from default render.
    # Fixed findings from other tasks do not appear in CURRENT_TASK.md.
    finding_ids = {f["finding_id"] for f in data["findings_open"]}
    assert "D1-HISTORY" not in finding_ids


def test_generate_current_task_md_no_other_open_findings(isolated_handoff: dict) -> None:
    """When no other tasks have open findings, no cross-task subheadings appear."""
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
    data = json.loads(payload["current_task_json"])
    # No related findings for daemon-3 (no cross-task open findings)
    assert len(data["findings_open"]) == 0


def test_generate_current_task_md_truncates_multiline_test_command(
    isolated_handoff: dict,
) -> None:
    """Multi-line test commands are stored verbatim in CURRENT_TASK.md JSON."""
    multiline_cmd = (
        "ORCH_ROOT=\"$(dirname $(pwd))\" && make something && python3 - <<'PY'\n"
        "from agent_handoff_mcp import list_plan_cursors\n"
        "from agent_handoff_mcp.config import RuntimeConfig\n"
        "cfg = RuntimeConfig(workspace_root=ORCH_ROOT)\n"
        "cursors = list_plan_cursors(cfg, task_ref='my-task')\n"
        "assert len(cursors) > 0, 'no cursors found'\n"
        "PY"
    )
    _parse(
        mcp_server.set_handoff_state(
            task_ref="cmd-truncate-test",
            objective="Test command truncation",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_test_result(
            task_ref="cmd-truncate-test",
            session="copilot",
            command=multiline_cmd,
            result="7 passed",
            passed=True,
        )
    )
    payload = _parse(mcp_server.generate_current_task_md(task_ref="cmd-truncate-test", write_file=False))
    data = json.loads(payload["current_task_json"])
    assert len(data["tests_recent"]) == 1
    stored_cmd = data["tests_recent"][0]["command"]
    assert "ORCH_ROOT" in stored_cmd


# ---------------------------------------------------------------------------
# Review Coverage section in generate_current_task_md
# ---------------------------------------------------------------------------


def test_generate_current_task_md_includes_review_coverage_section(isolated_handoff: dict) -> None:
    """Coverage section appears when review runs exist for the task."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="cov-section-1",
            objective="Test coverage section",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_run(
            review_run_id="cov-section-run-001",
            session="s1",
            subject_path="docs/tasks/cov-test.md",
            task_ref="cov-section-1",
            verdict="pass_with_findings",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            task_ref="cov-section-1",
            finding_id="cov-section-1-001",
            session="s1",
            severity="medium",
            file_path="docs/tasks/cov-test.md",
            description="Test finding",
        )
    )
    payload = _parse(mcp_server.generate_current_task_md(task_ref="cov-section-1", write_file=False))
    data = json.loads(payload["current_task_json"])
    assert "review_coverage" in data
    assert data["review_coverage"]["run_count"] == 1
    assert data["review_coverage"]["latest_verdict"] == "pass_with_findings"


def test_generate_current_task_md_review_coverage_zero_runs(isolated_handoff: dict) -> None:
    """Coverage section shows zero runs when no review runs exist for the task."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="cov-zero-1",
            objective="No runs yet",
            status="in_progress",
        )
    )
    payload = _parse(mcp_server.generate_current_task_md(task_ref="cov-zero-1", write_file=False))
    data = json.loads(payload["current_task_json"])
    assert "review_coverage" in data
    assert data["review_coverage"]["run_count"] == 0
    assert data["review_coverage"]["latest_verdict"] is None or data["review_coverage"]["latest_verdict"] == "none"


def test_internal_write_path_includes_task_ref(isolated_handoff: dict) -> None:
    """_write_current_task_md_for_task must include task_ref in rendered output (not 'unknown')."""
    from agent_handoff_mcp._shared import _write_current_task_md_from_state

    _parse(
        mcp_server.set_handoff_state(
            task_ref="iw-task-ref-test",
            objective="Internal write path task_ref check",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="s-iw",
            finding_id="IW-FIND-001",
            severity="low",
            file_path="foo.py",
            description="Internal write path finding",
        )
    )

    _write_current_task_md_from_state("iw-task-ref-test")
    _parse(mcp_server.generate_dashboard_md(write_file=True))

    current_task_payload = json.loads(isolated_handoff["current_task_path"].read_text())
    assert current_task_payload["task_ref"] == "iw-task-ref-test"
    assert current_task_payload["active"]["task_ref"] == "iw-task-ref-test"
    md = isolated_handoff["dashboard_path"].read_text()
    assert "iw-task-ref-test" in md
    assert "unknown" not in md


def test_internal_write_path_includes_review_coverage(isolated_handoff: dict) -> None:
    """_write_current_task_md_for_task must render ## Review Coverage when runs exist."""
    from agent_handoff_mcp._shared import _write_current_task_md_from_state

    _parse(
        mcp_server.set_handoff_state(
            task_ref="iw-cov-test",
            objective="Internal write coverage check",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_run(
            review_run_id="RUN-IW-001",
            session="s-iw-cov",
            task_ref="iw-cov-test",
            subject_path="src/foo.py",
            review_mode="branch",
            verdict="pass",
        )
    )

    _write_current_task_md_from_state("iw-cov-test")

    current_task_payload = json.loads(isolated_handoff["current_task_path"].read_text())
    assert current_task_payload["review_coverage"]["run_count"] == 1
    assert current_task_payload["review_coverage"]["latest_verdict"] == "pass"


def test_internal_write_path_reuses_existing_connection_for_review_coverage(
    isolated_handoff: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the internal write path must not reopen the DB via the public coverage tool."""
    import importlib

    _review_findings_mod = importlib.import_module("agent_handoff_mcp.review_findings")
    from agent_handoff_mcp._shared import _get_db_connection, _write_current_task_md_for_task

    _parse(
        mcp_server.set_handoff_state(
            task_ref="iw-cov-inline",
            objective="Inline coverage reuse",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_run(
            review_run_id="RUN-IW-INLINE-001",
            session="s-iw-inline",
            task_ref="iw-cov-inline",
            subject_path="src/inline.py",
            review_mode="branch",
            verdict="pass",
        )
    )

    def _unexpected_public_helper(*args: object, **kwargs: object) -> str:
        raise AssertionError("public get_review_coverage should not be called from _write_current_task_md_for_task")

    monkeypatch.setattr(_review_findings_mod, "get_review_coverage", _unexpected_public_helper)

    with _get_db_connection() as conn:
        _write_current_task_md_for_task(conn, "iw-cov-inline")

    current_task_payload = json.loads(isolated_handoff["current_task_path"].read_text())
    assert current_task_payload["review_coverage"]["run_count"] == 1
    assert current_task_payload["review_coverage"]["latest_verdict"] == "pass"


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
    rejected = _parse(mcp_server.update_review_finding(finding_db_id=db_ids[2], status="fixed"))
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


# ---------------------------------------------------------------------------
# Focus field tests
# ---------------------------------------------------------------------------


def test_set_handoff_state_focus_round_trip(isolated_handoff: dict) -> None:
    """Focus can be set on insert, preserved when omitted, and cleared explicitly."""
    created = _parse(
        mcp_server.set_handoff_state(
            task_ref="focus-rt",
            objective="Test focus",
            status="in_progress",
            focus="implementing slice 1",
        )
    )
    assert created["ok"] is True
    assert created["active"]["focus"] == "implementing slice 1"

    # Omitting focus preserves existing value
    updated = _parse(
        mcp_server.set_handoff_state(
            task_ref="focus-rt",
            status="in_progress",
            expected_revision=0,
        )
    )
    assert updated["ok"] is True
    assert updated["active"]["focus"] == "implementing slice 1"

    # Explicitly passing empty string clears it
    cleared = _parse(
        mcp_server.set_handoff_state(
            task_ref="focus-rt",
            status="in_progress",
            focus="",
            expected_revision=1,
        )
    )
    assert cleared["ok"] is True
    assert cleared["active"].get("focus") in (None, "")


def test_set_handoff_state_focus_default_none(isolated_handoff: dict) -> None:
    """When no focus is passed on insert, it remains null."""
    created = _parse(
        mcp_server.set_handoff_state(
            task_ref="focus-none",
            objective="No focus",
            status="in_progress",
        )
    )
    assert created["ok"] is True
    assert created["active"].get("focus") is None


def test_set_handoff_state_target_worktree_path_round_trip(isolated_handoff: dict) -> None:
    """target_worktree_path can be set on insert, preserved when omitted, and updated explicitly."""
    created = _parse(
        mcp_server.set_handoff_state(
            task_ref="twp-rt",
            objective="Test target_worktree_path",
            status="in_progress",
            target_branch="feature/twp-rt",
            target_worktree_path="/tmp/context-alt-text-monorepo-twp-rt",
        )
    )
    assert created["ok"] is True
    assert created["active"]["target_worktree_path"] == "/tmp/context-alt-text-monorepo-twp-rt"
    assert created["active"]["target_branch"] == "feature/twp-rt"

    # Omitting preserves existing value
    updated = _parse(
        mcp_server.set_handoff_state(
            task_ref="twp-rt",
            status="in_progress",
            expected_revision=0,
            focus="now editing",
        )
    )
    assert updated["ok"] is True
    assert updated["active"]["target_worktree_path"] == "/tmp/context-alt-text-monorepo-twp-rt"
    assert updated["active"]["target_branch"] == "feature/twp-rt"

    # Explicitly updating overwrites
    moved = _parse(
        mcp_server.set_handoff_state(
            task_ref="twp-rt",
            status="in_progress",
            expected_revision=1,
            target_worktree_path="/tmp/context-alt-text-monorepo-twp-rt-v2",
        )
    )
    assert moved["ok"] is True
    assert moved["active"]["target_worktree_path"] == "/tmp/context-alt-text-monorepo-twp-rt-v2"


def test_set_handoff_state_target_worktree_path_default_none(isolated_handoff: dict) -> None:
    """When target_worktree_path is omitted on insert, it remains null."""
    created = _parse(
        mcp_server.set_handoff_state(
            task_ref="twp-none",
            objective="No worktree path",
            status="in_progress",
        )
    )
    assert created["ok"] is True
    assert created["active"].get("target_worktree_path") is None


def test_set_handoff_state_emits_context_drift_warning_on_branch_mismatch(isolated_handoff: dict) -> None:
    """When actor.branch differs from active task target_branch, write surfaces a warning."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="drift-warn",
            objective="Drift warning test",
            status="in_progress",
            target_branch="feature/drift-warn",
        )
    )
    drifted = _parse(
        mcp_server.set_handoff_state(
            task_ref="drift-warn",
            status="in_progress",
            expected_revision=0,
            actor={"agent": "test-agent", "branch": "feature/some-other-branch"},
        )
    )
    assert drifted["ok"] is True
    warnings = drifted.get("warnings") or []
    assert any("context_drift" in w and "feature/some-other-branch" in w for w in warnings), (
        f"Expected context_drift warning in {warnings!r}"
    )


def test_current_task_md_renders_focus_section(isolated_handoff: dict) -> None:
    """CURRENT_TASK.md includes a Current Focus section when focus is set."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="focus-md",
            objective="Doc focus test",
            status="in_progress",
            focus="working on E12-3 slice 1",
        )
    )
    result = _parse(mcp_server.generate_current_task_md(task_ref="focus-md", write_file=True))
    assert result["ok"] is True

    current_task_payload = json.loads(isolated_handoff["current_task_path"].read_text())
    assert current_task_payload["active"]["focus"] == "working on E12-3 slice 1"


def test_current_task_md_omits_focus_when_null(isolated_handoff: dict) -> None:
    """CURRENT_TASK.md does not render a focus section when focus is null."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="focus-null-md",
            objective="No focus test",
            status="in_progress",
        )
    )
    result = _parse(mcp_server.generate_current_task_md(task_ref="focus-null-md", write_file=True))
    assert result["ok"] is True

    current_task_payload = json.loads(isolated_handoff["current_task_path"].read_text())
    assert current_task_payload["active"]["focus"] is None


def test_is_slice_complete_legacy_format() -> None:
    """Legacy slice_complete_* format is recognized."""
    assert handoff_core.is_slice_complete_decision("slice_complete_foo") is True
    assert handoff_core.is_slice_complete_decision("slice_complete_docs_audit") is True


def test_is_slice_complete_prefixed_format() -> None:
    """New prefixed format is recognized."""
    assert handoff_core.is_slice_complete_decision("cdx_slice_complete_E12-1_gate_validation") is True
    assert handoff_core.is_slice_complete_decision("cop_slice_complete_E12-3_close_check") is True
    assert handoff_core.is_slice_complete_decision("gem_slice_complete_ADPH-3_metrics") is True


def test_is_slice_complete_rejects_invalid() -> None:
    """Non-slice-complete decisions are rejected."""
    assert handoff_core.is_slice_complete_decision("note_only") is False
    assert handoff_core.is_slice_complete_decision("review_complete") is False
    assert handoff_core.is_slice_complete_decision("_slice_complete_bad") is False
    assert handoff_core.is_slice_complete_decision("toolong_slice_complete_E12-1_foo") is False


def test_extract_slice_label_legacy() -> None:
    """Legacy format extracts the slug."""
    assert handoff_core.extract_slice_label("slice_complete_docs_audit") == "docs_audit"


def test_extract_slice_label_prefixed() -> None:
    """Prefixed format extracts work_ref + slug."""
    assert handoff_core.extract_slice_label("cdx_slice_complete_E12-1_gate_validation") == "E12-1_gate_validation"


def test_validate_decision_accepts_prefixed_slice_complete(isolated_handoff: dict) -> None:
    """record_decision accepts the new prefixed slice_complete format with structured rationale."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="grammar-test",
            objective="Grammar test",
            status="in_progress",
        )
    )
    actor = {"agent": "test", "branch": "test", "commit_sha": "abc123"}
    structured_rationale = (
        "## Changes\n- core.py: is_slice_complete_decision ; added helper\n\n"
        "## Verification\n- pytest: 5 passed\n\n"
        "## Schema / Contract Changes\n- none.\n\n"
        "## Open Threads\n- none."
    )
    result = _parse(
        mcp_server.record_decision(
            session="s-grammar",
            decision="cdx_slice_complete_E12-3_grammar_helpers",
            rationale=structured_rationale,
            actor=actor,
        )
    )
    assert result["ok"] is True


def test_close_check_recognizes_prefixed_slice_complete(isolated_handoff: dict) -> None:
    """handoff_close_check finds prefixed slice_complete decisions for close readiness."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="close-prefix",
            objective="Close check prefixed",
            status="done",
        )
    )
    actor = {"agent": "test", "branch": "test", "commit_sha": "def456"}
    structured_rationale = (
        "## Changes\n- core.py: handoff_close_check ; updated query\n\n"
        "## Verification\n- pytest: 3 passed\n\n"
        "## Schema / Contract Changes\n- none.\n\n"
        "## Open Threads\n- none."
    )
    _parse(
        mcp_server.record_decision(
            session="s-close",
            decision="cop_slice_complete_E12-3_close_check_compat",
            rationale=structured_rationale,
            actor=actor,
        )
    )
    _parse(mcp_server.generate_current_task_md(task_ref="close-prefix", write_file=True))

    result = _parse(mcp_server.handoff_close_check(enforce=True, current_commit_sha="def456"))
    assert result["ok"] is True
    assert result["ready_to_close"] is True
    assert result["checks"]["current_commit_handoff"]["structured_slice_decision_count"] >= 1


# HANDOFF-REV-001 regression: generate_current_task_md for archived non-active task
def test_generate_current_task_md_renders_archived_non_active_task(isolated_handoff: dict) -> None:
    """generate_current_task_md renders the objective for an archived task that is no longer active."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="archived-render-task",
            objective="Archived Task Objective",
            status="done",
        )
    )
    _parse(mcp_server.archive_task_state(task_ref="archived-render-task"))

    # Make a different task active so archived-render-task is definitely not active.
    _parse(
        mcp_server.set_handoff_state(
            task_ref="current-active-task",
            objective="Current Active Objective",
            status="in_progress",
        )
    )

    payload = _parse(mcp_server.generate_current_task_md(task_ref="archived-render-task", write_file=False))
    assert payload["ok"] is True
    assert payload["task_ref"] == "archived-render-task"
    assert payload["current_task_json"] is not None
    data = json.loads(payload["current_task_json"])
    assert data["active"]["objective"] == "Archived Task Objective"


# HANDOFF-REV-002 regression: close_slice atomicity on set_handoff_state failure
def test_close_slice_does_not_write_md_on_state_failure(isolated_handoff: dict) -> None:
    """close_slice returns ok=False and leaves CURRENT_TASK.md untouched when set_handoff_state fails."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="close-atomic-test",
            objective="Atomic slice test",
            status="in_progress",
        )
    )

    # Write a sentinel so we can verify the file is NOT overwritten.
    sentinel = "SENTINEL_BEFORE_FAILED_CLOSE"
    isolated_handoff["current_task_path"].write_text(sentinel)

    # Provide a wrong expected_revision to force set_handoff_state to fail.
    result = _parse(
        mcp_server.close_slice(
            session="s-atomic",
            decision="non-slice-atomic-close-test",
            expected_revision=9999,
            task_ref="close-atomic-test",
        )
    )

    assert result["ok"] is False
    assert result["decision_recorded"] is False
    assert result["state_updated"] is False
    assert result["current_task_md_written"] is False
    assert isolated_handoff["current_task_path"].read_text() == sentinel


def test_close_slice_requires_expected_revision_before_recording_decision(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="close-preflight-test",
            objective="Preflight required",
            status="in_progress",
        )
    )

    result = _parse(
        mcp_server.close_slice(
            session="s-preflight",
            decision="non-slice-preflight-test",
            task_ref="close-preflight-test",
        )
    )

    assert result["ok"] is False
    assert result["decision_recorded"] is False
    assert "expected_revision is required for updates" in result["state_error"]
    assert "get_handoff_state(sections='identity')" in result["state_error"]

    state = _parse(mcp_server.get_handoff_state(task_ref="close-preflight-test"))
    assert state["ok"] is True
    assert [item["decision"] for item in state["decisions_recent"]] == []


def test_close_slice_writes_current_task_json_on_success(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="close-dashboard",
            objective="Close slice dashboard proof",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            task_ref="close-dashboard-other",
            session="close-dash-find",
            finding_id="CLOSE-DASH-01",
            severity="low",
            file_path="docs/close.md",
            description="Other task stays visible after close_slice regeneration",
        )
    )

    result = _parse(
        mcp_server.close_slice(
            session="close-dash",
            decision="cop_slice_complete_E12-11_close_slice_dashboard_regen",
            rationale=(
                "## Changes\n- verify close_slice dashboard regeneration.\n\n"
                "## Verification\n- unit test.\n\n"
                "## Schema / Contract Changes\n- none.\n\n"
                "## Open Threads\n- none."
            ),
            task_ref="close-dashboard",
            expected_revision=0,
        )
    )

    assert result["ok"] is True
    assert result["current_task_md_written"] is True
    # OC-003: close_slice returns decision row and task_revision
    assert isinstance(result["decision"], dict)
    assert "id" in result["decision"]
    assert "decision" in result["decision"]
    assert isinstance(result["task_revision"], int)
    assert result["task_revision"] >= 1

    # CURRENT_TASK.md is machine-readable JSON (active-task only).
    # Cross-task sections (All Tasks table, other-task findings) live in DASHBOARD.md.
    current_task_payload = json.loads(isolated_handoff["current_task_path"].read_text())
    assert current_task_payload["task_ref"] == "close-dashboard"
    assert current_task_payload["active"]["status"] == "in_progress"


def test_close_slice_persists_changed_files_on_decision_row(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="close-files",
            objective="Close slice changed files proof",
            status="in_progress",
        )
    )

    result = _parse(
        mcp_server.close_slice(
            session="close-files",
            decision="cop_slice_complete_E13_close_slice_changed_files",
            rationale=(
                "## Changes\n- persist changed files.\n\n"
                "## Verification\n- unit test.\n\n"
                "## Schema / Contract Changes\n- none.\n\n"
                "## Open Threads\n- none."
            ),
            task_ref="close-files",
            expected_revision=0,
            changed_files=[
                "packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py",
                "packages/agent-handoff-mcp/tests/test_handoff_state.py",
            ],
        )
    )

    assert result["ok"] is True

    with sqlite3.connect(isolated_handoff["db_path"]) as conn:
        conn.row_factory = sqlite3.Row
        decision_row = conn.execute(
            "SELECT changed_files_json FROM decisions WHERE decision = ?",
            ("cop_slice_complete_E13_close_slice_changed_files",),
        ).fetchone()

    assert decision_row is not None
    assert json.loads(decision_row["changed_files_json"]) == [
        "packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py",
        "packages/agent-handoff-mcp/tests/test_handoff_state.py",
    ]


# AHMCP-22: close_slice rejects XML-embedded actor/changed_files in rationale
def test_close_slice_rejects_xml_actor_tag_in_rationale(isolated_handoff: dict) -> None:
    """AHMCP-22 / Layer 2 of the XML-in-rationale bug class eradication.
    close_slice must reject rationale strings containing <actor> tags
    because they indicate the caller embedded the actor parameter inside
    the rationale instead of passing it as a separate top-level field."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="xml-reject-test",
            objective="XML tag rejection test",
            status="in_progress",
        )
    )
    result = _parse(
        mcp_server.close_slice(
            session="s-xml",
            decision="clo_slice_complete_xml_reject_test_s1",
            expected_revision=0,
            rationale='## Changes\nDid some work.\n<actor>{"agent": "test"}</actor>',
        )
    )
    assert result["ok"] is False
    assert "<actor>" in result["error"]
    assert "separate top-level JSON fields" in result["error"]


def test_close_slice_rejects_xml_changed_files_tag_in_rationale(isolated_handoff: dict) -> None:
    """Same bug class, different tag: <changed_files> in rationale."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="xml-reject-cf-test",
            objective="CF tag rejection test",
            status="in_progress",
        )
    )
    result = _parse(
        mcp_server.close_slice(
            session="s-xml-cf",
            decision="clo_slice_complete_xml_reject_cf_test_s1",
            expected_revision=0,
            rationale='## Changes\nDid work.\n<changed_files>["a.py"]</changed_files>',
        )
    )
    assert result["ok"] is False
    assert "<changed_files>" in result["error"]


def test_close_slice_rejects_uppercase_xml_actor_tag(isolated_handoff: dict) -> None:
    """AHMCP-22-BR-01 regression: the guard must be case-insensitive so
    <ACTOR>, <Actor>, <Changed_Files> etc. are all caught."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="xml-upper-test",
            objective="Uppercase tag test",
            status="in_progress",
        )
    )
    result = _parse(
        mcp_server.close_slice(
            session="s-xml-upper",
            decision="clo_slice_complete_xml_upper_test_s1",
            expected_revision=0,
            rationale='## Changes\nWork.\n<ACTOR>{"agent":"x"}</ACTOR>',
        )
    )
    assert result["ok"] is False
    assert "actor" in result["error"].lower()


def test_close_slice_surfaces_verbose_rationale_warning(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="close-warn",
            objective="Close slice warning propagation",
            status="in_progress",
        )
    )

    result = _parse(
        mcp_server.close_slice(
            session="s-close-warn",
            decision="cop_slice_complete_AHMCP-24_warning_propagation",
            rationale=(
                "## Changes\n- packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py: close_slice ; preserved warnings.\n\n"
                "## Verification\n- none.\n\n"
                "## Schema / Contract Changes\n- none.\n\n"
                "## Open Threads\n- none.\n\n" + ("x" * 1550)
            ),
            expected_revision=0,
            task_ref="close-warn",
        )
    )

    assert result["ok"] is True
    warnings = result.get("warnings", [])
    assert any("1,500 chars" in warning for warning in warnings)


def test_close_slice_allows_clean_rationale(isolated_handoff: dict) -> None:
    """A rationale that does not contain XML anti-pattern tags should pass through."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="xml-allow-test",
            objective="Clean rationale test",
            status="in_progress",
        )
    )
    result = _parse(
        mcp_server.close_slice(
            session="s-xml-allow",
            decision="clo_slice_complete_xml_allow_test_s1",
            expected_revision=0,
            rationale=(
                "## Changes\nFixed the bug.\n\n"
                "## Verification\n1 passed.\n\n"
                "## Schema / Contract Changes\nNone.\n\n"
                "## Open Threads\nNone."
            ),
        )
    )
    assert result["ok"] is True


# E12-5 review: load_session compound tool
def test_load_session_merges_state_and_findings(isolated_handoff: dict) -> None:
    """load_session returns combined handoff state + open findings in a single payload."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="ls-test",
            objective="Load session compound test",
            status="in_progress",
        )
    )
    mcp_server.record_review_finding(
        session="s-ls",
        finding_id="ls-f1",
        severity="medium",
        file_path="some/file.py",
        description="Test finding for load_session.",
        task_ref="ls-test",
    )

    result = _parse(mcp_server.load_session(task_ref="ls-test"))

    assert result["ok"] is True
    assert result["task_ref"] == "ls-test"
    # State is the full v2 envelope from get_handoff_state; data is nested.
    state = result["state"]
    state_data = state.get("data", state)
    assert state_data["active"]["status"] == "in_progress"
    assert state_data["active"]["objective"] == "Load session compound test"
    # Open findings at top-level "open_findings"
    findings = result["open_findings"]
    assert isinstance(findings, list)
    assert result["open_findings_count"] >= 1
    assert any(f["finding_id"] == "ls-f1" for f in findings)


# ---------------------------------------------------------------------------
# classify_decision_id / audit_decision_ids (E12-3 stretch goal)
# ---------------------------------------------------------------------------


def test_classify_decision_id_canonical() -> None:
    """Full canonical grammar is classified as 'canonical'."""
    assert handoff_core.classify_decision_id("cdx_slice_complete_E12-1_gate_validation") == "canonical"
    assert handoff_core.classify_decision_id("cop_review_complete_E12-3_audit") == "canonical"
    assert handoff_core.classify_decision_id("cla_record_ADPH-4_fix_rev_001") == "canonical"
    assert handoff_core.classify_decision_id("ab_foo_TASK-1_bar") == "canonical"


def test_classify_decision_id_legacy_slice() -> None:
    """Legacy slice_complete_* is classified as 'legacy_slice'."""
    assert handoff_core.classify_decision_id("slice_complete_docs_audit") == "legacy_slice"
    assert handoff_core.classify_decision_id("slice_complete_foo") == "legacy_slice"


def test_classify_decision_id_malformed_slice() -> None:
    """Ids containing slice_complete but violating the grammar are 'malformed_slice'."""
    assert handoff_core.classify_decision_id("_slice_complete_bad") == "malformed_slice"
    assert handoff_core.classify_decision_id("toolong_slice_complete_E12-1_foo") == "malformed_slice"
    assert handoff_core.classify_decision_id("ABC_slice_complete_E12-1_foo") == "malformed_slice"


def test_classify_decision_id_freeform() -> None:
    """Ids with no slice_complete and no canonical form are 'freeform'."""
    assert handoff_core.classify_decision_id("review_handoff_state_slice_audit") == "freeform"
    assert handoff_core.classify_decision_id("note_only") == "freeform"
    assert handoff_core.classify_decision_id("review_complete") == "freeform"


def test_audit_decision_ids_healthy_when_all_canonical(isolated_handoff: dict) -> None:
    """audit_decision_ids reports healthy=True when all decisions are canonical."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="audit-canonical",
            objective="Canonical audit test",
            status="in_progress",
        )
    )
    structured_rationale = (
        "## Changes\n- none.\n\n## Verification\n- pytest passed.\n\n"
        "## Schema / Contract Changes\n- none.\n\n## Open Threads\n- none."
    )
    _parse(
        mcp_server.record_decision(
            session="s-audit",
            decision="cdx_slice_complete_E12-3_canonical_check",
            rationale=structured_rationale,
            task_ref="audit-canonical",
        )
    )
    _parse(
        mcp_server.record_decision(
            session="s-audit",
            decision="cop_review_complete_E12-3_audit",
            task_ref="audit-canonical",
        )
    )

    result = _parse(mcp_server.audit_decision_ids(task_ref="audit-canonical"))

    assert result["ok"] is True
    assert result["task_ref"] == "audit-canonical"
    assert result["healthy"] is True
    assert result["counts"]["canonical"] == 2
    assert result["counts"]["malformed_slice"] == 0
    assert result["violations"] == []


def test_audit_decision_ids_flags_malformed_slice(isolated_handoff: dict) -> None:
    """audit_decision_ids reports healthy=False when a malformed slice_complete id exists."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="audit-bad",
            objective="Malformed audit test",
            status="in_progress",
        )
    )
    # Insert a malformed decision by bypassing validation (direct DB write).
    import sqlite3 as _sqlite3

    db_path = isolated_handoff["db_path"]
    with _sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO decisions (task_ref, session, decision, created_at) "
            "VALUES ('audit-bad', 's-bad', 'toolong_slice_complete_E12-1_foo', datetime('now'))"
        )

    result = _parse(mcp_server.audit_decision_ids(task_ref="audit-bad"))

    assert result["ok"] is True
    assert result["healthy"] is False
    assert result["counts"]["malformed_slice"] >= 1
    malformed_ids = [v["decision"] for v in result["violations"]]
    assert "toolong_slice_complete_E12-1_foo" in malformed_ids


def test_audit_decision_ids_legacy_slice_not_in_default_violations(isolated_handoff: dict) -> None:
    """Legacy slice_complete_* rows appear in counts but not the default violations list."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="audit-legacy",
            objective="Legacy audit test",
            status="in_progress",
        )
    )
    import sqlite3 as _sqlite3

    db_path = isolated_handoff["db_path"]
    with _sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO decisions (task_ref, session, decision, created_at) "
            "VALUES ('audit-legacy', 's-leg', 'slice_complete_old_format', datetime('now'))"
        )

    result = _parse(mcp_server.audit_decision_ids(task_ref="audit-legacy"))

    assert result["ok"] is True
    # Legacy rows are counted but not in the default violations list.
    assert result["counts"]["legacy_slice"] >= 1
    legacy_in_violations = [v for v in result["violations"] if v["category"] == "legacy_slice"]
    assert legacy_in_violations == []


def test_audit_decision_ids_include_categories_override(isolated_handoff: dict) -> None:
    """include_categories=['legacy_slice'] reports legacy rows in violations."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="audit-legacy-override",
            objective="Legacy include test",
            status="in_progress",
        )
    )
    import sqlite3 as _sqlite3

    db_path = isolated_handoff["db_path"]
    with _sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO decisions (task_ref, session, decision, created_at) "
            "VALUES ('audit-legacy-override', 's-lo', 'slice_complete_old_format', datetime('now'))"
        )

    result = _parse(
        mcp_server.audit_decision_ids(
            task_ref="audit-legacy-override",
            include_categories=["legacy_slice"],
        )
    )

    assert result["ok"] is True
    assert any(v["category"] == "legacy_slice" for v in result["violations"])


def test_audit_decision_ids_limit_is_respected(isolated_handoff: dict) -> None:
    """audit_decision_ids only inspects up to limit rows."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="audit-limit",
            objective="Limit audit test",
            status="in_progress",
        )
    )
    import sqlite3 as _sqlite3

    db_path = isolated_handoff["db_path"]
    with _sqlite3.connect(str(db_path)) as conn:
        for i in range(10):
            conn.execute(
                "INSERT INTO decisions (task_ref, session, decision, created_at) "
                "VALUES ('audit-limit', 's-lim', ?, datetime('now'))",
                (f"freeform_decision_{i}",),
            )

    result = _parse(mcp_server.audit_decision_ids(task_ref="audit-limit", limit=5))

    assert result["ok"] is True
    assert result["total_inspected"] == 5
