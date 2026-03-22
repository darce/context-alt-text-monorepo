from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

try:
    from backend_adapter import BackendAdapter, BackendResult
except ImportError:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from backend_adapter import BackendAdapter, BackendResult


class ClaudeCodeAdapter(BackendAdapter):
    """Execution adapter for the `claude` CLI (Anthropic)."""

    def __init__(self, claude_bin: str = "claude"):
        self.claude_bin = claude_bin

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
        """Claude Code currently handles effort via model selection; return default."""
        return None, ["Claude Code uses model-level reasoning controls"]

    def execute(
        self,
        prompt: str,
        schema: dict[str, Any],
        worktree_path: Path,
        model: str | None = None,
        reasoning_effort: str | None = None,
        session_mode: str | None = None,
        env: dict[str, str] | None = None,
        progress_callback: Callable[..., None] | None = None,
        **kwargs: Any,
    ) -> BackendResult:
        """Execute turn via `claude` CLI."""
        if progress_callback:
            progress_callback("exec_spawned", backend="claude-code")

        with tempfile.TemporaryDirectory(prefix="claude-code-") as tmpdir:
            tmp = Path(tmpdir)
            prompt_file = tmp / "prompt.md"
            result_file = tmp / "result.json"

            # Claude Code expects a natural language prompt. 
            # We append the schema requirements to the prompt.
            full_prompt = (
                f"{prompt}\n\n"
                f"IMPORTANT: Your final output must be a single JSON object matching this schema:\n"
                f"{json.dumps(schema, indent=2)}\n"
            )
            prompt_file.write_text(full_prompt)

            # Note: This assumes 'claude' CLI supports a non-interactive mode.
            # In practice, we might need 'claude execute' or similar.
            cmd = [
                self.claude_bin,
                "execute", 
                "--cwd", str(worktree_path),
                "--file", str(prompt_file),
            ]
            if model:
                cmd.extend(["--model", model])

            try:
                # We use a longer timeout for LLM execution
                completed = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env or os.environ.copy(),
                    timeout=600, 
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError("Claude Code execution timed out after 10 minutes.")
            except FileNotFoundError:
                raise RuntimeError(f"Claude CLI '{self.claude_bin}' not found in PATH.")

            if completed.returncode != 0:
                stderr_text = (completed.stderr or "").strip()
                stdout_text = (completed.stdout or "").strip()
                stderr_tail = stderr_text[-500:] if stderr_text else ""
                stdout_tail = stdout_text[-500:] if stdout_text else ""
                raise RuntimeError(
                    f"Claude Code failed (exit {completed.returncode}).\n"
                    f"STDOUT: {stdout_tail}\n"
                    f"STDERR: {stderr_tail}"
                )

            # Claude Code output is usually to stdout; we try to find the JSON block.
            # This is a heuristic parser.
            output = completed.stdout
            json_match = re.search(r"(\{.*\})", output, re.DOTALL)
            if not json_match:
                raise RuntimeError("Claude Code completed but no JSON block was found in output.")

            try:
                payload = json.loads(json_match.group(1))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Failed to parse JSON from Claude Code output: {exc}")

            if progress_callback:
                progress_callback("exec_complete", backend="claude-code")

            return BackendResult.from_dict(payload)
