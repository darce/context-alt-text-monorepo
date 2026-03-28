from __future__ import annotations

import json

import pytest

from agent_handoff_mcp.orchestration import review_ready as review_ready_module
from agent_handoff_mcp.orchestration.review_ready import (
    _load_ok_payload,
    evaluate_review_ready,
    main,
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
        scope_source="branch_diff",
        review_kind="branch",
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
        scope_source="slice_packet",
        review_kind="branch",
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
        scope_source="slice_packet",
        review_kind="planning",
        review={"ok": True, "counts": {"status": {"open": 2}}},
        state={"ok": True, "task_ref": "task-ref", "tests_recent": []},
        close={
            "ok": True,
            "checks": {
                "open_blockers": {"count": 1},
                "current_task_sync": {"is_in_sync": False},
                "current_commit_handoff": {"is_violation": True},
            },
        },
    )

    rendered = render_review_ready(result)

    assert "REVIEW READY: NOT READY" in rendered
    assert "Review kind: planning" in rendered
    assert "Scope source: slice_packet" in rendered
    assert "- 2 open review finding(s)" in rendered
    assert "- 1 open blocker(s)" in rendered
    assert "- CURRENT_TASK.md is out of sync with handoff state" in rendered
    assert "- no structured slice-completion summary recorded for the current commit" in rendered
    assert "- no recorded test evidence in handoff state" in rendered


def test_main_reports_latest_slice_lookup_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "review_ready.py",
            "--orchestrator-root",
            "/tmp/orchestrator",
            "--worktree-root",
            "/tmp/worktree",
            "--task-ref",
            "task-ref",
            "--review-base",
            "main",
            "--latest-slice",
            "--review-kind",
            "planning",
        ],
    )
    monkeypatch.setattr(review_ready_module, "_configure_runtime", lambda _: None)
    monkeypatch.setattr(review_ready_module, "_run_git", lambda *args, **kwargs: "abc123def456")
    monkeypatch.setattr(
        review_ready_module,
        "_load_latest_slice_packet",
        lambda *args, **kwargs: _load_ok_payload(
            "get_latest_slice_review_packet",
            json.dumps({"ok": False, "error": "No matching slice review packet found."}),
        ),
    )

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "MCP query failed: get_latest_slice_review_packet: No matching slice review packet found." in captured.err
