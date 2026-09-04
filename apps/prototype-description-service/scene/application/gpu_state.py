"""Fail-closed reader for the GPU lifecycle snapshot (GPUUX-1).

The lifecycle controller is the single writer of ``/run/acx/gpu-state.json``
(DATA-14). This module only reads it. Missing, unreadable, corrupt, unknown
enum, or stale snapshots become ``GpuState.UNKNOWN`` — never fabricated
``ready`` (RES-03).
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

GPU_STATE_PATH_ENV = "ACX_GPU_STATE_PATH"
DEFAULT_GPU_STATE_PATH = "/run/acx/gpu-state.json"
GPU_STATE_STALE_SECONDS_ENV = "ACX_GPU_STATE_STALE_SECONDS"
DEFAULT_GPU_STATE_STALE_SECONDS = 180.0
GPU_STATE_FUTURE_SKEW_SECONDS = 5.0


class GpuState(StrEnum):
    """Burst-GPU execution state on DescribeRunResponse (sr-007)."""

    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTING = "starting"
    WARMING = "warming"
    READY = "ready"
    DEGRADED = "degraded"


_OBSERVED_LOCK = threading.Lock()
_last_observed: GpuState | None = None


@dataclass(frozen=True)
class GpuStateSettings:
    """Immutable GPU snapshot policy loaded once when the service starts.

    An unset stale-seconds variable intentionally uses the documented 180s
    default. An explicitly configured value must be a finite positive number;
    malformed configuration fails startup instead of silently changing policy.
    """

    stale_seconds: float

    @classmethod
    def from_environment(cls) -> GpuStateSettings:
        raw = os.environ.get(GPU_STATE_STALE_SECONDS_ENV)
        if raw is None:
            return cls(stale_seconds=DEFAULT_GPU_STATE_STALE_SECONDS)
        try:
            seconds = float(raw)
        except ValueError:
            seconds = math.nan
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(
                f"{GPU_STATE_STALE_SECONDS_ENV} must be a finite number in the "
                f"range 0 < seconds < infinity; got {raw!r}"
            )
        return cls(stale_seconds=seconds)


_GPU_STATE_SETTINGS = GpuStateSettings.from_environment()


def resolve_gpu_state_path() -> str:
    """Single source of truth for the lifecycle snapshot path (rg-008)."""
    configured_path = os.environ.get(GPU_STATE_PATH_ENV)
    if configured_path is None or not configured_path.strip():
        return DEFAULT_GPU_STATE_PATH
    return configured_path


def resolve_gpu_state_stale_seconds() -> float:
    """Return the immutable snapshot freshness window loaded at startup."""
    return _GPU_STATE_SETTINGS.stale_seconds


def reset_gpu_state_observation_for_tests() -> None:
    """Clear the last-logged state so tests can assert transition logging."""
    global _last_observed
    with _OBSERVED_LOCK:
        _last_observed = None


def read_gpu_state(*, now: float | None = None) -> GpuState:
    """Read the lifecycle snapshot, fail-closed to ``unknown``."""
    state = _read_snapshot(now=time.time() if now is None else now)
    _log_transition(state)
    return state


def _read_snapshot(*, now: float) -> GpuState:
    path = Path(resolve_gpu_state_path())
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return GpuState.UNKNOWN
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return GpuState.UNKNOWN
    if not isinstance(payload, dict):
        return GpuState.UNKNOWN
    return _state_from_payload(payload, now=now)


def _state_from_payload(payload: dict[str, Any], *, now: float) -> GpuState:
    # Standalone mirror of docs/workbay/contracts/gpu-lifecycle.md. The API and
    # lifecycle controller are separate deployables, so do not couple them with
    # a cross-boundary validation import.
    state_raw = payload.get("state")
    if not isinstance(state_raw, str):
        return GpuState.UNKNOWN
    try:
        state = GpuState(state_raw)
    except ValueError:
        return GpuState.UNKNOWN
    if state is GpuState.UNKNOWN:
        return GpuState.UNKNOWN
    written_at = payload.get("written_at")
    if isinstance(written_at, bool) or not isinstance(written_at, (int, float)):
        return GpuState.UNKNOWN
    if not math.isfinite(written_at):
        return GpuState.UNKNOWN

    instance_id = payload.get("instance_id")
    if instance_id is not None and (
        not isinstance(instance_id, str) or not instance_id.strip()
    ):
        return GpuState.UNKNOWN

    reason = payload.get("reason")
    if state is GpuState.DEGRADED:
        if not isinstance(reason, str) or not reason.strip():
            return GpuState.UNKNOWN
    elif reason is not None:
        return GpuState.UNKNOWN

    if "since" in payload:
        since = payload["since"]
        if (
            isinstance(since, bool)
            or not isinstance(since, (int, float))
            or not math.isfinite(since)
            or since > written_at
        ):
            return GpuState.UNKNOWN

    if written_at - now > GPU_STATE_FUTURE_SKEW_SECONDS:
        return GpuState.UNKNOWN
    if now - written_at > resolve_gpu_state_stale_seconds():
        return GpuState.UNKNOWN
    return state


def _log_transition(state: GpuState) -> None:
    global _last_observed
    with _OBSERVED_LOCK:
        previous = _last_observed
        if previous is state:
            return
        _logger.info("gpu_state transition %s -> %s", previous, state)
        _last_observed = state
