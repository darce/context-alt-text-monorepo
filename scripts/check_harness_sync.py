#!/usr/bin/env python3
"""Check shared Claude/VS Code harness surfaces against harness-protocol.yaml.

The contract at ``docs/agentic/contracts/harness-protocol.yaml`` defines four
sections that every managed harness must keep in sync:

* ``cold_start.shared_steps``   — phrases that must appear in each shared
                                  cold-start doc (CLAUDE.md, copilot
                                  instructions).
* ``branch_isolation``          — protected branches, code roots, and file
                                  extensions that every enforcer script must
                                  reference.
* ``hooks``                     — matcher+command pairs that each harness
                                  settings file must list.
* ``python_api_fallback``       — package-root symbols the Python fallback
                                  surface must export (checked when
                                  ``--check-api-surface`` is passed).

The validator fails fast with a named error for any drift between the contract
and the committed surface.
"""

from __future__ import annotations

import ast
import json
import re
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


def _check_hooks(contract: dict, *, repo_root: Path = REPO_ROOT) -> list[str]:
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


def _check_cold_start(contract: dict, *, repo_root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []
    steps = ((contract.get("cold_start") or {}).get("shared_steps")) or []
    if not isinstance(steps, list):
        return ["cold_start.shared_steps must be a list"]
    cache: dict[Path, str] = {}
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"cold_start.shared_steps[{idx}] must be a mapping with id/phrase/references")
            continue
        step_id = step.get("id") or f"<index {idx}>"
        phrase = step.get("phrase")
        references = step.get("references")
        if not isinstance(phrase, str) or not phrase:
            errors.append(f"cold_start: step `{step_id}` missing non-empty `phrase`")
            continue
        if not isinstance(references, list) or not references:
            errors.append(f"cold_start: step `{step_id}` missing non-empty `references`")
            continue
        for reference in references:
            if not isinstance(reference, str) or not reference:
                errors.append(f"cold_start: step `{step_id}` has invalid reference entry")
                continue
            full = repo_root / reference
            if not full.exists():
                errors.append(f"cold_start: reference `{reference}` for step `{step_id}` not found")
                continue
            text = cache.get(full)
            if text is None:
                text = full.read_text()
                cache[full] = text
            if phrase not in text:
                errors.append(
                    f"cold_start: `{reference}` does not contain phrase `{phrase}` for step `{step_id}`"
                )
    return errors


def _token_present(token: str, text: str) -> bool:
    """Return True when *token* appears as a literal OR a word-bounded form.

    The protected-extension contract uses dot-prefixed forms (".py") but some
    harness enforcers encode the extensions inside a regex alternation
    (``\\.(py|ts|tsx|...)``) where the dot is shared and each token appears
    bare. Treat either form as a valid reference.
    """
    if token in text:
        return True
    stripped = token.lstrip(".")
    if not stripped:
        return False
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(stripped)}(?![A-Za-z0-9_])"
    return re.search(pattern, text) is not None


def _check_branch_isolation(contract: dict, *, repo_root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []
    spec = contract.get("branch_isolation")
    if not isinstance(spec, dict):
        return ["branch_isolation must be a mapping"]
    protected_branches = spec.get("protected_branches") or []
    code_roots = spec.get("code_roots") or []
    protected_extensions = spec.get("protected_extensions") or []
    enforcers = spec.get("enforcers") or []
    if not isinstance(enforcers, list) or not enforcers:
        return ["branch_isolation.enforcers must be a non-empty list"]
    for idx, enforcer in enumerate(enforcers):
        if not isinstance(enforcer, dict):
            errors.append(f"branch_isolation.enforcers[{idx}] must be a mapping with a `path`")
            continue
        path = enforcer.get("path")
        harness = enforcer.get("harness") or "?"
        if not isinstance(path, str) or not path:
            errors.append(f"branch_isolation.enforcers[{idx}] missing non-empty `path`")
            continue
        full = repo_root / path
        if not full.exists():
            errors.append(f"branch_isolation: enforcer `{path}` ({harness}) not found")
            continue
        text = full.read_text()
        for branch in protected_branches:
            if not isinstance(branch, str):
                errors.append(f"branch_isolation: protected_branches entries must be strings")
                continue
            if branch not in text:
                errors.append(
                    f"branch_isolation: `{path}` ({harness}) does not reference protected branch `{branch}`"
                )
        for root in code_roots:
            if not isinstance(root, str):
                errors.append(f"branch_isolation: code_roots entries must be strings")
                continue
            if root not in text:
                errors.append(
                    f"branch_isolation: `{path}` ({harness}) does not reference code root `{root}`"
                )
        for ext in protected_extensions:
            if not isinstance(ext, str):
                errors.append(f"branch_isolation: protected_extensions entries must be strings")
                continue
            if not _token_present(ext, text):
                errors.append(
                    f"branch_isolation: `{path}` ({harness}) does not reference protected extension `{ext}`"
                )
    return errors


def _check_python_api_surface(contract: dict) -> list[str]:
    exports = _load_python_exports()
    required = set(contract.get("python_api_fallback", {}).get("required_exports", []))
    missing = sorted(required - exports)
    return [f"missing agent_handoff_mcp export `{name}`" for name in missing]


def run_checks(contract: dict, *, check_api_surface: bool = False, repo_root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []
    errors.extend(_check_hooks(contract, repo_root=repo_root))
    errors.extend(_check_cold_start(contract, repo_root=repo_root))
    errors.extend(_check_branch_isolation(contract, repo_root=repo_root))
    if check_api_surface:
        errors.extend(_check_python_api_surface(contract))
    return errors


def main(argv: list[str]) -> int:
    check_api_surface = "--check-api-surface" in argv
    contract = _load_contract()
    errors = run_checks(contract, check_api_surface=check_api_surface)
    if errors:
        print("check-harness-sync: FAILED", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("check-harness-sync: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
