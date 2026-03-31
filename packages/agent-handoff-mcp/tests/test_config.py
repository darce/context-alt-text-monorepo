import os
from pathlib import Path
from unittest import mock

from agent_handoff_mcp.config import RuntimeConfig


def test_runtime_config_defaults_to_workspace_state() -> None:
    root = Path("/tmp/agent-handoff").resolve()
    runtime = RuntimeConfig.for_workspace(root)

    assert runtime.workspace_root == root
    assert runtime.state_dir == root / ".task-state"
    assert runtime.db_path == root / ".task-state" / "handoff.db"
    assert runtime.current_task_path == root / "CURRENT_TASK.md"
    assert runtime.exports_dir == root / ".task-state" / "exports"


def test_runtime_config_default_tool_profile_is_core() -> None:
    root = Path("/tmp/agent-handoff").resolve()
    runtime = RuntimeConfig.for_workspace(root)
    assert runtime.tool_profile == "core"


def test_runtime_config_tool_profile_override() -> None:
    root = Path("/tmp/agent-handoff").resolve()
    runtime = RuntimeConfig.for_workspace(root, tool_profile="full")
    assert runtime.tool_profile == "full"


def test_runtime_config_from_args_reads_tool_profile_env() -> None:
    root = Path("/tmp/agent-handoff").resolve()

    class FakeArgs:
        workspace_root = str(root)
        state_dir = None
        current_task_path = None
        exports_dir = None
        tool_profile = None

    with mock.patch.dict(os.environ, {"AGENT_HANDOFF_TOOL_PROFILE": "full"}):
        runtime = RuntimeConfig.from_args(FakeArgs())
    assert runtime.tool_profile == "full"


def test_runtime_config_from_args_cli_flag_takes_precedence() -> None:
    root = Path("/tmp/agent-handoff").resolve()

    class FakeArgs:
        workspace_root = str(root)
        state_dir = None
        current_task_path = None
        exports_dir = None
        tool_profile = "full"

    with mock.patch.dict(os.environ, {"AGENT_HANDOFF_TOOL_PROFILE": "core"}):
        runtime = RuntimeConfig.from_args(FakeArgs())
    assert runtime.tool_profile == "full"
