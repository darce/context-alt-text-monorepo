#!/usr/bin/env python3
"""PreToolUse hook: block the raw Vitest command that strands VS Code chat.

This hook is intentionally narrow. It does not enforce general terminal
discipline, native-tool preferences, or an allowlist. Its only job is to stop
the known-bad ``vitest run`` / ``npx vitest run`` command shape and point agents
at the repo-local wrapper that returns control to chat.

Exit codes
----------
Always 0. VS Code applies ``permissionDecision`` from stdout JSON only when the
hook process exits cleanly.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path


RAW_VITEST_RUN_RE = re.compile(r"^(?:npx\s+)?vitest\s+run(?:\s|$)")
SHELL_SEGMENT_RE = re.compile(r"\s*(?:&&|\|\||[;|&])\s*")


def _strip_env_prefix(cmd: str) -> str:
    """Strip simple navigation/env prefixes before matching the real command."""
    s = cmd.strip()
    prefix_patterns = [
        r"^setopt(?:\s+\S+)+\s*&&\s*",
        r"^cd\s+\S+\s*&&\s*",
        r"^export\s+\w+=\S+\s*&&\s*",
        r'^\w+=(?:"[^"]*"|\'[^\']*\'|\S*)\s*&&\s*',
        r'^(?:\w+=(?:"[^"]*"|\'[^\']*\'|\S*)\s+)+',
        r"^\w+=\S*\s*&&\s*",
        r"^(\w+=\S*\s+)+",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in prefix_patterns:
            new = re.sub(pattern, "", s)
            if new != s:
                s = new
                changed = True
                break
    return s


def _base_command(cmd: str) -> str:
    """Return the command segment before shell control operators."""
    return re.split(r"[|;&]", cmd, maxsplit=1)[0].strip()


def _raw_vitest_segment(cmd: str) -> str | None:
    """Return the raw Vitest segment, even after a leading no-op command."""
    for segment in SHELL_SEGMENT_RE.split(cmd):
        segment = _strip_env_prefix(segment.strip())
        if RAW_VITEST_RUN_RE.match(segment):
            return segment
    return None


def _log_telemetry(command: str, decision: str, trigger: str) -> None:
    """Best-effort append of a blocked event to .task-state/terminal_guard.jsonl."""
    try:
        state_dir = Path(".task-state")
        state_dir.mkdir(exist_ok=True)
        record = {
            "timestamp": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            "command": command[:200],
            "decision": decision,
            "trigger": trigger,
        }
        with (state_dir / "terminal_guard.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _check_command(command: str) -> tuple[str, str, str] | None:
    """Return a block decision only for raw Vitest run commands."""
    stripped = _strip_env_prefix(command.strip())
    base = _raw_vitest_segment(stripped)
    if base is None:
        return None

    reason = (
        "[terminal-guard] BLOCKED: raw `vitest run` / `npx vitest run` can finish "
        "and still strand the VS Code chat terminal. Use "
        "`npm run test:agent -- <path>` for agent-chat Vitest runs, then read the "
        "output for pass/fail because the wrapper intentionally returns control to chat.\n"
        f"Command: {base[:120]!r}"
    )
    return "block", "npm run test:agent", reason


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = data.get("toolName") or data.get("tool_name") or ""
    if tool_name != "run_in_terminal":
        sys.exit(0)

    tool_input = data.get("toolInput") or data.get("tool_input") or {}
    command = (tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
    if not command:
        sys.exit(0)

    result = _check_command(command)
    if result is None:
        sys.exit(0)

    decision, trigger, reason = result
    _log_telemetry(command, decision, trigger)
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
    sys.exit(0)


if __name__ == "__main__":
    main()
