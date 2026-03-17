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

from _env import pythonpath_env
from backend_registry import get_backend_choices
from backend_registry import get_backend_spec
from backend_registry import resolve_bridge
from backend_registry import validate_backend


# ---------------------------------------------------------------------------
# Codex discovery (shared with review_runner.py)
# ---------------------------------------------------------------------------

_CODEX_SEARCH_PATHS = (
    "/Applications/Codex.app/Contents/Resources/codex",
    "{home}/.local/bin/codex",
)
BACKEND_CHOICES = get_backend_choices()


def find_codex(explicit: str | None = None) -> str:
    """Return the path to a ``codex`` binary, or raise if not found."""
    if explicit:
        return explicit

    # ``command -v`` via Python
    for name in ("codex",):
        result = subprocess.run(
            ["which", name], capture_output=True, text=True, check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

    home = Path.home()
    for tpl in _CODEX_SEARCH_PATHS:
        candidate = Path(tpl.format(home=home))
        if candidate.is_file() and candidate.stat().st_mode & 0o111:
            return str(candidate)

    raise RuntimeError(
        "codex CLI not found.  Install Codex or pass --codex-bin explicitly."
    )


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


def _run_codex_process(
    *,
    cmd: list[str],
    stdin_fh: Any,
    env: dict[str, str],
    heartbeat_interval: int = 20,
    progress_callback: Callable[..., None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``codex exec`` and emit periodic heartbeat callbacks while it works."""
    proc = subprocess.Popen(
        cmd,
        stdin=stdin_fh,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    started = time.monotonic()
    if progress_callback:
        progress_callback("exec_spawned", pid=proc.pid)

    while True:
        try:
            stdout, stderr = proc.communicate(timeout=heartbeat_interval)
            return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired as exc:
            if progress_callback:
                payload: dict[str, Any] = {
                    "pid": proc.pid,
                    "elapsed_seconds": int(time.monotonic() - started),
                }
                stderr_tail = _tail_text(getattr(exc, "stderr", "") or "")
                stdout_tail = _tail_text(getattr(exc, "stdout", "") or getattr(exc, "output", "") or "")
                if stderr_tail:
                    payload["stderr_tail"] = stderr_tail
                elif stdout_tail:
                    payload["stdout_tail"] = stdout_tail
                progress_callback("exec_heartbeat", **payload)


def _run_subagent(
    backend_name: str,
    *,
    prompt_text: str,
    schema_text: str,
    worktree_path: Path,
    env: dict[str, str] | None = None,
    progress_callback: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Run the optional host-provided Codex subagent bridge and return structured JSON."""
    runner = resolve_bridge(backend_name)

    if progress_callback:
        progress_callback("exec_spawned", backend=backend_name)

    runner_kwargs: dict[str, Any] = {
        "prompt": prompt_text,
        "schema": json.loads(schema_text),
        "cwd": str(worktree_path),
    }
    if env is not None:
        runner_kwargs["env"] = env
    try:
        payload = runner(**runner_kwargs)
    except TypeError as exc:
        if env is None or "env" not in str(exc):
            raise
        runner_kwargs.pop("env", None)
        payload = runner(**runner_kwargs)

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{backend_name} backend returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{backend_name} backend returned non-object payload: {type(payload).__name__}"
        )
    if progress_callback:
        progress_callback("exec_complete", backend=backend_name)
    return payload


def _validate_lane_result_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the lane-result contract for subagent execution."""
    required_text = ("handoff_action", "summary", "details")
    for key in required_text:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Lane execution result missing required non-empty string '{key}'.")

    action = payload["handoff_action"]
    if action not in {"merge_ready", "needs_guidance"}:
        raise RuntimeError(
            "Lane execution result has invalid 'handoff_action'. "
            "Valid values: merge_ready, needs_guidance"
        )

    for key in ("tests_run", "blockers"):
        value = payload.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise RuntimeError(f"Lane execution result '{key}' must be an array of strings.")

    return payload


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
    backend_name = validate_backend(backend)
    env = pythonpath_env(orchestrator_root, task_ref=task_ref, lane_id=lane_id)

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

    if get_backend_spec(backend_name).kind == "bridge":
        payload = _validate_lane_result_payload(_run_subagent(
            backend_name,
            prompt_text=prompt_text,
            schema_text=schema_text,
            worktree_path=worktree_path,
            env=env,
            progress_callback=progress_callback,
        ))
        out = output_path or _temp_output_path(lane_id=lane_id)
        out.write_text(json.dumps(payload, indent=2))
        return out

    codex = find_codex(codex_bin)

    # Write temp files and execute
    with tempfile.TemporaryDirectory(prefix=f"lane-exec-{lane_id}-") as tmpdir:
        prompt_file = Path(tmpdir) / "prompt.md"
        schema_file = Path(tmpdir) / "schema.json"
        result_file = Path(tmpdir) / "result.json"

        prompt_file.write_text(prompt_text)
        schema_file.write_text(schema_text)

        cmd = [
            codex,
            "exec",
            "-C", str(worktree_path),
            *(codex_args or []),
            "--output-schema", str(schema_file),
            "-o", str(result_file),
            "-",
        ]

        with prompt_file.open("r") as stdin_fh:
            completed = _run_codex_process(
                cmd=cmd,
                stdin_fh=stdin_fh,
                env=env,
                heartbeat_interval=heartbeat_interval,
                progress_callback=progress_callback,
            )

        if completed.returncode != 0:
            # Preserve partial result if any
            out = output_path or _temp_output_path(lane_id=lane_id)
            if result_file.is_file():
                shutil.copy2(result_file, out)
            raise RuntimeError(
                f"codex exec failed (exit {completed.returncode}):\n"
                f"stderr: {completed.stderr.strip()[:500]}\n"
                f"Result preserved at: {out if result_file.is_file() else 'none'}"
            )

        if not result_file.is_file():
            raise RuntimeError("codex exec completed but did not produce a result file.")

        # Copy to persistent location
        out = output_path or _temp_output_path(lane_id=lane_id)
        shutil.copy2(result_file, out)
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
        codex_bin=args.codex_bin,
        codex_args=codex_args,
        prompt_override=prompt_override,
        dry_run=args.dry_run,
    )

    print(json.dumps({"ok": True, "result_path": str(result_path)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
