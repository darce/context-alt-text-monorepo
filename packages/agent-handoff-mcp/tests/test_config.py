from pathlib import Path

from agent_handoff_mcp.config import RuntimeConfig


def test_runtime_config_defaults_to_workspace_state() -> None:
    root = Path("/tmp/agent-handoff").resolve()
    runtime = RuntimeConfig.for_workspace(root)

    assert runtime.workspace_root == root
    assert runtime.state_dir == root / ".task-state"
    assert runtime.db_path == root / ".task-state" / "handoff.db"
    assert runtime.current_task_path == root / "CURRENT_TASK.md"
    assert runtime.exports_dir == root / ".task-state" / "exports"
