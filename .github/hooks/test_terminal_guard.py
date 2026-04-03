"""Tests for the PreToolUse terminal-guard hook.

The hook operates in three tiers:
  1. Allowlist     → exit 0, no JSON output (pass through silently)
  2. Hard block    → permissionDecision "block" (deterministic native-tool violations)
  3. Default deny  → permissionDecision "ask"  (not allowlisted; gray area)

Performance note: 77 of 85 tests call _check_command() directly (in-process, ~0ms each).
The remaining 8 tests use _run_hook() (subprocess) only where stdin/stdout/exit-code or
file I/O side-effects require full process isolation.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_SCRIPT = Path(__file__).parent / "terminal-guard.py"

# ---------------------------------------------------------------------------
# Direct import of _check_command for in-process classification tests.
# importlib is required because the filename contains a hyphen.
# ---------------------------------------------------------------------------

_spec = importlib.util.spec_from_file_location("terminal_guard", HOOK_SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
_check_command = _mod._check_command


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
    result = _check_command(command)
    assert result is not None, f"Expected a decision for: {command!r}"
    decision, native_tool, reason = result
    assert decision == "block", f"Expected 'block', got '{decision}' for: {command!r}"
    assert expected_tool in reason, f"Expected '{expected_tool}' in reason, got: {reason}"


# ---------------------------------------------------------------------------
# Tier 3: Default deny — commands not in the allowlist and not a known
# deterministic violation.  Hook must ask for confirmation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "echo hello",
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
    result = _check_command(command)
    assert result is not None, f"Expected JSON output for default-denied command: {command!r}"
    decision, _, _ = result
    assert decision == "ask", f"Expected 'ask' for default deny, got '{decision}' for: {command!r}"


def test_ls_is_allowlisted() -> None:
    assert _check_command("ls -la") is None, "ls -la should pass through silently"


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
        "${PYENV_ROOT:-$HOME/.pyenv}/versions/description-service/bin/python -u -m pytest tests/ -q | tail -n 40",
        "${PYENV_ROOT:-$HOME/.pyenv}/versions/description-service/bin/python -m pytest tests/test_lane_exec.py tests/test_lane_result.py -q",
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
        "cd ${REPO_ROOT:-$PWD} && make test-handoff",
        "cd /repo && pytest tests/ -x",
        "cd /repo && make test-handoff > /tmp/out.txt 2>&1; tail -5 /tmp/out.txt",
        # cd + export combo (VS Code prepends cd <workspace> && before agent commands)
        "cd ${REPO_ROOT:-$PWD} && export PYTHONPATH=packages/agent-handoff-mcp/src:packages/codex-subagent-bridge/src && pytest tests/ -v 2>&1 | tail -60",
        # Env-var prefixed commands
        "PYENV_VERSION=description-service pytest tests/ -x",
        "export PYTHONPATH=pkg/src && pytest tests/",
        'REPO_ROOT="${REPO_ROOT:-$PWD}" && PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" && PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest "$REPO_ROOT/packages/agent-handoff-mcp/tests/test_import_export_regressions.py" -q',
        # git ls-files: read-only file listing
        "git ls-files --others --exclude-standard -- apps/prototype-description-service/",
        # git log: read-only history queries
        "git log --oneline -n 5",
        "git log --format='%H %s' -n 4 | head -n 4",
        "git -C ${REPO_ROOT:-$PWD} log --oneline -n 5",
        # git rev-parse: read-only SHA / path resolution
        "git rev-parse HEAD",
        "git rev-parse --show-toplevel",
        "git -C ${REPO_ROOT:-$PWD} rev-parse HEAD",
        "pwd && git rev-parse --show-toplevel && git branch --show-current && git rev-parse --git-dir && git rev-parse --git-common-dir",
        # Read-only measurement
        "wc -l /tmp/bd_product_diff.patch",
        "wc -lw apps/prototype-description-service/recognition/domain/suggestion.py",
        # Pipe output-control patterns
        "pytest tests/ | tail -n 40",
        "make test 2>&1 | tail -n 30",
        # File deletion (non-recursive and recursive without force)
        "rm tests/test_pytest_progress_heartbeat.py",
        "rm /tmp/pytest_output.txt",
        "rm -r ${REPO_ROOT:-$PWD}/packages/agent-handoff-mcp/.hypothesis",
        "rm -r .hypothesis",
    ],
)
def test_allowlisted_commands_pass_through(command: str) -> None:
    """Allowlisted commands must pass through silently with no JSON output."""
    result = _check_command(command)
    assert result is None, f"Expected None for allowlisted command {command!r}, got: {result}"


# ---------------------------------------------------------------------------
# Allowlist boundary: git status -sb is allowed; bare git status is blocked.
# ---------------------------------------------------------------------------


def test_git_status_bare_is_blocked() -> None:
    result = _check_command("git status")
    assert result is not None
    decision, _, _ = result
    assert decision == "block"


def test_git_status_sb_is_allowed() -> None:
    assert _check_command("git status -sb") is None, "git status -sb should pass through silently"


# ---------------------------------------------------------------------------
# rm boundary: rm and rm -r allowed; rm -rf / rm -fr / rm -r -f denied.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /some/dir",
        "rm -fr /some/dir",
        "rm -r -f /some/dir",
    ],
)
def test_rm_force_is_denied(command: str) -> None:
    result = _check_command(command)
    assert result is not None, f"Expected denial for {command!r}"


def test_rm_recursive_without_force_is_allowed() -> None:
    assert _check_command("rm -r .hypothesis") is None


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/ -q 2>&1 | tee /tmp/pytest_output.txt",
        "vendor/bin/phpunit tests/Unit/SnapshotProjectorTest.php | tee /tmp/phpunit_snapshot.txt",
        "npx vitest run js/admin/hooks/__tests__/useClusterSelection.test.ts | tee /tmp/vitest_selection.txt",
    ],
)
def test_tee_commands_require_confirmation(command: str) -> None:
    result = _check_command(command)
    assert result is not None, f"Expected tee command to require confirmation: {command!r}"
    decision, _, reason = result
    assert decision == "ask"
    assert "tee" in reason


# ---------------------------------------------------------------------------
# /tmp/ path boundary: tail on redirect output is allowed; on source files blocked.
# ---------------------------------------------------------------------------


def test_tail_tmp_file_is_not_hard_blocked() -> None:
    """tail -n N /tmp/output.txt (redirect reads) must NOT hard-block; it gets default-deny (ask)."""
    result = _check_command("tail -n 5 /tmp/guard_tests.txt")
    assert result is not None, "tail on /tmp/ should still trigger default-deny"
    decision, _, _ = result
    assert decision == "ask"


def test_tail_source_file_is_blocked() -> None:
    """tail -n N on a workspace source file must still hard-block."""
    result = _check_command("tail -n 20 src/main.py")
    assert result is not None
    decision, _, _ = result
    assert decision == "block"


# ---------------------------------------------------------------------------
# Telemetry: blocked and default-denied commands must be logged.
# These tests require subprocess isolation (file I/O side-effects).
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
# Schema / robustness — these tests exercise main() and require subprocess.
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
