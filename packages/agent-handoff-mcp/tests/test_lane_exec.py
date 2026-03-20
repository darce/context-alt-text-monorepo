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


def test_tail_text_accepts_bytes() -> None:
    mod = _load_module()
    assert mod._tail_text(b"one\ntwo\n") == "one two"


def test_backend_choices_come_from_registry() -> None:
    mod = _load_module()
    assert "codex-cli" in mod.BACKEND_CHOICES
    assert "codex-subagent" in mod.BACKEND_CHOICES
    assert "copilot-host" in mod.BACKEND_CHOICES


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
    assert "/.pyenv/versions/description-service/bin" in env["PATH"]


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
        mock.patch.object(mod, "_render_prompt", return_value="Test prompt"),
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
        mock.patch.object(mod, "find_codex") as mock_find_codex,
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

    with (
        mock.patch.object(mod, "_render_prompt", return_value="Test prompt"),
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
        mock.patch.object(mod, "_run_subagent", return_value=subagent_payload) as mock_run_subagent,
        mock.patch.object(mod, "find_codex") as mock_find_codex,
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
    mock_run_subagent.assert_called_once()
    assert mock_run_subagent.call_args.args[0] == "codex-subagent"
    mock_find_codex.assert_not_called()


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

    with (
        mock.patch.object(mod, "_render_prompt", return_value="Test prompt"),
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
        mock.patch.object(mod, "_run_subagent", return_value=subagent_payload) as mock_run_subagent,
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

    env = mock_run_subagent.call_args.kwargs["env"]
    assert env["CODEX_REASONING_EFFORT"] == "high"


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
        mock.patch.object(mod, "_run_subagent") as mock_subagent,
        mock.patch.object(mod, "find_codex") as mock_find_codex,
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
    mock_subagent.assert_not_called()
    mock_find_codex.assert_not_called()


def test_run_subagent_emits_progress_callbacks() -> None:
    mod = _load_module()
    progress: list[tuple[str, dict[str, Any]]] = []
    fake_runner = mock.Mock(return_value={"handoff_action": "merge_ready", "summary": "Done."})

    with mock.patch.object(mod, "resolve_bridge", return_value=fake_runner):
        payload = mod._run_subagent(
            "codex-subagent",
            prompt_text="Prompt",
            schema_text=json.dumps({"type": "object"}),
            worktree_path=Path("/tmp/worktree"),
            progress_callback=lambda event, **kw: progress.append((event, kw)),
        )

    assert payload == {"handoff_action": "merge_ready", "summary": "Done."}
    assert [event for event, _ in progress] == ["exec_spawned", "exec_complete"]
    assert progress[0][1]["backend"] == "codex-subagent"


def test_run_subagent_does_not_emit_complete_for_invalid_payload() -> None:
    mod = _load_module()
    progress: list[tuple[str, dict[str, Any]]] = []
    fake_runner = mock.Mock(return_value="not-json")

    with mock.patch.object(mod, "resolve_bridge", return_value=fake_runner):
        with pytest.raises(RuntimeError, match="invalid JSON"):
            mod._run_subagent(
                "codex-subagent",
                prompt_text="Prompt",
                schema_text=json.dumps({"type": "object"}),
                worktree_path=Path("/tmp/worktree"),
                progress_callback=lambda event, **kw: progress.append((event, kw)),
            )

    assert [event for event, _ in progress] == ["exec_spawned"]


def test_run_subagent_passes_env_when_bridge_supports_it() -> None:
    mod = _load_module()
    fake_runner = mock.Mock(return_value={"handoff_action": "merge_ready", "summary": "Done."})
    env = {"TMPDIR": "/tmp/lane", "PYENV_VERSION": "description-service"}

    with mock.patch.object(mod, "resolve_bridge", return_value=fake_runner):
        mod._run_subagent(
            "codex-subagent",
            prompt_text="Prompt",
            schema_text=json.dumps({"type": "object"}),
            worktree_path=Path("/tmp/worktree"),
            env=env,
        )

    assert fake_runner.call_args.kwargs["env"] == env


def test_run_subagent_falls_back_when_bridge_does_not_accept_env() -> None:
    mod = _load_module()

    def legacy_runner(*, prompt: str, schema: dict[str, Any], cwd: str) -> dict[str, Any]:
        return {"handoff_action": "merge_ready", "summary": "Done."}

    fake_runner = mock.Mock(side_effect=legacy_runner)

    with mock.patch.object(mod, "resolve_bridge", return_value=fake_runner):
        payload = mod._run_subagent(
            "codex-subagent",
            prompt_text="Prompt",
            schema_text=json.dumps({"type": "object"}),
            worktree_path=Path("/tmp/worktree"),
            env={"TMPDIR": "/tmp/lane"},
        )

    assert payload == {"handoff_action": "merge_ready", "summary": "Done."}
    assert fake_runner.call_count == 2
    assert "env" not in fake_runner.call_args.kwargs


def test_validate_lane_result_payload_rejects_missing_fields() -> None:
    mod = _load_module()
    with pytest.raises(RuntimeError, match="missing required non-empty string 'details'"):
        mod._validate_lane_result_payload(
            {
                "handoff_action": "merge_ready",
                "summary": "Done.",
                "tests_run": [],
                "blockers": [],
            }
        )


def test_run_lane_exec_subagent_backend_rejects_invalid_payload(tmp_path: Path) -> None:
    mod = _load_module()
    output = tmp_path / "result.json"
    schema_json = json.dumps({"type": "object", "properties": {}})

    with (
        mock.patch.object(mod, "_render_prompt", return_value="Test prompt"),
        mock.patch.object(mod, "_render_schema", return_value=schema_json),
        mock.patch.object(
            mod,
            "_run_subagent",
            return_value={"handoff_action": "merge_ready", "summary": "Done.", "tests_run": [], "blockers": []},
        ),
    ):
        with pytest.raises(RuntimeError, match="missing required non-empty string 'details'"):
            mod.run_lane_exec(
                orchestrator_root=REPO_ROOT,
                task_ref="test-task",
                lane_id="test-lane",
                session="test-task-test-lane",
                worktree_path=tmp_path,
                output_path=output,
                backend="codex-subagent",
            )


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


def test_run_codex_process_emits_heartbeat() -> None:
    mod = _load_module()
    progress: list[tuple[str, dict[str, Any]]] = []

    class FakeProc:
        def __init__(self) -> None:
            self.pid = 4242
            self.returncode = 0
            self.calls = 0

        def communicate(self, timeout: int | None = None) -> tuple[str, str]:
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(
                    cmd=["codex", "exec"],
                    timeout=timeout or 20,
                    output="still working",
                    stderr="waiting on tests",
                )
            return ('{"handoff_action":"needs_guidance"}', "")

    with mock.patch("subprocess.Popen", return_value=FakeProc()):
        completed = mod._run_codex_process(
            cmd=["codex", "exec"],
            stdin_fh=mock.Mock(),
            env={},
            heartbeat_interval=1,
            progress_callback=lambda event, **kw: progress.append((event, kw)),
        )

    assert completed.returncode == 0
    assert [event for event, _ in progress] == ["exec_spawned", "exec_heartbeat"]
    assert progress[1][1]["pid"] == 4242
    assert "stderr_tail" in progress[1][1]
