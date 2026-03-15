"""Tests for scripts/mcp/lane_exec.py -- non-reporting lane execution primitive."""
from __future__ import annotations

import importlib.util
import json
import os
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
# ---------------------------------------------------------------------------


def test_find_codex_explicit_path() -> None:
    mod = _load_module()
    assert mod.find_codex("/usr/local/bin/codex") == "/usr/local/bin/codex"


def test_find_codex_which_fallback() -> None:
    mod = _load_module()
    fake_result = mock.Mock()
    fake_result.returncode = 0
    fake_result.stdout = "/opt/homebrew/bin/codex\n"
    with mock.patch("subprocess.run", return_value=fake_result):
        assert mod.find_codex(None) == "/opt/homebrew/bin/codex"


def test_find_codex_raises_when_not_found(tmp_path: Path) -> None:
    mod = _load_module()
    # Patch the subprocess module reference held by the dynamically-loaded module
    fake_which = mock.Mock(returncode=1, stdout="")
    orig_paths = mod._CODEX_SEARCH_PATHS
    mod._CODEX_SEARCH_PATHS = ()
    orig_run = mod.subprocess.run
    mod.subprocess.run = mock.Mock(return_value=fake_which)
    try:
        with pytest.raises(RuntimeError, match="codex CLI not found"):
            mod.find_codex(None)
    finally:
        mod._CODEX_SEARCH_PATHS = orig_paths
        mod.subprocess.run = orig_run


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


# ---------------------------------------------------------------------------
# PYTHONPATH env
# ---------------------------------------------------------------------------


def test_pythonpath_env_includes_mcp_src() -> None:
    mod = _load_module()
    env = mod.pythonpath_env(REPO_ROOT)
    expected = str(REPO_ROOT / "packages" / "agent-handoff-mcp" / "src")
    assert expected in env["PYTHONPATH"]


# ---------------------------------------------------------------------------
# run_lane_exec dry_run
# ---------------------------------------------------------------------------


def test_run_lane_exec_dry_run(tmp_path: Path) -> None:
    mod = _load_module()
    output = tmp_path / "result.json"

    schema_json = json.dumps({"type": "object", "properties": {}})

    with (
        mock.patch.object(mod, "_render_prompt", return_value="Test prompt"),
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
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
    assert "Test prompt" in data["prompt"]
    assert "handoff_action" in data["prompt"]  # appended instructions


def test_run_lane_exec_dry_run_with_prompt_override(tmp_path: Path) -> None:
    mod = _load_module()
    output = tmp_path / "result.json"

    schema_json = json.dumps({"type": "object", "properties": {}})

    with (
        mock.patch.object(mod, "_render_prompt") as mock_prompt,
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
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


# ---------------------------------------------------------------------------
# _render_prompt subprocess call shape
# ---------------------------------------------------------------------------


def test_render_prompt_calls_lane_prompt(tmp_path: Path) -> None:
    mod = _load_module()
    fake_result = mock.Mock()
    fake_result.returncode = 0
    fake_result.stdout = "rendered prompt text"

    with mock.patch("subprocess.run", return_value=fake_result) as mock_run:
        result = mod._render_prompt(
            orchestrator_root=REPO_ROOT,
            task_ref="t",
            lane_id="l",
            worktree_path=tmp_path,
        )

    assert result == "rendered prompt text"
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
