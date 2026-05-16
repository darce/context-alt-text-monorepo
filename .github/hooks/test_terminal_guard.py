"""Tests for the narrow VS Code terminal guard."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


HOOK_SCRIPT = Path(__file__).parent / "terminal-guard.py"

spec = importlib.util.spec_from_file_location("terminal_guard", HOOK_SCRIPT)
module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(module)  # type: ignore[union-attr]
_check_command = module._check_command


def _run_hook(payload: dict, cwd: str | None = None) -> tuple[int, dict | None, str]:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        cwd=cwd,
    )
    stdout_json = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, stdout_json, proc.stderr


@pytest.mark.parametrize(
    "command",
    [
        "vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx",
        "npx vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx",
        "cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx",
        "pwd && npx vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx",
        "ls -la; vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx",
        "VIRTUAL_ENV= npx vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx",
        "export NODE_ENV=test && vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx",
    ],
)
def test_raw_vitest_run_is_blocked(command: str) -> None:
    result = _check_command(command)
    assert result is not None
    decision, trigger, reason = result
    assert decision == "block"
    assert trigger == "npm run test:agent"
    assert "strand the VS Code chat terminal" in reason


@pytest.mark.parametrize(
    "command",
    [
        "npm run test:agent -- js/admin/pages/workbench/__tests__/JobTimeline.test.tsx",
        "npm run test -- js/admin/pages/workbench/__tests__/JobTimeline.test.tsx",
        "npx vitest --version",
        "pytest scripts/test_harness_terminal_stall_investigation_doc.py -q",
        "cat README.md",
        "rg terminal-guard .github/hooks",
        "git status",
        "echo hello",
        "curl https://example.com",
        "npm run lint",
        "npx vitest runx js/admin/pages/workbench/__tests__/JobTimeline.test.tsx",
        "echo 'npx vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx'",
    ],
)
def test_everything_except_raw_vitest_run_passes_through(command: str) -> None:
    assert _check_command(command) is None


def test_camelcase_payload_schema_blocks_raw_vitest(tmp_path: Path) -> None:
    payload = {
        "toolName": "run_in_terminal",
        "toolInput": {"command": "npx vitest run js/admin/pages/workbench/__tests__/JobTimeline.test.tsx"},
    }
    exit_code, stdout_json, stderr = _run_hook(payload, cwd=str(tmp_path))

    assert exit_code == 0
    assert stderr == ""
    assert stdout_json is not None
    hook_output = stdout_json["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "block"
    assert "npm run test:agent" in hook_output["permissionDecisionReason"]

    log_file = tmp_path / ".task-state" / "terminal_guard.jsonl"
    assert log_file.exists()
    record = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert record["decision"] == "block"
    assert record["trigger"] == "npm run test:agent"


def test_snakecase_payload_schema_allows_non_vitest(tmp_path: Path) -> None:
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": "cat README.md"}}
    exit_code, stdout_json, stderr = _run_hook(payload, cwd=str(tmp_path))

    assert exit_code == 0
    assert stdout_json is None
    assert stderr == ""
    assert not (tmp_path / ".task-state" / "terminal_guard.jsonl").exists()


def test_non_terminal_tool_is_ignored(tmp_path: Path) -> None:
    payload = {"toolName": "read_file", "toolInput": {"command": "npx vitest run some.test.ts"}}
    exit_code, stdout_json, stderr = _run_hook(payload, cwd=str(tmp_path))

    assert exit_code == 0
    assert stdout_json is None
    assert stderr == ""


def test_malformed_payload_is_ignored() -> None:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input="not json",
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert proc.returncode == 0
    assert proc.stdout == ""
    assert proc.stderr == ""
