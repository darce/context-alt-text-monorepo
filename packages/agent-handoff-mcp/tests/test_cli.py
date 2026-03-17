from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_handoff_mcp import api
from agent_handoff_mcp import cli


def _run_cli(argv: list[str], capsys) -> dict:
    original_argv = sys.argv
    sys.argv = argv
    try:
        cli.main()
    finally:
        sys.argv = original_argv
    return json.loads(capsys.readouterr().out)


def test_doctor_cli_reports_workspace_paths(tmp_path: Path, capsys) -> None:
    payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "doctor",
        ],
        capsys,
    )

    assert payload["ok"] is True
    assert payload["workspace_root"] == str(tmp_path.resolve())


def test_state_review_list_and_close_check_cli_smoke(tmp_path: Path, capsys) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="task-1", objective="cli smoke"))
    json.loads(
        api.record_review_finding(
            session="cli",
            finding_id="M-1",
            severity="medium",
            file_path="README.md",
            description="cli review list smoke",
        )
    )

    state_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "state",
        ],
        capsys,
    )
    assert state_payload["ok"] is True
    assert state_payload["task_ref"] == "task-1"

    findings_payload = _run_cli([
        "agent-handoff-mcp",
        "--workspace-root",
        str(tmp_path),
        "review-list",
    ], capsys)
    assert findings_payload["ok"] is True
    assert findings_payload["total_matching"] == 1

    close_payload = _run_cli([
        "agent-handoff-mcp",
        "--workspace-root",
        str(tmp_path),
        "handoff-close-check",
    ], capsys)
    assert close_payload["ok"] is True
    assert close_payload["ready_to_close"] is False


def test_lane_cli_smoke(tmp_path: Path, capsys) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="task-lane", objective="lane cli"))

    lane_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "lane-upsert",
            "--lane-id",
            "frontend",
            "--worktree-path",
            "/tmp/frontend",
            "--branch",
            "codex/p5-frontend",
            "--status",
            "active",
        ],
        capsys,
    )
    assert lane_payload["ok"] is True

    report_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "lane-report",
            "--lane-id",
            "frontend",
            "--session",
            "cli",
            "--summary",
            "ready",
            "--changed-file",
            "apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx",
            "--test-command",
            "npm run test",
            "--merge-ready",
        ],
        capsys,
    )
    assert report_payload["ok"] is True

    activity_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "lane-activity",
            "--lane-id",
            "frontend",
        ],
        capsys,
    )
    assert activity_payload["ok"] is True
    assert activity_payload["lane"]["lane_id"] == "frontend"
    assert len(activity_payload["reports"]) == 1


def test_review_update_cli_accepts_explicit_task_ref(tmp_path: Path, capsys) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="task-a", objective="task a"))
    json.loads(
        api.record_review_finding(
            session="cli",
            finding_id="M-9",
            severity="medium",
            file_path="README.md",
            description="cross-task cli update",
        )
    )
    json.loads(api.set_handoff_state(task_ref="task-b", objective="task b", expected_revision=0))

    payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "review-update",
            "--finding-id",
            "M-9",
            "--status",
            "fixed",
            "--task-ref",
            "task-a",
        ],
        capsys,
    )

    assert payload["ok"] is True
    assert payload["finding"]["task_ref"] == "task-a"
    assert payload["finding"]["status"] == "fixed"


def test_review_update_cli_accepts_verified_commit_sha(tmp_path: Path, capsys, monkeypatch) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="task-a", objective="task a"))
    json.loads(
        api.record_review_finding(
            session="cli",
            finding_id="M-10",
            severity="medium",
            file_path="README.md",
            description="descendant verification",
            actor={"agent": "reviewer", "branch": "feature/review", "commit_sha": "abc123"},
        )
    )

    from agent_handoff_mcp import core as handoff_core

    monkeypatch.setattr(handoff_core, "_detect_git_write_context", lambda: ("feature/review", "def456"))
    monkeypatch.setattr(
        handoff_core,
        "_classify_commit_relation",
        lambda reference_sha, candidate_sha: "descendant" if (reference_sha, candidate_sha) == ("abc123", "def456") else "same",
    )

    payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "review-update",
            "--finding-id",
            "M-10",
            "--status",
            "fixed",
            "--resolution-notes",
            "Verified on descendant commit def456.",
            "--verified-commit-sha",
            "def456",
            "--task-ref",
            "task-a",
        ],
        capsys,
    )

    assert payload["ok"] is True
    assert payload["finding"]["status"] == "fixed"
    assert payload["commit_guard"]["verified_commit_sha"] == "def456"
