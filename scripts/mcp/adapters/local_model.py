from __future__ import annotations

import json
import os
import urllib.request
import time
from pathlib import Path
from typing import Any, Callable

import sys as _sys
_PARENT = str(Path(__file__).resolve().parent.parent)
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)

from backend_adapter import BackendAdapter, BackendResult
from _env import resolve_auto_reasoning_effort


class LocalModelAdapter(BackendAdapter):
    """Execution adapter for local OpenAI-compatible models (Ollama, vLLM, etc)."""

    def __init__(self, base_url: str = "http://localhost:11434/v1", api_key: str = "ollama"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def available(self) -> bool:
        """Check if the local model endpoint is reachable."""
        try:
            req = urllib.request.Request(f"{self.base_url}/models", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def resolve_reasoning_effort(
        self,
        orchestrator_root: Path,
        task_ref: str,
        lane_id: str,
        requested: str,
        cycle: int,
        prompt_override: str | None = None,
    ) -> tuple[str | None, list[str]]:
        """Resolve reasoning effort using shared auto-scoring logic."""
        return resolve_auto_reasoning_effort(
            orchestrator_root=orchestrator_root,
            task_ref=task_ref,
            lane_id=lane_id,
            requested=requested,
            cycle=cycle,
            prompt_override=prompt_override,
        )

    def execute(
        self,
        prompt: str,
        schema: dict[str, Any],
        worktree_path: Path,
        model: str | None = None,
        env: dict[str, str] | None = None,
        progress_callback: Callable[..., None] | None = None,
        **kwargs: Any,
    ) -> BackendResult:
        """Execute turn via OpenAI-compatible completion API."""
        if not model:
            raise ValueError("model is required for LocalModelAdapter.")

        if progress_callback:
            progress_callback("exec_spawned", backend="local-model-openai", model=model)

        # Build message payload for instruction-following model
        messages = [
            {"role": "system", "content": "You are a helpful coding assistant. Follow the output schema strictly."},
            {"role": "user", "content": prompt}
        ]
        
        # Note: In a real implementation with structured output, we would use
        # tools or json-mode if supported by the local backend.
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.0
        }

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                
                if progress_callback:
                    progress_callback("exec_complete", backend="local-model-openai")
                
                # We expect the model's content to be valid JSON matching the schema
                # for the purposes of this adapter.
                result_data = json.loads(content)
                return BackendResult.from_dict(result_data)
        except Exception as exc:
            raise RuntimeError(f"Local model call failed: {exc}")
