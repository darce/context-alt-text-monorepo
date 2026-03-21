#!/usr/bin/env python3
"""Non-reporting lane execution primitive: render prompt, run Codex, write structured result.

This module is the reusable inner step for both human ``make lane-run`` and the
autonomous worker daemon.  It does NOT record anything to MCP or trigger handoff
side-effects -- callers decide what to do with the result file.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _env import WORKER_REASONING_EFFORT_CHOICES
from _env import apply_backend_runtime_hints
from _env import pythonpath_env
from adapters.codex_cli import find_codex
from backend_registry import get_adapter
from backend_registry import get_backend_choices
from backend_registry import get_backend_spec
from backend_registry import resolve_bridge
from backend_registry import validate_backend
from lane_manifest import get_lane_config


BACKEND_CHOICES = get_backend_choices()


# ---------------------------------------------------------------------------
# Prompt / schema helpers
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Prompt / schema helpers
# ---------------------------------------------------------------------------


def _render_prompt(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
    worktree_path: Path,
) -> str:
    """Call ``lane_prompt.py`` and return the rendered prompt text."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "lane_prompt.py"),
        "--orchestrator-root", str(orchestrator_root),
        "--task-ref", task_ref,
        "--lane-id", lane_id,
        "--worktree-path", str(worktree_path),
    ]
    env = pythonpath_env(orchestrator_root, task_ref=task_ref, lane_id=lane_id)
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if completed.returncode != 0:
        raise RuntimeError(
            f"lane_prompt.py failed (exit {completed.returncode}):\n{completed.stderr.strip()}"
        )
    return completed.stdout


def _render_schema(orchestrator_root: Path) -> str:
    """Call ``lane_result.py schema`` and return the JSON string."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "lane_result.py"),
        "schema",
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"lane_result.py schema failed (exit {completed.returncode}):\n{completed.stderr.strip()}"
        )
    return completed.stdout


_HANDOFF_INSTRUCTIONS = """
When you finish, do not run `make lane-handoff` or `make lane-report` yourself.
Return a single JSON object that matches the provided output schema.

Set `handoff_action` to:
- `merge_ready` only if you produced lane-owned code changes that are ready for orchestrator review
- `needs_guidance` if you were blocked, verification was blocked, permissions/sandbox prevented progress, or the assigned issue already appears resolved and now needs orchestrator review instead of new lane code
"""


# ---------------------------------------------------------------------------
# Prompt augmentation for fix cycles
# ---------------------------------------------------------------------------


def build_fix_prompt(base_prompt: str, findings: list[dict[str, Any]]) -> str:
    """Augment a base lane prompt with review findings for a fix cycle."""
    if not findings:
        return base_prompt

    lines = [base_prompt.rstrip(), "", "--- REVIEW FINDINGS TO FIX ---", ""]
    for f in findings:
        severity = f.get("severity", "unknown").upper()
        category = f.get("category", "")
        file_path = f.get("file_path", "")
        desc = f.get("description", "")
        fix = f.get("fix", "")
        loc = file_path
        if isinstance(f.get("line_start"), int):
            loc = f"{file_path}:{f['line_start']}"
        lines.append(f"- [{severity}] [{category}] {loc}: {desc}")
        if fix:
            lines.append(f"  Fix: {fix}")

    lines.extend([
        "",
        "Address each finding above. After fixing, return a JSON result per the output schema.",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Subprocess execution with heartbeats
# ---------------------------------------------------------------------------


def _tail_text(text: str | bytes, *, limit: int = 240) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    value = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _run_lane_preflight(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
    worktree_path: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    try:
        lane_config = get_lane_config(task_ref, lane_id, orchestrator_root=str(orchestrator_root)) or {}
    except FileNotFoundError:
        return {"ok": True, "commands": [], "capability_tags": []}
    commands = [str(item).strip() for item in lane_config.get("preflight_commands", []) if str(item).strip()]
    capability_tags = [str(item).strip() for item in lane_config.get("capability_tags", []) if str(item).strip()]
    if not commands:
        return {"ok": True, "commands": [], "capability_tags": capability_tags}

    failures: list[dict[str, Any]] = []
    for command in commands:
        completed = subprocess.run(
            ["/bin/zsh", "-lc", command],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if completed.returncode == 0:
            continue
        failures.append(
            {
                "command": command,
                "exit_code": completed.returncode,
                "stderr_tail": _tail_text(completed.stderr or ""),
                "stdout_tail": _tail_text(completed.stdout or ""),
            }
        )

    return {
        "ok": not failures,
        "commands": commands,
        "capability_tags": capability_tags,
        "failures": failures,
        "failure_summary": str(lane_config.get("preflight_failure_summary") or "").strip(),
        "failure_details": str(lane_config.get("preflight_failure_details") or "").strip(),
    }


def _preflight_failure_payload(
    *,
    lane_id: str,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    commands = [str(item) for item in preflight.get("commands", []) if str(item).strip()]
    capability_tags = [str(item) for item in preflight.get("capability_tags", []) if str(item).strip()]
    failures = [item for item in preflight.get("failures", []) if isinstance(item, dict)]
    summary = str(preflight.get("failure_summary") or "").strip()
    if not summary:
        summary = f"Lane preflight failed for {lane_id}; required local capabilities are unavailable."

    default_detail = (
        f"The lane requires local capabilities ({', '.join(capability_tags)}) before execution."
        if capability_tags
        else "The lane requires local prerequisites before execution."
    )
    detail_lines = [str(preflight.get("failure_details") or "").strip() or default_detail, "", "Preflight failures:"]
    blockers: list[str] = []
    for failure in failures:
        command = str(failure.get("command") or "").strip()
        stderr_tail = str(failure.get("stderr_tail") or "").strip()
        stdout_tail = str(failure.get("stdout_tail") or "").strip()
        exit_code = failure.get("exit_code")
        reason = stderr_tail or stdout_tail or f"exit {exit_code}"
        detail_lines.append(f"- `{command}` -> {reason}")
        blockers.append(f"`{command}` failed: {reason}")

    if not blockers:
        blockers.append("Lane preflight failed before execution.")

    return {
        "handoff_action": "needs_guidance",
        "summary": summary,
        "details": "\n".join(detail_lines).strip(),
        "tests_run": commands,
        "blockers": blockers,
    }




# ---------------------------------------------------------------------------
# Temp-file helpers
# ---------------------------------------------------------------------------


def _temp_output_path(*, lane_id: str) -> Path:
    fd, name = tempfile.mkstemp(suffix=".json", prefix=f"lane-exec-{lane_id}-")
    os.close(fd)
    return Path(name)


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------


def run_lane_exec(
    *,
    orchestrator_root: Path,
    task_ref: str,
    lane_id: str,
    session: str,
    worktree_path: Path,
    output_path: Path | None = None,
    backend: str = "codex-cli",
    session_mode: str = "fresh_turn",
    reasoning_effort: str | None = None,
    model: str | None = None,
    codex_bin: str | None = None,
    codex_args: list[str] | None = None,
    prompt_override: str | None = None,
    heartbeat_interval: int = 20,
    progress_callback: Callable[..., None] | None = None,
    dry_run: bool = False,
) -> Path:
    """Run Codex for a lane and write a structured result file.

    Returns the path to the result JSON file.  Does NOT trigger any MCP
    recording or handoff side-effects.
    """
    # 1. Load manifest for overrides
    lane_cfg = get_lane_config(task_ref, lane_id, orchestrator_root=str(orchestrator_root)) or {}

    # Priority: CLI > Manifest > Default
    # If caller provided a non-default backend, keep it.
    # Otherwise, check manifest.
    backend_name = backend
    if backend_name == "codex-cli" and lane_cfg.get("preferred_backend"):
        backend_name = str(lane_cfg["preferred_backend"])
    backend_name = validate_backend(backend_name)

    model_name = model or lane_cfg.get("preferred_model")

    env = pythonpath_env(orchestrator_root, task_ref=task_ref, lane_id=lane_id)
    apply_backend_runtime_hints(
        env,
        reasoning_effort=reasoning_effort,
        model=model_name,
        session_mode=session_mode,
    )

    if not dry_run:
        preflight = _run_lane_preflight(
            orchestrator_root=orchestrator_root,
            task_ref=task_ref,
            lane_id=lane_id,
            worktree_path=worktree_path,
            env=env,
        )
        if not preflight.get("ok", True):
            out = output_path or _temp_output_path(lane_id=lane_id)
            out.write_text(json.dumps(_preflight_failure_payload(lane_id=lane_id, preflight=preflight), indent=2))
            return out

    # Build prompt
    if prompt_override:
        prompt_text = prompt_override
    else:
        prompt_text = _render_prompt(
            orchestrator_root=orchestrator_root,
            task_ref=task_ref,
            lane_id=lane_id,
            worktree_path=worktree_path,
        )
    prompt_text += _HANDOFF_INSTRUCTIONS

    # Build schema
    schema_text = _render_schema(orchestrator_root)

    if dry_run:
        result: dict[str, Any] = {
            "dry_run": True,
            "backend": backend_name,
            "model": model_name,
            "reasoning_effort": reasoning_effort,
            "handoff_action": "merge_ready",
            "summary": f"Dry-run lane execution for {lane_id}.",
            "details": "No codex exec was run; this is a simulated structured result.",
            "tests_run": [],
            "blockers": [],
            "prompt": prompt_text,
            "schema": json.loads(schema_text),
        }
        if backend_name == "codex-cli":
            result["codex_bin"] = find_codex(codex_bin)
        out = output_path or _temp_output_path(lane_id=lane_id)
        out.write_text(json.dumps(result, indent=2))
        return out

    # Get adapter and execute
    adapter = get_adapter(
        backend_name,
        codex_bin=codex_bin,
        codex_args=codex_args,
    )

    result = adapter.execute(
        prompt=prompt_text,
        schema=json.loads(schema_text),
        worktree_path=worktree_path,
        model=model_name,
        reasoning_effort=reasoning_effort,
        session_mode=session_mode,
        env=env,
        heartbeat_interval=heartbeat_interval,
        progress_callback=progress_callback,
    )

    out = output_path or _temp_output_path(lane_id=lane_id)
    out.write_text(json.dumps(result.to_dict(), indent=2))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Non-reporting lane execution: render prompt, run Codex, write result."
    )
    parser.add_argument("--orchestrator-root", required=True)
    parser.add_argument("--task-ref", required=True)
    parser.add_argument("--lane-id", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--output-path", help="Where to write the result JSON. Defaults to a temp file.")
    parser.add_argument("--backend", default="codex-cli", choices=BACKEND_CHOICES,
                        help="Execution backend to use (default: codex-cli).")
    parser.add_argument(
        "--reasoning-effort",
        choices=WORKER_REASONING_EFFORT_CHOICES,
        help="Optional reasoning effort hint for codex-subagent turns.",
    )
    parser.add_argument("--model", help="Explicit model to use (e.g. gpt-5.4-mini).")
    parser.add_argument("--codex-bin", help="Explicit path to the codex binary.")
    parser.add_argument("--codex-args", help="Extra args for codex exec (space-separated).")
    parser.add_argument("--prompt-file", help="Override the lane prompt with contents of this file.")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt/schema without running Codex.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    orchestrator_root = Path(args.orchestrator_root).expanduser().resolve()
    worktree_path = Path(args.worktree_path).expanduser().resolve()
    output_path = Path(args.output_path).expanduser().resolve() if args.output_path else None
    codex_args = args.codex_args.split() if args.codex_args else None

    prompt_override = None
    if args.prompt_file:
        prompt_override = Path(args.prompt_file).expanduser().resolve().read_text()

    result_path = run_lane_exec(
        orchestrator_root=orchestrator_root,
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        session=args.session,
        worktree_path=worktree_path,
        output_path=output_path,
        backend=args.backend,
        reasoning_effort=args.reasoning_effort,
        model=args.model,
        codex_bin=args.codex_bin,
        codex_args=codex_args,
        prompt_override=prompt_override,
        dry_run=args.dry_run,
    )

    print(json.dumps({"ok": True, "result_path": str(result_path)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
