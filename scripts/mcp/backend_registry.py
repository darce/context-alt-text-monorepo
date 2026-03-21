from dataclasses import dataclass, field
import importlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Type

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from backend_adapter import BackendAdapter


@dataclass(frozen=True)
class BackendCapabilities:
    is_available: bool = False
    supports_structured_output: bool = False
    supports_sandbox: bool = False
    supports_sync_turn: bool = False
    supports_reasoning_effort: bool = False


@dataclass(frozen=True)
class BackendSpec:
    kind: str
    adapter_class: Type[BackendAdapter]
    description: str
    module: str | None = None
    capabilities: BackendCapabilities = field(default_factory=BackendCapabilities)


def _get_cli_adapter() -> Type[BackendAdapter]:
    from adapters.codex_cli import CodexCliAdapter
    return CodexCliAdapter


def _get_subagent_adapter() -> Type[BackendAdapter]:
    from adapters.codex_subagent import CodexSubagentAdapter
    return CodexSubagentAdapter


def _get_claude_adapter() -> Type[BackendAdapter]:
    from adapters.claude_code import ClaudeCodeAdapter
    return ClaudeCodeAdapter


def _get_local_model_adapter() -> Type[BackendAdapter]:
    from adapters.local_model import LocalModelAdapter
    return LocalModelAdapter


BACKENDS: dict[str, BackendSpec] = {
    "codex-cli": BackendSpec(
        kind="cli",
        adapter_class=_get_cli_adapter,
        description="Shell out to codex exec.",
        capabilities=BackendCapabilities(
            supports_structured_output=True,
            supports_sandbox=True,
            supports_sync_turn=False,
        ),
    ),
    "codex-subagent": BackendSpec(
        kind="bridge",
        adapter_class=_get_subagent_adapter,
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
        adapter_class=_get_subagent_adapter,
        module="vscode_copilot_bridge",
        description="VS Code Copilot runSubagent bridge (no worktree isolation).",
        capabilities=BackendCapabilities(
            supports_structured_output=False,
            supports_sandbox=False,
            supports_sync_turn=True,
        ),
    ),
    "claude-code": BackendSpec(
        kind="cli",
        adapter_class=_get_claude_adapter,
        description="Anthropic Claude Code CLI.",
        capabilities=BackendCapabilities(
            supports_structured_output=True,
            supports_sandbox=True,
            supports_sync_turn=False,
        ),
    ),
    "local-model-openai": BackendSpec(
        kind="api",
        adapter_class=_get_local_model_adapter,
        description="Generic OpenAI-compatible local model API.",
        capabilities=BackendCapabilities(
            supports_structured_output=True,
            supports_sandbox=True,
            supports_sync_turn=False,
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


def get_adapter(name: str, **kwargs: Any) -> BackendAdapter:
    """Get an initialized adapter instance for the named backend."""
    spec = get_backend_spec(name)
    factory_or_cls = spec.adapter_class

    # Resolve lazy loading if it's a factory function
    # We check if it's a function (not a class) and callable.
    if not isinstance(factory_or_cls, type) and callable(factory_or_cls):
        cls = factory_or_cls()
    else:
        cls = factory_or_cls

    if spec.kind == "bridge":
        runner = resolve_bridge(name)
        return cls(runner, name=name)  # type: ignore[call-arg]

    # For CLI, we might pass codex_bin/args
    return cls(**kwargs)  # type: ignore[call-arg]


def find_codex(*args: Any, **kwargs: Any) -> str:
    """Backward compatibility wrapper for tests."""
    from adapters.codex_cli import find_codex as _find
    return _find(*args, **kwargs)


def detect_runtime() -> str | None:
    # ... (existing detect_runtime)
    if os.environ.get("VSCODE_PID") or os.environ.get("VSCODE_IPC_HOOK_CLI"):
        if "copilot" in os.environ.get("VSCODE_AGENT_FOLDER", "").lower():
            return "copilot-host"
    return None


def probe_capabilities(name: str) -> BackendCapabilities:
    """Probe the environment to see if a backend is available and what it supports."""
    spec = get_backend_spec(name)
    base = spec.capabilities

    if name == "codex-cli":
        try:
            bin_path = find_codex()
            # Probe for reasoning-effort
            help_res = subprocess.run([bin_path, "exec", "--help"], capture_output=True, text=True, check=False)
            has_reasoning = "reasoning-effort" in help_res.stdout

            return BackendCapabilities(
                is_available=True,
                supports_structured_output=base.supports_structured_output,
                supports_sandbox=base.supports_sandbox,
                supports_sync_turn=base.supports_sync_turn,
                supports_reasoning_effort=has_reasoning,
            )
        except RuntimeError:
            return BackendCapabilities(is_available=False)

    if name == "codex-subagent" or name == "copilot-host":
        try:
            resolve_bridge(name)
            return BackendCapabilities(
                is_available=True,
                supports_structured_output=base.supports_structured_output,
                supports_sandbox=base.supports_sandbox,
                supports_sync_turn=base.supports_sync_turn,
            )
        except RuntimeError:
            return BackendCapabilities(is_available=False)

    return base
