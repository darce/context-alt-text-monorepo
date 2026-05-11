from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_CONFIG_PATH = REPO_ROOT / ".vscode" / "mcp.json"
INSTRUCTIONS_PATH = REPO_ROOT / "docs" / "agentic" / "instructions.md"
CLAUDE_PATH = REPO_ROOT / "CLAUDE.md"
HANDOFF_MK_PATH = REPO_ROOT / "mk" / "handoff.mk"
SLICE_START_INLINE_PATH = REPO_ROOT / "scripts" / "_slice_start_inline.py"


def test_root_mcp_launchers_do_not_require_current_task_path() -> None:
    payload = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))

    for server_name in ("mcp-agent-handoff", "mcp-agent-orchestrator"):
        args = payload["servers"][server_name]["args"]
        assert "--current-task-path" not in args
        assert "${workspaceFolder}/CURRENT_TASK.json" not in args
        assert "--exports-dir" in args


def test_shared_docs_describe_current_task_as_on_demand_export() -> None:
    expected_snippet = "CURRENT_TASK.json` = optional task-scoped export only if an explicit render wrote it; do not assume it exists or is current."

    instructions_text = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    claude_text = CLAUDE_PATH.read_text(encoding="utf-8")

    assert expected_snippet in instructions_text
    assert expected_snippet in claude_text

    stale_snippet = "CURRENT_TASK.json` = machine-readable state."
    assert stale_snippet not in instructions_text
    assert stale_snippet not in claude_text

    stale_instructions_snippets = (
        "`CURRENT_TASK.json` must expose the latest decision separately from the recent-decisions list.",
        "Switch when the objective changes or `CURRENT_TASK.json` would show the wrong latest decision.",
        "Non-archived, non-active tasks default to `active` in the CURRENT_TASK.json dashboard.",
    )
    for snippet in stale_instructions_snippets:
        assert snippet not in instructions_text


def test_slice_start_refreshes_dashboard_instead_of_current_task() -> None:
    handoff_mk_text = HANDOFF_MK_PATH.read_text(encoding="utf-8")
    slice_start_inline_text = SLICE_START_INLINE_PATH.read_text(encoding="utf-8")

    assert 'scripts/_slice_start_inline.py' in handoff_mk_text
    assert 'render_handoff_fn(kind="dashboard")' in slice_start_inline_text
    assert 'render_handoff(kind=\'dashboard\')' in slice_start_inline_text
    assert 'kind="current_task"' not in slice_start_inline_text