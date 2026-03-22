"""Tests for scripts/mcp/lane_exec.py -- non-reporting lane execution primitive."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "lane_exec.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("lane_exec", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load lane_exec module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Codex discovery
# (Now handled by adapters, verified in test_backend_registry.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Handoff instructions
# ---------------------------------------------------------------------------


def test_handoff_instructions_present() -> None:
    mod = _load_module()
    assert "handoff_action" in mod._HANDOFF_INSTRUCTIONS
    assert "merge_ready" in mod._HANDOFF_INSTRUCTIONS
    assert "needs_guidance" in mod._HANDOFF_INSTRUCTIONS


# ---------------------------------------------------------------------------
# build_fix_prompt
# ---------------------------------------------------------------------------


def test_build_fix_prompt_no_findings() -> None:
    mod = _load_module()
    base = "Implement the feature."
    assert mod.build_fix_prompt(base, []) == base


def test_build_fix_prompt_with_findings() -> None:
    mod = _load_module()
    base = "Implement the feature."
    findings = [
        {
            "severity": "high",
            "category": "GAP",
            "file_path": "src/foo.py",
            "description": "Missing error handler.",
            "line_start": 42,
        },
        {
            "severity": "low",
            "category": "COMPLEXITY",
            "file_path": "src/bar.py",
            "description": "Nested too deep.",
        },
    ]
    result = mod.build_fix_prompt(base, findings)
    assert "REVIEW FINDINGS TO FIX" in result
    assert "src/foo.py:42" in result
    assert "[HIGH]" in result
    assert "[GAP]" in result
    assert "Missing error handler." in result
    assert "[LOW]" in result
    assert "[COMPLEXITY]" in result


def test_build_fix_prompt_includes_fix_hint() -> None:
    mod = _load_module()
    findings = [
        {
            "severity": "medium",
            "category": "ANTIPATTERN",
            "file_path": "src/baz.py",
            "description": "Use context manager.",
            "fix": "Replace with 'with' block.",
        }
    ]
    result = mod.build_fix_prompt("base", findings)
    assert "Fix: Replace with 'with' block." in result


def test_tail_text_accepts_bytes() -> None:
    mod = _load_module()
    assert mod._tail_text(b"one\ntwo\n") == "one two"


def test_backend_choices_come_from_registry() -> None:
    mod = _load_module()
    assert "codex-cli" in mod.BACKEND_CHOICES
    assert "codex-subagent" in mod.BACKEND_CHOICES


# ---------------------------------------------------------------------------
# PYTHONPATH env
# ---------------------------------------------------------------------------


def test_pythonpath_env_includes_mcp_src() -> None:
    mod = _load_module()
    env = mod.pythonpath_env(REPO_ROOT, task_ref="phase-5-retention-export-and-audit-controls", lane_id="backend-domain")
    expected_mcp = str(REPO_ROOT / "packages" / "agent-handoff-mcp" / "src")
    expected_bridge = str(REPO_ROOT / "packages" / "codex-subagent-bridge" / "src")
    assert expected_mcp in env["PYTHONPATH"]
    assert expected_bridge in env["PYTHONPATH"]
    assert env["PYENV_VERSION"] == "description-service"
    assert env["TMPDIR"].endswith("/.task-state/tmp/backend-domain")


# ---------------------------------------------------------------------------
# run_lane_exec dry_run
# ---------------------------------------------------------------------------


def test_run_lane_exec_dry_run(tmp_path: Path) -> None:
    mod = _load_module()
    output = tmp_path / "result.json"

    schema_json = json.dumps({"type": "object", "properties": {}})

    with (
        mock.patch.object(mod, "_render_prompt", return_value=("Test prompt", {})),
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
        mock.patch.object(mod, "get_lane_config", return_value={}),
    ):
        result_path = mod.run_lane_exec(
            orchestrator_root=REPO_ROOT,
            task_ref="test-task",
            lane_id="test-lane",
            session="test-task-test-lane",
            worktree_path=tmp_path,
            output_path=output,
            dry_run=True,
        )

    assert result_path == output
    data = json.loads(output.read_text())
    assert data["dry_run"] is True
    assert data["handoff_action"] == "merge_ready"
    assert "Test prompt" in data["prompt"]
    assert "handoff_action" in data["prompt"]  # appended instructions


def test_run_lane_exec_dry_run_with_prompt_override(tmp_path: Path) -> None:
    mod = _load_module()
    output = tmp_path / "result.json"

    schema_json = json.dumps({"type": "object", "properties": {}})

    with (
        mock.patch.object(mod, "_render_prompt") as mock_prompt,
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
        mock.patch.object(mod, "get_lane_config", return_value={}),
    ):
        result_path = mod.run_lane_exec(
            orchestrator_root=REPO_ROOT,
            task_ref="test-task",
            lane_id="test-lane",
            session="test-task-test-lane",
            worktree_path=tmp_path,
            output_path=output,
            prompt_override="Custom prompt here.",
            dry_run=True,
        )

    mock_prompt.assert_not_called()
    data = json.loads(output.read_text())
    assert "Custom prompt here." in data["prompt"]


def test_run_lane_exec_dry_run_subagent_skips_find_codex(tmp_path: Path) -> None:
    mod = _load_module()
    output = tmp_path / "result.json"
    schema_json = json.dumps({"type": "object", "properties": {}})

    with (
        mock.patch.object(mod, "_render_prompt", return_value=("Test prompt", {})),
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
        mock.patch.object(mod, "find_codex") as mock_find_codex,
        mock.patch.object(mod, "get_lane_config", return_value={}),
    ):
        result_path = mod.run_lane_exec(
            orchestrator_root=REPO_ROOT,
            task_ref="test-task",
            lane_id="test-lane",
            session="test-task-test-lane",
            worktree_path=tmp_path,
            output_path=output,
            backend="codex-subagent",
            dry_run=True,
        )

    assert result_path == output
    data = json.loads(output.read_text())
    assert data["backend"] == "codex-subagent"
    assert "codex_bin" not in data
    mock_find_codex.assert_not_called()


def test_run_lane_exec_subagent_backend_writes_structured_result(tmp_path: Path) -> None:
    mod = _load_module()
    output = tmp_path / "result.json"
    schema_json = json.dumps({"type": "object", "properties": {}})
    subagent_payload = {
        "handoff_action": "merge_ready",
        "summary": "Done.",
        "details": "Implemented the slice.",
        "tests_run": [],
        "blockers": [],
    }

    mock_adapter = mock.Mock()
    mock_adapter.execute.return_value = mock.Mock(to_dict=lambda: subagent_payload)

    with (
        mock.patch.object(mod, "_render_prompt", return_value=("Test prompt", {})),
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
        mock.patch.object(mod, "get_adapter", return_value=mock_adapter),
        mock.patch.object(mod, "bootstrap_lane", return_value=0),
        mock.patch.object(mod, "get_lane_config", return_value={}),
    ):
        result_path = mod.run_lane_exec(
            orchestrator_root=REPO_ROOT,
            task_ref="test-task",
            lane_id="test-lane",
            session="test-task-test-lane",
            worktree_path=tmp_path,
            output_path=output,
            backend="codex-subagent",
        )

    assert result_path == output
    assert json.loads(output.read_text()) == subagent_payload
    mock_adapter.execute.assert_called_once()
    assert mock_adapter.execute.call_args.kwargs["model"] is None


def test_run_lane_exec_subagent_backend_passes_reasoning_effort_env(tmp_path: Path) -> None:
    mod = _load_module()
    output = tmp_path / "result.json"
    schema_json = json.dumps({"type": "object", "properties": {}})
    subagent_payload = {
        "handoff_action": "merge_ready",
        "summary": "Done.",
        "details": "Implemented the slice.",
        "tests_run": [],
        "blockers": [],
    }

    mock_adapter = mock.Mock()
    mock_adapter.execute.return_value = mock.Mock(to_dict=lambda: subagent_payload)

    with (
        mock.patch.object(mod, "_render_prompt", return_value=("Test prompt", {})),
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
        mock.patch.object(mod, "get_adapter", return_value=mock_adapter),
        mock.patch.object(mod, "bootstrap_lane", return_value=0),
        mock.patch.object(mod, "get_lane_config", return_value={}),
    ):
        mod.run_lane_exec(
            orchestrator_root=REPO_ROOT,
            task_ref="test-task",
            lane_id="test-lane",
            session="test-task-test-lane",
            worktree_path=tmp_path,
            output_path=output,
            backend="codex-subagent",
            reasoning_effort="high",
        )

    kwargs = mock_adapter.execute.call_args.kwargs
    assert kwargs["reasoning_effort"] == "high"


def test_run_lane_exec_preflight_failure_returns_needs_guidance_without_running_backend(tmp_path: Path) -> None:
    mod = _load_module()
    output = tmp_path / "result.json"

    with (
        mock.patch.object(
            mod,
            "_run_lane_preflight",
            return_value={
                "ok": False,
                "commands": ["pg_isready -h localhost -p 5432"],
                "capability_tags": ["postgres-ready"],
                "failures": [
                    {
                        "command": "pg_isready -h localhost -p 5432",
                        "exit_code": 2,
                        "stderr_tail": "no response",
                        "stdout_tail": "",
                    }
                ],
                "failure_summary": "backend-domain DB preflight failed",
                "failure_details": "postgres is unavailable",
            },
        ),
        mock.patch.object(mod, "_render_prompt") as mock_prompt,
        mock.patch.object(mod, "_render_schema") as mock_schema,
        mock.patch.object(mod, "get_adapter") as mock_get_adapter,
        mock.patch.object(mod, "bootstrap_lane", return_value=0),
        mock.patch.object(mod, "get_lane_config", return_value={}),
    ):
        result_path = mod.run_lane_exec(
            orchestrator_root=REPO_ROOT,
            task_ref="test-task",
            lane_id="backend-domain",
            session="test-task-backend-domain",
            worktree_path=tmp_path,
            output_path=output,
            backend="codex-subagent",
        )

    assert result_path == output
    data = json.loads(output.read_text())
    assert data["handoff_action"] == "needs_guidance"
    assert data["summary"] == "backend-domain DB preflight failed"
    assert "postgres is unavailable" in data["details"]
    assert "pg_isready -h localhost -p 5432" in data["tests_run"]
    mock_prompt.assert_not_called()
    mock_schema.assert_not_called()
    mock_get_adapter.assert_not_called()



# ---------------------------------------------------------------------------
# _render_prompt subprocess call shape
# ---------------------------------------------------------------------------


def test_render_prompt_calls_lane_prompt(tmp_path: Path) -> None:
    mod = _load_module()
    fake_result = mock.Mock()
    fake_result.returncode = 0
    fake_result.stdout = "rendered prompt text"
    fake_result.stderr = ""

    with mock.patch("subprocess.run", return_value=fake_result) as mock_run:
        result = mod._render_prompt(
            orchestrator_root=REPO_ROOT,
            task_ref="t",
            lane_id="l",
            worktree_path=tmp_path,
        )

    assert result == ("rendered prompt text", {})
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert "lane_prompt.py" in cmd[1]
    assert "--task-ref" in cmd
    assert "--lane-id" in cmd


def test_render_prompt_raises_on_failure(tmp_path: Path) -> None:
    mod = _load_module()
    fake_result = mock.Mock()
    fake_result.returncode = 1
    fake_result.stderr = "some error"

    with mock.patch("subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError, match="lane_prompt.py failed"):
            mod._render_prompt(
                orchestrator_root=REPO_ROOT,
                task_ref="t",
                lane_id="l",
                worktree_path=tmp_path,
            )


# ---------------------------------------------------------------------------
# _render_schema subprocess call shape
# ---------------------------------------------------------------------------


def test_render_schema_calls_lane_result() -> None:
    mod = _load_module()
    fake_result = mock.Mock()
    fake_result.returncode = 0
    fake_result.stdout = '{"type": "object"}'

    with mock.patch("subprocess.run", return_value=fake_result) as mock_run:
        result = mod._render_schema(REPO_ROOT)

    assert result == '{"type": "object"}'
    cmd = mock_run.call_args[0][0]
    assert "lane_result.py" in cmd[1]
    assert "schema" in cmd


def test_render_schema_raises_on_failure() -> None:
    mod = _load_module()
    fake_result = mock.Mock()
    fake_result.returncode = 1
    fake_result.stderr = "schema error"

    with mock.patch("subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError, match="lane_result.py schema failed"):
            mod._render_schema(REPO_ROOT)
