from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from agent_handoff_mcp.config import RuntimeConfig

from agent_orchestrator_mcp import api as mcp_server


@pytest.fixture()
def isolated_handoff(tmp_path: Path):
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=tmp_path / ".task-state",
        current_task_path=tmp_path / "CURRENT_TASK.md",
    )
    mcp_server.configure_runtime(runtime)
    return runtime


def _parse(payload: str | dict) -> dict:
    """AHMCP-10 dict-return migration: handler returns are dicts now;
    only fall back to json.loads when something legitimately hands us a
    string (e.g. CLI stdout capture)."""
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


def test_require_clean_slice_fails_without_recent_tests(isolated_handoff: RuntimeConfig) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="review-guide-hardening",
            objective="Test clean slice gate",
            status="in_progress",
        )
    )

    response = _parse(
        mcp_server.plan_cursor(
            operation="upsert",
            plan_item_id="slice-1",
            state="completed",
            summary="Complete slice",
            require_clean_slice=True,
        )
    )

    assert response["ok"] is False
    assert "missing_recent_test" in response["missing_gates"]


def test_require_clean_slice_fails_with_open_high_findings_in_lane(isolated_handoff: RuntimeConfig) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="review-guide-hardening",
            objective="Test clean slice lane scope",
            status="in_progress",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="review",
            finding_id="F-HIGH",
            severity="high",
            file_path="docs/a.md",
            description="Lane finding",
            actor={"lane_id": "docs-guides"},
        )
    )
    _parse(
        mcp_server.record_test_result(
            session="verify",
            command="pytest lane",
            passed=True,
        )
    )

    response = _parse(
        mcp_server.plan_cursor(
            operation="upsert",
            plan_item_id="slice-1",
            state="completed",
            lane_id="docs-guides",
            summary="Complete slice",
            require_clean_slice=True,
        )
    )

    assert response["ok"] is False
    assert "open_high_findings" in response["missing_gates"]
    assert response["gate"]["lane_scope"] == "docs-guides"


def test_require_clean_slice_passes_with_recent_test_and_no_open_high_findings(isolated_handoff: RuntimeConfig) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="review-guide-hardening",
            objective="Test clean slice success",
            status="in_progress",
        )
    )
    created = _parse(
        mcp_server.plan_cursor(
            operation="upsert",
            plan_item_id="slice-1",
            state="dispatched",
            lane_id="docs-guides",
            summary="Dispatch slice",
        )
    )
    assert created["ok"] is True

    time.sleep(1)
    _parse(
        mcp_server.record_test_result(
            session="verify",
            command="pytest lane",
            passed=True,
            actor={"lane_id": "docs-guides"},
        )
    )

    completed = _parse(
        mcp_server.plan_cursor(
            operation="upsert",
            plan_item_id="slice-1",
            state="completed",
            lane_id="docs-guides",
            require_clean_slice=True,
        )
    )

    assert completed["ok"] is True
    assert completed["cursor"]["state"] == "completed"
