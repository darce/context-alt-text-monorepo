from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..backend_adapter import BackendAdapter, BackendResult


class CodexSubagentAdapter(BackendAdapter):
    """Execution adapter for backends that use a `run_subagent` bridge."""

    def __init__(self, runner: Callable[..., dict[str, Any] | str], name: str = "subagent"):
        self.runner = runner
        self.name = name

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
        from .._env import resolve_auto_reasoning_effort  # noqa: PLC0415

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
        reasoning_effort: str | None = None,
        session_mode: str | None = None,
        env: dict[str, str] | None = None,
        progress_callback: Callable[..., None] | None = None,
        **kwargs: Any,
    ) -> BackendResult:
        """Execute turn via the provided bridge runner."""
        if progress_callback:
            progress_callback("exec_spawned", backend=self.name)

        runner_kwargs: dict[str, Any] = {
            "prompt": prompt,
            "schema": schema,
            "cwd": str(worktree_path),
        }

        # Inject model into env so the bridge picks it up via CODEX_MODEL.
        if model and env is not None:
            env.setdefault("CODEX_MODEL", model)

        # Handle optional parameters based on bridge support
        if env is not None:
            runner_kwargs["env"] = env

        if progress_callback is not None:
            runner_kwargs["telemetry_callback"] = lambda telemetry: progress_callback(
                "subagent_turn_complete",
                backend=self.name,
                phase="execution",
                **telemetry,
            )

        try:
            payload = self._call_runner(runner_kwargs)
        except TypeError as exc:
            # Fallback for bridges that don't support telemetry_callback or env
            if "telemetry_callback" in str(exc):
                runner_kwargs.pop("telemetry_callback", None)
                payload = self._call_runner(runner_kwargs)
            elif "env" in str(exc):
                runner_kwargs.pop("env", None)
                payload = self._call_runner(runner_kwargs)
            else:
                raise

        if isinstance(payload, str):
            payload = json.loads(payload)

        if progress_callback:
            progress_callback("exec_complete", backend=self.name)

        return BackendResult.from_dict(payload)

    def _call_runner(self, kwargs: dict[str, Any]) -> dict[str, Any] | str:
        return self.runner(**kwargs)
