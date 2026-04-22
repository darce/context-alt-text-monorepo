from __future__ import annotations

import json
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def test_claude_matchers_cover_current_altcontext_tool_names() -> None:
    payload = _read_json(REPO_ROOT / ".claude" / "settings.json")
    matchers = [entry.get("matcher", "") for entry in payload["hooks"]["PreToolUse"] + payload["hooks"]["PostToolUse"]]

    assert any("mcp_altcontext-mc_record_event" in matcher for matcher in matchers)
    assert any("mcp_altcontext-mc_close_slice" in matcher for matcher in matchers)
    assert any("mcp_altcontext-mc_get_handoff_state" in matcher for matcher in matchers)
    assert any("mcp_altcontext-mc_load_session" in matcher for matcher in matchers)
    assert any("mcp_altcontext-mc_review_findings" in matcher for matcher in matchers)


def test_vscode_matchers_cover_current_altcontext_tool_names() -> None:
    payload = _read_json(REPO_ROOT / ".github" / "hooks" / "terminal-guard.json")
    matchers = [entry.get("matcher", "") for entry in payload["hooks"]["PreToolUse"] + payload["hooks"]["PostToolUse"]]

    assert any("mcp_altcontext-mc_record_event" in matcher for matcher in matchers)
    assert any("mcp_altcontext-mc_close_slice" in matcher for matcher in matchers)
    assert any("mcp_altcontext-mc_get_handoff_state" in matcher for matcher in matchers)
    assert any("mcp_altcontext-mc_load_session" in matcher for matcher in matchers)
    assert any("mcp_altcontext-mc_review_findings" in matcher for matcher in matchers)


def test_codex_project_config_enables_hooks() -> None:
    payload = _read_toml(REPO_ROOT / ".codex" / "config.toml")

    assert payload["features"]["codex_hooks"] is True


def test_codex_hooks_register_bash_test_output_filter() -> None:
    payload = _read_json(REPO_ROOT / ".codex" / "hooks.json")
    entries = payload["hooks"]["PostToolUse"]
    bash_entries = [entry for entry in entries if entry.get("matcher") == "Bash"]

    assert bash_entries, "expected a Bash PostToolUse hook registration for Codex"
    commands = [hook["command"] for entry in bash_entries for hook in entry.get("hooks", [])]
    assert any("scripts/hooks/filter-test-output.py" in command for command in commands)


def test_codex_hooks_register_dashboard_refresh_for_state_changing_mcp_writes() -> None:
    payload = _read_json(REPO_ROOT / ".codex" / "hooks.json")
    entries = payload["hooks"]["PostToolUse"]
    refresh_entries = [
        entry
        for entry in entries
        if "mcp__agent-handoff-mcp__record_event" in entry.get("matcher", "")
    ]

    assert refresh_entries, "expected a Codex PostToolUse hook for handoff dashboard refresh"
    commands = [hook["command"] for entry in refresh_entries for hook in entry.get("hooks", [])]
    assert any("scripts/hooks/regenerate-task-views.sh" in command for command in commands)
