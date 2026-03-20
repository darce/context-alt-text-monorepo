from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

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


def test_worker_event_history_cli_smoke(tmp_path: Path, capsys) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    fake_ctl = mock.Mock()
    fake_ctl.daemon_event_history.return_value = {
        "lane_id": "frontend",
        "process": None,
        "events": [{"event": "subagent_turn_observed"}],
        "returned": 1,
    }

    with mock.patch.object(api, "_import_scripts_mcp_module", return_value=fake_ctl):
        payload = _run_cli(
            [
                "agent-handoff-mcp",
                "--workspace-root",
                str(tmp_path),
                "worker-event-history",
                "--task-ref",
                "task-1",
                "--lane-id",
                "frontend",
                "--event-name",
                "subagent_turn_observed",
            ],
            capsys,
        )

    assert payload["ok"] is True
    assert payload["returned"] == 1


def test_lane_cli_accepts_explicit_task_ref_for_cross_task_reporting(tmp_path: Path, capsys) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="task-a", objective="lane cli task a"))
    json.loads(
        api.upsert_worktree_lane(
            lane_id="frontend",
            worktree_path="/tmp/frontend",
            branch="codex/p5-frontend",
            status="active",
        )
    )
    json.loads(api.set_handoff_state(task_ref="task-b", objective="lane cli task b", expected_revision=0))

    report_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "lane-report",
            "--task-ref",
            "task-a",
            "--lane-id",
            "frontend",
            "--session",
            "cli",
            "--summary",
            "ready",
        ],
        capsys,
    )
    assert report_payload["ok"] is True
    assert report_payload["report"]["task_ref"] == "task-a"

    message_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "lane-message",
            "--task-ref",
            "task-a",
            "--lane-id",
            "frontend",
            "--session",
            "cli",
            "--direction",
            "worker_to_orchestrator",
            "--message",
            "please review",
        ],
        capsys,
    )
    assert message_payload["ok"] is True
    assert message_payload["message"]["task_ref"] == "task-a"

    brief_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "lane-brief",
            "--task-ref",
            "task-a",
            "--lane-id",
            "frontend",
            "--session",
            "cli",
            "--source-lane",
            "backend-domain",
            "--reason",
            "api-contract-changed",
            "--summary",
            "Retention export contract changed.",
            "--required-action",
            "Update the typed client.",
        ],
        capsys,
    )
    assert brief_payload["ok"] is True
    assert brief_payload["message"]["payload"]["source_lane"] == "backend-domain"

    brief_list_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "lane-brief-list",
            "--task-ref",
            "task-a",
            "--lane-id",
            "frontend",
        ],
        capsys,
    )
    assert brief_list_payload["ok"] is True
    assert brief_list_payload["total_matching"] == 1

    updated_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "lane-message-update",
            "--task-ref",
            "task-a",
            "--message-id",
            str(message_payload["message"]["id"]),
            "--status",
            "acknowledged",
        ],
        capsys,
    )
    assert updated_payload["ok"] is True
    assert updated_payload["message"]["status"] == "acknowledged"


def test_lane_cli_accepts_explicit_task_ref_for_cross_task_lane_upsert(tmp_path: Path, capsys) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="task-a", objective="lane cli task a"))
    json.loads(api.set_handoff_state(task_ref="task-b", objective="lane cli task b", expected_revision=0))

    payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "lane-upsert",
            "--task-ref",
            "task-a",
            "--lane-id",
            "frontend",
            "--worktree-path",
            "/tmp/frontend",
            "--branch",
            "codex/p5-frontend",
            "--status",
            "blocked",
        ],
        capsys,
    )

    assert payload["ok"] is True
    assert payload["lane"]["task_ref"] == "task-a"
    assert payload["lane"]["status"] == "blocked"


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


def test_serve_http_parser_defaults() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["serve-http"])
    assert args.command == "serve-http"
    assert args.host == "127.0.0.1"
    assert args.port == 8741


def test_serve_http_parser_custom_host_port() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["serve-http", "--host", "0.0.0.0", "--port", "9999"])
    assert args.host == "0.0.0.0"
    assert args.port == 9999
