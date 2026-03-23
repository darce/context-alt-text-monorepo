from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_handoff_mcp" / "orchestration"
if str(_ORCHESTRATION_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATION_DIR))

from agent_handoff_mcp.orchestration.backend_adapter import BackendResult  # noqa: E402
from agent_handoff_mcp.orchestration.adapters.codex_cli import CodexCliAdapter  # noqa: E402
from agent_handoff_mcp.orchestration.adapters.codex_subagent import CodexSubagentAdapter  # noqa: E402


def test_backend_result_serialization() -> None:
    data = {
        "handoff_action": "merge_ready",
        "summary": "Fixed bugs",
        "details": "Modified logic in app.py",
        "tests_run": ["test_logic"],
        "blockers": [],
    }
    result = BackendResult.from_dict(data)
    assert result.handoff_action == "merge_ready"
    assert result.summary == "Fixed bugs"
    assert result.tests_run == ["test_logic"]

    serialized = result.to_dict()
    assert serialized["handoff_action"] == "merge_ready"
    assert serialized["summary"] == "Fixed bugs"
    assert serialized["raw_payload"] == data


def test_codex_cli_adapter_execute(tmp_path: Path) -> None:
    mock_bin = "/usr/local/bin/codex"
    adapter = CodexCliAdapter(codex_bin=mock_bin)

    prompt = "Review this code"
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    # Mock _run_codex_process to simulate success and result file creation
    def fake_run(cmd, stdin_fh, env, heartbeat_interval, progress_callback):
        # The result file path is in the cmd list: cmd[...] == "-o", cmd[...+1] == result_path
        res_idx = cmd.index("-o") + 1
        result_path = Path(cmd[res_idx])
        result_path.write_text(json.dumps({
            "handoff_action": "needs_guidance",
            "summary": "Done",
            "details": "Details",
        }))
        return mock.Mock(returncode=0, stdout="")

    with mock.patch.object(adapter, "_run_codex_process", side_effect=fake_run):
        result = adapter.execute(prompt, schema, worktree)
        assert result.handoff_action == "needs_guidance"
        assert result.summary == "Done"


def test_codex_subagent_adapter_execute(tmp_path: Path) -> None:
    runner = mock.Mock(return_value={
        "handoff_action": "merge_ready",
        "summary": "Subagent done",
        "details": "More details",
    })
    adapter = CodexSubagentAdapter(runner, name="test-bridge")

    prompt = "Refactor this"
    schema = {"type": "object"}
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    result = adapter.execute(prompt, schema, worktree)
    assert result.handoff_action == "merge_ready"
    assert result.summary == "Subagent done"
    runner.assert_called_once()
    args, kwargs = runner.call_args
    assert kwargs["prompt"] == prompt
    assert kwargs["schema"] == schema
    assert kwargs["cwd"] == str(worktree)


def test_codex_subagent_adapter_fallback_on_telemetry(tmp_path: Path) -> None:
    # Simulate an older bridge that doesn't accept telemetry_callback
    def runner_no_telemetry(**kwargs):
        if "telemetry_callback" in kwargs:
            raise TypeError("unexpected keyword argument 'telemetry_callback'")
        return {"handoff_action": "needs_guidance", "summary": "Legacy", "details": "..."}

    adapter = CodexSubagentAdapter(runner_no_telemetry)
    progress = mock.Mock()

    result = adapter.execute(
        "prompt", {}, tmp_path, progress_callback=progress
    )
    assert result.summary == "Legacy"
    # progress("exec_spawned") should still be called
    progress.assert_any_call("exec_spawned", backend="subagent")
