"""Tests for review findings: global lookup, ambiguity, repo-scope, schema, and renderer."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agent_handoff_mcp import BranchMismatchError
from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp._shared import _get_db_connection, _render_current_task_md, _render_dashboard_section
from agent_handoff_mcp.config import RuntimeConfig
from agent_handoff_mcp.current_task_rendering import _infer_epic_ref


def _parse(raw: str | dict) -> dict:
    """Convenience accessor: AHMCP-10 dict-return refactor means handlers
    yield dicts directly, so we just normalise + flatten data into the top
    level for ergonomic test reads. The string branch survives only for the
    rare callers that capture serialised CLI output.
    """
    result = raw if isinstance(raw, dict) else json.loads(raw)
    if isinstance(result, dict) and result.get("schema_version") == 2:
        data = result.get("data", {})
        scope = result.get("scope", {})
        flat = {**result, **data}
        if "task_ref" not in flat and scope.get("task_ref"):
            flat["task_ref"] = scope["task_ref"]
        return flat
    return result


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
    cells = row[46:].split()
    assert cells[0] == status
    assert cells[1] == str(open_findings)
    assert cells[2] == str(open_blockers)
    assert cells[3] == str(pending_actions)


@pytest.fixture()
def isolated_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_dir = tmp_path / ".task-state"
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


# ---------------------------------------------------------------------------
# Schema: review_runs table bootstrap
# ---------------------------------------------------------------------------


def test_review_runs_table_is_bootstrapped(isolated_handoff: dict) -> None:
    """review_runs table exists and can accept rows after bootstrap."""
    with _get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO review_runs (review_run_id, subject_path, review_mode)
            VALUES ('rr-001', 'docs/tasks/test.md', 'planning')
            """
        )
        row = conn.execute("SELECT * FROM review_runs WHERE review_run_id = 'rr-001'").fetchone()
    assert row is not None
    assert row["review_mode"] == "planning"
    assert row["subject_path"] == "docs/tasks/test.md"


def test_review_runs_review_mode_rejects_invalid(isolated_handoff: dict) -> None:
    """review_runs.review_mode CHECK rejects invalid values."""
    with _get_db_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO review_runs (review_run_id, subject_path, review_mode) VALUES ('rr-bad', 'x.md', 'invalid')"
            )


def test_review_runs_supports_all_three_modes(isolated_handoff: dict) -> None:
    """review_runs accepts branch, release_audit, and planning modes."""
    with _get_db_connection() as conn:
        for mode in ("branch", "release_audit", "planning"):
            conn.execute(
                "INSERT INTO review_runs (review_run_id, subject_path, review_mode) VALUES (?, 'x.md', ?)",
                (f"rr-{mode}", mode),
            )
        rows = conn.execute("SELECT review_mode FROM review_runs ORDER BY id").fetchall()
    assert {str(r["review_mode"]) for r in rows} == {"branch", "release_audit", "planning"}


def test_review_findings_has_review_run_id_column(isolated_handoff: dict) -> None:
    """review_findings.review_run_id column exists after migration."""
    with _get_db_connection() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(review_findings)").fetchall()}
    assert "review_run_id" in cols


# ---------------------------------------------------------------------------
# review_mode: planning accepted by record_review_finding
# ---------------------------------------------------------------------------


def test_record_review_finding_accepts_planning_review_mode(isolated_handoff: dict) -> None:
    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))
    result = _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="T1-PLAN-01",
            severity="medium",
            file_path="docs/plan.md",
            description="Planning gap",
            review_mode="planning",
        )
    )
    assert result["ok"] is True
    assert result["finding"]["review_mode"] == "planning"


def test_record_review_finding_raises_branch_mismatch_error_when_enforcement_enabled(
    isolated_handoff: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT", raising=False)
    monkeypatch.setenv("AGENT_HANDOFF_ENFORCE_BRANCH", "1")
    _parse(
        mcp_server.set_handoff_state(
            task_ref="rf-enforced",
            objective="Enforce branch match on finding writes",
            status="in_progress",
            target_branch="feature/rf-enforced",
        )
    )

    with pytest.raises(BranchMismatchError, match="feature/rf-enforced"):
        mcp_server.record_review_finding(
            session="s1",
            finding_id="RF-ENFORCED-001",
            severity="medium",
            file_path="docs/plan.md",
            description="Branch mismatch should fail before insert",
            task_ref="rf-enforced",
            actor={"agent": "test-agent", "branch": "feature/not-rf-enforced"},
        )

    with _get_db_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM review_findings WHERE task_ref = ?",
            ("rf-enforced",),
        ).fetchone()[0]
    assert count == 0


def test_batch_record_review_findings_raises_branch_mismatch_error_when_enforcement_enabled(
    isolated_handoff: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT", raising=False)
    monkeypatch.setenv("AGENT_HANDOFF_ENFORCE_BRANCH", "1")
    _parse(
        mcp_server.set_handoff_state(
            task_ref="rf-batch-enforced",
            objective="Enforce branch match on batch finding writes",
            status="in_progress",
            target_branch="feature/rf-batch-enforced",
        )
    )

    with pytest.raises(BranchMismatchError, match="feature/rf-batch-enforced"):
        mcp_server.batch_record_review_findings(
            session="s1",
            findings=[
                {
                    "finding_id": "RF-BATCH-001",
                    "severity": "low",
                    "file_path": "docs/plan.md",
                    "description": "Batch write should fail before insert",
                }
            ],
            task_ref="rf-batch-enforced",
            actor={"agent": "test-agent", "branch": "feature/not-rf-batch-enforced"},
        )

    with _get_db_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM review_findings WHERE task_ref = ?",
            ("rf-batch-enforced",),
        ).fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# Slice 2: Global exact-id lookup — list_review_findings
# ---------------------------------------------------------------------------


def test_list_review_findings_global_lookup_by_finding_id(isolated_handoff: dict) -> None:
    """list_review_findings finds a finding globally when task_ref is omitted."""
    _parse(mcp_server.set_handoff_state(task_ref="task-A", objective="A", status="in_progress"))
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="GLOBAL-001",
            severity="medium",
            file_path="core.py",
            description="Global finding",
            task_ref="task-A",
        )
    )
    # Switch active task
    _parse(mcp_server.set_handoff_state(task_ref="task-B", objective="B", status="in_progress", expected_revision=0))

    # Without task_ref: global lookup succeeds
    result = _parse(mcp_server.list_review_findings(finding_id="GLOBAL-001"))
    assert result["ok"] is True
    assert result["findings"][0]["finding_id"] == "GLOBAL-001"
    assert result["task_ref"] == "task-A"


def test_list_review_findings_global_lookup_by_finding_db_id(isolated_handoff: dict) -> None:
    """list_review_findings global lookup works with finding_db_id too."""
    _parse(mcp_server.set_handoff_state(task_ref="task-A", objective="A", status="in_progress"))
    created = _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="GLOBAL-002",
            severity="low",
            file_path="core.py",
            description="db id global",
            task_ref="task-A",
        )
    )
    db_id = int(created["finding"]["id"])
    _parse(mcp_server.set_handoff_state(task_ref="task-B", objective="B", status="in_progress", expected_revision=0))

    result = _parse(mcp_server.list_review_findings(finding_db_id=db_id))
    assert result["ok"] is True
    assert result["findings"][0]["finding_id"] == "GLOBAL-002"


def test_list_review_findings_global_ambiguity_error(isolated_handoff: dict) -> None:
    """list_review_findings returns an ambiguity error when finding_id exists under multiple task_refs."""
    _parse(mcp_server.set_handoff_state(task_ref="task-A", objective="A", status="in_progress"))
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="DUP-001",
            severity="low",
            file_path="f.py",
            description="dup under A",
            task_ref="task-A",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="DUP-001",
            severity="low",
            file_path="f.py",
            description="dup under B",
            task_ref="task-B",
        )
    )

    result = _parse(mcp_server.list_review_findings(finding_id="DUP-001"))
    assert result["ok"] is False
    assert "Ambiguous" in result["error"]
    assert "task-A" in result["error"]
    assert "task-B" in result["error"]


def test_list_review_findings_explicit_task_ref_still_scopes(isolated_handoff: dict) -> None:
    """When task_ref is explicit, list_review_findings still scopes to that task."""
    _parse(mcp_server.set_handoff_state(task_ref="task-A", objective="A", status="in_progress"))
    db_id_a = int(
        _parse(
            mcp_server.record_review_finding(
                session="s1",
                finding_id="SCOPED-001",
                severity="low",
                file_path="f.py",
                description="under A",
                task_ref="task-A",
            )
        )["finding"]["id"]
    )

    result = _parse(mcp_server.list_review_findings(finding_db_id=db_id_a, task_ref="task-B"))
    assert result["ok"] is False
    assert "Finding not found for task." in result["error"]


# ---------------------------------------------------------------------------
# Slice 2: Global exact-id lookup — update_review_finding
# ---------------------------------------------------------------------------


def test_update_review_finding_global_lookup(isolated_handoff: dict) -> None:
    """update_review_finding finds and updates a finding globally when task_ref is omitted."""
    _parse(mcp_server.set_handoff_state(task_ref="task-A", objective="A", status="in_progress"))
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="UPD-GLOBAL-001",
            severity="medium",
            file_path="f.py",
            description="update global",
            task_ref="task-A",
        )
    )
    _parse(mcp_server.set_handoff_state(task_ref="task-B", objective="B", status="in_progress", expected_revision=0))

    result = _parse(mcp_server.update_review_finding(finding_id="UPD-GLOBAL-001", status="fixed"))
    assert result["ok"] is True
    assert result["finding"]["status"] == "fixed"


def test_update_review_finding_global_ambiguity_error(isolated_handoff: dict) -> None:
    """update_review_finding returns ambiguity error when finding_id is not unique globally."""
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="UPD-DUP-001",
            severity="low",
            file_path="f.py",
            description="dup A",
            task_ref="task-X",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="UPD-DUP-001",
            severity="low",
            file_path="f.py",
            description="dup B",
            task_ref="task-Y",
        )
    )

    result = _parse(
        mcp_server.update_review_finding(finding_id="UPD-DUP-001", status="wontfix", resolution_notes="dup")
    )
    assert result["ok"] is False
    assert "Ambiguous" in result["error"]


def test_update_review_finding_raises_branch_mismatch_error_when_enforcement_enabled(
    isolated_handoff: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT", raising=False)
    monkeypatch.setenv("AGENT_HANDOFF_ENFORCE_BRANCH", "1")
    _parse(
        mcp_server.set_handoff_state(
            task_ref="rf-update-enforced",
            objective="Enforce branch match on finding updates",
            status="in_progress",
            target_branch="feature/rf-update-enforced",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="seed",
            finding_id="RF-UPD-001",
            severity="medium",
            file_path="docs/plan.md",
            description="Seed finding",
            task_ref="rf-update-enforced",
            actor={"agent": "seed-agent", "branch": "feature/rf-update-enforced"},
        )
    )

    with pytest.raises(BranchMismatchError, match="feature/rf-update-enforced"):
        mcp_server.update_review_finding(
            finding_id="RF-UPD-001",
            task_ref="rf-update-enforced",
            status="fixed",
            resolution_notes="Should not be applied from the wrong branch",
            actor={"agent": "test-agent", "branch": "feature/not-rf-update-enforced", "commit_sha": "abc123"},
        )

    row = _parse(mcp_server.list_review_findings(task_ref="rf-update-enforced", finding_id="RF-UPD-001"))["findings"][0]
    assert row["status"] == "open"


def test_repair_review_finding_provenance_raises_branch_mismatch_error_when_enforcement_enabled(
    isolated_handoff: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT", raising=False)
    monkeypatch.setenv("AGENT_HANDOFF_ENFORCE_BRANCH", "1")
    _parse(
        mcp_server.set_handoff_state(
            task_ref="rf-repair-enforced",
            objective="Enforce branch match on provenance repair",
            status="in_progress",
            target_branch="feature/rf-repair-enforced",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="seed",
            finding_id="RF-REPAIR-001",
            severity="low",
            file_path="docs/plan.md",
            description="Seed finding for provenance repair",
            task_ref="rf-repair-enforced",
            actor={
                "agent": "seed-agent",
                "branch": "feature/rf-repair-enforced",
                "commit_sha": "abc123",
            },
        )
    )

    with pytest.raises(BranchMismatchError, match="feature/rf-repair-enforced"):
        mcp_server.repair_review_finding_provenance(
            session="repair",
            finding_id="RF-REPAIR-001",
            expected_branch="feature/rf-repair-enforced",
            expected_commit_sha="abc123",
            new_branch="feature/rf-repair-enforced-fixed",
            new_commit_sha="def456",
            reason="Repair original provenance",
            task_ref="rf-repair-enforced",
            actor={"agent": "test-agent", "branch": "feature/not-rf-repair-enforced"},
        )

    finding = _parse(mcp_server.list_review_findings(task_ref="rf-repair-enforced", finding_id="RF-REPAIR-001"))[
        "findings"
    ][0]
    assert finding["branch"] == "feature/rf-repair-enforced"
    assert finding["commit_sha"] == "abc123"


# ---------------------------------------------------------------------------
# Slice 2: repo-scope sentinel ("__repo__")
# ---------------------------------------------------------------------------


def test_record_review_finding_with_repo_scope_sentinel(isolated_handoff: dict) -> None:
    """record_review_finding accepts task_ref='__repo__' as repo-scoped sentinel."""
    result = _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="REPO-001",
            severity="low",
            file_path="docs/agentic/instructions.md",
            description="Repo-level planning gap",
            task_ref="__repo__",
        )
    )
    assert result["ok"] is True
    assert result["finding"]["task_ref"] == "__repo__"


def test_repo_scoped_finding_visible_via_global_lookup(isolated_handoff: dict) -> None:
    """Repo-scoped findings are retrievable via global lookup by finding_id."""
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="REPO-002",
            severity="low",
            file_path="docs/plan.md",
            description="Repo finding",
            task_ref="__repo__",
        )
    )
    result = _parse(mcp_server.list_review_findings(finding_id="REPO-002"))
    assert result["ok"] is True
    assert result["findings"][0]["task_ref"] == "__repo__"


def test_repo_scoped_finding_not_in_task_scoped_list(isolated_handoff: dict) -> None:
    """Repo-scoped findings are NOT returned by task-scoped listing queries."""
    _parse(mcp_server.set_handoff_state(task_ref="real-task", objective="obj", status="in_progress"))
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="REPO-003",
            severity="low",
            file_path="docs/plan.md",
            description="Repo finding",
            task_ref="__repo__",
        )
    )
    # Task-scoped list should NOT include __repo__ findings
    result = _parse(mcp_server.list_review_findings(task_ref="real-task", status="open"))
    finding_ids = [f["finding_id"] for f in result.get("findings", [])]
    assert "REPO-003" not in finding_ids


# ---------------------------------------------------------------------------
# Slice 2b: _render_current_task_md for non-active, non-archived task_ref
# ---------------------------------------------------------------------------


def test_render_current_task_md_empty_state_returns_no_active_stub() -> None:
    """When state has no data at all, render returns the 'No active handoff state found.' stub."""
    state: dict = {
        "active": None,
        "task_ref": "E12-8",
        "decisions_recent": [],
        "findings_open": [],
        "blockers_open": [],
        "actions_pending": [],
    }
    md = _render_current_task_md(state)
    assert "No active handoff state found." in md


def test_render_current_task_md_with_decisions_but_no_active(isolated_handoff: dict) -> None:
    """When active is None but decisions exist, render produces a context view instead of stub."""
    _parse(
        mcp_server.record_decision(
            session="s1",
            decision="test_decision_for_render",
            task_ref="E12-test-render",
        )
    )
    result = _parse(mcp_server.generate_current_task_md(task_ref="E12-test-render"))
    assert result["ok"] is True
    _parse(mcp_server.generate_dashboard_md(write_file=True))

    current_task_path = Path(isolated_handoff["current_task_path"])
    current_task_payload = json.loads(current_task_path.read_text())
    dash_md = Path(isolated_handoff["dashboard_path"]).read_text()
    assert current_task_payload["task_ref"] == "E12-test-render"
    # Decision is stored in the active-task JSON (CURRENT_TASK.md)
    assert any(
        "test_decision_for_render" in d.get("decision", "") for d in current_task_payload.get("decisions_recent", [])
    )
    # Task appears in the dashboard All Tasks table
    assert "No active handoff state found." not in dash_md
    assert "E12-test-render" in dash_md


def test_infer_epic_ref_for_epic_task_plan_refs() -> None:
    assert _infer_epic_ref("E13-1") == "E13"
    assert _infer_epic_ref("E13-12-followup") == "E13"
    assert _infer_epic_ref("E13") is None
    assert _infer_epic_ref("phase-5-retention-export-and-audit-controls") is None


def test_render_current_task_md_with_findings_but_no_active(isolated_handoff: dict) -> None:
    """When active is None but open findings exist, render produces a context view."""
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="RENDER-001",
            severity="medium",
            file_path="docs/plan.md",
            description="Finding for render test",
            task_ref="E12-render-findings",
        )
    )
    result = _parse(mcp_server.generate_current_task_md(task_ref="E12-render-findings"))
    assert result["ok"] is True
    _parse(mcp_server.generate_dashboard_md(write_file=True))

    current_task_path = Path(isolated_handoff["current_task_path"])
    current_task_payload = json.loads(current_task_path.read_text())
    dash_md = Path(isolated_handoff["dashboard_path"]).read_text()
    assert current_task_payload["task_ref"] == "E12-render-findings"
    assert "No active handoff state found." not in dash_md
    assert "E12-render-findings" in dash_md


def test_cross_task_finding_write_keeps_current_task_on_active_task(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="E15-2",
            objective="Active task should remain visible",
            status="in_progress",
        )
    )

    _parse(
        mcp_server.record_review_finding(
            session="cross-active",
            task_ref="E14-2",
            finding_id="CROSS-ACTIVE-001",
            severity="medium",
            file_path="docs/tasks/14.0/E14-2-multi-environment-deployment-task-plan.md",
            description="Cross-task finding should render under related findings.",
        )
    )

    current_task_payload = json.loads(isolated_handoff["current_task_path"].read_text())
    assert current_task_payload["task_ref"] == "E15-2"
    # Cross-task finding must not appear in active-task JSON
    assert all(f["finding_id"] != "CROSS-ACTIVE-001" for f in current_task_payload["findings_open"])
    _parse(mcp_server.generate_dashboard_md(write_file=True))
    md = isolated_handoff["dashboard_path"].read_text()
    # Active task appears in dashboard
    assert "E15-2" in md


def test_render_dashboard_section_handles_zero_one_and_multiple_tasks() -> None:
    empty_lines = _render_dashboard_section([], active_task_ref=None)
    assert "ALL TASKS" in empty_lines
    assert any("(no tasks)" in line for line in empty_lines)

    single_lines = _render_dashboard_section(
        [
            {
                "task_ref": "E12-11",
                "status": "active",
                "last_activity": "2026-03-30 21:10:00",
                "open_blockers": 0,
                "pending_actions": 1,
                "open_findings": 2,
                "archived_at": None,
            }
        ],
        active_task_ref="E12-11",
    )
    _assert_dashboard_row(
        "\n".join(single_lines),
        "E12-11",
        status="active",
        open_findings=2,
        open_blockers=0,
        pending_actions=1,
        active=True,
    )

    multiple_lines = _render_dashboard_section(
        [
            {
                "task_ref": "E12-9",
                "status": "active",
                "last_activity": "2026-03-30 20:50:00",
                "open_blockers": 0,
                "pending_actions": 0,
                "open_findings": 0,
                "archived_at": None,
            },
            {
                "task_ref": "__repo__",
                "status": "archived",
                "last_activity": "2026-03-30 04:52:00",
                "open_blockers": 1,
                "pending_actions": 2,
                "open_findings": 3,
                "archived_at": "2026-03-30 04:52:00",
            },
        ],
        active_task_ref="E12-9",
    )
    multiple_md = "\n".join(multiple_lines)
    _assert_dashboard_row(
        multiple_md,
        "E12-9",
        status="active",
        open_findings=0,
        open_blockers=0,
        pending_actions=0,
        active=True,
    )
    _assert_dashboard_row(
        multiple_md,
        "__repo__",
        status="archived",
        open_findings=3,
        open_blockers=1,
        pending_actions=2,
        active=False,
    )


def test_render_dashboard_section_truncates_long_task_refs() -> None:
    long_task_ref = "rls-tenant-context-restoration-after-chunk-commit"

    lines = _render_dashboard_section(
        [
            {
                "task_ref": long_task_ref,
                "status": "done",
                "last_activity": "2026-03-31 05:50:00",
                "open_blockers": 0,
                "pending_actions": 0,
                "open_findings": 0,
                "archived_at": None,
            }
        ],
        active_task_ref=long_task_ref,
    )

    row = next(line for line in lines if line.startswith("> "))
    assert row[2:46] == f"{long_task_ref[:41]}..."
    assert row[46:].split()[:4] == ["done", "0", "0", "0"]


def test_render_current_task_md_active_task_only() -> None:
    """CURRENT_TASK.md renders active-task sections only; no All Tasks table or cross-task data."""
    state: dict = {
        "task_ref": "E12-11",
        "active": {
            "task_ref": "E12-11",
            "objective": "Render active task only",
            "status": "in_progress",
            "revision": 3,
            "updated_at": "2026-03-30 21:15:00",
        },
        "decisions_recent": [],
        "findings_open": [],
        "blockers_open": [],
        "actions_pending": [],
        "tests_recent": [],
        "worktree_lanes": [],
        "worker_reports_recent": [],
        "lane_messages_open": [],
    }

    md = _render_current_task_md(state)

    assert "ALL TASKS" not in md
    assert "E12-10" not in md
    assert "## Objective\nRender active task only" in md
    assert "- epic_ref: `E12`" in md
    assert "- task_ref: `E12-11`" in md


def test_render_current_task_md_without_active_includes_epic_context() -> None:
    state: dict = {
        "task_ref": "E13-1",
        "active": None,
        "decisions_recent": [{"id": 1, "decision": "cop_slice_complete_E13-1_context_only"}],
        "findings_open": [],
        "blockers_open": [],
        "actions_pending": [],
        "tests_recent": [],
        "worktree_lanes": [],
        "worker_reports_recent": [],
        "lane_messages_open": [],
    }

    md = _render_current_task_md(state)

    assert "## Task Context" in md
    assert "- epic_ref: `E13`" in md
    assert "- task_ref: `E13-1`" in md


def test_render_current_task_md_keeps_detail_section_additive() -> None:
    base_state: dict = {
        "task_ref": "E12-11",
        "active": {
            "task_ref": "E12-11",
            "objective": "Keep detail section unchanged",
            "status": "in_progress",
            "revision": 5,
            "updated_at": "2026-03-30 21:20:00",
        },
        "decisions_recent": [
            {
                "id": 1,
                "decision": "cop_slice_complete_E12-11_additive_detail",
                "agent": "copilot",
            }
        ],
        "findings_open": [],
        "blockers_open": [],
        "actions_pending": [],
        "tests_recent": [],
        "worktree_lanes": [],
        "worker_reports_recent": [],
        "lane_messages_open": [],
    }

    without_dashboard = _render_current_task_md(base_state)
    with_dashboard = _render_current_task_md(
        {
            **base_state,
            "dashboard_tasks": [
                {
                    "task_ref": "E12-11",
                    "status": "in_progress",
                    "last_activity": "2026-03-30 21:20:00",
                    "open_blockers": 0,
                    "pending_actions": 0,
                    "open_findings": 0,
                    "archived_at": None,
                }
            ],
        }
    )

    detail_start = without_dashboard.index("## Objective")
    assert with_dashboard[with_dashboard.index("## Objective") :] == without_dashboard[detail_start:]


# ---------------------------------------------------------------------------
# Slice 3: record_review_run / list_review_runs / get_review_coverage
# ---------------------------------------------------------------------------


def test_record_review_run_inserts_row(isolated_handoff: dict) -> None:
    """record_review_run stores a row and returns it in the response."""
    result = _parse(
        mcp_server.record_review_run(
            review_run_id="E12-8-review-1",
            session="test-session",
            subject_path="docs/tasks/12.0/E12-8-plan.md",
            subject_kind="task_plan",
            review_mode="planning",
            verdict="pass_with_findings",
            verdict_decision="review_verdict_E12-8-1",
            task_ref="E12-8",
        )
    )
    assert result["ok"] is True
    run = result["review_run"]
    assert run["review_run_id"] == "E12-8-review-1"
    assert run["subject_path"] == "docs/tasks/12.0/E12-8-plan.md"
    assert run["verdict"] == "pass_with_findings"
    assert run["task_ref"] == "E12-8"
    assert result["mutation"]["entity"] == "review_run"
    assert result["mutation"]["operation"] == "insert"
    assert result["mutation"]["affected_ids"] == ["E12-8-review-1"]
    assert result["mutation"]["task_revision"] is None


def test_record_review_run_rejects_duplicate_id(isolated_handoff: dict) -> None:
    """record_review_run refuses a second insert with the same review_run_id."""
    kwargs = dict(
        review_run_id="E12-8-dup",
        session="s",
        subject_path="docs/plan.md",
    )
    first = _parse(mcp_server.record_review_run(**kwargs))
    assert first["ok"] is True
    second = _parse(mcp_server.record_review_run(**kwargs))
    assert second["ok"] is False
    assert "already exists" in second["error"]


def test_record_review_run_rejects_invalid_verdict(isolated_handoff: dict) -> None:
    result = _parse(
        mcp_server.record_review_run(
            review_run_id="E12-bad-verdict",
            session="s",
            subject_path="docs/plan.md",
            verdict="PASS",  # uppercase — not valid
        )
    )
    assert result["ok"] is False
    assert "verdict" in result["error"].lower()


def test_record_review_run_rejects_invalid_subject_kind(isolated_handoff: dict) -> None:
    result = _parse(
        mcp_server.record_review_run(
            review_run_id="E12-bad-kind",
            session="s",
            subject_path="docs/plan.md",
            subject_kind="unknown_kind",
        )
    )
    assert result["ok"] is False
    assert "subject_kind" in result["error"].lower()


def test_list_review_runs_paginates_and_filters_by_task_ref(isolated_handoff: dict) -> None:
    """list_review_runs returns only runs matching task_ref."""
    for i in range(3):
        _parse(
            mcp_server.record_review_run(
                review_run_id=f"E12-8-run-{i}",
                session="s",
                subject_path="docs/plan.md",
                task_ref="E12-8",
            )
        )
    _parse(
        mcp_server.record_review_run(
            review_run_id="OTHER-run-1",
            session="s",
            subject_path="docs/other.md",
            task_ref="OTHER-TASK",
        )
    )
    result = _parse(mcp_server.list_review_runs(task_ref="E12-8"))
    assert result["ok"] is True
    assert result["total_matching"] == 3
    assert all(r["task_ref"] == "E12-8" for r in result["runs"])


def test_list_review_runs_filters_by_verdict(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.record_review_run(
            review_run_id="v-pass",
            session="s",
            subject_path="docs/p.md",
            verdict="pass",
            task_ref="T-1",
        )
    )
    _parse(
        mcp_server.record_review_run(
            review_run_id="v-fail",
            session="s",
            subject_path="docs/p.md",
            verdict="fail",
            task_ref="T-1",
        )
    )
    result = _parse(mcp_server.list_review_runs(task_ref="T-1", verdict="pass"))
    assert result["ok"] is True
    assert result["total_matching"] == 1
    assert result["runs"][0]["review_run_id"] == "v-pass"


def test_list_review_runs_filter_by_subject_path(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.record_review_run(
            review_run_id="sp-1",
            session="s",
            subject_path="docs/alpha.md",
        )
    )
    _parse(
        mcp_server.record_review_run(
            review_run_id="sp-2",
            session="s",
            subject_path="docs/beta.md",
        )
    )
    result = _parse(mcp_server.list_review_runs(subject_path="docs/alpha.md"))
    assert result["ok"] is True
    assert result["total_matching"] == 1
    assert result["runs"][0]["review_run_id"] == "sp-1"


def test_get_review_coverage_by_task_ref(isolated_handoff: dict) -> None:
    """get_review_coverage returns run_count and finding counts for a task_ref."""
    _parse(
        mcp_server.record_review_run(
            review_run_id="cov-run-1",
            session="s",
            subject_path="docs/e.md",
            verdict="pass_with_findings",
            task_ref="COV-TASK",
        )
    )
    _parse(
        mcp_server.record_review_run(
            review_run_id="cov-run-2",
            session="s",
            subject_path="docs/e.md",
            verdict="pass",
            task_ref="COV-TASK",
        )
    )
    # Record two open findings linked to the task
    for i in range(2):
        _parse(
            mcp_server.record_review_finding(
                session="s",
                finding_id=f"COV-F-{i}",
                severity="medium",
                file_path="docs/e.md",
                description=f"finding {i}",
                task_ref="COV-TASK",
            )
        )
    result = _parse(mcp_server.get_review_coverage(task_ref="COV-TASK"))
    assert result["ok"] is True
    assert result["run_count"] == 2
    assert result["latest_verdict"] == "pass"  # most recent run
    assert result["latest_review_run_id"] == "cov-run-2"
    assert result["open_findings_by_severity"]["medium"] == 2
    assert result["reopened_findings_count"] == 0


def test_get_review_coverage_requires_at_least_one_arg(isolated_handoff: dict) -> None:
    result = _parse(mcp_server.get_review_coverage())
    assert result["ok"] is False
    assert "task_ref" in result["error"] or "subject_path" in result["error"]


def test_get_review_coverage_no_runs_returns_zero_counts(isolated_handoff: dict) -> None:
    result = _parse(mcp_server.get_review_coverage(task_ref="NO-RUNS-TASK"))
    assert result["ok"] is True
    assert result["run_count"] == 0
    assert result["latest_verdict"] is None
    assert result["latest_review_run_id"] is None
    assert result["open_findings_by_severity"] == {"high": 0, "medium": 0, "low": 0}


def test_get_review_coverage_by_subject_path(isolated_handoff: dict) -> None:
    """When only subject_path is given, coverage is derived through review_run_id links."""
    _parse(
        mcp_server.record_review_run(
            review_run_id="sp-cov-run",
            session="s",
            subject_path="docs/target.md",
        )
    )
    result = _parse(mcp_server.get_review_coverage(subject_path="docs/target.md"))
    assert result["ok"] is True
    assert result["run_count"] == 1
    assert result["latest_review_run_id"] == "sp-cov-run"


# ---------------------------------------------------------------------------
# list_review_findings detail parameter
# ---------------------------------------------------------------------------


def test_list_review_findings_detail_summary_truncates(isolated_handoff: dict) -> None:
    """detail='summary' truncates long description text in findings."""
    _parse(
        mcp_server.set_handoff_state(task_ref="rf-det", objective="Review finding detail test", status="in_progress")
    )
    long_desc = "D" * 500
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="rf-det-1",
            severity="medium",
            file_path="some/file.py",
            description=long_desc,
            task_ref="rf-det",
        )
    )

    full = _parse(mcp_server.list_review_findings(task_ref="rf-det", detail="full"))
    assert len(full["findings"][0]["description"]) == 500

    summary = _parse(mcp_server.list_review_findings(task_ref="rf-det", detail="summary"))
    desc = summary["findings"][0]["description"]
    assert desc.endswith("...")
    assert len(desc) == 203


def test_list_review_findings_detail_summary_single_lookup(isolated_handoff: dict) -> None:
    """detail='summary' also works for single-finding lookup by finding_id."""
    _parse(mcp_server.set_handoff_state(task_ref="rf-single", objective="Single finding detail", status="in_progress"))
    long_desc = "E" * 500
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="rf-single-1",
            severity="high",
            file_path="a/b.py",
            description=long_desc,
            task_ref="rf-single",
        )
    )

    summary = _parse(mcp_server.list_review_findings(finding_id="rf-single-1", task_ref="rf-single", detail="summary"))
    assert summary["ok"] is True
    assert summary["findings"][0]["description"].endswith("...")
    assert len(summary["findings"][0]["description"]) == 203


def test_load_session_passes_detail_through(isolated_handoff: dict) -> None:
    """load_session passes detail parameter to both get_handoff_state and list_review_findings."""
    _parse(mcp_server.set_handoff_state(task_ref="ls-det", objective="Load session detail", status="in_progress"))
    long_rationale = "R" * 500
    _parse(mcp_server.record_decision(session="s1", decision="d1", rationale=long_rationale))
    long_desc = "F" * 500
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="ls-det-1",
            severity="medium",
            file_path="x.py",
            description=long_desc,
            task_ref="ls-det",
        )
    )

    result = _parse(mcp_server.load_session(task_ref="ls-det", detail="summary"))
    assert result["ok"] is True
    # State is a v2 envelope; decisions are in state.data
    state = result["state"]
    state_data = state.get("data", state)
    assert state_data["decisions_recent"][0]["rationale"].endswith("...")
    # Findings should be truncated
    assert result["open_findings"][0]["description"].endswith("...")


def test_load_session_passes_sections_through(isolated_handoff: dict) -> None:
    """load_session passes sections through to the nested get_handoff_state payload."""
    _parse(mcp_server.set_handoff_state(task_ref="ls-sec", objective="Load session sections", status="in_progress"))
    _parse(mcp_server.record_decision(session="s1", decision="d1"))
    _parse(mcp_server.report_blocker(operation="add", description="b1"))
    _parse(
        mcp_server.record_review_finding(
            session="s1",
            finding_id="ls-sec-1",
            severity="medium",
            file_path="x.py",
            description="Open finding preserved by load_session",
            task_ref="ls-sec",
        )
    )

    result = _parse(mcp_server.load_session(task_ref="ls-sec", sections="decisions_recent"))
    assert result["ok"] is True

    state = result["state"]
    state_data = state.get("data", state)
    assert "active" in state_data
    assert "limits" in state_data
    assert "decisions_recent" in state_data
    assert "blockers_open" not in state_data
    assert result["open_findings"][0]["finding_id"] == "ls-sec-1"


def test_review_findings_domain_tool_batch_record_and_list(isolated_handoff: dict) -> None:
    _parse(mcp_server.set_handoff_state(task_ref="rf-domain", objective="Review findings domain", status="in_progress"))

    written = _parse(
        mcp_server.review_findings(
            review={
                "operation": "batch_record",
                "session": "rf-domain",
                "task_ref": "rf-domain",
                "findings": [
                    {
                        "finding_id": "RF-001",
                        "severity": "medium",
                        "file_path": "a.py",
                        "description": "First review finding.",
                    },
                    {
                        "finding_id": "RF-002",
                        "severity": "low",
                        "file_path": "b.py",
                        "description": "Second review finding.",
                    },
                ],
            }
        )
    )
    assert written["ok"] is True
    assert written["written"] == 2

    listed = _parse(
        mcp_server.review_findings(
            review={"operation": "list", "task_ref": "rf-domain", "status": "open", "detail": "summary"}
        )
    )
    assert listed["ok"] is True
    assert listed["total_matching"] == 2


def test_review_runs_domain_tool_record_and_coverage(isolated_handoff: dict) -> None:
    recorded = _parse(
        mcp_server.review_runs(
            review={
                "operation": "record",
                "review_run_id": "rr-domain-001",
                "session": "rr-domain",
                "subject_path": "docs/tasks/example.md",
                "task_ref": "rr-domain",
            }
        )
    )
    assert recorded["ok"] is True
    assert recorded["review_run"]["review_run_id"] == "rr-domain-001"

    coverage = _parse(mcp_server.review_runs(review={"operation": "coverage", "task_ref": "rr-domain"}))
    assert coverage["ok"] is True
    assert coverage["run_count"] == 1


def test_next_actions_domain_tool_add_and_list(isolated_handoff: dict) -> None:
    _parse(mcp_server.set_handoff_state(task_ref="na-domain", objective="Next actions domain", status="in_progress"))

    added = _parse(
        mcp_server.next_actions(
            action={
                "operation": "add",
                "task_ref": "na-domain",
                "action": "Wire the next_actions domain tool",
                "priority": 7,
            }
        )
    )
    assert added["ok"] is True
    assert added["action"]["action"] == "Wire the next_actions domain tool"

    listed = _parse(
        mcp_server.next_actions(action={"operation": "list", "task_ref": "na-domain", "status": "pending", "limit": 10})
    )
    assert listed["ok"] is True
    assert listed["returned"] == 1
    assert listed["actions"][0]["action"] == "Wire the next_actions domain tool"


@pytest.mark.parametrize(
    ("tool_name", "surface_class", "entity_family"),
    [
        ("get_handoff_state", "query", "handoff_state"),
        ("next_actions", "action", "handoff_state"),
        ("record_file_touch", "action", "handoff_state"),
        ("get_touched_files", "query", "handoff_state"),
        ("review_findings", "action", "review_findings"),
        ("review_runs", "action", "review_runs"),
        ("handoff_close_check", "generator", "lifecycle"),
        ("generate_current_task_md", "generator", "lifecycle"),
        ("export_handoff_state", "generator", "lifecycle"),
        ("load_session", "query", "session"),
        ("close_slice", "action", "lifecycle"),
        ("artifacts", "action", "artifacts"),
        ("search_handoff", "generator", "handoff_state"),
    ],
)
def test_tool_registry_metadata_matches_contract_taxonomy(
    tool_name: str,
    surface_class: str,
    entity_family: str,
) -> None:
    """Representative registry metadata stays aligned with the documented taxonomy."""
    registry = {entry.name: entry for entry in mcp_server._build_tool_registry()}

    assert registry[tool_name].surface_class == surface_class
    assert registry[tool_name].entity_family == entity_family


# ---------------------------------------------------------------------------
# AHMCP-15: repair_review_finding_provenance — bounded admin op
# ---------------------------------------------------------------------------
#
# Motivating bug (AHMCP-14-BR-04 → BR-05): a review finding row was attributed
# to the reviewing agent's workspace HEAD (an unrelated branch) instead of the
# actual buggy code's commit. The standard `record` upsert COALESCEs existing
# branch/commit_sha so re-recording cannot fix it; `update` doesn't expose the
# source columns. `repair_provenance` is the bounded admin path that mutates
# exactly those two columns and writes a `repair_provenance_<finding_id>`
# decision row as the audit trail.


_AHMCP15_OLD_BRANCH = "feature/wrong-branch"
_AHMCP15_OLD_SHA = "1111111111111111111111111111111111111111"
_AHMCP15_NEW_BRANCH = "feature/correct-branch"
_AHMCP15_NEW_SHA = "2222222222222222222222222222222222222222"
_AHMCP15_REASON = (
    "Original row was tagged with the reviewing agent's workspace HEAD instead of the "
    "AHMCP-14 source commit; repair so commit_guard descendant check is meaningful."
)


def _seed_finding_with_provenance(
    *,
    task_ref: str,
    finding_id: str,
    branch: str,
    commit_sha: str,
) -> int:
    """Insert a review_findings row directly so the test controls source provenance."""
    with _get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO review_findings (
                task_ref, finding_id, severity, file_path, description,
                status, session, agent, branch, commit_sha,
                created_at, updated_at
            )
            VALUES (?, ?, 'medium', 'src/foo.py', 'wrong attribution',
                    'open', 'seed-session', 'Test Agent', ?, ?,
                    datetime('now'), datetime('now'))
            """,
            (task_ref, finding_id, branch, commit_sha),
        )
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def test_repair_provenance_happy_path(isolated_handoff: dict) -> None:
    """Happy path: repair updates branch+commit_sha and writes audit decision."""
    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))
    db_id = _seed_finding_with_provenance(
        task_ref="T1",
        finding_id="T1-BR-01",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=_AHMCP15_OLD_SHA,
    )

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "task_ref": "T1",
                "finding_id": "T1-BR-01",
                "expected_branch": _AHMCP15_OLD_BRANCH,
                "expected_commit_sha": _AHMCP15_OLD_SHA,
                "new_branch": _AHMCP15_NEW_BRANCH,
                "new_commit_sha": _AHMCP15_NEW_SHA,
                "reason": _AHMCP15_REASON,
            }
        )
    )

    assert result["ok"] is True, result
    assert result["finding"]["branch"] == _AHMCP15_NEW_BRANCH
    assert result["finding"]["commit_sha"] == _AHMCP15_NEW_SHA
    assert result["before"] == {"branch": _AHMCP15_OLD_BRANCH, "commit_sha": _AHMCP15_OLD_SHA}
    assert result["after"] == {"branch": _AHMCP15_NEW_BRANCH, "commit_sha": _AHMCP15_NEW_SHA}
    # AHMCP-15-BR-02: audit decision id must conform to the canonical grammar.
    from agent_handoff_mcp.slice_decision import is_canonical_decision

    audit_decision_id = result["audit_decision_id"]
    assert "repair_provenance" in audit_decision_id
    assert is_canonical_decision(audit_decision_id), (
        f"audit_decision_id {audit_decision_id!r} must match the canonical decision-id grammar"
    )
    assert isinstance(result["audit_decision_db_id"], int)

    # Row in DB reflects the change
    with _get_db_connection() as conn:
        row = conn.execute("SELECT branch, commit_sha FROM review_findings WHERE id = ?", (db_id,)).fetchone()
    assert row["branch"] == _AHMCP15_NEW_BRANCH
    assert row["commit_sha"] == _AHMCP15_NEW_SHA

    # Audit decision row exists with before/after embedded in rationale
    with _get_db_connection() as conn:
        decision_row = conn.execute(
            "SELECT decision, rationale, task_ref FROM decisions WHERE id = ?",
            (result["audit_decision_db_id"],),
        ).fetchone()
    assert decision_row["decision"] == audit_decision_id
    assert decision_row["task_ref"] == "T1"
    assert _AHMCP15_OLD_BRANCH in decision_row["rationale"]
    assert _AHMCP15_OLD_SHA in decision_row["rationale"]
    assert _AHMCP15_NEW_BRANCH in decision_row["rationale"]
    assert _AHMCP15_NEW_SHA in decision_row["rationale"]
    assert _AHMCP15_REASON in decision_row["rationale"]


def test_repair_provenance_rejects_branch_mismatch(isolated_handoff: dict) -> None:
    """Concurrency guard: expected_branch must match the stored row exactly."""
    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))
    _seed_finding_with_provenance(
        task_ref="T1",
        finding_id="T1-BR-02",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=_AHMCP15_OLD_SHA,
    )

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "task_ref": "T1",
                "finding_id": "T1-BR-02",
                "expected_branch": "feature/some-other-branch",
                "expected_commit_sha": _AHMCP15_OLD_SHA,
                "new_branch": _AHMCP15_NEW_BRANCH,
                "new_commit_sha": _AHMCP15_NEW_SHA,
                "reason": _AHMCP15_REASON,
            }
        )
    )
    assert result["ok"] is False
    assert "expected_branch does not match" in result["error"]
    assert result["actual_branch"] == _AHMCP15_OLD_BRANCH

    # Row was NOT modified
    with _get_db_connection() as conn:
        row = conn.execute("SELECT branch, commit_sha FROM review_findings WHERE finding_id = 'T1-BR-02'").fetchone()
    assert row["branch"] == _AHMCP15_OLD_BRANCH
    assert row["commit_sha"] == _AHMCP15_OLD_SHA


def test_repair_provenance_rejects_commit_sha_mismatch(isolated_handoff: dict) -> None:
    """Concurrency guard: expected_commit_sha must match the stored row exactly."""
    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))
    _seed_finding_with_provenance(
        task_ref="T1",
        finding_id="T1-BR-03",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=_AHMCP15_OLD_SHA,
    )

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "task_ref": "T1",
                "finding_id": "T1-BR-03",
                "expected_branch": _AHMCP15_OLD_BRANCH,
                "expected_commit_sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                "new_branch": _AHMCP15_NEW_BRANCH,
                "new_commit_sha": _AHMCP15_NEW_SHA,
                "reason": _AHMCP15_REASON,
            }
        )
    )
    assert result["ok"] is False
    assert "expected_commit_sha does not match" in result["error"]
    assert result["actual_commit_sha"] == _AHMCP15_OLD_SHA


def test_repair_provenance_rejects_missing_finding(isolated_handoff: dict) -> None:
    """Missing finding (no row with finding_id under the task_ref) is rejected."""
    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "task_ref": "T1",
                "finding_id": "T1-DOES-NOT-EXIST",
                "expected_branch": _AHMCP15_OLD_BRANCH,
                "expected_commit_sha": _AHMCP15_OLD_SHA,
                "new_branch": _AHMCP15_NEW_BRANCH,
                "new_commit_sha": _AHMCP15_NEW_SHA,
                "reason": _AHMCP15_REASON,
            }
        )
    )
    assert result["ok"] is False
    assert "Finding not found" in result["error"]


def test_repair_provenance_rejects_short_reason(isolated_handoff: dict) -> None:
    """reason must be at least 20 characters."""
    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))
    _seed_finding_with_provenance(
        task_ref="T1",
        finding_id="T1-BR-04",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=_AHMCP15_OLD_SHA,
    )

    # Pydantic min_length=20 catches this at the discriminator boundary
    with pytest.raises(Exception):  # ValidationError from pydantic
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "task_ref": "T1",
                "finding_id": "T1-BR-04",
                "expected_branch": _AHMCP15_OLD_BRANCH,
                "expected_commit_sha": _AHMCP15_OLD_SHA,
                "new_branch": _AHMCP15_NEW_BRANCH,
                "new_commit_sha": _AHMCP15_NEW_SHA,
                "reason": "too short",
            }
        )


def test_repair_provenance_rejects_short_reason_at_core_boundary(isolated_handoff: dict) -> None:
    """The core function also rejects short reasons (defense in depth, bypassing pydantic)."""
    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))
    _seed_finding_with_provenance(
        task_ref="T1",
        finding_id="T1-BR-04b",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=_AHMCP15_OLD_SHA,
    )

    result = _parse(
        mcp_server.repair_review_finding_provenance(
            session="ahmcp-15-test",
            task_ref="T1",
            finding_id="T1-BR-04b",
            expected_branch=_AHMCP15_OLD_BRANCH,
            expected_commit_sha=_AHMCP15_OLD_SHA,
            new_branch=_AHMCP15_NEW_BRANCH,
            new_commit_sha=_AHMCP15_NEW_SHA,
            reason="too short",
        )
    )
    assert result["ok"] is False
    assert "at least 20 characters" in result["error"]


def test_repair_provenance_rejects_no_op_repair(isolated_handoff: dict) -> None:
    """If expected and new are identical, the operation refuses (nothing to repair)."""
    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))
    _seed_finding_with_provenance(
        task_ref="T1",
        finding_id="T1-BR-05",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=_AHMCP15_OLD_SHA,
    )

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "task_ref": "T1",
                "finding_id": "T1-BR-05",
                "expected_branch": _AHMCP15_OLD_BRANCH,
                "expected_commit_sha": _AHMCP15_OLD_SHA,
                "new_branch": _AHMCP15_OLD_BRANCH,
                "new_commit_sha": _AHMCP15_OLD_SHA,
                "reason": _AHMCP15_REASON,
            }
        )
    )
    assert result["ok"] is False
    assert "nothing to repair" in result["error"]


def test_repair_provenance_global_lookup_ambiguity_error(isolated_handoff: dict) -> None:
    """When the same finding_id exists under multiple task_refs and task_ref is omitted,
    the operation reports ambiguity instead of guessing."""
    _parse(mcp_server.set_handoff_state(task_ref="task-A", objective="A", status="in_progress"))
    _seed_finding_with_provenance(
        task_ref="task-A",
        finding_id="DUP-BR-01",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=_AHMCP15_OLD_SHA,
    )
    _parse(mcp_server.set_handoff_state(task_ref="task-B", objective="B", status="in_progress", expected_revision=0))
    _seed_finding_with_provenance(
        task_ref="task-B",
        finding_id="DUP-BR-01",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=_AHMCP15_OLD_SHA,
    )

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "finding_id": "DUP-BR-01",
                "expected_branch": _AHMCP15_OLD_BRANCH,
                "expected_commit_sha": _AHMCP15_OLD_SHA,
                "new_branch": _AHMCP15_NEW_BRANCH,
                "new_commit_sha": _AHMCP15_NEW_SHA,
                "reason": _AHMCP15_REASON,
            }
        )
    )
    assert result["ok"] is False
    assert "Ambiguous finding_id" in result["error"]


def test_repair_provenance_global_lookup_succeeds_when_unique(isolated_handoff: dict) -> None:
    """When task_ref is omitted but finding_id is globally unique, the repair lands."""
    _parse(mcp_server.set_handoff_state(task_ref="task-A", objective="A", status="in_progress"))
    _seed_finding_with_provenance(
        task_ref="task-A",
        finding_id="UNIQUE-BR-01",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=_AHMCP15_OLD_SHA,
    )

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "finding_id": "UNIQUE-BR-01",
                "expected_branch": _AHMCP15_OLD_BRANCH,
                "expected_commit_sha": _AHMCP15_OLD_SHA,
                "new_branch": _AHMCP15_NEW_BRANCH,
                "new_commit_sha": _AHMCP15_NEW_SHA,
                "reason": _AHMCP15_REASON,
            }
        )
    )
    assert result["ok"] is True
    assert result["task_ref"] == "task-A"
    assert result["finding"]["branch"] == _AHMCP15_NEW_BRANCH


def test_repair_provenance_accepts_stored_abbreviated_sha(
    isolated_handoff: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AHMCP-15-BR-01 regression: a finding row whose commit_sha is stored as
    an abbreviation must still be repairable when the caller passes the same
    abbreviation. Production validation expands the caller's input to its
    40-char canonical form, so the comparison must succeed even when the
    stored row has not yet been expanded.

    Tests bypass `_validate_and_expand_commit_sha` via
    `AGENT_HANDOFF_SKIP_SHA_VALIDATION`, so this test mocks the validator to
    simulate the production expansion path.
    """
    short_old = "2c270d01"
    full_old = "2c270d0192de21217ecb0d13d0f42d5ca123779b"
    short_new = "39a23e50"
    full_new = "39a23e503939393939393939393939393939393b"

    def fake_expand(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return value
        if normalized in (short_old, full_old):
            return full_old
        if normalized in (short_new, full_new):
            return full_new
        return value

    monkeypatch.setattr(
        "agent_handoff_mcp.shared_write_context._validate_and_expand_commit_sha",
        fake_expand,
    )

    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))
    db_id = _seed_finding_with_provenance(
        task_ref="T1",
        finding_id="T1-BR-06",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=short_old,  # row stores the abbreviation
    )

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "task_ref": "T1",
                "finding_id": "T1-BR-06",
                "expected_branch": _AHMCP15_OLD_BRANCH,
                "expected_commit_sha": short_old,  # caller passes the same abbreviation
                "new_branch": _AHMCP15_NEW_BRANCH,
                "new_commit_sha": short_new,
                "reason": _AHMCP15_REASON,
            }
        )
    )
    assert result["ok"] is True, result
    # The stored row should be updated to the expanded canonical form
    assert result["finding"]["commit_sha"] == full_new
    with _get_db_connection() as conn:
        row = conn.execute("SELECT commit_sha FROM review_findings WHERE id = ?", (db_id,)).fetchone()
    assert row["commit_sha"] == full_new


def test_repair_provenance_accepts_full_input_against_stored_abbreviation(
    isolated_handoff: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AHMCP-15-BR-01 corollary: a caller passing the canonical 40-char SHA
    must also be able to repair a row that still carries the historical
    abbreviation. The fix expands the stored SHA best-effort so either side
    can be in either form."""
    short_old = "2c270d01"
    full_old = "2c270d0192de21217ecb0d13d0f42d5ca123779b"
    short_new = "39a23e50"
    full_new = "39a23e503939393939393939393939393939393b"

    def fake_expand(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return value
        if normalized in (short_old, full_old):
            return full_old
        if normalized in (short_new, full_new):
            return full_new
        return value

    monkeypatch.setattr(
        "agent_handoff_mcp.shared_write_context._validate_and_expand_commit_sha",
        fake_expand,
    )

    _parse(mcp_server.set_handoff_state(task_ref="T1", objective="obj", status="in_progress"))
    _seed_finding_with_provenance(
        task_ref="T1",
        finding_id="T1-BR-07",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=short_old,  # row stores the abbreviation
    )

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "task_ref": "T1",
                "finding_id": "T1-BR-07",
                "expected_branch": _AHMCP15_OLD_BRANCH,
                "expected_commit_sha": full_old,  # caller passes the canonical 40-char SHA
                "new_branch": _AHMCP15_NEW_BRANCH,
                "new_commit_sha": full_new,
                "reason": _AHMCP15_REASON,
            }
        )
    )
    assert result["ok"] is True, result


def test_repair_provenance_audit_decision_id_is_canonical(isolated_handoff: dict) -> None:
    """AHMCP-15-BR-02 regression: the audit-trail decision id written by the
    repair op must conform to the canonical decision-id grammar so that
    `audit_decision_ids` does not flag it as freeform.
    """
    from agent_handoff_mcp.slice_decision import classify_decision_id, is_canonical_decision

    _parse(mcp_server.set_handoff_state(task_ref="AHMCP-15", objective="obj", status="in_progress"))
    _seed_finding_with_provenance(
        task_ref="AHMCP-15",
        finding_id="AHMCP-15-BR-99",
        branch=_AHMCP15_OLD_BRANCH,
        commit_sha=_AHMCP15_OLD_SHA,
    )

    result = _parse(
        mcp_server.review_findings(
            review={
                "operation": "repair_provenance",
                "session": "ahmcp-15-test",
                "task_ref": "AHMCP-15",
                "finding_id": "AHMCP-15-BR-99",
                "expected_branch": _AHMCP15_OLD_BRANCH,
                "expected_commit_sha": _AHMCP15_OLD_SHA,
                "new_branch": _AHMCP15_NEW_BRANCH,
                "new_commit_sha": _AHMCP15_NEW_SHA,
                "reason": _AHMCP15_REASON,
            }
        )
    )
    assert result["ok"] is True, result
    audit_id = result["audit_decision_id"]
    assert is_canonical_decision(audit_id), f"audit decision id {audit_id!r} must conform to the canonical grammar"
    assert classify_decision_id(audit_id) == "canonical"

    audit_report = _parse(mcp_server.audit_decision_ids(task_ref="AHMCP-15"))
    counts = audit_report["counts"]
    violations = audit_report["violations"]
    assert counts["freeform"] == 0, f"audit_decision_ids must not see any freeform rows after repair: {audit_report}"
    assert all(v["decision"] != audit_id for v in violations), (
        f"audit row {audit_id!r} should not be flagged as a violation: {violations}"
    )
