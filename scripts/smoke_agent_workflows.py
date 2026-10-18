#!/usr/bin/env python3
"""Optional workflow-routing smoke checks for host-specific adapters."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Mapping


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_manifest_path() -> Path:
    repo_root = _repo_root()
    local_manifest = repo_root / "config" / "agent-workflows" / "portable_commands.json"
    if local_manifest.is_file():
        return local_manifest
    return (
        repo_root
        / ".workbay"
        / "remote"
        / "packages"
        / "workbay-system"
        / "config"
        / "agent-workflows"
        / "portable_commands.json"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=_default_manifest_path())
    parser.add_argument(
        "--backend",
        choices=("auto", "claude", "copilot", "codex"),
        default="auto",
        help="Host adapter surface to validate. 'auto' uses a best-effort environment probe and skips if unknown.",
    )
    parser.add_argument(
        "--command-id",
        action="append",
        dest="command_ids",
        help="Command id to validate. Defaults to branch-review and planning-review.",
    )
    return parser.parse_args()


def _load_manifest(path: Path) -> dict:
    payload = json.loads(path.read_text())
    commands = payload.get("commands", [])
    if not isinstance(commands, list):
        raise SystemExit(f"{path} must contain a commands list.")
    return payload


def _detect_backend(env: Mapping[str, str]) -> str | None:
    term_program = env.get("TERM_PROGRAM", "").lower()
    if "vscode" in term_program or env.get("VSCODE_GIT_IPC_HANDLE"):
        return "copilot"
    if env.get("CLAUDECODE") or env.get("CLAUDE_CONFIG_DIR"):
        return "claude"
    if env.get("CODEX_SANDBOX") or env.get("CODEX_HOME"):
        return "codex"
    return None


def _manifest_expectations(manifest: dict, command_ids: list[str]) -> dict[str, tuple[str, str]]:
    commands = {command["command_id"]: command for command in manifest["commands"]}
    expectations: dict[str, tuple[str, str]] = {}
    for command_id in command_ids:
        command = commands.get(command_id)
        if command is None:
            raise SystemExit(f"command_id {command_id!r} not found in manifest")
        expectations[command_id] = (command["skill"], command["makefile_target"])
    return expectations


def _parse_line(pattern: str, content: str, source: Path) -> str:
    match = re.search(pattern, content, re.MULTILINE)
    if match is None:
        raise ValueError(f"{source}: missing expected pattern {pattern!r}")
    return match.group(1)


def _resolve_claude(repo_root: Path, command_id: str) -> tuple[str, str]:
    source = repo_root / ".claude" / "commands" / f"{command_id}.md"
    content = source.read_text()
    skill = _parse_line(r"^Active skill: `([^`]+)`$", content, source)
    target = _parse_line(r"^Makefile entry point: `([^`]+)`$", content, source)
    return skill, target


def _resolve_copilot(repo_root: Path, command_id: str) -> tuple[str, str]:
    source = repo_root / ".github" / "prompts" / f"{command_id}.prompt.md"
    content = source.read_text()
    skill = _parse_line(r"^Load the `([^`]+)` skill for this workflow\.$", content, source)
    target = _parse_line(r"^Makefile entry point: `([^`]+)`$", content, source)
    return skill, target


def _resolve_codex(repo_root: Path, command_id: str) -> tuple[str, str]:
    source = repo_root / "docs" / "workbay" / "generated" / "codex-command-router.md"
    content = source.read_text()
    pattern = rf"^\- `/{re.escape(command_id)}`(?: \([^)]+\))? -> skill `([^`]+)` -> `([^`]+)`$"
    match = re.search(pattern, content, re.MULTILINE)
    if match is None:
        raise ValueError(f"{source}: missing command map entry for /{command_id}")
    return match.group(1), match.group(2)


def smoke_agent_workflows(
    repo_root: Path,
    manifest_path: Path,
    backend: str = "auto",
    command_ids: list[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[list[str], str | None]:
    command_ids = command_ids or ["branch-review", "planning-review"]
    env = os.environ if env is None else env
    manifest = _load_manifest(manifest_path)
    expectations = _manifest_expectations(manifest, command_ids)

    resolved_backend = backend
    if backend == "auto":
        resolved_backend = _detect_backend(env)
        if resolved_backend is None:
            return [], None

    resolvers = {
        "claude": _resolve_claude,
        "copilot": _resolve_copilot,
        "codex": _resolve_codex,
    }
    resolver = resolvers[resolved_backend]
    failures: list[str] = []
    for command_id, expected in expectations.items():
        try:
            actual = resolver(repo_root, command_id)
        except (FileNotFoundError, ValueError) as exc:
            failures.append(str(exc))
            continue
        if actual != expected:
            failures.append(
                f"/{command_id} resolved as skill={actual[0]!r}, target={actual[1]!r}; expected skill={expected[0]!r}, target={expected[1]!r}"
            )
    return failures, resolved_backend


def main() -> int:
    args = _parse_args()
    repo_root = _repo_root()
    failures, resolved_backend = smoke_agent_workflows(
        repo_root=repo_root,
        manifest_path=args.manifest,
        backend=args.backend,
        command_ids=args.command_ids,
    )
    if resolved_backend is None:
        print("- smoke-agent-workflows: skipped (could not auto-detect backend; pass --backend claude|copilot|codex)")
        return 0
    if failures:
        print(f"workflow smoke check failed for backend {resolved_backend}:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    command_ids = args.command_ids or ["branch-review", "planning-review"]
    rendered = ", ".join(f"/{command_id}" for command_id in command_ids)
    print(f"✓ smoke-agent-workflows: {resolved_backend} resolves {rendered} via the manifest contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())