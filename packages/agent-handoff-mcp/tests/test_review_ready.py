from __future__ import annotations

import pytest

from agent_handoff_mcp.orchestration.review_ready import (
    _load_ok_payload,
    evaluate_review_ready,
    render_review_ready,
)


def test_load_ok_payload_rejects_mcp_errors() -> None:
    with pytest.raises(RuntimeError, match="MCP query failed: get_handoff_state: boom"):
        _load_ok_payload("get_handoff_state", '{"ok": false, "error": "boom"}')


def test_evaluate_review_ready_reports_contract_violation() -> None:
    result = evaluate_review_ready(
        task_ref="task-ref",
        base_ref="main",
        base_sha="abcdef1234567890",
        changed_files=["apps/prototype-wp-alt-context/src/api/class-foo.php"],
        review={"ok": True, "counts": {"status": {"open": 0}}},
        state={"ok": True, "task_ref": "task-ref", "tests_recent": [{"id": 1}]},
        close={
            "ok": True,
            "checks": {
                "open_blockers": {"count": 0},
                "current_task_sync": {"is_in_sync": True},
            },
        },
    )

    assert result.ready is False
    assert result.contract_violation is True
    assert "boundary-touching files changed without contract/checklist co-change" in result.reasons


def test_evaluate_review_ready_uses_contract_files_to_clear_violation() -> None:
    result = evaluate_review_ready(
        task_ref="task-ref",
        base_ref="main",
        base_sha="abcdef1234567890",
        changed_files=[
            "apps/prototype-wp-alt-context/src/api/class-foo.php",
            "docs/agentic/contracts/foo-contract.md",
        ],
        review={"ok": True, "counts": {"status": {"open": 0}}},
        state={"ok": True, "task_ref": "task-ref", "tests_recent": [{"id": 1}]},
        close={
            "ok": True,
            "checks": {
                "open_blockers": {"count": 0},
                "current_task_sync": {"is_in_sync": True},
            },
        },
    )

    assert result.ready is True
    assert result.contract_violation is False


def test_render_review_ready_includes_not_ready_reasons() -> None:
    result = evaluate_review_ready(
        task_ref="task-ref",
        base_ref="main",
        base_sha="abcdef1234567890",
        changed_files=[],
        review={"ok": True, "counts": {"status": {"open": 2}}},
        state={"ok": True, "task_ref": "task-ref", "tests_recent": []},
        close={
            "ok": True,
            "checks": {
                "open_blockers": {"count": 1},
                "current_task_sync": {"is_in_sync": False},
            },
        },
    )

    rendered = render_review_ready(result)

    assert "REVIEW READY: NOT READY" in rendered
    assert "- 2 open review finding(s)" in rendered
    assert "- 1 open blocker(s)" in rendered
    assert "- CURRENT_TASK.md is out of sync with handoff state" in rendered
    assert "- no recorded test evidence in handoff state" in rendered
