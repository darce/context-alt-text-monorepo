#!/usr/bin/env python3
"""PreToolUse drift guard: block wrong-worktree edits by default."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _harness_protocol import HarnessContractMissingError, find_permitted_main_surface, load_branch_isolation_policy


MAIN_BRANCHES = frozenset({"main", "master"})
PACKAGE_SRC = Path(__file__).resolve().parents[2] / "packages" / "agent-handoff-mcp" / "src"
PACKAGE_ROOT = PACKAGE_SRC / "agent_handoff_mcp"
TRACE_LOG_NAME = "branch_isolation_guard.jsonl"

if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))


@dataclass(frozen=True)
class ActiveTaskContext:
    task_ref: str | None
    target_worktree: str | None
    target_branch: str | None
    primary_worktree: str


@dataclass(frozen=True)
class DriftDecision:
    outcome: str
    reason: str | None = None
    primary_worktree: str | None = None
    path: str | None = None
    candidate_worktree: str | None = None
    target_worktree: str | None = None
    task_ref: str | None = None
    repo_relative_path: str | None = None
    matched_pattern: str | None = None
    matched_reason: str | None = None


def _payload_value(payload: dict[str, Any], snake_key: str, camel_key: str, default: Any = "") -> Any:
    if snake_key in payload and payload[snake_key] not in (None, ""):
        return payload[snake_key]
    if camel_key in payload and payload[camel_key] not in (None, ""):
        return payload[camel_key]
    return default


def _extract_candidate_paths(tool_name: str, tool_input: dict[str, Any]) -> list[str]:
    if not tool_name:
        file_path = _payload_value(tool_input, "file_path", "filePath")
        return [str(file_path)] if isinstance(file_path, str) and file_path.strip() else []

    if tool_name in {
        "Edit",
        "Write",
        "create_file",
        "replace_string_in_file",
        "multi_replace_string_in_file",
    }:
        file_path = _payload_value(tool_input, "file_path", "filePath")
        return [str(file_path)] if isinstance(file_path, str) and file_path.strip() else []

    if tool_name != "apply_patch":
        return []

    patch_input = tool_input.get("input")
    if not isinstance(patch_input, str) or not patch_input.strip():
        return []

    paths: list[str] = []
    for line in patch_input.splitlines():
        if not line.startswith("*** ") or " File: " not in line:
            continue
        _, raw_path = line.split(" File: ", 1)
        parsed_path = raw_path.split(" -> ", 1)[0].strip()
        if parsed_path:
            paths.append(parsed_path)
    return paths


def _load_handoff_exports() -> tuple[Any, Any, Any] | None:
    try:
        module = importlib.import_module("agent_handoff_mcp")
    except ImportError:
        return None
    try:
        return (
            getattr(module, "RuntimeConfig"),
            getattr(module, "configure_runtime"),
            getattr(module, "get_handoff_state"),
        )
    except AttributeError:
        return None


def _primary_workspace_root(workspace_root: Path) -> str:
    resolved_root = workspace_root.resolve(strict=False)
    try:
        proc = subprocess.run(
            ["git", "-C", str(resolved_root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return str(resolved_root)

    if proc.returncode == 0 and proc.stdout.strip():
        common_dir = Path(proc.stdout.strip())
        if not common_dir.is_absolute():
            common_dir = resolved_root / common_dir
        common_dir = common_dir.resolve(strict=False)
        if common_dir.name == ".git":
            return str(common_dir.parent)
    return str(resolved_root)


def _load_active_task(workspace_root: Path) -> ActiveTaskContext:
    exports = _load_handoff_exports()
    if exports is None:
        primary = _primary_workspace_root(workspace_root)
        return ActiveTaskContext(None, None, None, primary)
    RuntimeConfig, configure_runtime, get_handoff_state = exports

    try:
        runtime = RuntimeConfig.for_repo(workspace_root)
        configure_runtime(runtime)
        raw = get_handoff_state(sections="identity")
    except Exception:
        primary = _primary_workspace_root(workspace_root)
        return ActiveTaskContext(None, None, None, primary)

    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return ActiveTaskContext(None, None, None, str(Path(runtime.workspace_root).resolve(strict=False)))

    data = parsed.get("data") if isinstance(parsed, dict) else None
    active = data.get("active") if isinstance(data, dict) else None
    if not isinstance(active, dict):
        return ActiveTaskContext(None, None, None, str(Path(runtime.workspace_root).resolve(strict=False)))

    task_ref = active.get("task_ref")
    target_worktree_path = active.get("target_worktree_path")
    target_branch = active.get("target_branch")
    return ActiveTaskContext(
        str(task_ref) if isinstance(task_ref, str) and task_ref else None,
        str(target_worktree_path) if isinstance(target_worktree_path, str) and target_worktree_path else None,
        str(target_branch) if isinstance(target_branch, str) and target_branch else None,
        str(runtime.workspace_root),
    )


def _workspace_root() -> Path:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return Path.cwd()
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return Path.cwd()


def _canonical_target_worktree(target_worktree_path: str | None) -> str | None:
    if not target_worktree_path:
        return None
    return str(Path(target_worktree_path).expanduser().resolve(strict=False))


def _candidate_abspath(raw_path: str, workspace_root: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    return candidate.resolve(strict=False)


def _candidate_worktree_root(candidate_path: Path) -> str | None:
    probe_dir = candidate_path if candidate_path.is_dir() else candidate_path.parent
    try:
        proc = subprocess.run(
            ["git", "-C", str(probe_dir), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return str(Path(proc.stdout.strip()).resolve(strict=False))


def _repo_relative_path(path: Path, repo_root: str) -> str | None:
    try:
        return str(path.resolve(strict=False).relative_to(Path(repo_root).resolve(strict=False))).replace("\\", "/")
    except ValueError:
        return None


def _log_trace(decision: DriftDecision) -> None:
    if not decision.primary_worktree:
        return
    try:
        state_dir = Path(decision.primary_worktree) / ".task-state"
        state_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "tool": "guard-worktree-drift",
            "outcome": decision.outcome,
            "task_ref": decision.task_ref,
            "path": decision.path,
            "candidate_worktree": decision.candidate_worktree,
            "target_worktree": decision.target_worktree,
            "repo_relative_path": decision.repo_relative_path,
            "matched_pattern": decision.matched_pattern,
            "matched_reason": decision.matched_reason,
            "reason": decision.reason,
        }
        with (state_dir / TRACE_LOG_NAME).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError:
        pass


def evaluate_payload(
    payload: dict[str, Any],
    *,
    workspace_root: Path | None = None,
    active_task: ActiveTaskContext | tuple[str | None, str | None] | tuple[str | None, str | None, str | None] | None = None,
) -> DriftDecision | None:
    root = workspace_root or _workspace_root()
    tool_name = _payload_value(payload, "tool_name", "toolName")
    tool_input = _payload_value(payload, "tool_input", "toolInput", {})
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return None

    if isinstance(active_task, ActiveTaskContext):
        context = active_task
    elif isinstance(active_task, tuple):
        primary_worktree = _primary_workspace_root(root)
        if len(active_task) == 2:
            context = ActiveTaskContext(active_task[0], active_task[1], None, primary_worktree)
        else:
            context = ActiveTaskContext(active_task[0], active_task[1], active_task[2], primary_worktree)
    else:
        context = _load_active_task(root)

    if not context.target_worktree:
        return None

    target_worktree = _canonical_target_worktree(context.target_worktree)
    if not target_worktree:
        return None
    primary_worktree = _canonical_target_worktree(context.primary_worktree) or _primary_workspace_root(root)
    if context.target_branch and context.target_branch in MAIN_BRANCHES:
        return None
    if context.task_ref and context.task_ref.startswith("MAINT-"):
        return DriftDecision(
            outcome="maintenance_bypass",
            reason="MAINT task bypass",
            primary_worktree=primary_worktree,
            task_ref=context.task_ref,
            target_worktree=target_worktree,
        )
    if os.environ.get("ALT_ALLOW_WORKTREE_DRIFT") == "1":
        return DriftDecision(
            outcome="env_bypass",
            reason="ALT_ALLOW_WORKTREE_DRIFT=1",
            primary_worktree=primary_worktree,
            task_ref=context.task_ref,
            target_worktree=target_worktree,
        )

    allowlisted_decisions: list[DriftDecision] = []
    policy = None
    for raw_path in _extract_candidate_paths(tool_name, tool_input):
        candidate_path = _candidate_abspath(raw_path, root)
        candidate_worktree = _candidate_worktree_root(candidate_path)
        if not candidate_worktree or candidate_worktree == target_worktree:
            continue

        repo_relative = _repo_relative_path(candidate_path, primary_worktree)
        if candidate_worktree == primary_worktree and repo_relative:
            try:
                if policy is None:
                    policy = load_branch_isolation_policy(Path(primary_worktree))
            except HarnessContractMissingError as exc:
                return DriftDecision(
                    outcome="block",
                    reason=str(exc),
                    primary_worktree=primary_worktree,
                    path=str(candidate_path),
                    candidate_worktree=candidate_worktree,
                    target_worktree=target_worktree,
                    task_ref=context.task_ref or "(unknown task)",
                    repo_relative_path=repo_relative,
                )
            matched_surface = find_permitted_main_surface(repo_relative, policy)
            if matched_surface is not None:
                allowlisted_decisions.append(
                    DriftDecision(
                    outcome="allowlisted_main_surface",
                    reason=f"allow-listed main surface: {matched_surface.reason}",
                    primary_worktree=primary_worktree,
                    path=str(candidate_path),
                    candidate_worktree=candidate_worktree,
                    target_worktree=target_worktree,
                    task_ref=context.task_ref or "(unknown task)",
                    repo_relative_path=repo_relative,
                    matched_pattern=matched_surface.pattern,
                    matched_reason=matched_surface.reason,
                )
                )
                continue

        return DriftDecision(
            outcome="block",
            primary_worktree=primary_worktree,
            path=str(candidate_path),
            candidate_worktree=candidate_worktree,
            target_worktree=target_worktree,
            task_ref=context.task_ref or "(unknown task)",
            repo_relative_path=repo_relative,
        )
    if allowlisted_decisions:
        return allowlisted_decisions[0]
    return None


def _build_block_reason(decision: DriftDecision) -> str:
    assert decision.path is not None
    assert decision.candidate_worktree is not None
    assert decision.target_worktree is not None
    return (
        "WorkspaceRootDriftError: edit resolved into the wrong worktree.\n\n"
        f"Task: {decision.task_ref}\n"
        f"Edit path: {decision.path}\n"
        f"Edit worktree: {decision.candidate_worktree}\n"
        f"Target worktree: {decision.target_worktree}\n\n"
        "Escape hatches:\n"
        "  1. Use a `MAINT-*` task ref for intentional main-worktree maintenance edits.\n"
        "  2. Set `ALT_ALLOW_WORKTREE_DRIFT=1` for a shell-scoped warn-only bypass.\n"
        "  3. Add the path to `branch_isolation.permitted_main_surfaces` in harness-protocol.yaml."
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    decision = evaluate_payload(payload)
    if decision is None:
        return 0
    if decision.outcome != "silent":
        _log_trace(decision)
    if decision.outcome != "block":
        return 0

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "block",
                    "permissionDecisionReason": decision.reason or _build_block_reason(decision),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
