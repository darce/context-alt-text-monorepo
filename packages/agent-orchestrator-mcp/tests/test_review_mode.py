from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp.config import RuntimeConfig


@pytest.fixture()
def isolated_handoff(tmp_path: Path):
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=tmp_path / ".task-state",
        current_task_path=tmp_path / "CURRENT_TASK.json",
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


def _data(payload: str | dict) -> dict:
    parsed = _parse(payload)
    data = parsed.get("data")
    return data if isinstance(data, dict) else parsed


def test_record_and_filter_review_findings_by_review_mode(isolated_handoff: RuntimeConfig) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="review-guide-hardening",
            objective="Test review mode filters",
            status="review",
        )
    )

    _parse(
        mcp_server.record_review_finding(
            session="review",
            finding_id="F-BRANCH",
            severity="medium",
            file_path="docs/a.md",
            description="Default branch finding",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="review",
            finding_id="F-EXPLICIT-BRANCH",
            severity="low",
            file_path="docs/c.md",
            description="Explicit branch finding",
            review_mode="branch",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="review",
            finding_id="F-AUDIT",
            severity="high",
            file_path="docs/b.md",
            description="Release audit finding",
            review_mode="release_audit",
        )
    )

    branch_only = _data(mcp_server.list_review_findings(review_mode="branch"))
    audit_only = _data(mcp_server.list_review_findings(review_mode="release_audit"))
    unfiltered = _data(mcp_server.list_review_findings())

    assert {finding["finding_id"] for finding in branch_only["findings"]} == {"F-BRANCH", "F-EXPLICIT-BRANCH"}
    assert {finding["finding_id"] for finding in audit_only["findings"]} == {"F-AUDIT"}
    assert {finding["finding_id"] for finding in unfiltered["findings"]} == {"F-BRANCH", "F-EXPLICIT-BRANCH", "F-AUDIT"}


def test_rerecord_preserves_existing_review_mode_when_omitted(isolated_handoff: RuntimeConfig) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="review-guide-hardening",
            objective="Test review mode preservation",
            status="review",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="review",
            finding_id="F-PRESERVE",
            severity="medium",
            file_path="docs/a.md",
            description="Initial audit finding",
            review_mode="release_audit",
        )
    )
    _parse(
        mcp_server.record_review_finding(
            session="review-rerun",
            finding_id="F-PRESERVE",
            severity="medium",
            file_path="docs/a.md",
            description="Rerecorded finding without review mode",
        )
    )

    audit_only = _data(mcp_server.list_review_findings(review_mode="release_audit"))
    branch_only = _data(mcp_server.list_review_findings(review_mode="branch"))

    assert {finding["finding_id"] for finding in audit_only["findings"]} == {"F-PRESERVE"}
    assert {finding["finding_id"] for finding in branch_only["findings"]} == set()


def test_invalid_review_mode_returns_error(isolated_handoff: RuntimeConfig) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref="review-guide-hardening",
            objective="Test invalid review mode",
            status="review",
        )
    )

    raw = _parse(mcp_server.list_review_findings(review_mode="not-a-mode"))
    response = _data(raw)

    assert raw["ok"] is False
    assert "Invalid review_mode" in response["error"]
