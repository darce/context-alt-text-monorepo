"""Tests for lane/state functions relocated from agent-handoff-mcp to agent-orchestrator-mcp in E12-9.

These tests were originally in packages/agent-handoff-mcp/tests/test_handoff_state.py (at HEAD) and
were deleted during E12-9 Slice 1. They are restored here because the tested functions now live in
agent-orchestrator-mcp (lanes, turn_metrics, plan_cursors, switch_task, etc.).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_handoff_mcp import PromptMetrics, TokenUsage
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp.config import RuntimeConfig

from agent_orchestrator_mcp import api as mcp_server
from agent_orchestrator_mcp import lanes as lanes_module


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


def _parse(payload: str | dict) -> dict:
    """AHMCP-10 dict-return migration: handlers return native dicts;
    only fall back to json.loads when something legitimately hands us a
    string (e.g. CLI stdout capture).
    """
    if not isinstance(payload, dict):
        payload = json.loads(payload)
    if isinstance(payload, dict) and payload.get("schema_version") == 2:
        data = payload.get("data")
        scope = payload.get("scope")
        flat = dict(payload)
        if isinstance(data, dict):
            flat.update(data)
        if "task_ref" not in flat and isinstance(scope, dict) and scope.get("task_ref"):
            flat["task_ref"] = scope["task_ref"]
        return flat
    return payload


def _data(payload: str | dict) -> dict:
    parsed = _parse(payload)
    data = parsed.get("data")
    return data if isinstance(data, dict) else parsed


def _manage_worktree_lane(**kwargs: object) -> dict:
    return _parse(mcp_server.manage_worktree_lane(**kwargs))


def _plan_cursor(**kwargs: object) -> dict:
    return _parse(mcp_server.plan_cursor(**kwargs))


def _worker_reports(**kwargs: object) -> dict:
    return _parse(mcp_server.worker_reports(**kwargs))


def _turn_metrics(**kwargs: object) -> dict:
    return _parse(mcp_server.turn_metrics(**kwargs))


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


def test_turn_metrics_round_trip_and_summary(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="turn-metrics-task",
            objective="Track durable turn metrics",
            status="in_progress",
        )
    )

    created = _turn_metrics(
        operation="record",
        task_ref="turn-metrics-task",
        session="worker-backend",
        lane_id="backend",
        cycle=2,
        phase="execution",
        backend="codex-cli",
        model="gpt-5.4",
        token_usage=TokenUsage(
            input_tokens=101,
            output_tokens=29,
            cached_input_tokens=7,
            reasoning_output_tokens=3,
            total_tokens=130,
            usage_source="observed",
        ),
        prompt_metrics=PromptMetrics(
            prompt_tokens=120,
            prompt_chars=480,
            prompt_token_source="char_estimate",
            pressure_level="elevated",
        ),
        attribution={"used_artifact_context": True},
        section_sizes={"assignment": 120, "artifact_context": 60},
        raw_usage={"last": {"input_tokens": 101}},
        actor={"lane_id": "backend"},
    )

    assert created["ok"] is True
    metric = created["turn_metric"]
    assert metric["usage_source"] == "observed"
    assert metric["prompt_token_source"] == "char_estimate"
    assert metric["attribution"]["used_artifact_context"] is True
    assert metric["section_sizes"]["artifact_context"] == 60

    listed = _turn_metrics(operation="list", task_ref="turn-metrics-task", lane_id="backend")
    assert listed["ok"] is True
    assert listed["returned"] == 1
    assert listed["turn_metrics"][0]["total_tokens"] == 130

    summary = _turn_metrics(operation="summary", task_ref="turn-metrics-task", lane_id="backend")
    assert summary["ok"] is True
    assert summary["summary"]["usage_source_counts"]["observed"] == 1
    assert summary["summary"]["prompt_token_source_counts"]["char_estimate"] == 1
    assert summary["summary"]["pressure_level_counts"]["elevated"] == 1
    assert summary["summary"]["preflight_observed_drift"]["comparable_turns"] == 1
    assert summary["summary"]["preflight_observed_drift"]["net_token_drift"] == -19


def test_list_turn_metrics_applies_offset_without_dropping_rows(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="turn-metrics-pagination",
            objective="List paginated turn metrics",
            status="in_progress",
        )
    )

    for cycle in range(3):
        created = _turn_metrics(
            operation="record",
            task_ref="turn-metrics-pagination",
            session="worker-backend",
            lane_id="backend",
            cycle=cycle,
            phase="execution",
            backend="codex-cli",
            model="gpt-5.4",
            token_usage=TokenUsage(
                total_tokens=100 + cycle,
                usage_source="observed",
            ),
            prompt_metrics=PromptMetrics(
                prompt_tokens=90 + cycle,
                prompt_chars=360 + cycle,
                prompt_token_source="observed",
                pressure_level="normal",
            ),
        )
        assert created["ok"] is True

    listed = _turn_metrics(
        operation="list",
        task_ref="turn-metrics-pagination",
        lane_id="backend",
        limit=1,
        offset=1,
    )

    assert listed["ok"] is True
    assert listed["returned"] == 1
    assert listed["has_more"] is True
    assert listed["turn_metrics"][0]["cycle"] == 1


def test_list_turn_metrics_supports_bounded_read_parameters(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="turn-metrics-bounded",
            objective="Shape turn metric reads",
            status="in_progress",
        )
    )
    for cycle in range(2):
        created = _turn_metrics(
            operation="record",
            task_ref="turn-metrics-bounded",
            session="worker-backend",
            lane_id="backend",
            cycle=cycle,
            phase="execution",
            backend="codex-cli",
            model="gpt-5.4",
            token_usage=TokenUsage(total_tokens=100 + cycle, usage_source="observed"),
            prompt_metrics=PromptMetrics(prompt_tokens=90 + cycle, prompt_chars=360 + cycle, prompt_token_source="observed"),
            raw_usage={"cycle": cycle, "tokens": 100 + cycle},
        )
        assert created["ok"] is True

    full = _turn_metrics(operation="list", task_ref="turn-metrics-bounded", lane_id="backend")
    shaped = _turn_metrics(
        operation="list",
        task_ref="turn-metrics-bounded",
        lane_id="backend",
        sections="turn_metrics",
        detail="summary",
        fields="id,total_tokens",
        top_n_turn_metrics=1,
    )

    assert full["returned"] == 2
    assert set(shaped) == {"ok", "turn_metrics"}
    assert shaped["turn_metrics"] == [{"id": full["turn_metrics"][0]["id"], "total_tokens": full["turn_metrics"][0]["total_tokens"]}]
    assert len(json.dumps(shaped)) < len(json.dumps(full))




def test_plan_cursor_crud_round_trip(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="daemon-5-task-plan-driven-orchestrator",
            objective="Drive work from a task plan",
            status="in_progress",
        )
    )

    created = _plan_cursor(
        operation="upsert",
        task_ref="daemon-5-task-plan-driven-orchestrator",
        plan_item_id="phase-1::phase-1-backend::checklist_1",
        state="dispatched",
        lane_id="backend-domain",
        summary="Implement backend slice",
        source_heading="Phase 1: Backend",
    )
    assert created["ok"] is True
    assert created["cursor"]["dispatch_count"] == 1

    fetched = _plan_cursor(
        operation="get",
        task_ref="daemon-5-task-plan-driven-orchestrator",
        plan_item_id="phase-1::phase-1-backend::checklist_1",
    )
    assert fetched["cursor"]["state"] == "dispatched"

    updated = _plan_cursor(
        operation="upsert",
        task_ref="daemon-5-task-plan-driven-orchestrator",
        plan_item_id="phase-1::phase-1-backend::checklist_1",
        state="completed",
        lane_id="backend-domain",
        summary="Implement backend slice",
    )
    assert updated["cursor"]["state"] == "completed"
    assert updated["cursor"]["completed_at"] is not None

    listed = _plan_cursor(
        operation="list",
        task_ref="daemon-5-task-plan-driven-orchestrator",
        state="completed",
    )
    assert listed["returned"] == 1


def test_list_plan_cursors_supports_bounded_read_parameters(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="plan-cursor-bounded",
            objective="Shape plan cursor reads",
            status="in_progress",
        )
    )
    for plan_item_id in ("phase-1::a", "phase-1::b"):
        created = _plan_cursor(
            operation="upsert",
            task_ref="plan-cursor-bounded",
            plan_item_id=plan_item_id,
            state="dispatched",
            lane_id="backend-domain",
            summary=f"Dispatch {plan_item_id}",
        )
        assert created["ok"] is True

    full = _plan_cursor(operation="list", task_ref="plan-cursor-bounded", state="dispatched")
    shaped = _plan_cursor(
        operation="list",
        task_ref="plan-cursor-bounded",
        state="dispatched",
        sections="cursors",
        fields="plan_item_id,state",
        top_n_cursors=1,
    )

    assert full["returned"] == 2
    assert set(shaped) == {"ok", "cursors"}
    assert shaped["cursors"] == [
        {"plan_item_id": full["cursors"][0]["plan_item_id"], "state": full["cursors"][0]["state"]}
    ]
    assert len(json.dumps(shaped)) < len(json.dumps(full))


def test_get_latest_slice_review_packet_returns_branch_packet(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="slice-review-packet",
            objective="Test latest slice review packet lookup",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.manage_worktree_lane(
            operation="upsert",
            task_ref="slice-review-packet",
            lane_id="backend-domain",
            worktree_path="/tmp/backend-domain",
            branch="tooling/review-hardening",
            status="active",
        )
    )
    _parse(
        mcp_server.plan_cursor(
            operation="upsert",
            task_ref="slice-review-packet",
            plan_item_id="slice-1",
            lane_id="backend-domain",
            state="completed",
            summary="Backend slice complete",
        )
    )
    _parse(
        mcp_server.worker_reports(
            operation="record",
            task_ref="slice-review-packet",
            lane_id="backend-domain",
            session="slice-1",
            summary="Implemented backend slice",
            changed_files=[
                "packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py",
                "docs/agentic/contracts/agent-handoff-mcp.md",
            ],
            test_commands=["pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q"],
            merge_ready=True,
        )
    )
    _parse(
        mcp_server.record_decision(
            session="slice-1",
            decision="cdx_slice_complete_packet_packet_lookup",
            rationale="## Changes\n- Added packet lookup.\n\n## Verification\n- pytest.\n\n## Schema / Contract Changes\n- Contract updated.\n\n## Open Threads\n- none.",
            actor={"lane_id": "backend-domain"},
        )
    )

    payload = _parse(mcp_server.get_latest_slice_review_packet(task_ref="slice-review-packet"))

    assert payload["ok"] is True
    assert payload["packet"]["slice_label"] == "packet_packet_lookup"
    assert payload["packet"]["review_kind"] == "branch"
    assert payload["packet"]["scope_source"] == "slice_packet"
    assert payload["packet"]["plan_item_id"] == "slice-1"
    assert payload["packet"]["contract_files"] == ["docs/agentic/contracts/agent-handoff-mcp.md"]
    assert "packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py" in payload["packet"]["changed_files"]


def test_get_latest_slice_review_packet_filters_to_planning_slices(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="slice-review-packet-planning",
            objective="Test planning slice packet lookup",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.manage_worktree_lane(
            operation="upsert",
            task_ref="slice-review-packet-planning",
            lane_id="docs-lane",
            worktree_path="/tmp/docs-lane",
            branch="tooling/review-hardening",
            status="active",
        )
    )
    _parse(
        mcp_server.worker_reports(
            operation="record",
            task_ref="slice-review-packet-planning",
            lane_id="docs-lane",
            session="slice-docs",
            summary="Updated planning docs",
            changed_files=[
                "docs/tasks/12.0/slice-review-packet-and-cross-agent-review-task-plan.md",
                "docs/agentic/rules/planning-review-guide.md",
            ],
            test_commands=["rg -n \"slice review packet\" docs/agentic/rules/planning-review-guide.md"],
            merge_ready=True,
        )
    )
    _parse(
        mcp_server.record_decision(
            session="slice-docs",
            decision="cdx_slice_complete_docs_docs_packet",
            rationale="## Changes\n- Updated docs.\n\n## Verification\n- rg.\n\n## Schema / Contract Changes\n- none.\n\n## Open Threads\n- none.",
            actor={"lane_id": "docs-lane"},
        )
    )

    planning_payload = _parse(
        mcp_server.get_latest_slice_review_packet(
            task_ref="slice-review-packet-planning",
            review_kind="planning",
        )
    )

    assert planning_payload["ok"] is True
    assert planning_payload["packet"]["review_kind"] == "planning"
    assert planning_payload["packet"]["review_guide_path"].endswith("planning-review-guide.md")


def test_get_latest_slice_review_packet_returns_error_when_no_matching_slice_exists(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="slice-review-packet-empty",
            objective="No slice packet yet",
            status="in_progress",
        )
    )

    payload = _parse(mcp_server.get_latest_slice_review_packet(task_ref="slice-review-packet-empty"))

    assert payload["ok"] is False
    assert payload["error"] == "No matching slice review packet found."


def test_get_latest_slice_review_packet_uses_decision_rationale_when_worker_report_missing(
    isolated_handoff: dict,
) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="slice-review-rationale-fallback",
            objective="Use structured slice decisions as packet fallback",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_decision(
            session="slice-rationale",
            decision="cdx_slice_complete_fallback_rationale_fallback",
            rationale=(
                "## Changes\n"
                "- packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_runner.py: run_review ; packet-backed dispatch.\n"
                "- docs/agentic/rules/branch-review-guide.md: latest-slice review intake ; guidance update.\n"
                "\n## Verification\n"
                "- pytest packages/agent-handoff-mcp/tests/test_review_runner.py -q: passed.\n"
                "\n## Schema / Contract Changes\n"
                "- docs/agentic/contracts/agent-handoff-mcp.md: latest slice packet query documented.\n"
                "\n## Open Threads\n"
                "- none.\n"
            ),
            actor={"lane_id": "backend-domain"},
        )
    )

    payload = _parse(
        mcp_server.get_latest_slice_review_packet(task_ref="slice-review-rationale-fallback")
    )

    assert payload["ok"] is True
    assert payload["packet"]["scope_source"] == "slice_packet"
    assert payload["packet"]["review_kind"] == "branch"
    assert payload["packet"]["changed_files"] == [
        "packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_runner.py",
        "docs/agentic/rules/branch-review-guide.md",
    ]




def test_get_latest_slice_review_packet_prefers_decision_changed_files_over_rationale(
    isolated_handoff: dict,
) -> None:
    """changed_files_json on the decision row takes precedence over rationale parsing."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="slice-review-decision-files",
            objective="Test decision-row changed_files precedence",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_decision(
            session="slice-decision-files",
            decision="cdx_slice_complete_decision_files_test",
            rationale=(
                "## Changes\n"
                "- docs/wrong-file-from-rationale.md: should not appear.\n"
                "\n## Verification\n- ok\n"
                "\n## Schema / Contract Changes\n- none\n"
                "\n## Open Threads\n- none\n"
            ),
            changed_files=[
                "packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py",
                "docs/agentic/contracts/agent-handoff-mcp.md",
            ],
        )
    )

    payload = _parse(
        mcp_server.get_latest_slice_review_packet(task_ref="slice-review-decision-files")
    )

    assert payload["ok"] is True
    assert payload["packet"]["scope_source"] == "slice_packet"
    assert payload["packet"]["changed_files"] == [
        "packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py",
        "docs/agentic/contracts/agent-handoff-mcp.md",
    ]
    assert payload["packet"]["contract_files"] == [
        "docs/agentic/contracts/agent-handoff-mcp.md",
    ]


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
        mcp_server.manage_worktree_lane(
            operation="upsert",
            lane_id="frontend",
            worktree_path=str(frontend_root),
            branch="codex/p5-frontend",
            status="active",
        )
    )
    _parse(
        mcp_server.manage_worktree_lane(
            operation="upsert",
            lane_id="backend-http",
            worktree_path=str(backend_root),
            branch="codex/p5-backend-http",
            status="active",
        )
    )
    _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="record",
            lane_id="frontend",
            session="dispatch-frontend",
            direction="orchestrator_to_worker",
            subject="Frontend dispatch",
            message="Frontend lane should see this open dispatch.",
        )
    )
    _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="record",
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

    worker_state = _data(mcp_server.get_handoff_state())
    assert worker_state["current_lane"]["lane_id"] == "frontend"
    assert [message["lane_id"] for message in worker_state["lane_messages_open"]] == ["frontend"]
    assert worker_state["lane_messages_open"][0]["subject"] == "Frontend dispatch"

    worker_messages = _parse(mcp_server.lane_communication(kind="message", operation="list", status="open"))
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
    orchestrator_state = _data(mcp_server.get_handoff_state())
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
        mcp_server.manage_worktree_lane(
            operation="upsert",
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
        mcp_server.worker_reports(
            operation="record",
            lane_id="backend-http",
            session="s1",
            summary="lane summary",
            changed_files=["apps/prototype-description-service/foo.py"],
            test_commands=["pytest -q"],
            merge_ready=True,
        )
    )
    _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="record",
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

    state = _data(mcp_server.get_handoff_state(task_ref="4.12.0", verbose=True))
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
        mcp_server.manage_worktree_lane(
            operation="upsert",
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
        mcp_server.worker_reports(
            operation="record",
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
        mcp_server.lane_communication(
            kind="message",
            operation="record",
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

    listed_reports = _worker_reports(operation="list", lane_id="frontend")
    assert listed_reports["total_matching"] == 1
    assert listed_reports["reports"][0]["lane_id"] == "frontend"

    listed_messages = _parse(mcp_server.lane_communication(kind="message", operation="list", lane_id="frontend"))
    assert listed_messages["total_matching"] == 1
    updated_message = _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="update",
            message_id=listed_messages["messages"][0]["id"],
            status="acknowledged",
        )
    )
    assert updated_message["message"]["status"] == "acknowledged"


def test_list_worker_reports_supports_bounded_read_parameters(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="worker-reports-bounded",
            objective="Shape worker report reads",
            status="in_progress",
        )
    )
    _manage_worktree_lane(
        operation="upsert",
        lane_id="frontend",
        worktree_path="/tmp/frontend",
        branch="codex/p5-frontend",
        status="active",
        task_ref="worker-reports-bounded",
    )
    for session in ("lane-1", "lane-2"):
        recorded = _worker_reports(
            operation="record",
            task_ref="worker-reports-bounded",
            lane_id="frontend",
            session=session,
            summary=f"Summary for {session}",
            changed_files=["apps/prototype-description-service/app.py", "docs/notes.md"],
            test_commands=["pytest -q"],
            blockers=["none"],
        )
        assert recorded["ok"] is True

    full = _worker_reports(operation="list", task_ref="worker-reports-bounded", lane_id="frontend")
    shaped = _worker_reports(
        operation="list",
        task_ref="worker-reports-bounded",
        lane_id="frontend",
        sections="reports",
        fields="id,summary,merge_ready",
        top_n_reports=1,
    )

    assert full["returned"] == 2
    assert set(shaped) == {"ok", "reports"}
    assert shaped["reports"] == [
        {
            "id": full["reports"][0]["id"],
            "summary": full["reports"][0]["summary"],
            "merge_ready": full["reports"][0]["merge_ready"],
        }
    ]
    assert len(json.dumps(shaped)) < len(json.dumps(full))


def test_list_lane_messages_supports_bounded_read_parameters(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="lane-messages-bounded",
            objective="Shape lane message reads",
            status="in_progress",
        )
    )
    _manage_worktree_lane(
        operation="upsert",
        lane_id="frontend",
        worktree_path="/tmp/frontend",
        branch="codex/p5-frontend",
        status="active",
        task_ref="lane-messages-bounded",
    )
    for idx in range(2):
        recorded = _parse(
            mcp_server.lane_communication(
                kind="message",
                operation="record",
                task_ref="lane-messages-bounded",
                lane_id="frontend",
                session=f"lane-{idx}",
                direction="worker_to_orchestrator",
                subject=f"Need guidance {idx}",
                message=f"Detailed worker guidance body {idx}",
            )
        )
        assert recorded["ok"] is True

    full = _parse(
        mcp_server.lane_communication(kind="message", operation="list", task_ref="lane-messages-bounded", lane_id="frontend")
    )
    shaped = _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="list",
            task_ref="lane-messages-bounded",
            lane_id="frontend",
            sections="messages",
            fields="id,subject,status",
            top_n_messages=1,
        )
    )

    assert full["returned"] == 2
    assert set(shaped) == {"ok", "messages"}
    assert shaped["messages"] == [
        {"id": full["messages"][0]["id"], "subject": full["messages"][0]["subject"], "status": full["messages"][0]["status"]}
    ]
    assert len(json.dumps(shaped)) < len(json.dumps(full))


def test_list_lane_messages_escapes_subject_prefix_wildcards(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="lane-messages-like-escape",
            objective="Escape subject prefix wildcards",
            status="in_progress",
        )
    )
    _manage_worktree_lane(
        operation="upsert",
        task_ref="lane-messages-like-escape",
        lane_id="frontend",
        worktree_path="/tmp/frontend",
        branch="codex/p5-frontend",
        status="active",
    )
    for subject in ("brief:_literal", "brief:xliteral"):
        recorded = _parse(
            mcp_server.lane_communication(
                kind="message",
                operation="record",
                task_ref="lane-messages-like-escape",
                lane_id="frontend",
                session=subject,
                direction="orchestrator_to_worker",
                subject=subject,
                message="body",
            )
        )
        assert recorded["ok"] is True

    listed = _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="list",
            task_ref="lane-messages-like-escape",
            lane_id="frontend",
            subject_prefix="brief:_",
        )
    )
    assert [row["subject"] for row in listed["messages"]] == ["brief:_literal"]


def test_list_lane_messages_rejects_unknown_sections(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="lane-messages-invalid-sections",
            objective="Reject invalid message sections",
            status="in_progress",
        )
    )
    payload = _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="list",
            task_ref="lane-messages-invalid-sections",
            sections="not-a-real-section",
        )
    )
    assert payload["ok"] is False
    assert "Invalid sections" in payload["error"]


def test_get_lane_activity_supports_bounded_read_parameters(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="lane-activity-bounded",
            objective="Shape lane activity reads",
            status="in_progress",
        )
    )
    _manage_worktree_lane(
        operation="upsert",
        lane_id="frontend",
        worktree_path="/tmp/frontend",
        branch="codex/p5-frontend",
        status="active",
        task_ref="lane-activity-bounded",
    )
    _worker_reports(
        operation="record",
        task_ref="lane-activity-bounded",
        lane_id="frontend",
        session="lane",
        summary="Frontend report summary",
        changed_files=["apps/prototype-description-service/app.py"],
    )
    _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="record",
            task_ref="lane-activity-bounded",
            lane_id="frontend",
            session="lane",
            direction="worker_to_orchestrator",
            subject="Need guidance",
            message="Detailed guidance body",
        )
    )

    full = _parse(mcp_server.get_lane_activity(task_ref="lane-activity-bounded", lane_id="frontend"))
    shaped = _parse(
        mcp_server.get_lane_activity(
            task_ref="lane-activity-bounded",
            lane_id="frontend",
            sections="messages,reports",
            detail="summary",
            fields="id,summary,status",
            top_n_messages=1,
            top_n_reports=1,
        )
    )

    assert "lane" not in shaped
    assert set(shaped) == {"ok", "task_ref", "format", "messages", "reports"}
    assert len(shaped["messages"]) == 1
    assert len(shaped["reports"]) == 1
    assert set(shaped["messages"][0]) == {"id", "status"}
    assert set(shaped["reports"][0]) == {"id", "summary", "status"}
    assert len(json.dumps(shaped)) < len(json.dumps(full))


def test_get_lane_activity_only_fetches_requested_sections(
    isolated_handoff: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="lane-activity-lazy-fetch",
            objective="Fetch only requested sections",
            status="in_progress",
        )
    )
    _manage_worktree_lane(
        operation="upsert",
        task_ref="lane-activity-lazy-fetch",
        lane_id="frontend",
        worktree_path="/tmp/frontend",
        branch="codex/p5-frontend",
        status="active",
    )

    fetched_tables: list[str] = []

    def fake_fetch_handoff_rows(conn, *, table, where_sql, order_sql, limit, params):
        fetched_tables.append(table)
        return []

    monkeypatch.setattr(lanes_module, "_fetch_handoff_rows", fake_fetch_handoff_rows)
    payload = _parse(
        mcp_server.get_lane_activity(
            task_ref="lane-activity-lazy-fetch",
            lane_id="frontend",
            sections="messages",
        )
    )

    assert payload["ok"] is True
    assert fetched_tables == ["lane_messages"]


def test_lane_briefs_round_trip_with_structured_payload(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="5.1.0",
            objective="Lane briefs",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.manage_worktree_lane(
            operation="upsert",
            lane_id="frontend",
            worktree_path="/tmp/frontend",
            branch="codex/p5-frontend",
            status="active",
        )
    )

    brief = _parse(
        mcp_server.lane_communication(
            kind="brief",
            operation="record",
            task_ref="5.1.0",
            lane_id="frontend",
            session="briefs",
            source_lane="backend-domain",
            reason="api-contract-changed",
            summary="Export response now includes purge eligibility metadata.",
            required_actions=["Update the client contract.", "Refresh the status copy."],
            artifacts=["apps/prototype-description-service/export_service.py"],
        )
    )
    assert brief["ok"] is True
    assert brief["message"]["subject"] == "brief:api-contract-changed"
    assert brief["message"]["payload"]["source_lane"] == "backend-domain"

    listed = _parse(mcp_server.lane_communication(kind="brief", operation="list", task_ref="5.1.0", lane_id="frontend"))
    assert listed["ok"] is True
    assert listed["total_matching"] == 1
    assert listed["briefs"][0]["payload"]["required_actions"] == [
        "Update the client contract.",
        "Refresh the status copy.",
    ]

    activity = _parse(mcp_server.get_lane_activity(task_ref="5.1.0", lane_id="frontend"))
    assert activity["messages"][0]["payload"]["summary"] == "Export response now includes purge eligibility metadata."


def test_get_lane_activity_archival_format_returns_compact_summary(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="5.2.0",
            objective="Archival lane summary",
            status="in_progress",
        )
    )
    actor = {"agent": "codex", "branch": "codex/p5-backend", "commit_sha": "abc123", "lane_id": "backend"}
    _parse(
        mcp_server.manage_worktree_lane(
            operation="upsert",
            task_ref="5.2.0",
            lane_id="backend",
            worktree_path="/tmp/backend",
            branch="codex/p5-backend",
            status="active",
        )
    )
    _parse(
        mcp_server.record_decision(
            session="archival",
            decision="sync_contract_updated",
            rationale="Updated the retention contract to include explicit archival retention semantics.",
            actor=actor,
        )
    )
    _parse(
        mcp_server.record_test_result(
            session="archival",
            command="pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q",
            passed=True,
            actor=actor,
        )
    )
    _parse(
        mcp_server.record_test_result(
            session="archival",
            command="pytest packages/agent-handoff-mcp/tests/test_review_ready.py -q",
            passed=False,
            exit_code=1,
            actor=actor,
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="archival",
            finding_id="ARCH-1",
            severity="high",
            file_path="docs/agentic/contracts/agent-handoff-mcp.md",
            description="Retention rules need the age-based purge threshold.",
            actor=actor,
            task_ref="5.2.0",
        )
    )
    _parse(
        mcp_server.update_review_finding(
            task_ref="5.2.0",
            finding_id="ARCH-1",
            status="fixed",
            session="archival",
            actor=actor,
            verification_evidence="Retention section now includes older_than_days guidance.",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="archival",
            finding_id="ARCH-2",
            severity="medium",
            file_path="packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py",
            description="Archival summary needs multi-lane isolation coverage.",
            actor=actor,
            task_ref="5.2.0",
        )
    )
    _parse(
        mcp_server.worker_reports(
            operation="record",
            task_ref="5.2.0",
            lane_id="backend",
            session="archival",
            summary="Backend archival summary is ready for review.",
            changed_files=["packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py"],
            merge_ready=True,
            actor=actor,
        )
    )
    _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="record",
            task_ref="5.2.0",
            lane_id="backend",
            session="archival",
            direction="worker_to_orchestrator",
            message="Archival summary is ready.",
            status="acknowledged",
            actor=actor,
        )
    )

    activity = _parse(
        mcp_server.get_lane_activity(task_ref="5.2.0", lane_id="backend", format="archival")
    )

    assert activity["ok"] is True
    assert activity["format"] == "archival"
    assert "decisions" not in activity
    assert activity["summary"]["decisions"]["count"] == 1
    assert activity["summary"]["findings"]["counts_by_status"] == {
        "deferred": 0,
        "fixed": 1,
        "open": 1,
        "wontfix": 0,
    }
    assert activity["summary"]["reports"] == {
        "count": 1,
        "latest_merge_ready": True,
    }
    assert activity["summary"]["messages"]["counts_by_direction"] == {
        "orchestrator_to_worker": 0,
        "worker_to_orchestrator": 1,
    }
    assert activity["summary"]["messages"]["counts_by_status"] == {
        "acknowledged": 1,
        "closed": 0,
        "open": 0,
    }
    assert activity["summary"]["tests"] == {
        "total": 2,
        "passed": 1,
        "pass_rate": 0.5,
    }
    assert "retention contract" in activity["summary"]["decisions"]["latest_rationale_excerpt"]




def test_get_lane_activity_archival_format_truncates_long_decision_rationale(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="5.2.3",
            objective="Archival truncation",
            status="in_progress",
        )
    )
    actor = {"agent": "codex", "branch": "codex/p5-backend", "commit_sha": "def456", "lane_id": "backend"}
    _parse(
        mcp_server.manage_worktree_lane(
            operation="upsert",
            task_ref="5.2.3",
            lane_id="backend",
            worktree_path="/tmp/backend-truncation",
            branch="codex/p5-backend",
            status="active",
        )
    )
    long_rationale = " ".join(["retention-proof"] * 40)
    assert len(long_rationale) > 240
    _parse(
        mcp_server.record_decision(
            session="archival",
            decision="long_rationale_recorded",
            rationale=long_rationale,
            actor=actor,
        )
    )

    activity = _parse(
        mcp_server.get_lane_activity(task_ref="5.2.3", lane_id="backend", format="archival")
    )

    excerpt = activity["summary"]["decisions"]["latest_rationale_excerpt"]
    assert excerpt is not None
    assert excerpt.endswith("...")
    assert len(excerpt) <= 240


def test_get_lane_activity_archival_format_handles_empty_lane() -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="5.2.1",
            objective="Empty archival lane",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.manage_worktree_lane(
            operation="upsert",
            task_ref="5.2.1",
            lane_id="frontend",
            worktree_path="/tmp/frontend",
            branch="codex/p5-frontend",
            status="planned",
        )
    )

    activity = _parse(
        mcp_server.get_lane_activity(task_ref="5.2.1", lane_id="frontend", format="archival")
    )

    assert activity["ok"] is True
    assert activity["summary"]["decisions"] == {
        "count": 0,
        "latest_rationale_excerpt": None,
    }
    assert activity["summary"]["reports"] == {
        "count": 0,
        "latest_merge_ready": None,
    }
    assert activity["summary"]["tests"] == {
        "total": 0,
        "passed": 0,
        "pass_rate": None,
    }


def test_get_lane_activity_rejects_unknown_format(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="5.2.2",
            objective="Bad archival format",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.manage_worktree_lane(
            operation="upsert",
            task_ref="5.2.2",
            lane_id="backend",
            worktree_path="/tmp/backend",
            branch="codex/p5-backend",
            status="active",
        )
    )

    activity = _parse(
        mcp_server.get_lane_activity(task_ref="5.2.2", lane_id="backend", format="compact")
    )

    assert activity["ok"] is False
    assert activity["error"] == "Invalid format. Valid: archival, full."


def test_import_handoff_state_prefers_decoded_lane_message_payload(isolated_handoff: dict) -> None:
    payload_path = isolated_handoff["state_dir"] / "exports" / "payload-precedence.json"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(
        json.dumps(
            {
                "task_ref": "5.1.1",
                "snapshot": {
                    "active": {
                        "task_ref": "5.1.1",
                        "objective": "payload precedence",
                        "status": "in_progress",
                    },
                    "blockers": [],
                    "next_actions": [],
                    "decisions": [],
                    "verified_tests": [],
                    "review_findings": [],
                    "worktree_lanes": [
                        {
                            "lane_id": "frontend",
                            "worktree_path": "/tmp/frontend",
                            "branch": "codex/p5-frontend",
                            "status": "active",
                        }
                    ],
                    "worker_reports": [],
                    "lane_messages": [
                        {
                            "lane_id": "frontend",
                            "session": "import",
                            "direction": "orchestrator_to_worker",
                            "subject": "brief:api-contract-changed",
                            "message": "old payload_json should not win",
                            "status": "open",
                            "payload_json": json.dumps({"source_lane": "backend-domain", "summary": "stale"}),
                            "payload": {"source_lane": "backend-domain", "summary": "fresh"},
                        }
                    ],
                    "plan_cursors": [],
                },
            }
        )
    )

    response = _parse(
        mcp_server.import_handoff_state(
            input_path=str(payload_path),
            mode="merge",
            set_active=True,
        )
    )
    assert response["ok"] is True

    listed = _parse(
        mcp_server.lane_communication(kind="brief", operation="list", task_ref="5.1.1", lane_id="frontend")
    )
    assert listed["briefs"][0]["payload"]["summary"] == "fresh"




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

    listed_response = _parse(mcp_server.list_review_findings())
    listed = _data(listed_response)
    assert listed_response["ok"] is True
    assert listed["workspace_git"]["branch"] == "feature/review"
    assert listed["workspace_git"]["commit_sha"] == "def456"
    assert listed["findings"][0]["workspace_commit_relation"] == "descendant"
    assert listed["findings"][0]["workspace_branch_matches"] is True

    summary = _parse(mcp_server.get_review_findings_summary())
    assert summary["ok"] is True
    assert summary["workspace_git"]["commit_sha"] == "def456"
    assert summary["open_top"][0]["workspace_commit_relation"] == "descendant"




def test_lane_reports_and_messages_accept_explicit_task_ref_cross_task(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="phase-5-a",
            objective="Task A",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.manage_worktree_lane(
            operation="upsert",
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
        mcp_server.worker_reports(
            operation="record",
            lane_id="backend-domain",
            session="cross-task",
            summary="hidden",
        )
    )
    assert hidden_report["ok"] is False

    explicit_report = _parse(
        mcp_server.worker_reports(
            operation="record",
            task_ref="phase-5-a",
            lane_id="backend-domain",
            session="cross-task",
            summary="reported to original task",
        )
    )
    assert explicit_report["ok"] is True
    assert explicit_report["report"]["task_ref"] == "phase-5-a"

    hidden_message = _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="record",
            lane_id="backend-domain",
            session="cross-task",
            direction="worker_to_orchestrator",
            message="hidden",
        )
    )
    assert hidden_message["ok"] is False

    explicit_message = _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="record",
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
        mcp_server.lane_communication(
            kind="message",
            operation="update",
            message_id=explicit_message["message"]["id"],
            status="acknowledged",
        )
    )
    assert hidden_update["ok"] is False

    explicit_update = _parse(
        mcp_server.lane_communication(
            kind="message",
            operation="update",
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
        mcp_server.manage_worktree_lane(
            operation="upsert",
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
    open_finding = _data(
        mcp_server.record_review_finding(
            session="s-summary",
            finding_id="H-2",
            severity="high",
            file_path="scripts/mcp/unified_server.py",
            description="Open finding",
        )
    )
    fixed_finding = _data(
        mcp_server.record_review_finding(
            session="s-summary",
            finding_id="M-3",
            severity="medium",
            file_path="scripts/mcp/unified_server.py",
            description="Will be fixed",
        )
    )
    deferred_finding = _data(
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




def test_switch_task_clears_focus_on_restore(isolated_handoff: dict) -> None:
    """Switching away and back clears focus unless explicitly provided."""
    _parse(
        mcp_server.set_handoff_state(
            task_ref="sw-focus-a",
            objective="Task A",
            status="in_progress",
            focus="deep in slice 2",
        )
    )
    # Create second task and switch to it
    _parse(
        mcp_server.switch_task(
            task_ref="sw-focus-b",
            objective="Task B",
            status="in_progress",
        )
    )
    # Switch back to A; focus should be cleared (restored from archive without focus)
    result_response = _parse(
        mcp_server.switch_task(task_ref="sw-focus-a")
    )
    result = _data(result_response)
    assert result_response["ok"] is True
    assert result["active"].get("focus") is None

    # Now switch with explicit focus
    _parse(mcp_server.switch_task(task_ref="sw-focus-b"))
    result2_response = _parse(
        mcp_server.switch_task(task_ref="sw-focus-a", focus="resuming slice 3")
    )
    result2 = _data(result2_response)
    assert result2_response["ok"] is True
    assert result2["active"]["focus"] == "resuming slice 3"


def test_switch_task_regenerates_current_task_with_dashboard(isolated_handoff: dict) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="sw-dashboard-a",
            objective="Task A dashboard state",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            task_ref="sw-dashboard-other",
            session="sw-dash-find",
            finding_id="SW-DASH-01",
            severity="medium",
            file_path="docs/switch.md",
            description="Cross-task context survives switch_task regeneration",
        )
    )

    result_response = _parse(
        mcp_server.switch_task(
            task_ref="sw-dashboard-b",
            objective="Task B dashboard state",
            status="in_progress",
        )
    )

    result = _data(result_response)
    assert result_response["ok"] is True
    assert result["current_task_md_regen"] == "ok"

    # After AHMCP-23: "## All Tasks" lives in DASHBOARD.md, not CURRENT_TASK.md.
    # Generate DASHBOARD.md and assert the cross-task sections are there.
    dash_result = mcp_server.generate_dashboard_md(write_file=False)
    assert dash_result["ok"] is True
    md = dash_result["markdown"]
    assert "ALL TASKS" in md
    _assert_dashboard_row(
        md,
        "sw-dashboard-b",
        status="in_progress",
        open_findings=0,
        open_blockers=0,
        pending_actions=0,
        active=True,
    )
    _assert_dashboard_row(
        md,
        "sw-dashboard-a",
        status="in_progress",
        open_findings=0,
        open_blockers=0,
        pending_actions=0,
        active=False,
    )
    _assert_dashboard_row(
        md,
        "sw-dashboard-other",
        status="active",
        open_findings=1,
        open_blockers=0,
        pending_actions=0,
        active=False,
    )


# ---------------------------------------------------------------------------
# Decision grammar helpers tests
# ---------------------------------------------------------------------------
