"""Atomic producer for the GPU lifecycle state consumed by the describe API."""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from contextlib import suppress
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from infra.oci.gpu_lifecycle.controller import GpuInstanceState

logger = logging.getLogger(__name__)

GPU_STATE_PATH_ENV = "ACX_GPU_STATE_PATH"
DEFAULT_GPU_STATE_PATH = "/run/acx/gpu-state.json"
DEFAULT_PREVIOUS_GPU_STATE_MAX_AGE_SECONDS = 180.0
DEFAULT_PREVIOUS_GPU_STATE_MAX_FUTURE_SKEW_SECONDS = 5.0


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
    configured_path = os.environ.get(GPU_STATE_PATH_ENV)
    if configured_path is None or not configured_path.strip():
        return Path(DEFAULT_GPU_STATE_PATH)
    return Path(configured_path)


def state_for_instance(instance_state: str) -> GpuLifecycleState:
    """Map an OCI lifecycle state to a conservative published state."""
    try:
        state = GpuInstanceState(instance_state)
    except (TypeError, ValueError):
        return GpuLifecycleState.DEGRADED
    return _INSTANCE_STATE_MAP[state]


def read_previous_gpu_state(
    path: str | Path | None = None,
    *,
    expected_instance_id: str | None,
    now: datetime | float | None = None,
    max_age_seconds: float = DEFAULT_PREVIOUS_GPU_STATE_MAX_AGE_SECONDS,
    max_future_skew_seconds: float = (DEFAULT_PREVIOUS_GPU_STATE_MAX_FUTURE_SKEW_SECONDS),
) -> GpuLifecycleState | None:
    """Read state only when it belongs to the currently reconciled instance."""
    if expected_instance_id is not None and (
        not isinstance(expected_instance_id, str) or not expected_instance_id.strip()
    ):
        raise ValueError("expected_instance_id must be a non-blank string or None")
    target = resolve_gpu_state_path() if path is None else Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    state_value = payload.get("state")
    if not isinstance(state_value, str):
        return None
    try:
        state = GpuLifecycleState(state_value)
    except ValueError:
        return None

    instance_id = payload.get("instance_id")
    if instance_id is not None and (not isinstance(instance_id, str) or not instance_id.strip()):
        return None
    if expected_instance_id is None or instance_id != expected_instance_id:
        return None
    reason = payload.get("reason")
    if state is GpuLifecycleState.DEGRADED:
        if not isinstance(reason, str) or not reason.strip():
            return None
    elif reason is not None:
        return None

    written_at = payload.get("written_at")
    if isinstance(written_at, bool) or not isinstance(written_at, (int, float)):
        return None
    if not math.isfinite(written_at):
        return None
    if (
        isinstance(max_age_seconds, bool)
        or not isinstance(max_age_seconds, (int, float))
        or not math.isfinite(max_age_seconds)
        or max_age_seconds < 0
    ):
        raise ValueError("max_age_seconds must be finite and non-negative")
    if (
        isinstance(max_future_skew_seconds, bool)
        or not isinstance(max_future_skew_seconds, (int, float))
        or not math.isfinite(max_future_skew_seconds)
        or max_future_skew_seconds < 0
    ):
        raise ValueError("max_future_skew_seconds must be finite and non-negative")

    if now is None:
        current_time = time.time()
    elif isinstance(now, datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        current_time = now.timestamp()
    elif isinstance(now, bool) or not isinstance(now, (int, float)):
        raise ValueError("now must be a datetime or finite epoch seconds")
    else:
        current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")

    if written_at - current_time > max_future_skew_seconds:
        return None
    if current_time - written_at > max_age_seconds:
        return None
    return state


def state_for_instances(
    instance_states: list[str],
    *,
    previous_state: GpuLifecycleState | None = None,
) -> GpuLifecycleState:
    """Reduce the configured instances to one fail-closed service state."""
    if not instance_states:
        return GpuLifecycleState.DEGRADED
    mapped = {state_for_instance(state) for state in instance_states}
    # READY and DEGRADED are per-cycle probe verdicts. OCI RUNNING alone proves
    # only WARMING, so neither verdict may displace it on a later unprobed
    # cycle. This gives DEGRADED an exit edge and prevents stale READY evidence
    # from being republished as though a current readiness probe produced it.
    del previous_state
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
    instance_id: str | None = None,
    reason: str | None = None,
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
    if instance_id is not None and (not isinstance(instance_id, str) or not instance_id.strip()):
        raise ValueError("instance_id must be a non-blank string or None")
    if published_state is GpuLifecycleState.DEGRADED:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("degraded GPU lifecycle snapshots require a reason")
    elif reason is not None:
        raise ValueError("reason is only valid for degraded GPU lifecycle snapshots")

    target = resolve_gpu_state_path() if path is None else Path(path)
    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        since = written_at
        try:
            previous = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            previous = None
        if (
            isinstance(previous, dict)
            and instance_id is not None
            and previous.get("instance_id") == instance_id
            and previous.get("state") == published_state.value
        ):
            previous_since = previous.get("since")
            if (
                not isinstance(previous_since, bool)
                and isinstance(previous_since, (int, float))
                and math.isfinite(previous_since)
                and previous_since <= written_at
            ):
                since = previous_since
        payload = {
            "state": published_state.value,
            "instance_id": instance_id,
            "written_at": written_at,
            "reason": reason,
            "since": since,
        }
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
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
        return False
    return True
