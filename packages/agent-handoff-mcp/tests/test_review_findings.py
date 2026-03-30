"""Tests for review findings: global lookup, ambiguity, repo-scope, schema, and renderer."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp.config import RuntimeConfig
from agent_handoff_mcp._shared import _get_db_connection, _render_current_task_md


def _parse(raw: str) -> dict:
    return json.loads(raw)


@pytest.fixture()
def isolated_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
            session="s1", finding_id="DUP-001", severity="low",
            file_path="f.py", description="dup under A", task_ref="task-A",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="s1", finding_id="DUP-001", severity="low",
            file_path="f.py", description="dup under B", task_ref="task-B",
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
    db_id_a = int(_parse(
        mcp_server.record_review_finding(
            session="s1", finding_id="SCOPED-001", severity="low",
            file_path="f.py", description="under A", task_ref="task-A",
        )
    )["finding"]["id"])

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
            session="s1", finding_id="UPD-GLOBAL-001", severity="medium",
            file_path="f.py", description="update global", task_ref="task-A",
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
            session="s1", finding_id="UPD-DUP-001", severity="low",
            file_path="f.py", description="dup A", task_ref="task-X",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="s1", finding_id="UPD-DUP-001", severity="low",
            file_path="f.py", description="dup B", task_ref="task-Y",
        )
    )

    result = _parse(mcp_server.update_review_finding(finding_id="UPD-DUP-001", status="wontfix", resolution_notes="dup"))
    assert result["ok"] is False
    assert "Ambiguous" in result["error"]


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
            session="s1", finding_id="REPO-002", severity="low",
            file_path="docs/plan.md", description="Repo finding",
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
            session="s1", finding_id="REPO-003", severity="low",
            file_path="docs/plan.md", description="Repo finding",
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

    current_task_path = Path(isolated_handoff["current_task_path"])
    md = current_task_path.read_text()
    assert "No active handoff state found." not in md
    assert "E12-test-render" in md
    assert "test_decision_for_render" in md


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

    current_task_path = Path(isolated_handoff["current_task_path"])
    md = current_task_path.read_text()
    assert "No active handoff state found." not in md
    assert "E12-render-findings" in md


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
        _parse(mcp_server.record_review_run(
            review_run_id=f"E12-8-run-{i}",
            session="s",
            subject_path="docs/plan.md",
            task_ref="E12-8",
        ))
    _parse(mcp_server.record_review_run(
        review_run_id="OTHER-run-1",
        session="s",
        subject_path="docs/other.md",
        task_ref="OTHER-TASK",
    ))
    result = _parse(mcp_server.list_review_runs(task_ref="E12-8"))
    assert result["ok"] is True
    assert result["total_matching"] == 3
    assert all(r["task_ref"] == "E12-8" for r in result["runs"])


def test_list_review_runs_filters_by_verdict(isolated_handoff: dict) -> None:
    _parse(mcp_server.record_review_run(
        review_run_id="v-pass", session="s", subject_path="docs/p.md", verdict="pass", task_ref="T-1",
    ))
    _parse(mcp_server.record_review_run(
        review_run_id="v-fail", session="s", subject_path="docs/p.md", verdict="fail", task_ref="T-1",
    ))
    result = _parse(mcp_server.list_review_runs(task_ref="T-1", verdict="pass"))
    assert result["ok"] is True
    assert result["total_matching"] == 1
    assert result["runs"][0]["review_run_id"] == "v-pass"


def test_list_review_runs_filter_by_subject_path(isolated_handoff: dict) -> None:
    _parse(mcp_server.record_review_run(
        review_run_id="sp-1", session="s", subject_path="docs/alpha.md",
    ))
    _parse(mcp_server.record_review_run(
        review_run_id="sp-2", session="s", subject_path="docs/beta.md",
    ))
    result = _parse(mcp_server.list_review_runs(subject_path="docs/alpha.md"))
    assert result["ok"] is True
    assert result["total_matching"] == 1
    assert result["runs"][0]["review_run_id"] == "sp-1"


def test_get_review_coverage_by_task_ref(isolated_handoff: dict) -> None:
    """get_review_coverage returns run_count and finding counts for a task_ref."""
    _parse(mcp_server.record_review_run(
        review_run_id="cov-run-1", session="s", subject_path="docs/e.md",
        verdict="pass_with_findings", task_ref="COV-TASK",
    ))
    _parse(mcp_server.record_review_run(
        review_run_id="cov-run-2", session="s", subject_path="docs/e.md",
        verdict="pass", task_ref="COV-TASK",
    ))
    # Record two open findings linked to the task
    for i in range(2):
        _parse(mcp_server.record_review_finding(
            session="s",
            finding_id=f"COV-F-{i}",
            severity="medium",
            file_path="docs/e.md",
            description=f"finding {i}",
            task_ref="COV-TASK",
        ))
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
    _parse(mcp_server.record_review_run(
        review_run_id="sp-cov-run", session="s",
        subject_path="docs/target.md",
    ))
    result = _parse(mcp_server.get_review_coverage(subject_path="docs/target.md"))
    assert result["ok"] is True
    assert result["run_count"] == 1
    assert result["latest_review_run_id"] == "sp-cov-run"
