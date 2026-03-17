from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any
from typing import Callable


@dataclass(frozen=True)
class BackendSpec:
    kind: str
    module: str | None
    description: str


BACKENDS: dict[str, BackendSpec] = {
    "codex-cli": BackendSpec(
        kind="cli",
        module=None,
        description="Shell out to codex exec.",
    ),
    "codex-subagent": BackendSpec(
        kind="bridge",
        module="codex_subagent_bridge",
        description="Codex app-server via bridge module.",
    ),
}


def get_backend_choices() -> tuple[str, ...]:
    return tuple(BACKENDS.keys())


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
