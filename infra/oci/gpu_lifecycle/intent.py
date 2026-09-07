"""Reader for operator GPU lifecycle intent snapshots.

The description service is the only writer for these files.  The lifecycle
process deliberately keeps this module read-only and treats every malformed
publication as ``auto`` so an operator-control outage cannot disable the
existing safety policy.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

INTENT_SCHEMA_VERSION = 1
MAX_INTENT_TTL_SECONDS = 7200.0
MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS = 5.0


class IntentAction(StrEnum):
    """Operator-requested lifecycle mode."""

    START = "start"
    STOP = "stop"
    AUTO = "auto"


class IntentStatus(StrEnum):
    """How the lifecycle controller handled the effective intent."""

    NONE = "none"
    PENDING = "pending"
    HONOURED = "honoured"
    BLOCKED_WORK_IN_FLIGHT = "blocked_work_in_flight"
    EXPIRED = "expired"


@dataclass(frozen=True)
class OperatorIntent:
    """One validated operator intent publication."""

    action: IntentAction
    requested_at: datetime
    expires_at: datetime
    nonce: str
    requested_by: str | None = None
    ttl_seconds: float | None = None
    schema_version: int = INTENT_SCHEMA_VERSION
    source: Path | None = None


@dataclass(frozen=True)
class EffectiveIntent:
    """The newest unexpired publication across all environments."""

    action: IntentAction = IntentAction.AUTO
    requested_at: datetime | None = None
    expires_at: datetime | None = None
    nonce: str | None = None
    requested_by: str | None = None
    source: Path | None = None
    status: IntentStatus = IntentStatus.NONE

    @property
    def intent(self) -> IntentAction:
        """Alias used by snapshot consumers for the C2 field name."""
        return self.action


def _coerce_now(now: datetime | float | int | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if isinstance(now, datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return now.astimezone(UTC)
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
        raise ValueError("now must be a finite epoch timestamp or timezone-aware datetime")
    return datetime.fromtimestamp(float(now), tz=UTC)


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _invalid(path: Path, error: object) -> None:
    logger.warning("operator intent invalid file %s: %s", path, error)


def _read_one(path: Path, *, read_time: datetime | None = None) -> OperatorIntent | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _invalid(path, exc)
        return None
    if not isinstance(payload, dict):
        _invalid(path, "payload must be a JSON object")
        return None

    schema_version = payload.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != INTENT_SCHEMA_VERSION:
        _invalid(path, f"schema_version must be {INTENT_SCHEMA_VERSION}")
        return None

    raw_action = payload.get("action")
    try:
        action = IntentAction(raw_action)
    except (TypeError, ValueError) as exc:
        _invalid(path, f"action must be one of {[item.value for item in IntentAction]} ({exc})")
        return None

    try:
        requested_at = _parse_timestamp(payload.get("requested_at"), field="requested_at")
        expires_at = _parse_timestamp(payload.get("expires_at"), field="expires_at")
    except ValueError as exc:
        _invalid(path, exc)
        return None
    if expires_at <= requested_at:
        _invalid(path, "expires_at must be later than requested_at")
        return None

    expiry_anchor = requested_at
    if read_time is not None:
        future_skew = (requested_at - read_time).total_seconds()
        if future_skew > MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS:
            _invalid(
                path,
                "requested_at is future-dated by "
                f"{future_skew:.1f}s (allowance={MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS:.1f}s)",
            )
            return None
        # A small clock skew is tolerated, but its TTL must still be measured
        # from the reader's clock rather than allowing a writer to extend it.
        expiry_anchor = min(requested_at, read_time)

    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce.strip():
        _invalid(path, "nonce must be a non-blank string")
        return None

    requested_by = payload.get("requested_by")
    if requested_by is not None and (not isinstance(requested_by, str) or not requested_by.strip()):
        _invalid(path, "requested_by must be a non-blank string when present")
        return None

    ttl_seconds = payload.get("ttl_seconds")
    if ttl_seconds is not None:
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not math.isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            _invalid(path, "ttl_seconds must be a positive finite number when present")
            return None
        ttl_seconds = float(ttl_seconds)

    # Treat an overlong expiry as a bounded operator request rather than
    # allowing a malformed writer to pin the machine indefinitely.
    maximum_expiry = expiry_anchor + timedelta(seconds=MAX_INTENT_TTL_SECONDS)
    if expires_at > maximum_expiry:
        logger.warning(
            "operator intent expiry clamped to %.0fs: %s (expires_at=%s)",
            MAX_INTENT_TTL_SECONDS,
            path,
            expires_at.isoformat(),
        )
        expires_at = maximum_expiry

    return OperatorIntent(
        action=action,
        requested_at=requested_at,
        expires_at=expires_at,
        nonce=nonce,
        requested_by=requested_by,
        ttl_seconds=ttl_seconds,
        schema_version=schema_version,
        source=path,
    )


def _candidate_paths(intent_dir: Path) -> list[Path]:
    try:
        if not intent_dir.exists():
            _invalid(intent_dir / "*/gpu-intent.json", "intent directory does not exist")
            return []
        if not intent_dir.is_dir():
            _invalid(intent_dir, "intent path is not a directory")
            return []
        paths = sorted(intent_dir.glob("*/gpu-intent.json"))
    except OSError as exc:
        _invalid(intent_dir / "*/gpu-intent.json", exc)
        return []
    if not paths:
        _invalid(intent_dir / "*/gpu-intent.json", "no intent file found")
    return paths


def read_effective_intent(
    intent_dir: str | Path | None,
    now: datetime | float | int | None = None,
) -> EffectiveIntent:
    """Aggregate ``*/gpu-intent.json`` and choose the effective publication.

    The newest unexpired ``requested_at`` wins.  Publications with equal
    timestamps resolve to STOP, which is the conservative tie-breaker.  A
    ``None`` directory means the optional feature is disabled and is silent,
    preserving the legacy lifecycle behavior exactly.
    """
    if intent_dir is None:
        return EffectiveIntent()

    current_time = _coerce_now(now)
    root = Path(intent_dir)
    valid: list[OperatorIntent] = []
    expired = False
    for path in _candidate_paths(root):
        intent = _read_one(path, read_time=current_time)
        if intent is None:
            continue
        if intent.expires_at <= current_time:
            expired = True
            _invalid(path, f"intent expired at {intent.expires_at.isoformat()}")
            continue
        valid.append(intent)

    if not valid:
        return EffectiveIntent(status=IntentStatus.EXPIRED if expired else IntentStatus.NONE)

    winner = max(
        valid,
        key=lambda item: (
            item.requested_at,
            item.action is IntentAction.STOP,
            str(item.source or ""),
        ),
    )
    return EffectiveIntent(
        action=winner.action,
        requested_at=winner.requested_at,
        expires_at=winner.expires_at,
        nonce=winner.nonce,
        requested_by=winner.requested_by,
        source=winner.source,
        status=IntentStatus.NONE,
    )
