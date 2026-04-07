from __future__ import annotations

import importlib
import json

import agent_handoff_mcp
import pytest

from agent_orchestrator_mcp.orchestration import review_ready as review_ready_module
from agent_orchestrator_mcp.orchestration.handoff_read_shapes import review_ready_state_kwargs
from agent_orchestrator_mcp.orchestration.review_ready import (
    _load_ok_payload,
    evaluate_review_ready,
    main,
    render_review_ready,
)

handoff_review_findings_module = importlib.import_module("agent_handoff_mcp.review_findings")


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


def test_evaluate_review_ready_accepts_custom_boundary_and_contract_paths() -> None:
    result = evaluate_review_ready(
        task_ref="task-ref",
        base_ref="main",
        base_sha="abcdef1234567890",
        changed_files=[
            "runtime-boundary/foo.py",
            "runtime-contracts/foo.md",
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
        boundary_prefixes=("runtime-boundary/",),
        contract_prefixes=("runtime-contracts/",),
        contract_checklist_path="runtime-contracts/checklist.md",
    )

    assert result.ready is True
    assert result.boundary_files == ["runtime-boundary/foo.py"]
    assert result.contract_files == ["runtime-contracts/foo.md"]
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


def test_main_requests_only_identity_and_recent_tests(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: dict[str, dict[str, object]] = {}

    def fake_get_review_findings_summary(*, task_ref: str) -> str:
        calls["review"] = {"task_ref": task_ref}
        return json.dumps({"ok": True, "task_ref": task_ref, "counts": {"status": {"open": 0}}})

    def fake_get_handoff_state(**kwargs: object) -> str:
        calls["state"] = dict(kwargs)
        return json.dumps({"ok": True, "task_ref": "task-ref", "tests_recent": [{"id": 1}]})

    def fake_handoff_close_check(**kwargs: object) -> str:
        calls["close"] = dict(kwargs)
        return json.dumps(
            {
                "ok": True,
                "checks": {
                    "open_blockers": {"count": 0},
                    "current_task_sync": {"is_in_sync": True},
                    "current_commit_handoff": {"is_violation": False},
                },
            }
        )

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
        ],
    )
    monkeypatch.setattr(review_ready_module, "_configure_runtime", lambda _: None)
    monkeypatch.setattr(review_ready_module, "_run_git", lambda *args, **kwargs: "abc123def456")
    monkeypatch.setattr(agent_handoff_mcp, "get_handoff_state", fake_get_handoff_state)
    monkeypatch.setattr(agent_handoff_mcp, "handoff_close_check", fake_handoff_close_check)
    monkeypatch.setattr(
        handoff_review_findings_module, "get_review_findings_summary", fake_get_review_findings_summary
    )

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "REVIEW READY: READY" in captured.out
    assert calls["review"] == {"task_ref": "task-ref"}
    assert calls["state"] == review_ready_state_kwargs("task-ref")
    assert calls["close"] == {"task_ref": "task-ref", "current_commit_sha": "abc123def456"}
