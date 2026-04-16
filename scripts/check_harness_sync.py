#!/usr/bin/env python3
"""Check shared Claude/VS Code harness surfaces against harness-protocol.yaml."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "docs" / "agentic" / "contracts" / "harness-protocol.yaml"
CLAUDE_HOOKS_PATH = REPO_ROOT / ".claude" / "settings.json"
VSCODE_HOOKS_PATH = REPO_ROOT / ".github" / "hooks" / "terminal-guard.json"
PYTHON_EXPORTS_PATH = REPO_ROOT / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp" / "__init__.py"


def _load_contract() -> dict:
    payload = yaml.safe_load(CONTRACT_PATH.read_text()) or {}
    if not isinstance(payload, dict):
        raise ValueError("harness-protocol.yaml must parse to a mapping")
    return payload


def _flatten_claude_entries(stage_entries: list[dict]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for entry in stage_entries:
        matcher = entry.get("matcher", "")
        for hook in entry.get("hooks", []):
            command = hook.get("command")
            if matcher and isinstance(command, str):
                found.add((matcher, command))
    return found


def _flatten_vscode_entries(stage_entries: list[dict]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for entry in stage_entries:
        matcher = entry.get("matcher", "")
        hooks = entry.get("hooks")
        if isinstance(hooks, list):
            for hook in hooks:
                command = hook.get("command")
                if matcher and isinstance(command, str):
                    found.add((matcher, command))
            continue
        command = entry.get("command")
        if matcher and isinstance(command, str):
            found.add((matcher, command))
    return found


def _load_hook_pairs() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    claude_payload = json.loads(CLAUDE_HOOKS_PATH.read_text())
    vscode_payload = json.loads(VSCODE_HOOKS_PATH.read_text())
    claude_hooks = claude_payload["hooks"]
    vscode_hooks = vscode_payload["hooks"]
    return (
        _flatten_claude_entries(claude_hooks["PreToolUse"]) | _flatten_claude_entries(claude_hooks["PostToolUse"]),
        _flatten_vscode_entries(vscode_hooks["PreToolUse"]) | _flatten_vscode_entries(vscode_hooks["PostToolUse"]),
    )


def _load_python_exports() -> set[str]:
    module = ast.parse(PYTHON_EXPORTS_PATH.read_text(), filename=str(PYTHON_EXPORTS_PATH))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if not isinstance(node.value, (ast.List, ast.Tuple)):
                        raise ValueError("__all__ must be a list or tuple literal")
                    exports: set[str] = set()
                    for elt in node.value.elts:
                        if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
                            raise ValueError("__all__ must contain only string literals")
                        exports.add(elt.value)
                    return exports
    raise ValueError("agent_handoff_mcp.__all__ not found")


def _check_hooks(contract: dict) -> list[str]:
    claude_pairs, vscode_pairs = _load_hook_pairs()
    errors: list[str] = []
    hook_spec = contract.get("hooks", {})
    for stage in ("pre_tool_use", "post_tool_use"):
        for item in hook_spec.get(stage, []):
            matcher = item["matcher"]
            claude_command = item["claude_command"]
            vscode_command = item["vscode_command"]
            if (matcher, claude_command) not in claude_pairs:
                errors.append(f"missing Claude hook `{item['id']}` ({stage})")
            if (matcher, vscode_command) not in vscode_pairs:
                errors.append(f"missing VS Code hook `{item['id']}` ({stage})")
    return errors


def _check_python_api_surface(contract: dict) -> list[str]:
    exports = _load_python_exports()
    required = set(contract.get("python_api_fallback", {}).get("required_exports", []))
    missing = sorted(required - exports)
    return [f"missing agent_handoff_mcp export `{name}`" for name in missing]


def main(argv: list[str]) -> int:
    check_api_surface = "--check-api-surface" in argv
    contract = _load_contract()
    errors = _check_hooks(contract)
    if check_api_surface:
        errors.extend(_check_python_api_surface(contract))
    if errors:
        print("check-harness-sync: FAILED", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("check-harness-sync: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
