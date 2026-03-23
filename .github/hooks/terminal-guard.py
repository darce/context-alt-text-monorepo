#!/usr/bin/env python3
"""
PreToolUse hook: enforces terminal discipline using an allowlist-first, default-deny model.

Algorithm
---------
1. Allowlist (exit 0, no JSON output): command is an unambiguously legitimate terminal use.
2. Hard block (permissionDecision "block"): command has a deterministic native-tool equivalent.
3. Default deny (permissionDecision "ask"): command not in allowlist and not a known violation;
   requires human confirmation before proceeding.

Allowlisted terminal uses
-------------------------
- Tests: pytest, python -m pytest, npm test/run test, vitest, playwright, phpunit
- Build: make <target>
- pyenv
- Git write / coordination / history: commit, push, rebase, cherry-pick, worktree, stash,
  fetch, pull, log, checkout, merge, branch, tag, add, reset
- Git metadata reads: diff --name-only, diff --shortstat, status -sb (narrow forms only)

Everything else is default-denied.

Exit codes
----------
Always 0. VS Code parses stdout JSON on exit 0 and applies permissionDecision.
Exit 2 hard-blocks but discards the JSON reason; we avoid it to keep feedback useful.

Telemetry
---------
Every blocked or prompted command is appended to .task-state/terminal_guard.jsonl so
policy violations can be reviewed and the allowlist tuned from evidence.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Allowlist: commands whose terminal use is unambiguously correct.
# Patterns are anchored (^) and matched against the *base command* —
# the portion before the first pipe, after stripping env-var prefixes.
# ---------------------------------------------------------------------------

_ALLOWLIST: list[re.Pattern[str]] = [
    re.compile(p)
    for p in [
        # Tests
        r"^pytest\b",
        r"^python3?\s+-m\s+pytest\b",
        r"^npm\s+test\b",
        r"^npm\s+run\s+test\b",
        r"^vitest\b",
        r"^playwright\b",
        r"^phpunit\b",
        # Build
        r"^make\b",
        # pyenv
        r"^pyenv\b",
        # Git write / coordination / history
        r"^git\s+commit\b",
        r"^git\s+push\b",
        r"^git\s+rebase\b",
        r"^git\s+cherry-pick\b",
        r"^git\s+worktree\b",
        r"^git\s+stash\b",
        r"^git\s+fetch\b",
        r"^git\s+pull\b",
        r"^git\s+log\b",
        r"^git\s+checkout\b",
        r"^git\s+merge\b",
        r"^git\s+branch\b",
        r"^git\s+tag\b",
        r"^git\s+add\b",
        r"^git\s+reset\b",
        # git diff: metadata forms only (no full diff output)
        r"^git\s+diff\b.*--name-only\b",
        r"^git\s+diff\b.*--shortstat\b",
        # git status: narrow concise form only; bare 'git status' is hard-blocked below
        r"^git\s+status\s+-sb\b",
    ]
]


# ---------------------------------------------------------------------------
# Hard-block patterns: deterministic violations where a native VS Code tool
# is always better. Checked against the full command (including pipe sections).
# ---------------------------------------------------------------------------

_HARD_BLOCKS: list[tuple[re.Pattern[str], str, str]] = [
    # File reading
    (
        re.compile(r"\bcat\s+\S"),
        "read_file",
        "Read file contents with `read_file`, not `cat`.",
    ),
    (
        re.compile(r"\bsed\s+-n\b"),
        "read_file",
        "Read file lines with `read_file`, not `sed -n`.",
    ),
    (
        re.compile(
            # Exclude /tmp/ paths — those are legitimate redirect-output reads, not source reads.
            r"\bhead\s+(-n\s*\d+\s+)?(?!/tmp/)\S+\.(py|ts|tsx|js|jsx|php|md|json|toml|yaml|yml|txt)\b"
        ),
        "read_file",
        "Read a source file with `read_file`, not `head`.",
    ),
    (
        re.compile(
            # Exclude /tmp/ paths — those are legitimate redirect-output reads, not source reads.
            r"\btail\s+-n\s*\d+\s+(?!/tmp/)\S+\.(py|ts|tsx|js|jsx|php|md|json|toml|yaml|yml|txt)\b"
        ),
        "read_file",
        "Read a source file with `read_file`, not `tail`.",
    ),
    # Code search
    (
        re.compile(r"\bgrep\s+-[a-zA-Z]*[rRnliI]"),
        "grep_search",
        "Search code with `grep_search`, not `grep`.",
    ),
    (
        re.compile(r"\brg\s+"),
        "grep_search",
        "Search code with `grep_search`, not `rg`.",
    ),
    (
        re.compile(r"\bfind\s+\S+\s+-name\b"),
        "file_search",
        "Find files with `file_search`, not `find -name`.",
    ),
    # Git state reads — get_changed_files is always better in VS Code
    (
        re.compile(r"\bgit\s+diff\b"),
        "get_changed_files",
        "Inspect diffs with `get_changed_files`, not `git diff`.",
    ),
    (
        re.compile(r"\bgit\s+status\b"),
        "get_changed_files",
        "List changes with `get_changed_files`, not `git status`. "
        "Use `git status -sb` if you genuinely need the narrow terminal form.",
    ),
    # Lint / type checking
    (re.compile(r"\bmypy\b"), "get_errors", "Type-check with `get_errors`, not `mypy`."),
    (re.compile(r"\bpylint\b"), "get_errors", "Lint with `get_errors`, not `pylint`."),
    (re.compile(r"\bflake8\b"), "get_errors", "Lint with `get_errors`, not `flake8`."),
    (re.compile(r"\bruff\s+check\b"), "get_errors", "Lint with `get_errors`, not `ruff check`."),
    (
        re.compile(r"\bnpm\s+run\s+(lint|type-?check)\b"),
        "get_errors",
        "Run lint/typecheck with `get_errors`, not `npm run`.",
    ),
    (
        re.compile(r"\bphpstan\s+analys"),
        "get_errors",
        "Run PHPStan with `get_errors`, not the CLI.",
    ),
    (re.compile(r"\bphpcs\b"), "get_errors", "Run PHPCS with `get_errors`, not the CLI."),
    (re.compile(r"\beslint\b"), "get_errors", "Run ESLint with `get_errors`, not the CLI."),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_env_prefix(cmd: str) -> str:
    """Strip leading shell env-var assignments and navigation prefixes.

    Handles (in any combination/order):
      cd /absolute/path && make ...
      export PYTHONPATH=src && pytest ...
      PYENV_VERSION=x pytest ...
      cd /repo && export VAR=val && pytest ...
    """
    s = cmd.strip()
    _PREFIX_PATTERNS = [
        r"^cd\s+\S+\s*&&\s*",           # cd <path> &&
        r"^export\s+\w+=\S+\s*&&\s*",   # export VAR=value &&
        r"^(\w+=\S+\s+)+",              # VAR=value inline prefix tokens
    ]
    # Loop until no pattern matches (handles cd && export && <cmd>).
    changed = True
    while changed:
        changed = False
        for pat in _PREFIX_PATTERNS:
            new = re.sub(pat, "", s)
            if new != s:
                s = new
                changed = True
                break  # restart from first pattern after a strip
    return s


def _base_command(cmd: str) -> str:
    """Return the portion of a command before the first pipe."""
    return cmd.split("|")[0].strip()


def _log_telemetry(command: str, decision: str, trigger: str) -> None:
    """Best-effort append of a blocked/prompted event to .task-state/terminal_guard.jsonl."""
    try:
        state_dir = Path(".task-state")
        state_dir.mkdir(exist_ok=True)
        record = {
            "timestamp": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            "command": command[:200],
            "decision": decision,
            "trigger": trigger,
        }
        with (state_dir / "terminal_guard.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass  # telemetry is best-effort; must not crash the hook


def _check_command(command: str) -> tuple[str, str, str] | None:
    """Classify a terminal command.

    Returns (decision, native_tool, reason) when terminal use is disallowed:
      decision "block" — deterministic violation; a native tool is always better.
      decision "ask"   — not in allowlist; human confirmation required.
    Returns None when the command is allowlisted (pass through silently).
    """
    stripped = _strip_env_prefix(command.strip())
    base = _base_command(stripped)

    # 1. Allowlist: unambiguously correct terminal use.
    for pattern in _ALLOWLIST:
        if pattern.match(base):
            return None

    # 2. Hard block: deterministic native-tool equivalent.
    for pattern, native_tool, hint in _HARD_BLOCKS:
        if pattern.search(stripped):
            reason = (
                f"[terminal-guard] BLOCKED: {hint}\n"
                f"`{native_tool}` reads live IDE state and is always more reliable here.\n"
                f"Command: {base[:80]!r}"
            )
            return "block", native_tool, reason

    # 3. Default deny: unknown command not in allowlist.
    reason = (
        f"[terminal-guard] NOT IN ALLOWLIST: {base[:80]!r}\n"
        "Terminal is reserved for tests, make, approved git operations, and pyenv.\n"
        "If no native tool covers this operation, confirm to proceed."
    )
    return "ask", "native tools", reason


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # Unparseable input — do not block.

    # Handle both camelCase (VS Code) and snake_case (Claude Code) key names.
    tool_name: str = data.get("toolName") or data.get("tool_name") or ""
    if tool_name not in ("run_in_terminal",):
        sys.exit(0)

    tool_input = data.get("toolInput") or data.get("tool_input") or {}
    command: str = (tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
    if not command:
        sys.exit(0)

    result = _check_command(command)
    if result is None:
        sys.exit(0)  # Allowlisted — pass through silently.

    decision, native_tool, reason = result
    _log_telemetry(command, decision, native_tool)

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    # Always exit 0: VS Code parses stdout JSON only when the process exits cleanly.
    # permissionDecision "block" in the JSON is the hard-stop signal; exit 2 would
    # hard-block too but would discard the JSON reason, making diagnostics harder.
    sys.exit(0)


if __name__ == "__main__":
    main()
