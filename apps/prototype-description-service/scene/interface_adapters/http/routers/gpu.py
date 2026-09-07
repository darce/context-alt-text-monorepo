"""GPU lifecycle status and operator intent routes (GPUOPS-1 C3)."""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from recognition.interface_adapters.http.deps import require_auth, require_write_access
from scene.application.describe_load import resolve_load_path
from scene.application.gpu_intent import (
    IntentAction,
    OperatorIntent,
    read_gpu_intent,
    resolve_gpu_intent_path,
    write_gpu_intent,
)
from scene.application.gpu_state import GpuState, read_gpu_state, resolve_gpu_state_path

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["gpu"])

SNAPSHOT_FRESH_SECONDS = 120.0


class GpuIntentStatus(StrEnum):
    """Controller handling status from C2."""

    NONE = "none"
    PENDING = "pending"
    HONOURED = "honoured"
    BLOCKED_WORK_IN_FLIGHT = "blocked_work_in_flight"
    EXPIRED = "expired"


class GpuTransitionReason(StrEnum):
    """Lifecycle transition reason from C2."""

    WORK = "work"
    OPERATOR = "operator"
    IDLE = "idle"
    LEASE_CAP = "lease_cap"
    START_FAILED = "start_failed"
    UNKNOWN = "unknown"


class GpuIntentRequest(BaseModel):
    """Validated POST /gpu/intent body."""

    model_config = ConfigDict(extra="forbid")

    action: IntentAction
    ttl_seconds: StrictInt | None = None
    requested_by: StrictStr | None = None


class OperatorIntentResponse(BaseModel):
    """C1 intent object exposed by the status API."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    action: IntentAction
    requested_at: str
    expires_at: str
    ttl_seconds: int
    requested_by: str
    nonce: str


class GpuStateResponse(BaseModel):
    """C2 GPU lifecycle snapshot, including additive intent fields."""

    model_config = ConfigDict(extra="forbid")

    state: GpuState = GpuState.UNKNOWN
    instance_id: str | None = None
    written_at: float | None = None
    reason: str | None = None
    since: float | None = None
    intent: IntentAction = IntentAction.AUTO
    intent_expires_at: str | None = None
    intent_status: GpuIntentStatus = GpuIntentStatus.NONE
    honoured_nonce: str | None = None
    lease_expires_at: str | None = None
    instance_running_since: str | None = None
    last_transition_reason: GpuTransitionReason = GpuTransitionReason.UNKNOWN


class GpuLoadResponse(BaseModel):
    """Load snapshot summary used by the operator UI."""

    model_config = ConfigDict(extra="forbid")

    has_work: bool = False
    written_at: float | None = None
    fresh: bool = False


class GpuStatusResponse(BaseModel):
    """C3 status response shared by GET and accepted POST responses."""

    model_config = ConfigDict(extra="forbid")

    gpu_state: GpuStateResponse
    snapshot_age_seconds: float | None
    snapshot_fresh: bool
    intent: OperatorIntentResponse | None
    load: GpuLoadResponse
    server_time: str


@router.get("/gpu/status", response_model=GpuStatusResponse)
async def get_gpu_status(auth=Depends(require_auth)) -> GpuStatusResponse:
    """Return the latest lifecycle, operator-intent, and load observations."""
    del auth
    return _status_response(now=_now())


@router.post(
    "/gpu/intent",
    response_model=GpuStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_gpu_intent(
    request: GpuIntentRequest,
    auth=Depends(require_write_access),
) -> GpuStatusResponse:
    """Persist one operator intent and return the resulting status view."""
    if _is_demo_tier(auth):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="gpu_control_forbidden")
    now = _now()
    intent_path = resolve_gpu_intent_path()
    try:
        write_gpu_intent(
            intent_path,
            action=request.action,
            ttl_seconds=request.ttl_seconds,
            requested_by=request.requested_by,
            now=now,
        )
    except OSError as exc:
        _logger.warning("GPU intent unavailable path=%s: %s", intent_path, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="gpu_intent_unavailable",
        ) from exc
    return _status_response(now=now)


def _now() -> float:
    return time.time()


def _status_response(*, now: float) -> GpuStatusResponse:
    state_payload = _read_json_object(Path(resolve_gpu_state_path()))
    snapshot_age = _snapshot_age(state_payload, now=now)
    snapshot_fresh = _is_fresh(state_payload, now=now)
    state = read_gpu_state(now=now)
    if not snapshot_fresh:
        state = GpuState.UNKNOWN
    gpu_state = _gpu_state_response(state_payload, state=state)
    load = _load_response(Path(resolve_load_path()), now=now)
    intent = read_gpu_intent(resolve_gpu_intent_path())
    return GpuStatusResponse(
        gpu_state=gpu_state,
        snapshot_age_seconds=snapshot_age,
        snapshot_fresh=snapshot_fresh,
        intent=_intent_response(intent),
        load=load,
        server_time=_format_server_time(now),
    )


def _gpu_state_response(payload: dict[str, Any] | None, *, state: GpuState) -> GpuStateResponse:
    payload = payload or {}
    return GpuStateResponse(
        state=state,
        instance_id=_optional_string(payload.get("instance_id")),
        written_at=_finite_number(payload.get("written_at")),
        reason=_optional_string(payload.get("reason")),
        since=_finite_number(payload.get("since")),
        intent=_enum_value(payload.get("intent"), IntentAction, IntentAction.AUTO),
        intent_expires_at=_optional_string(payload.get("intent_expires_at")),
        intent_status=_enum_value(payload.get("intent_status"), GpuIntentStatus, GpuIntentStatus.NONE),
        honoured_nonce=_optional_string(payload.get("honoured_nonce")),
        lease_expires_at=_optional_string(payload.get("lease_expires_at")),
        instance_running_since=_optional_string(payload.get("instance_running_since")),
        last_transition_reason=_enum_value(
            payload.get("last_transition_reason"),
            GpuTransitionReason,
            GpuTransitionReason.UNKNOWN,
        ),
    )


def _load_response(path: Path, *, now: float) -> GpuLoadResponse:
    payload = _read_json_object(path) or {}
    written_at = _finite_number(payload.get("written_at"))
    has_work = any(
        _positive_number(payload.get(key))
        for key in ("queue_depth", "in_flight")
    ) or payload.get("batch_in_progress") is True
    return GpuLoadResponse(
        has_work=has_work,
        written_at=written_at,
        fresh=written_at is not None and _is_fresh_timestamp(written_at, now=now),
    )


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _logger.warning("GPU snapshot unavailable path=%s: %s", path, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _snapshot_age(payload: dict[str, Any] | None, *, now: float) -> float | None:
    written_at = _finite_number((payload or {}).get("written_at"))
    if written_at is None:
        return None
    return max(0.0, now - written_at)


def _is_fresh(payload: dict[str, Any] | None, *, now: float) -> bool:
    written_at = _finite_number((payload or {}).get("written_at"))
    return written_at is not None and _is_fresh_timestamp(written_at, now=now)


def _is_fresh_timestamp(written_at: float, *, now: float) -> bool:
    return written_at - now <= 5.0 and now - written_at <= SNAPSHOT_FRESH_SECONDS


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _positive_number(value: Any) -> bool:
    numeric = _finite_number(value)
    return numeric is not None and numeric > 0


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _enum_value(value: Any, enum_type, default):
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return default


def _intent_response(intent: OperatorIntent | None) -> OperatorIntentResponse | None:
    if intent is None:
        return None
    return OperatorIntentResponse(
        schema_version=1,
        action=intent.action,
        requested_at=_format_server_time(intent.requested_at.timestamp()),
        expires_at=_format_server_time(intent.expires_at.timestamp()),
        ttl_seconds=intent.ttl_seconds,
        requested_by=intent.requested_by,
        nonce=intent.nonce,
    )


def _format_server_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")


def _is_demo_tier(auth: Any) -> bool:
    """Recognize the demo marker exposed by auth fakes and auth contexts."""
    for attribute in ("rate_limit_tier", "tier", "demo_tier"):
        value = getattr(auth, attribute, None)
        if hasattr(value, "value"):
            value = value.value
        if isinstance(value, str) and value.strip().lower() in {"demo", "demo_tier"}:
            return True
    return any(bool(getattr(auth, attribute, False)) for attribute in ("is_demo", "demo"))


__all__ = [
    "GpuIntentRequest",
    "GpuIntentStatus",
    "GpuLoadResponse",
    "GpuStateResponse",
    "GpuStatusResponse",
    "GpuTransitionReason",
    "OperatorIntentResponse",
    "router",
]
