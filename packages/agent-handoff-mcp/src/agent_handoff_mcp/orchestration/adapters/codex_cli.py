from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.mcp.backend_adapter import BackendAdapter, BackendResult
except ModuleNotFoundError:  # pragma: no cover - compatibility for script-style test loaders
    from backend_adapter import BackendAdapter, BackendResult


_CODEX_SEARCH_PATHS = (
    "/Applications/Codex.app/Contents/Resources/codex",
    "{home}/.local/bin/codex",
)


def find_codex(explicit_path: str | None = None) -> str:
    """Find the codex CLI executable."""
    if explicit_path:
        return explicit_path
    for path in _CODEX_SEARCH_PATHS:
        expanded = Path(path.format(home=str(Path.home()))).expanduser()
        if expanded.exists():
            return str(expanded)
    import subprocess
    res = subprocess.run(["which", "codex"], capture_output=True, text=True)
    if res.returncode == 0:
        return res.stdout.strip()
    raise RuntimeError(
        "codex CLI not found in SEARCH_PATHS or PATH. "
        "Install it or provide --codex-bin."
    )


class CodexCliAdapter(BackendAdapter):
    """Execution adapter for the `@openai/codex` CLI."""

    def __init__(self, codex_bin: str | None = None, codex_args: list[str] | None = None):
        self.codex_bin = find_codex(codex_bin)
        self.codex_args = codex_args or []

    def resolve_reasoning_effort(
        self,
        *,
        orchestrator_root: Path,
        task_ref: str,
        lane_id: str,
        requested: str,
        cycle: int,
        prompt_override: str | None,
        previous_run_exhausted: bool = False,
    ) -> tuple[str | None, list[str]]:
        try:
            from scripts.mcp._env import resolve_auto_reasoning_effort
        except ModuleNotFoundError:  # pragma: no cover - compatibility for script-style test loaders
            from _env import resolve_auto_reasoning_effort

        return resolve_auto_reasoning_effort(
            orchestrator_root=orchestrator_root,
            task_ref=task_ref,
            lane_id=lane_id,
            requested=requested,
            cycle=cycle,
            prompt_override=prompt_override,
            previous_run_exhausted=previous_run_exhausted,
        )

    def execute(
        self,
        prompt: str,
        schema: dict[str, Any],
        worktree_path: Path,
        model: str | None = None,
        env: dict[str, str] | None = None,
        progress_callback: Callable[..., None] | None = None,
        heartbeat_interval: int = 20,
        **kwargs: Any,
    ) -> BackendResult:
        """Execute turn via `codex exec` subprocess."""
        # Extra codex-specific args from kwargs
        extra_args = kwargs.get("codex_args") or self.codex_args

        with tempfile.TemporaryDirectory(prefix="codex-cli-") as tmpdir:
            tmp = Path(tmpdir)
            prompt_file = tmp / "prompt.md"
            schema_file = tmp / "schema.json"
            result_file = tmp / "result.json"

            prompt_file.write_text(prompt)
            schema_file.write_text(json.dumps(schema))

            cmd = [
                self.codex_bin,
                "exec",
                "-C",
                str(worktree_path),
                *extra_args,
            ]
            if model:
                cmd.extend(["--model", model])
            cmd.extend(
                [
                    "--output-schema",
                    str(schema_file),
                    "-o",
                    str(result_file),
                    "-",
                ]
            )

            with prompt_file.open("r") as stdin_fh:
                completed = self._run_codex_process(
                    cmd=cmd,
                    stdin_fh=stdin_fh,
                    env=env or os.environ.copy(),
                    heartbeat_interval=heartbeat_interval,
                    progress_callback=progress_callback,
                )

            if completed.returncode != 0:
                stderr_tail = self._tail_text(completed.stderr)
                raise RuntimeError(
                    f"codex exec failed (exit {completed.returncode}):\n{stderr_tail}"
                )

            if not result_file.is_file():
                raise RuntimeError("codex exec completed but no result file was produced.")

            payload = json.loads(result_file.read_text())
            return BackendResult.from_dict(payload)


    def _run_codex_process(
        self,
        *,
        cmd: list[str],
        stdin_fh: Any,
        env: dict[str, str],
        heartbeat_interval: int,
        progress_callback: Callable[..., None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Subprocess runner with heartbeats."""
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
            progress_callback("exec_spawned", pid=proc.pid, backend="codex-cli")

        while True:
            try:
                stdout, stderr = proc.communicate(timeout=heartbeat_interval)
                if progress_callback:
                    progress_callback("exec_complete", pid=proc.pid, backend="codex-cli")
                return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired as exc:
                if progress_callback:
                    elapsed = int(time.monotonic() - started)
                    progress_callback(
                        "exec_heartbeat",
                        pid=proc.pid,
                        elapsed_seconds=elapsed,
                        backend="codex-cli",
                    )

    def _tail_text(self, text: str | bytes, limit: int = 500) -> str:
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        return text.strip()[-limit:]
