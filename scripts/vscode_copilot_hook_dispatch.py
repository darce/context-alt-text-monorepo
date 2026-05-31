#!/usr/bin/env python3
"""Single VS Code Copilot hook entry point for Workstate guards.

VS Code currently loads hook files but ignores matcher values, so registering
each Workstate guard as a separate hook makes every guard appear for every tool
call. This dispatcher keeps VS Code to one hook while preserving the same
tool-name routing before it invokes the underlying guard scripts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

FILE_MUTATION_TOOLS = {
    "Edit",
    "Write",
    "apply_patch",
    "create_file",
    "replace_string_in_file",
    "multi_replace_string_in_file",
}


def _tool_name(payload: dict[str, Any]) -> str:
    value = payload.get("tool_name") or payload.get("toolName") or ""
    return value if isinstance(value, str) else ""


def _is_file_mutation(tool_name: str) -> bool:
    return tool_name in FILE_MUTATION_TOOLS


def _is_bash(tool_name: str) -> bool:
    return tool_name == "Bash"


def _contains(*fragments: str) -> Callable[[str], bool]:
    return lambda tool_name: any(fragment in tool_name for fragment in fragments)


def _script(relative_path: str) -> Path:
    return REPO_ROOT / relative_path


PRE_TOOL_RULES: tuple[tuple[Callable[[str], bool], str], ...] = (
    (_is_file_mutation, ".github/hooks/guard-worktree-drift.py"),
    (_is_file_mutation, ".github/hooks/guard-main-branch.py"),
    (_is_bash, "scripts/hooks/guard-bash-main-branch.py"),
    (_is_file_mutation, "scripts/hooks/guard-task-plan-findings.py"),
    (
        _contains("record_event", "review_findings", "review_runs"),
        "scripts/hooks/validate-mcp-dict-params.py",
    ),
    (_contains("record_event", "close_slice"), "scripts/hooks/guard-rationale-size.py"),
)

POST_TOOL_RULES: tuple[tuple[Callable[[str], bool], str], ...] = (
    (_is_file_mutation, "scripts/hooks/record-file-touch.py"),
    (_contains("review_findings"), "scripts/hooks/ace-detect.py"),
    (
        _contains("get_handoff_state", "load_session", "render_handoff"),
        "scripts/hooks/slim-handoff-response.py",
    ),
    (_is_bash, "scripts/hooks/filter-test-output.py"),
)


def _run_script(script: Path, payload_text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        input=payload_text,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _permission_decision(parsed: dict[str, Any]) -> str | None:
    output = parsed.get("hookSpecificOutput")
    if not isinstance(output, dict):
        return None
    decision = output.get("permissionDecision")
    return decision if isinstance(decision, str) else None


def _additional_context(parsed: dict[str, Any]) -> str | None:
    output = parsed.get("hookSpecificOutput")
    if not isinstance(output, dict):
        return None
    context = output.get("additionalContext")
    return context if isinstance(context, str) and context.strip() else None


def _emit_process_output(proc: subprocess.CompletedProcess[str]) -> None:
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)


def dispatch(event: str, payload_text: str) -> int:
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    rules = PRE_TOOL_RULES if event == "pre-tool-use" else POST_TOOL_RULES
    tool_name = _tool_name(payload)
    context_messages: list[str] = []

    for predicate, relative_script in rules:
        if not predicate(tool_name):
            continue
        proc = _run_script(_script(relative_script), payload_text)
        parsed = _parse_json_object(proc.stdout)

        if proc.returncode != 0:
            _emit_process_output(proc)
            return proc.returncode

        if parsed is None:
            if proc.stdout.strip():
                sys.stdout.write(proc.stdout)
            if proc.stderr:
                sys.stderr.write(proc.stderr)
            continue

        decision = _permission_decision(parsed)
        if decision in {"block", "deny", "ask"}:
            print(json.dumps(parsed))
            return 0

        context = _additional_context(parsed)
        if context:
            context_messages.append(context)

    if context_messages:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse" if event == "pre-tool-use" else "PostToolUse",
                        "additionalContext": "\n\n".join(context_messages),
                    }
                }
            )
        )

    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or args[0] not in {"pre-tool-use", "post-tool-use"}:
        print("usage: vscode_copilot_hook_dispatch.py pre-tool-use|post-tool-use", file=sys.stderr)
        return 2
    return dispatch(args[0], sys.stdin.read())


if __name__ == "__main__":
    raise SystemExit(main())
