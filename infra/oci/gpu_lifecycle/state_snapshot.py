"""Atomic producer for the GPU lifecycle state consumed by the describe API."""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from enum import StrEnum
from pathlib import Path

from infra.oci.gpu_lifecycle.controller import GpuInstanceState

logger = logging.getLogger(__name__)

GPU_STATE_PATH_ENV = "ACX_GPU_STATE_PATH"
DEFAULT_GPU_STATE_PATH = "/run/acx/gpu-state.json"


class GpuLifecycleState(StrEnum):
    """States the lifecycle producer is permitted to publish."""

    STOPPED = "stopped"
    STARTING = "starting"
    WARMING = "warming"
    READY = "ready"
    DEGRADED = "degraded"


# Every OCI state has one conservative state before cycle-specific evidence is
# applied. In particular, only a readiness result may promote WARMING to READY.
_INSTANCE_STATE_MAP: dict[GpuInstanceState, GpuLifecycleState] = {
    GpuInstanceState.RUNNING: GpuLifecycleState.WARMING,
    GpuInstanceState.STOPPED: GpuLifecycleState.STOPPED,
    GpuInstanceState.STARTING: GpuLifecycleState.STARTING,
    GpuInstanceState.STOPPING: GpuLifecycleState.STOPPED,
    GpuInstanceState.UNKNOWN: GpuLifecycleState.DEGRADED,
}
if set(_INSTANCE_STATE_MAP) != set(GpuInstanceState):
    raise RuntimeError("GPU instance state mapping must be exhaustive")


def resolve_gpu_state_path() -> Path:
    """Resolve the shared producer/consumer path contract."""
    return Path(os.environ.get(GPU_STATE_PATH_ENV, DEFAULT_GPU_STATE_PATH))


def state_for_instance(instance_state: str) -> GpuLifecycleState:
    """Map an OCI lifecycle state to a conservative published state."""
    try:
        state = GpuInstanceState(instance_state)
    except (TypeError, ValueError):
        return GpuLifecycleState.DEGRADED
    return _INSTANCE_STATE_MAP[state]


def read_previous_gpu_state(
    path: str | Path | None = None,
) -> GpuLifecycleState | None:
    """Read a prior producer state for cycles that have no readiness evidence."""
    target = resolve_gpu_state_path() if path is None else Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        state = payload["state"]
        if not isinstance(state, str):
            return None
        return GpuLifecycleState(state)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def state_for_instances(
    instance_states: list[str],
    *,
    previous_state: GpuLifecycleState | None = None,
) -> GpuLifecycleState:
    """Reduce the configured instances to one fail-closed service state."""
    if not instance_states:
        return GpuLifecycleState.DEGRADED
    mapped = {state_for_instance(state) for state in instance_states}
    if (
        GpuLifecycleState.WARMING in mapped
        and previous_state
        in {
            GpuLifecycleState.STARTING,
            GpuLifecycleState.WARMING,
            GpuLifecycleState.READY,
            GpuLifecycleState.DEGRADED,
        }
    ):
        mapped.remove(GpuLifecycleState.WARMING)
        mapped.add(previous_state)
    for state in (
        GpuLifecycleState.DEGRADED,
        GpuLifecycleState.READY,
        GpuLifecycleState.WARMING,
        GpuLifecycleState.STARTING,
        GpuLifecycleState.STOPPED,
    ):
        if state in mapped:
            return state
    raise RuntimeError("unreachable GPU lifecycle state reduction")


def write_gpu_state_snapshot(
    state: GpuLifecycleState | str,
    *,
    now: float | None = None,
    path: str | Path | None = None,
) -> bool:
    """Atomically publish a fresh snapshot; telemetry failures never escape."""
    try:
        published_state = GpuLifecycleState(state)
    except ValueError as exc:
        raise ValueError(f"refusing to publish GPU lifecycle state {state!r}") from exc

    written_at = time.time() if now is None else now
    if isinstance(written_at, bool) or not isinstance(written_at, (int, float)):
        raise ValueError("written_at must be epoch seconds")
    if not math.isfinite(written_at):
        raise ValueError("written_at must be finite epoch seconds")

    target = resolve_gpu_state_path() if path is None else Path(path)
    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"state": published_state.value, "written_at": written_at}
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, target)
    except OSError as exc:
        logger.warning("failed to write GPU state snapshot %s: %s", target, exc)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return False
    return True
