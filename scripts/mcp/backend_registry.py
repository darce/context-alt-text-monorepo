from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import os
from typing import Any
from typing import Callable


@dataclass(frozen=True)
class BackendCapabilities:
    supports_structured_output: bool = False
    supports_sandbox: bool = False
    supports_sync_turn: bool = False


@dataclass(frozen=True)
class BackendSpec:
    kind: str
    module: str | None
    description: str
    capabilities: BackendCapabilities = field(default_factory=BackendCapabilities)


BACKENDS: dict[str, BackendSpec] = {
    "codex-cli": BackendSpec(
        kind="cli",
        module=None,
        description="Shell out to codex exec.",
        capabilities=BackendCapabilities(
            supports_structured_output=True,
            supports_sandbox=True,
            supports_sync_turn=False,
        ),
    ),
    "codex-subagent": BackendSpec(
        kind="bridge",
        module="codex_subagent_bridge",
        description="Codex app-server via bridge module.",
        capabilities=BackendCapabilities(
            supports_structured_output=True,
            supports_sandbox=True,
            supports_sync_turn=True,
        ),
    ),
    "copilot-host": BackendSpec(
        kind="bridge",
        module="vscode_copilot_bridge",
        description="VS Code Copilot runSubagent bridge (no worktree isolation).",
        capabilities=BackendCapabilities(
            supports_structured_output=False,
            supports_sandbox=False,
            supports_sync_turn=True,
        ),
    ),
}


def get_backend_choices() -> tuple[str, ...]:
    return tuple(BACKENDS.keys())


def register_backend(name: str, spec: BackendSpec) -> None:
    BACKENDS[name] = spec


def validate_backend(name: str) -> str:
    normalized = name.strip()
    if normalized not in BACKENDS:
        raise RuntimeError(
            f"Unsupported execution backend '{name}'. Valid values: {', '.join(get_backend_choices())}"
        )
    return normalized


def get_backend_spec(name: str) -> BackendSpec:
    return BACKENDS[validate_backend(name)]


def resolve_bridge(name: str) -> Callable[..., dict[str, Any] | str]:
    spec = get_backend_spec(name)
    if spec.kind != "bridge" or not spec.module:
        raise RuntimeError(f"Backend '{name}' does not expose a bridge runner.")
    try:
        bridge = importlib.import_module(spec.module)
    except ImportError as exc:
        raise RuntimeError(
            f"{name} backend is unavailable in this runtime. "
            f"Provide a host bridge module named '{spec.module}'."
        ) from exc

    runner = getattr(bridge, "run_subagent", None)
    if not callable(runner):
        raise RuntimeError(
            f"{spec.module}.run_subagent is required for the {name} backend."
        )
    return runner


def detect_runtime() -> str | None:
    """Probe environment for a known host runtime and return the matching backend name.

    Returns ``None`` when no recognizable host signals are present.
    """
    if os.environ.get("VSCODE_PID") or os.environ.get("VSCODE_IPC_HOOK_CLI"):
        if "copilot" in os.environ.get("VSCODE_AGENT_FOLDER", "").lower():
            return "copilot-host"
    return None
