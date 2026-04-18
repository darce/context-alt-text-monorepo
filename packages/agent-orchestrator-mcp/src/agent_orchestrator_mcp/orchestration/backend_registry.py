import importlib
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

from agent_orchestrator_mcp.orchestration.backend_adapter import BackendAdapter


@dataclass(frozen=True)
class BackendCapabilities:
    is_available: bool = False
    supports_structured_output: bool = False
    supports_sandbox: bool = False
    supports_sync_turn: bool = False
    supports_reasoning_effort: bool = False
    preflight_tokenizer_family: str | None = None


@dataclass(frozen=True)
class BackendSpec:
    kind: str
    adapter_path: str
    description: str
    module: str | None = None
    capabilities: BackendCapabilities = field(default_factory=BackendCapabilities)

    @property
    def adapter_class(self) -> type[BackendAdapter]:
        module_name, class_name = self.adapter_path.rsplit(".", 1)
        return getattr(importlib.import_module(module_name), class_name)


BACKENDS: dict[str, BackendSpec] = {
    "codex-cli": BackendSpec(
        kind="cli",
        adapter_path="agent_orchestrator_mcp.orchestration.adapters.codex_cli.CodexCliAdapter",
        description="Shell out to codex exec.",
        capabilities=BackendCapabilities(
            supports_structured_output=True,
            supports_sandbox=True,
            supports_sync_turn=False,
            preflight_tokenizer_family="tiktoken",
        ),
    ),
    "codex-subagent": BackendSpec(
        kind="bridge",
        adapter_path="agent_orchestrator_mcp.orchestration.adapters.codex_subagent.CodexSubagentAdapter",
        module="codex_subagent_bridge",
        description="Codex app-server via bridge module.",
        capabilities=BackendCapabilities(
            supports_structured_output=True,
            supports_sandbox=True,
            supports_sync_turn=True,
            preflight_tokenizer_family="tiktoken",
        ),
    ),
    "copilot-host": BackendSpec(
        kind="bridge",
        adapter_path="agent_orchestrator_mcp.orchestration.adapters.codex_subagent.CodexSubagentAdapter",
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
        adapter_path="agent_orchestrator_mcp.orchestration.adapters.claude_code.ClaudeCodeAdapter",
        description="Anthropic Claude Code CLI.",
        capabilities=BackendCapabilities(
            supports_structured_output=True,
            supports_sandbox=True,
            supports_sync_turn=False,
            supports_reasoning_effort=True,
        ),
    ),
    "structured-turn": BackendSpec(
        kind="in-process",
        adapter_path="agent_orchestrator_mcp.orchestration.adapters.structured_turn.StructuredTurnAdapter",
        description="Always-available in-repo adapter that composes run_structured_turn; anchors cross-vendor equivalence coverage.",
        capabilities=BackendCapabilities(
            is_available=True,
            supports_structured_output=True,
            supports_sandbox=False,
            supports_sync_turn=True,
        ),
    ),
    "local-model-openai": BackendSpec(
        kind="api",
        adapter_path="agent_orchestrator_mcp.orchestration.adapters.local_model.LocalModelAdapter",
        description="Generic OpenAI-compatible local model API.",
        capabilities=BackendCapabilities(
            supports_structured_output=True,
            supports_sandbox=True,
            supports_sync_turn=False,
            preflight_tokenizer_family="tiktoken",
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
        raise RuntimeError(f"Unsupported execution backend '{name}'. Valid values: {', '.join(get_backend_choices())}")
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
            f"{name} backend is unavailable in this runtime. Provide a host bridge module named '{spec.module}'."
        ) from exc

    runner = getattr(bridge, "run_subagent", None)
    if not callable(runner):
        raise RuntimeError(f"{spec.module}.run_subagent is required for the {name} backend.")
    return runner


def get_adapter(name: str, **kwargs: Any) -> BackendAdapter:
    """Get an initialized adapter instance for the named backend."""
    spec = get_backend_spec(name)
    module_name, class_name = spec.adapter_path.rsplit(".", 1)
    cls = getattr(importlib.import_module(module_name), class_name)

    if spec.kind == "bridge":
        runner = resolve_bridge(name)
        return cls(runner, name=name)  # type: ignore[call-arg]

    # For CLI, we might pass codex_bin/args
    return cls(**kwargs)  # type: ignore[call-arg]


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
        from agent_orchestrator_mcp.orchestration.adapters.codex_cli import find_codex  # noqa: PLC0415

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

    if name == "claude-code":
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                return BackendCapabilities(
                    is_available=True,
                    supports_structured_output=base.supports_structured_output,
                    supports_sandbox=base.supports_sandbox,
                    supports_sync_turn=base.supports_sync_turn,
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return BackendCapabilities(is_available=False)

    return base
