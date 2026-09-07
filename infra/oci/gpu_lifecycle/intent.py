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
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

INTENT_SCHEMA_VERSION = 1
MAX_INTENT_TTL_SECONDS = 7200.0
MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS = 120.0
_INTENT_FIELDS = frozenset(
    {
        "schema_version",
        "action",
        "requested_at",
        "expires_at",
        "ttl_seconds",
        "requested_by",
        "nonce",
    }
)


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
    requested_by: str
    ttl_seconds: int
    schema_version: int = INTENT_SCHEMA_VERSION
    source: Path | None = None
    reason: str | None = None


@dataclass(frozen=True)
class IntentFenceVerdict:
    """The fence's ruling on one candidate publication.

    ``expired`` is authoritative: it may expire a publication the wall clock
    still considers live (the resurrection case RES-10 exists to stop), and it
    may keep one alive past its wall-clock expiry when a declared late-event
    policy says so (FLOW-08).
    """

    expired: bool
    reason: str | None = None


@runtime_checkable
class IntentFence(Protocol):
    """Durable authority check layered over the writer-supplied timestamps."""

    def evaluate(
        self,
        intent: OperatorIntent,
        *,
        wall_clock_expired: bool,
        now: datetime,
    ) -> IntentFenceVerdict:
        """Rule on one publication. Raising means "refuse the grant"."""


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
    reason: str | None = None

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


def _invalid(path: Path, error: object, *, reason_sink: list[str] | None = None) -> None:
    message = str(error)
    if reason_sink is not None and not reason_sink:
        reason_sink.append(message)
    logger.warning("operator intent invalid file %s: %s", path, message)


def _read_one(
    path: Path,
    *,
    read_time: datetime | None = None,
    reason_sink: list[str] | None = None,
) -> OperatorIntent | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _invalid(path, exc, reason_sink=reason_sink)
        return None
    if not isinstance(payload, dict):
        _invalid(path, "payload must be a JSON object", reason_sink=reason_sink)
        return None

    schema_version = payload.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != INTENT_SCHEMA_VERSION:
        _invalid(path, f"schema_version must be {INTENT_SCHEMA_VERSION}", reason_sink=reason_sink)
        return None

    raw_action = payload.get("action")
    try:
        action = IntentAction(raw_action)
    except (TypeError, ValueError) as exc:
        _invalid(
            path,
            f"action must be one of {[item.value for item in IntentAction]} ({exc})",
            reason_sink=reason_sink,
        )
        return None

    try:
        requested_at = _parse_timestamp(payload.get("requested_at"), field="requested_at")
        expires_at = _parse_timestamp(payload.get("expires_at"), field="expires_at")
    except ValueError as exc:
        _invalid(path, exc, reason_sink=reason_sink)
        return None
    if expires_at <= requested_at:
        _invalid(path, "expires_at must be later than requested_at", reason_sink=reason_sink)
        return None

    ttl_seconds = payload.get("ttl_seconds")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        _invalid(path, "ttl_seconds must be a positive integer", reason_sink=reason_sink)
        return None

    requested_by = payload.get("requested_by")
    if not isinstance(requested_by, str) or not requested_by.strip():
        _invalid(path, "requested_by must be a non-blank string", reason_sink=reason_sink)
        return None

    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce.strip():
        _invalid(path, "nonce must be a UUID4", reason_sink=reason_sink)
        return None
    normalized_nonce = nonce.strip()
    try:
        parsed_nonce = uuid.UUID(normalized_nonce)
    except (AttributeError, ValueError) as exc:
        _invalid(path, f"nonce must be a UUID4 ({exc})", reason_sink=reason_sink)
        return None
    if parsed_nonce.variant != uuid.RFC_4122 or parsed_nonce.version != 4:
        _invalid(path, "nonce must be a UUID4", reason_sink=reason_sink)
        return None

    unexpected_fields = sorted(set(payload) - _INTENT_FIELDS)
    if unexpected_fields:
        _invalid(path, f"unexpected field {unexpected_fields[0]!r}", reason_sink=reason_sink)
        return None

    expiry_anchor = requested_at
    parse_reasons: list[str] = []
    if read_time is not None:
        read_time = _coerce_now(read_time)
        future_skew = (requested_at - read_time).total_seconds()
        if future_skew > MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS:
            _invalid(
                path,
                "requested_at is future-dated by "
                f"{future_skew:.1f}s (allowance={MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS:.1f}s)",
                reason_sink=reason_sink,
            )
            return None
        # A small clock skew is tolerated, but its TTL must still be measured
        # from the reader's clock rather than allowing a writer to extend it.
        expiry_anchor = min(requested_at, read_time)
        if requested_at > read_time:
            parse_reasons.append("requested_at within clock-skew tolerance")

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
        parse_reasons.append(f"expires_at clamped to {MAX_INTENT_TTL_SECONDS:.0f} seconds")

    return OperatorIntent(
        action=action,
        requested_at=requested_at,
        expires_at=expires_at,
        nonce=normalized_nonce,
        requested_by=requested_by,
        ttl_seconds=ttl_seconds,
        schema_version=schema_version,
        source=path,
        reason=("; ".join(parse_reasons) if parse_reasons else None),
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


def _fence_verdict(
    fence: IntentFence | None,
    intent: OperatorIntent,
    *,
    wall_clock_expired: bool,
    now: datetime,
) -> IntentFenceVerdict:
    """Apply the durable fence, failing closed when it cannot answer.

    Without a fence the wall clock is the only authority available, which is
    the legacy behavior.  With one, a fence that raises must revoke the grant
    rather than be skipped: the arm this gates is the one that suppresses the
    idle reaper and disables the cost governor (RLSE-05, OBS-08).
    """
    if fence is None:
        return IntentFenceVerdict(expired=wall_clock_expired)
    try:
        verdict = fence.evaluate(intent, wall_clock_expired=wall_clock_expired, now=now)
    except Exception as exc:  # noqa: BLE001 - an unusable fence revokes the grant
        logger.error("operator intent fence failed; refusing the grant: %s", exc)
        return IntentFenceVerdict(
            expired=True,
            reason=f"intent fence unavailable; grant refused ({type(exc).__name__}: {exc})",
        )
    if not isinstance(verdict, IntentFenceVerdict):
        logger.error("operator intent fence returned %r; refusing the grant", verdict)
        return IntentFenceVerdict(expired=True, reason="intent fence returned an unusable verdict")
    return verdict


def read_effective_intent(
    intent_dir: str | Path | None,
    now: datetime | float | int | None = None,
    *,
    fence: IntentFence | None = None,
) -> EffectiveIntent:
    """Aggregate ``*/gpu-intent.json`` and choose the effective publication.

    The newest unexpired ``requested_at`` wins.  Publications with equal
    timestamps resolve to STOP, which is the conservative tie-breaker.  A
    ``None`` directory means the optional feature is disabled and is silent,
    preserving the legacy lifecycle behavior exactly.

    ``fence`` is the durable authority check.  ``expires_at`` and
    ``requested_at`` are both wall-clock values supplied by the writer, so on
    their own they cannot survive a backwards NTP correction: an already-dead
    ``start`` grant would silently re-arm.  The fence owns the monotonic
    origin and the burned-nonce ledger that make the grant one-shot (RES-10).
    """
    if intent_dir is None:
        return EffectiveIntent()

    current_time = _coerce_now(now)
    root = Path(intent_dir)
    valid: list[OperatorIntent] = []
    expired = False
    parse_reasons: list[str] = []
    fence_reasons: list[str] = []
    for path in _candidate_paths(root):
        intent = _read_one(path, read_time=current_time, reason_sink=parse_reasons)
        if intent is None:
            continue
        wall_clock_expired = intent.expires_at <= current_time
        verdict = _fence_verdict(
            fence,
            intent,
            wall_clock_expired=wall_clock_expired,
            now=current_time,
        )
        if verdict.expired:
            expired = True
            reason = verdict.reason or f"intent expired at {intent.expires_at.isoformat()}"
            fence_reasons.append(reason)
            _invalid(path, reason)
            continue
        if verdict.reason:
            intent = replace(
                intent,
                reason="; ".join(part for part in (intent.reason, verdict.reason) if part),
            )
        valid.append(intent)

    if not valid:
        # A parse failure names a broken writer; a fence revocation names a
        # grant the controller deliberately refused. Both must reach the
        # operator, and the parse error is reported first because it is the
        # one that says the publication never became an intent at all.
        return EffectiveIntent(
            status=IntentStatus.EXPIRED if expired else IntentStatus.NONE,
            reason=(
                parse_reasons[0]
                if parse_reasons
                else (
                    fence_reasons[0]
                    if fence_reasons
                    else ("intent expired" if expired else None)
                )
            ),
        )

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
        reason=winner.reason,
    )
