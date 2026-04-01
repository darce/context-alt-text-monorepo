from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from agent_handoff_mcp import api, cli


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

    findings_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "review-list",
        ],
        capsys,
    )
    assert findings_payload["ok"] is True
    assert findings_payload["total_matching"] == 1

    close_payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "handoff-close-check",
        ],
        capsys,
    )
    assert close_payload["ok"] is True
    assert close_payload["ready_to_close"] is False


def test_state_cli_sections_flag(tmp_path: Path, capsys) -> None:
    """--sections limits which data sections appear in CLI output."""
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="sec-cli", objective="sections cli smoke"))
    json.loads(api.record_decision(session="s1", decision="d1"))
    json.loads(api.report_blocker(operation="add", description="b1"))

    payload = _run_cli(
        ["agent-handoff-mcp", "--workspace-root", str(tmp_path), "state", "--sections", "decisions_recent"],
        capsys,
    )
    assert payload["ok"] is True
    assert "active" in payload
    assert "limits" in payload
    assert "decisions_recent" in payload
    assert "blockers_open" not in payload

    # Identity-only: explicit 'identity' token → only active + limits
    identity = _run_cli(
        ["agent-handoff-mcp", "--workspace-root", str(tmp_path), "state", "--sections", "identity"],
        capsys,
    )
    assert identity["ok"] is True
    assert "active" in identity
    assert "limits" in identity
    assert "blockers_open" not in identity
    assert "decisions_recent" not in identity


def test_state_cli_detail_flag(tmp_path: Path, capsys) -> None:
    """--detail summary truncates long fields via CLI."""
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="det-cli", objective="detail cli smoke"))
    json.loads(api.record_decision(session="s1", decision="d1", rationale="R" * 500))

    full = _run_cli(
        ["agent-handoff-mcp", "--workspace-root", str(tmp_path), "state", "--detail", "full"],
        capsys,
    )
    assert len(full["decisions_recent"][0]["rationale"]) == 500

    summary = _run_cli(
        ["agent-handoff-mcp", "--workspace-root", str(tmp_path), "state", "--detail", "summary"],
        capsys,
    )
    assert summary["decisions_recent"][0]["rationale"].endswith("...")
    assert len(summary["decisions_recent"][0]["rationale"]) == 203


def test_review_list_cli_detail_flag(tmp_path: Path, capsys) -> None:
    """review-list --detail summary truncates long finding fields via CLI."""
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="rl-det", objective="review-list detail smoke"))
    json.loads(
        api.record_review_finding(
            session="cli",
            finding_id="M-1",
            severity="medium",
            file_path="README.md",
            description="D" * 500,
        )
    )

    full = _run_cli(
        ["agent-handoff-mcp", "--workspace-root", str(tmp_path), "review-list", "--detail", "full"],
        capsys,
    )
    assert len(full["findings"][0]["description"]) == 500

    summary = _run_cli(
        ["agent-handoff-mcp", "--workspace-root", str(tmp_path), "review-list", "--detail", "summary"],
        capsys,
    )
    assert summary["findings"][0]["description"].endswith("...")
    assert len(summary["findings"][0]["description"]) == 203


def test_artifact_search_cli_fields_flag(tmp_path: Path, capsys) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="artifact-search-cli", objective="artifact search cli"))
    json.loads(
        api.record_artifact(
            task_ref="artifact-search-cli",
            source_kind="log",
            source_label="artifact-search-log",
            content="column missing\n" * 120,
            summary="backend artifact search summary",
        )
    )

    payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "artifact-search",
            "--query",
            "column missing",
            "--fields",
            "source_id,title,snippet",
        ],
        capsys,
    )

    assert payload["ok"] is True
    assert payload["hits"]
    assert set(payload["hits"][0]) <= {"source_id", "title", "snippet"}


def test_artifact_list_cli_fields_flag(tmp_path: Path, capsys) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="artifact-list-cli", objective="artifact list cli"))
    json.loads(
        api.record_artifact(
            task_ref="artifact-list-cli",
            source_kind="log",
            source_label="artifact-list-log",
            content="list payload\n" * 120,
            summary="artifact list summary",
        )
    )

    payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "artifact-list",
            "--task-ref",
            "artifact-list-cli",
            "--fields",
            "source_label,summary",
        ],
        capsys,
    )

    assert payload["ok"] is True
    assert payload["sources"]
    assert set(payload["sources"][0]) <= {"source_label", "summary"}


def test_artifact_get_cli_detail_and_fields_flags(tmp_path: Path, capsys) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="artifact-get-cli", objective="artifact get cli"))
    recorded = json.loads(
        api.record_artifact(
            task_ref="artifact-get-cli",
            source_kind="doc",
            source_label="artifact-get-doc",
            content=("chunk body\n" * 200),
        )
    )

    payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "artifact-get",
            "--source-id",
            str(recorded["source_id"]),
            "--detail",
            "summary",
            "--fields",
            "source_label,chunk_count",
        ],
        capsys,
    )

    assert payload["ok"] is True
    assert set(payload["source"]) <= {"source_label", "chunk_count"}
    assert payload["source"]["source_label"] == "artifact-get-doc"


def test_handoff_search_cli_fields_flag(tmp_path: Path, capsys) -> None:
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="handoff-search-cli", objective="handoff search cli"))
    json.loads(api.record_decision(session="cli", decision="handoff search keyword"))

    payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "handoff-search",
            "--query",
            "handoff search",
            "--fields",
            "record_type,snippet",
        ],
        capsys,
    )

    assert payload["ok"] is True
    assert payload["results"]
    assert set(payload["results"][0]) <= {"record_type", "snippet"}


def test_decision_cli_changed_files_flag(tmp_path: Path, capsys) -> None:
    """decision --changed-files persists structured scope metadata."""
    api.configure_runtime(api.RuntimeConfig.for_workspace(tmp_path))
    json.loads(api.set_handoff_state(task_ref="dec-cli", objective="decision cli changed files"))

    payload = _run_cli(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(tmp_path),
            "decision",
            "--session",
            "cli",
            "--decision",
            "cop_slice_complete_decision_cli_changed_files",
            "--rationale",
            "## Changes\n- cli.\n## Verification\n- tested.\n## Schema / Contract Changes\n- none.\n## Open Threads\n- none.",
            "--changed-files",
            "packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py",
            "packages/agent-handoff-mcp/tests/test_cli.py",
        ],
        capsys,
    )

    assert payload["ok"] is True
    assert json.loads(payload["decision"]["changed_files_json"]) == [
        "packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py",
        "packages/agent-handoff-mcp/tests/test_cli.py",
    ]


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
        lambda reference_sha, candidate_sha: "descendant"
        if (reference_sha, candidate_sha) == ("abc123", "def456")
        else "same",
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
    assert args.subcommand == "serve-http"
    assert args.host == "127.0.0.1"
    assert args.port == 8741


def test_serve_http_parser_custom_host_port() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["serve-http", "--host", "0.0.0.0", "--port", "9999"])
    assert args.host == "0.0.0.0"
    assert args.port == 9999
