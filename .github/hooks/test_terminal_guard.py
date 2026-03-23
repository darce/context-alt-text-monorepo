"""Tests for the PreToolUse terminal-guard hook.

The hook operates in three tiers:
  1. Allowlist     → exit 0, no JSON output (pass through silently)
  2. Hard block    → permissionDecision "block" (deterministic native-tool violations)
  3. Default deny  → permissionDecision "ask"  (not allowlisted; gray area)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_SCRIPT = Path(__file__).parent / "terminal-guard.py"


def _run_hook(payload: dict, cwd: str | None = None) -> tuple[int, dict | None]:
    """Run the hook script with *payload* on stdin. Return (exit_code, parsed_stdout_or_None)."""
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        cwd=cwd,
    )
    stdout_json = None
    if proc.stdout.strip():
        stdout_json = json.loads(proc.stdout)
    return proc.returncode, stdout_json


# ---------------------------------------------------------------------------
# Tier 2: Hard-block violations — commands with a deterministic native-tool
# equivalent.  Hook must emit permissionDecision "block".
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command,expected_tool",
    [
        # File reading
        ("cat README.md", "read_file"),
        ("cat apps/prototype-description-service/pyproject.toml", "read_file"),
        ("sed -n '10,20p' somefile.py", "read_file"),
        ("head -n 50 src/main.ts", "read_file"),
        ("tail -n 20 src/main.py", "read_file"),
        # Code search
        ("grep -rn 'pattern' src/", "grep_search"),
        ("grep -rnI 'something' .", "grep_search"),
        ("rg 'pattern' src/", "grep_search"),
        ("find . -name '*.py'", "file_search"),
        # Git state reads
        ("git diff HEAD", "get_changed_files"),
        ("git diff", "get_changed_files"),
        ("git status", "get_changed_files"),
        # Lint / type checking
        ("mypy apps/prototype-description-service/", "get_errors"),
        ("npm run lint", "get_errors"),
        ("npm run type-check", "get_errors"),
        ("eslint src/", "get_errors"),
        ("phpstan analyse src/", "get_errors"),
        ("ruff check .", "get_errors"),
    ],
)
def test_hard_block_violations(command: str, expected_tool: str) -> None:
    """Deterministic violations must be hard-blocked (not just advisory)."""
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": command}}
    exit_code, output = _run_hook(payload)
    assert exit_code == 0, f"Expected exit 0, got {exit_code}"
    assert output is not None, "Expected JSON output for violation"
    decision = output["hookSpecificOutput"]["permissionDecision"]
    assert decision == "block", f"Expected 'block', got '{decision}' for: {command!r}"
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert expected_tool in reason, f"Expected '{expected_tool}' in reason, got: {reason}"


# ---------------------------------------------------------------------------
# Tier 3: Default deny — commands not in the allowlist and not a known
# deterministic violation.  Hook must ask for confirmation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "echo hello",
        "ls -la",
        "cd /tmp",
        "python --version",
        "python script.py",
        "curl https://example.com",
        "pip install requests",
        "node index.js",
    ],
)
def test_default_deny_unknown_commands(command: str) -> None:
    """Unknown commands not in the allowlist must be default-denied (ask)."""
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": command}}
    exit_code, output = _run_hook(payload)
    assert exit_code == 0
    assert output is not None, f"Expected JSON output for default-denied command: {command!r}"
    decision = output["hookSpecificOutput"]["permissionDecision"]
    assert decision == "ask", f"Expected 'ask' for default deny, got '{decision}' for: {command!r}"


# ---------------------------------------------------------------------------
# Tier 1: Allowlist — commands whose terminal use is unambiguously correct.
# Hook must pass through silently (exit 0, no JSON output).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        # Tests
        "pytest apps/prototype-description-service/ -x",
        "python -m pytest tests/ -v",
        "python3 -m pytest tests/ -v",
        "npm test",
        "npm run test",
        "vitest run",
        "phpunit tests/",
        # Build
        "make test-handoff",
        "make lint",
        # pyenv
        "pyenv install 3.12.7",
        # Git write / coordination / history
        "git commit -m 'fix something'",
        "git push origin main",
        "git rebase -i HEAD~3",
        "git cherry-pick abc123",
        "git worktree add ../lane -b codex/task-lane",
        "git stash",
        "git log --oneline -5",
        "git fetch origin",
        "git pull --rebase",
        "git checkout main",
        "git merge feature-branch",
        "git branch -d old-branch",
        "git tag v1.0.0",
        "git add .",
        "git rm path/to/file.py",
        "git reset HEAD~1",
        # git diff: metadata forms only
        "git diff --name-only HEAD",
        "git diff --shortstat HEAD",
        # git status: narrow concise form only
        "git status -sb",
        # cd <path> && <allowlisted command> navigation prefix
        "cd /Users/daniel/Development/context-alt-text-monorepo && make test-handoff",
        "cd /repo && pytest tests/ -x",
        "cd /repo && make test-handoff > /tmp/out.txt 2>&1; tail -5 /tmp/out.txt",
        # cd + export combo (VS Code prepends cd <workspace> && before agent commands)
        "cd /Users/daniel/Development/context-alt-text-monorepo && export PYTHONPATH=packages/agent-handoff-mcp/src:packages/codex-subagent-bridge/src && pytest tests/ -v 2>&1 | tail -60",
        # Env-var prefixed commands
        "PYENV_VERSION=description-service pytest tests/ -x",
        "export PYTHONPATH=pkg/src && pytest tests/",
        # git ls-files: read-only file listing
        "git ls-files --others --exclude-standard -- apps/prototype-description-service/",
        # git log: read-only history queries
        "git log --oneline -n 5",
        "git log --format='%H %s' -n 4 | head -n 4",
        "git -C /Users/daniel/Development/context-alt-text-monorepo log --oneline -n 5",
        # git rev-parse: read-only SHA / path resolution
        "git rev-parse HEAD",
        "git rev-parse --show-toplevel",
        "git -C /Users/daniel/Development/context-alt-text-monorepo rev-parse HEAD",
        # Read-only measurement
        "wc -l /tmp/bd_product_diff.patch",
        "wc -lw apps/prototype-description-service/recognition/domain/suggestion.py",
        # Pipe output-control patterns
        "pytest tests/ | tail -n 40",
        "make test 2>&1 | tail -n 30",
    ],
)
def test_allowlisted_commands_pass_through(command: str) -> None:
    """Allowlisted commands must pass through silently with no JSON output."""
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": command}}
    exit_code, output = _run_hook(payload)
    assert exit_code == 0, f"Expected exit 0, got {exit_code}"
    assert output is None, f"Expected no JSON output for allowlisted command {command!r}, got: {output}"


# ---------------------------------------------------------------------------
# Allowlist boundary: git status -sb is allowed; bare git status is blocked.
# ---------------------------------------------------------------------------


def test_git_status_bare_is_blocked() -> None:
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": "git status"}}
    _, output = _run_hook(payload)
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "block"


def test_git_status_sb_is_allowed() -> None:
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": "git status -sb"}}
    _, output = _run_hook(payload)
    assert output is None, "git status -sb should pass through silently"


# ---------------------------------------------------------------------------
# /tmp/ path boundary: tail on redirect output is allowed; on source files blocked.
# ---------------------------------------------------------------------------


def test_tail_tmp_file_is_not_hard_blocked() -> None:
    """tail -n N /tmp/output.txt (redirect reads) must NOT hard-block; it gets default-deny (ask)."""
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": "tail -n 5 /tmp/guard_tests.txt"}}
    _, output = _run_hook(payload)
    assert output is not None, "tail on /tmp/ should still trigger default-deny"
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_tail_source_file_is_blocked() -> None:
    """tail -n N on a workspace source file must still hard-block."""
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": "tail -n 20 src/main.py"}}
    _, output = _run_hook(payload)
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "block"


# ---------------------------------------------------------------------------
# Telemetry: blocked and default-denied commands must be logged.
# ---------------------------------------------------------------------------


def test_telemetry_written_on_hard_block(tmp_path: Path) -> None:
    """Hard-blocked commands must be appended to .task-state/terminal_guard.jsonl."""
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": "cat README.md"}}
    _run_hook(payload, cwd=str(tmp_path))

    log_file = tmp_path / ".task-state" / "terminal_guard.jsonl"
    assert log_file.exists(), "Telemetry log not created"
    record = json.loads(log_file.read_text().strip())
    assert record["decision"] == "block"
    assert record["trigger"] == "read_file"
    assert "cat README.md" in record["command"]
    assert "timestamp" in record


def test_telemetry_written_on_default_deny(tmp_path: Path) -> None:
    """Default-denied commands must also be logged."""
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": "echo hello"}}
    _run_hook(payload, cwd=str(tmp_path))

    log_file = tmp_path / ".task-state" / "terminal_guard.jsonl"
    assert log_file.exists(), "Telemetry log not created for default-deny"
    record = json.loads(log_file.read_text().strip())
    assert record["decision"] == "ask"
    assert "echo hello" in record["command"]


def test_telemetry_not_written_on_allowlist(tmp_path: Path) -> None:
    """Allowlisted commands must NOT be written to the telemetry log."""
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": "make test-handoff"}}
    _run_hook(payload, cwd=str(tmp_path))

    log_file = tmp_path / ".task-state" / "terminal_guard.jsonl"
    assert not log_file.exists(), "Telemetry log should not be created for allowlisted commands"


# ---------------------------------------------------------------------------
# Schema / robustness
# ---------------------------------------------------------------------------


def test_camelcase_payload_schema() -> None:
    """VS Code sends camelCase keys; the hook must handle them."""
    payload = {"toolName": "run_in_terminal", "toolInput": {"command": "cat README.md"}}
    _, output = _run_hook(payload)
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "block"


def test_non_terminal_tool_passes_through() -> None:
    payload = {"tool_name": "read_file", "tool_input": {"filePath": "README.md"}}
    exit_code, output = _run_hook(payload)
    assert exit_code == 0
    assert output is None


def test_empty_stdin_does_not_crash() -> None:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input="",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 0


def test_invalid_json_does_not_crash() -> None:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input="not json at all",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 0


def test_missing_tool_input_does_not_crash() -> None:
    payload = {"tool_name": "run_in_terminal"}
    exit_code, output = _run_hook(payload)
    assert exit_code == 0
    assert output is None
