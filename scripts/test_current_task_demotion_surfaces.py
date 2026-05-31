from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_CONFIG_PATH = REPO_ROOT / ".vscode" / "mcp.json"
INSTRUCTIONS_PATH = REPO_ROOT / "docs" / "workstate" / "instructions.md"
CLAUDE_PATH = REPO_ROOT / "CLAUDE.md"
HANDOFF_MK_PATH = REPO_ROOT / "mk" / "handoff.mk"
SLICE_START_INLINE_PATH = REPO_ROOT / "scripts" / "_slice_start_inline.py"


def test_root_mcp_launchers_do_not_require_current_task_path() -> None:
    payload = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))

    for server_name in ("workstate-handoff-mcp", "workstate-orchestrator-mcp"):
        args = payload["servers"][server_name]["args"]
        assert "--current-task-path" not in args
        assert "${workspaceFolder}/CURRENT_TASK.json" not in args
        # Workspace-rooted launch: exports/current-task paths are derived from
        # the workspace root on demand, never pinned at launch time.
        assert "--workspace-root" in args


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


def test_slice_start_owned_by_canonical_lifecycle_not_bespoke_inline() -> None:
    # MAINT-workstate-migration-20260530: the bespoke `slice-start` target and
    # scripts/_slice_start_inline.py were removed; canonical Makefile.d/lifecycle.mk
    # owns slice-start now (its handler refreshes the dashboard, never
    # CURRENT_TASK.json). Assert the bespoke surfaces are gone and canonical is wired.
    handoff_mk_text = HANDOFF_MK_PATH.read_text(encoding="utf-8")
    makefile_text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert not SLICE_START_INLINE_PATH.exists()
    assert "slice-start:" not in handoff_mk_text
    assert "-include Makefile.d/*.mk" in makefile_text