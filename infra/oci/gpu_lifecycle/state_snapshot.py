"""Atomic producer for the GPU lifecycle state consumed by the describe API."""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from infra.oci.gpu_lifecycle.controller import GpuInstanceState
from infra.oci.gpu_lifecycle.intent import IntentAction, IntentStatus

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


class LastTransitionReason(StrEnum):
    """Why the lifecycle last actuated a GPU instance."""

    WORK = "work"
    OPERATOR = "operator"
    IDLE = "idle"
    LEASE_CAP = "lease_cap"
    START_FAILED = "start_failed"
    UNKNOWN = "unknown"


_SNAPSHOT_FIELD_UNSET = object()


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


def _validate_expected_instance_id(expected_instance_id: str | None) -> None:
    """Own validation of the optional instance identity required for reuse."""
    if expected_instance_id is not None and (
        not isinstance(expected_instance_id, str) or not expected_instance_id.strip()
    ):
        raise ValueError("expected_instance_id must be a non-blank string or None")


def _read_snapshot_payload(target: Path) -> object | None:
    """Own classification of unreadable or malformed snapshot files as absent."""
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _parse_snapshot_state(payload: dict[str, object]) -> GpuLifecycleState | None:
    """Own parsing of the published lifecycle state field."""
    state_value = payload.get("state")
    if not isinstance(state_value, str):
        return None
    try:
        return GpuLifecycleState(state_value)
    except ValueError:
        return None


def _snapshot_identity_matches(payload: dict[str, object], expected_instance_id: str | None) -> bool:
    """Own validation that a prior snapshot belongs to the reconciled instance."""
    instance_id = payload.get("instance_id")
    if instance_id is not None and (not isinstance(instance_id, str) or not instance_id.strip()):
        return False
    return expected_instance_id is not None and instance_id == expected_instance_id


def _snapshot_reason_is_valid(payload: dict[str, object], state: GpuLifecycleState) -> bool:
    """Own validation of the state-dependent reason contract."""
    reason = payload.get("reason")
    if state is GpuLifecycleState.DEGRADED:
        return isinstance(reason, str) and bool(reason.strip())
    return reason is None


def _validate_previous_snapshot_schema(
    payload: dict[str, object],
    expected_instance_id: str | None,
) -> GpuLifecycleState | None:
    """Own validation of prior state, identity, and reason schema fields."""
    state = _parse_snapshot_state(payload)
    if state is None:
        return None
    if not _snapshot_identity_matches(payload, expected_instance_id):
        return None
    if not _snapshot_reason_is_valid(payload, state):
        return None
    return state


def _read_snapshot_written_at(payload: dict[str, object]) -> int | float | None:
    """Own validation of the numeric timestamp used for freshness checks."""
    written_at = payload.get("written_at")
    if isinstance(written_at, bool) or not isinstance(written_at, (int, float)):
        return None
    if not math.isfinite(written_at):
        return None
    return written_at


def _validate_previous_snapshot_limits(
    max_age_seconds: float,
    max_future_skew_seconds: float,
) -> None:
    """Own validation of the permitted prior-snapshot freshness window."""
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


def _resolve_previous_snapshot_now(now: datetime | float | None) -> float:
    """Own conversion and validation of the clock used for freshness checks."""
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
    return current_time


def _previous_snapshot_is_fresh(
    written_at: int | float,
    current_time: float,
    max_age_seconds: float,
    max_future_skew_seconds: float,
) -> bool:
    """Own the fallback decision that bounds prior-state reuse by time."""
    if written_at - current_time > max_future_skew_seconds:
        return False
    if current_time - written_at > max_age_seconds:
        return False
    return True


def read_previous_gpu_state(
    path: str | Path | None = None,
    *,
    expected_instance_id: str | None,
    now: datetime | float | None = None,
    max_age_seconds: float = DEFAULT_PREVIOUS_GPU_STATE_MAX_AGE_SECONDS,
    max_future_skew_seconds: float = (DEFAULT_PREVIOUS_GPU_STATE_MAX_FUTURE_SKEW_SECONDS),
) -> GpuLifecycleState | None:
    """Read state only when it belongs to the currently reconciled instance."""
    _validate_expected_instance_id(expected_instance_id)
    target = resolve_gpu_state_path() if path is None else Path(path)
    payload = _read_snapshot_payload(target)
    if not isinstance(payload, dict):
        return None
    state = _validate_previous_snapshot_schema(payload, expected_instance_id)
    if state is None:
        return None
    written_at = _read_snapshot_written_at(payload)
    if written_at is None:
        return None
    _validate_previous_snapshot_limits(max_age_seconds, max_future_skew_seconds)
    current_time = _resolve_previous_snapshot_now(now)
    if not _previous_snapshot_is_fresh(
        written_at,
        current_time,
        max_age_seconds,
        max_future_skew_seconds,
    ):
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


def _serialize_snapshot_time(value: datetime | str | None | object, *, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, str) and value.strip():
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} must include a timezone")
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise ValueError(f"{field} must be a timezone-aware datetime, ISO-8601 string, or None")


def _coerce_snapshot_state(state: GpuLifecycleState | str) -> GpuLifecycleState:
    """Own conversion and rejection of an unpublished lifecycle state value."""
    try:
        return GpuLifecycleState(state)
    except ValueError as exc:
        raise ValueError(f"refusing to publish GPU lifecycle state {state!r}") from exc


def _resolve_snapshot_written_at(now: float | None) -> int | float:
    """Own validation of the epoch timestamp emitted in a snapshot."""
    written_at = time.time() if now is None else now
    if isinstance(written_at, bool) or not isinstance(written_at, (int, float)):
        raise ValueError("written_at must be epoch seconds")
    if not math.isfinite(written_at):
        raise ValueError("written_at must be finite epoch seconds")
    return written_at


def _validate_snapshot_instance_id(instance_id: str | None) -> None:
    """Own validation of the optional instance identity emitted in a snapshot."""
    if instance_id is not None and (not isinstance(instance_id, str) or not instance_id.strip()):
        raise ValueError("instance_id must be a non-blank string or None")


def _validate_snapshot_reason(
    published_state: GpuLifecycleState,
    reason: str | None,
) -> None:
    """Own validation of the state-dependent reason emitted in a snapshot."""
    if published_state is GpuLifecycleState.DEGRADED:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("degraded GPU lifecycle snapshots require a reason")
    elif reason is not None:
        raise ValueError("reason is only valid for degraded GPU lifecycle snapshots")


def _coerce_snapshot_intent(intent: IntentAction | str | None | object) -> IntentAction:
    """Own conversion of the optional intent field and its error classification."""
    try:
        return IntentAction.AUTO if intent is _SNAPSHOT_FIELD_UNSET or intent is None else IntentAction(intent)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid intent snapshot value: {intent!r}") from exc


def _coerce_snapshot_intent_status(intent_status: IntentStatus | str | None | object) -> IntentStatus:
    """Own conversion of the optional intent status and its error classification."""
    try:
        return (
            IntentStatus.NONE
            if intent_status is _SNAPSHOT_FIELD_UNSET or intent_status is None
            else IntentStatus(intent_status)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid intent_status snapshot value: {intent_status!r}") from exc


def _coerce_snapshot_transition_reason(
    last_transition_reason: LastTransitionReason | str | None | object,
) -> LastTransitionReason:
    """Own conversion of the optional transition reason and its error classification."""
    try:
        return (
            LastTransitionReason.UNKNOWN
            if last_transition_reason is _SNAPSHOT_FIELD_UNSET or last_transition_reason is None
            else LastTransitionReason(last_transition_reason)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid last_transition_reason snapshot value: {last_transition_reason!r}") from exc


def _validate_snapshot_nonce(honoured_nonce: str | None | object) -> str | None:
    """Own validation of the optional nonce carried by an intent snapshot."""
    nonce = None if honoured_nonce is _SNAPSHOT_FIELD_UNSET else honoured_nonce
    if nonce is not None and (not isinstance(nonce, str) or not nonce.strip()):
        raise ValueError("honoured_nonce must be a non-blank string or None")
    return nonce


def _build_intent_snapshot_fields(
    *,
    intent: IntentAction | str | None | object,
    intent_expires_at: datetime | str | None | object,
    intent_status: IntentStatus | str | None | object,
    honoured_nonce: str | None | object,
    lease_expires_at: datetime | str | None | object,
    instance_running_since: datetime | str | None | object,
    last_transition_reason: LastTransitionReason | str | None | object,
) -> dict[str, object]:
    """Own optional C2 field inclusion, defaults, and timestamp serialization."""
    if not any(
        value is not _SNAPSHOT_FIELD_UNSET
        for value in (
            intent,
            intent_expires_at,
            intent_status,
            honoured_nonce,
            lease_expires_at,
            instance_running_since,
            last_transition_reason,
        )
    ):
        return {}

    effective_intent = _coerce_snapshot_intent(intent)
    effective_status = _coerce_snapshot_intent_status(intent_status)
    transition_reason = _coerce_snapshot_transition_reason(last_transition_reason)
    nonce = _validate_snapshot_nonce(honoured_nonce)
    return {
        "intent": effective_intent.value,
        "intent_expires_at": _serialize_snapshot_time(
            None if intent_expires_at is _SNAPSHOT_FIELD_UNSET else intent_expires_at,
            field="intent_expires_at",
        ),
        "intent_status": effective_status.value,
        "honoured_nonce": nonce,
        "lease_expires_at": _serialize_snapshot_time(
            None if lease_expires_at is _SNAPSHOT_FIELD_UNSET else lease_expires_at,
            field="lease_expires_at",
        ),
        "instance_running_since": _serialize_snapshot_time(
            None if instance_running_since is _SNAPSHOT_FIELD_UNSET else instance_running_since,
            field="instance_running_since",
        ),
        "last_transition_reason": transition_reason.value,
    }


def _snapshot_since(
    previous: object,
    instance_id: str | None,
    published_state: GpuLifecycleState,
    written_at: int | float,
) -> int | float:
    """Own fallback to the prior state-change timestamp when continuity is proven."""
    since = written_at
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
    return since


def _write_snapshot_atomically(
    target: Path,
    *,
    published_state: GpuLifecycleState,
    instance_id: str | None,
    written_at: int | float,
    reason: str | None,
    c2_payload: dict[str, object],
) -> bool:
    """Own directory setup, durable temp-file replacement, and write-error handling."""
    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = _read_snapshot_payload(target)
        since = _snapshot_since(previous, instance_id, published_state, written_at)
        payload = {
            "state": published_state.value,
            "instance_id": instance_id,
            "written_at": written_at,
            "reason": reason,
            "since": since,
        }
        payload.update(c2_payload)
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


def write_gpu_state_snapshot(
    state: GpuLifecycleState | str,
    *,
    instance_id: str | None = None,
    reason: str | None = None,
    now: float | None = None,
    path: str | Path | None = None,
    intent: IntentAction | str | None | object = _SNAPSHOT_FIELD_UNSET,
    intent_expires_at: datetime | str | None | object = _SNAPSHOT_FIELD_UNSET,
    intent_status: IntentStatus | str | None | object = _SNAPSHOT_FIELD_UNSET,
    honoured_nonce: str | None | object = _SNAPSHOT_FIELD_UNSET,
    lease_expires_at: datetime | str | None | object = _SNAPSHOT_FIELD_UNSET,
    instance_running_since: datetime | str | None | object = _SNAPSHOT_FIELD_UNSET,
    last_transition_reason: LastTransitionReason | str | None | object = _SNAPSHOT_FIELD_UNSET,
) -> bool:
    """Atomically publish a fresh snapshot; telemetry failures never escape."""
    published_state = _coerce_snapshot_state(state)
    written_at = _resolve_snapshot_written_at(now)
    _validate_snapshot_instance_id(instance_id)
    _validate_snapshot_reason(published_state, reason)
    c2_payload = _build_intent_snapshot_fields(
        intent=intent,
        intent_expires_at=intent_expires_at,
        intent_status=intent_status,
        honoured_nonce=honoured_nonce,
        lease_expires_at=lease_expires_at,
        instance_running_since=instance_running_since,
        last_transition_reason=last_transition_reason,
    )
    target = resolve_gpu_state_path() if path is None else Path(path)
    return _write_snapshot_atomically(
        target,
        published_state=published_state,
        instance_id=instance_id,
        written_at=written_at,
        reason=reason,
        c2_payload=c2_payload,
    )
