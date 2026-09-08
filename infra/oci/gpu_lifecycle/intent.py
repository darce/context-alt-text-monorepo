"""Reader for operator GPU lifecycle intent snapshots.

The description service is the only writer for these files.  The lifecycle
process deliberately keeps this module read-only and treats every malformed
publication as ``auto`` so an operator-control outage cannot disable the
existing safety policy.
"""

from __future__ import annotations

import json
import fcntl
import logging
import math
import os
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INTENT_SCHEMA_VERSION = 1
MIN_INTENT_SEQUENCE = 1
MAX_INTENT_TTL_SECONDS = 7200.0
MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS = 120.0
DEFAULT_GPU_STATE_DIR = Path("/var/lib/acx-gpu")
DEFAULT_INTENT_DIR = DEFAULT_GPU_STATE_DIR / "intents"
DEFAULT_INTENT_AUTHORITY_PATH = DEFAULT_GPU_STATE_DIR / "intent-authority.json"
DEFAULT_DEFERRED_STOP_PATH = DEFAULT_GPU_STATE_DIR / "deferred-stop.json"
DEFAULT_DECISION_LOG_PATH = DEFAULT_GPU_STATE_DIR / "decision-log.jsonl"
_INTENT_AUTHORITY_SCHEMA_VERSION = 1
_DEFERRED_STOP_SCHEMA_VERSION = 1
_INTENT_LOCK_TIMEOUT_SECONDS = 10.0
_INTENT_LOCK_RETRY_SECONDS = 0.05
_INTENT_FIELDS = frozenset(
    {
        "schema_version",
        "action",
        "requested_at",
        "expires_at",
        "ttl_seconds",
        "requested_by",
        "nonce",
        "sequence",
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
    sequence: int
    schema_version: int = INTENT_SCHEMA_VERSION
    source: Path | None = None
    reason: str | None = None


@dataclass(frozen=True)
class EffectiveIntent:
    """The newest unexpired publication across all environments."""

    action: IntentAction = IntentAction.AUTO
    requested_at: datetime | None = None
    expires_at: datetime | None = None
    nonce: str | None = None
    requested_by: str | None = None
    sequence: int | None = None
    source: Path | None = None
    status: IntentStatus = IntentStatus.NONE
    reason: str | None = None
    deferred_until: datetime | None = None
    deferred_reason: str | None = None
    deferred_rearm_failed: bool = False

    @property
    def intent(self) -> IntentAction:
        """Alias used by snapshot consumers for the C2 field name."""
        return self.action


@dataclass(frozen=True)
class DeferredStopRecord:
    """Durable write-ahead marker for a STOP waiting on in-flight work."""

    action: IntentAction
    requested_at: datetime
    expires_at: datetime
    nonce: str
    requested_by: str
    ttl_seconds: int
    sequence: int
    deferred_until: datetime
    deferred_reason: str
    schema_version: int = _DEFERRED_STOP_SCHEMA_VERSION

    def to_effective_intent(self, *, source: Path | None = None) -> EffectiveIntent:
        """Rehydrate the deferred STOP while its extension remains active."""
        return EffectiveIntent(
            action=self.action,
            requested_at=self.requested_at,
            # The original publication may have expired while work was in
            # flight.  The durable deferral is the new authority for the
            # effective expiry; retaining the old timestamp would make the
            # reaper discard the very STOP this record is meant to preserve.
            expires_at=self.deferred_until,
            nonce=self.nonce,
            requested_by=self.requested_by,
            sequence=self.sequence,
            source=source,
            status=IntentStatus.BLOCKED_WORK_IN_FLIGHT,
            reason="deferred stop re-armed from durable state",
            deferred_until=self.deferred_until,
            deferred_reason=self.deferred_reason,
        )


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


def _atomic_write_json(path: Path, payload: object, *, mode: int = 0o660) -> None:
    """Write JSON durably before publishing its replacement inode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.warning("could not remove temporary intent file %s", temporary)


def _durable_unlink(path: Path) -> None:
    """Remove a durable record and persist the directory entry update."""
    path.unlink(missing_ok=True)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


@contextmanager
def _intent_file_lock(path: Path) -> Iterator[None]:
    """Coordinate durable intent metadata writers with a bounded flock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    created = False
    try:
        lock_fd = os.open(
            lock_path,
            os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o660,
        )
        created = True
    except FileExistsError:
        lock_fd = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        if created:
            os.fchmod(lock_fd, 0o660)
        deadline = time.monotonic() + _INTENT_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"timed out after {_INTENT_LOCK_TIMEOUT_SECONDS:.1f}s waiting for intent lock"
                    ) from None
                time.sleep(min(_INTENT_LOCK_RETRY_SECONDS, remaining))
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


class IntentAuthorityError(RuntimeError):
    """The durable authority ledger cannot safely be interpreted."""


class IntentAuthorityStore:
    """Persist sequence and monotonic-expiry observations for intent fencing.

    The intent file's wall-clock timestamps remain useful for interoperability,
    but they are not allowed to move expiry backwards.  This ledger records a
    high-water wall clock, the highest sequence observed, and a per-nonce
    monotonic expiry for the current boot.  Once a nonce is expired it remains
    fenced even if NTP moves the wall clock backwards or the host reboots.
    """

    def __init__(
        self,
        path: str | Path = DEFAULT_INTENT_AUTHORITY_PATH,
        *,
        monotonic: Callable[[], float] | None = None,
        boot_id: str | None = None,
    ) -> None:
        self.path = Path(path)
        self._monotonic = monotonic or time.monotonic
        self._boot_id = boot_id if boot_id is not None else self._read_boot_id()

    @staticmethod
    def _read_boot_id() -> str | None:
        try:
            value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None

    def _read_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {
                "schema_version": _INTENT_AUTHORITY_SCHEMA_VERSION,
                "last_wall_time": None,
                "highest_sequence": 0,
                "intents": {},
            }
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise IntentAuthorityError(f"intent authority ledger is unreadable: {self.path}: {exc}") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != _INTENT_AUTHORITY_SCHEMA_VERSION
            or not isinstance(payload.get("intents"), dict)
            or isinstance(payload.get("highest_sequence"), bool)
            or not isinstance(payload.get("highest_sequence"), int)
            or payload.get("highest_sequence") < 0
        ):
            raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}")
        raw_sequences = payload.get("sequences", {})
        if not isinstance(raw_sequences, dict):
            raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}")
        for sequence, nonce in raw_sequences.items():
            if (
                not isinstance(sequence, str)
                or not sequence.isdecimal()
                or int(sequence) < MIN_INTENT_SEQUENCE
                or not isinstance(nonce, str)
                or not nonce.strip()
            ):
                raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}")
        raw_rejected_sequences = payload.get("rejected_sequences", [])
        if (
            not isinstance(raw_rejected_sequences, list)
            or any(
                isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence < MIN_INTENT_SEQUENCE
                for sequence in raw_rejected_sequences
            )
        ):
            raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}")
        last_wall_time = payload.get("last_wall_time")
        if last_wall_time is not None:
            try:
                _parse_timestamp(last_wall_time, field="last_wall_time")
            except ValueError as exc:
                raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}: {exc}") from exc
        for nonce, record in payload["intents"].items():
            if not isinstance(nonce, str) or not nonce.strip() or not isinstance(record, dict):
                raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}")
            sequence = record.get("sequence")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < MIN_INTENT_SEQUENCE:
                raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}")
            try:
                _parse_timestamp(record.get("expires_at"), field="expires_at")
            except ValueError as exc:
                raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}: {exc}") from exc
            if not isinstance(record.get("expired"), bool):
                raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}")
            publication = record.get("publication")
            if publication is not None:
                if (
                    not isinstance(publication, dict)
                    or publication.get("action") not in {item.value for item in IntentAction}
                    or not isinstance(publication.get("requested_at"), str)
                    or not isinstance(publication.get("expires_at"), str)
                    or isinstance(publication.get("ttl_seconds"), bool)
                    or not isinstance(publication.get("ttl_seconds"), int)
                    or publication.get("ttl_seconds") <= 0
                    or not isinstance(publication.get("requested_by"), str)
                    or not publication.get("requested_by").strip()
                    or isinstance(publication.get("sequence"), bool)
                    or not isinstance(publication.get("sequence"), int)
                    or publication.get("sequence") < MIN_INTENT_SEQUENCE
                ):
                    raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}")
                try:
                    _parse_timestamp(publication["requested_at"], field="requested_at")
                    _parse_timestamp(publication["expires_at"], field="expires_at")
                except ValueError as exc:
                    raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}: {exc}") from exc
            monotonic_expiry = record.get("monotonic_expires_at")
            if monotonic_expiry is not None and (
                isinstance(monotonic_expiry, bool)
                or not isinstance(monotonic_expiry, (int, float))
                or not math.isfinite(monotonic_expiry)
            ):
                raise IntentAuthorityError(f"intent authority ledger is invalid: {self.path}")
        return payload

    @staticmethod
    def _publication(intent: OperatorIntent) -> dict[str, object]:
        return {
            "action": intent.action.value,
            "requested_at": intent.requested_at.isoformat().replace("+00:00", "Z"),
            "expires_at": intent.expires_at.isoformat().replace("+00:00", "Z"),
            "ttl_seconds": intent.ttl_seconds,
            "requested_by": intent.requested_by,
            "sequence": intent.sequence,
        }

    def highest_sequence(self) -> int:
        """Return the durable high-water fencing sequence.

        Survives the publication that set it: an intent observed only after
        its own TTL elapsed still bumps the mark, so a deferred STOP can be
        fenced by a supersession the controller never saw while it was live.
        """
        with _intent_file_lock(self.path):
            return int(self._read_state()["highest_sequence"])

    def filter_valid(
        self,
        intents: list[OperatorIntent],
        *,
        now: datetime,
    ) -> tuple[list[OperatorIntent], set[str]]:
        """Return intents not expired by logical wall or current-boot monotonic time."""
        current_time = _coerce_now(now)
        try:
            monotonic_now = float(self._monotonic())
        except (TypeError, ValueError, OverflowError) as exc:
            raise IntentAuthorityError(f"intent monotonic clock unavailable: {exc}") from exc
        if not math.isfinite(monotonic_now) or monotonic_now < 0:
            raise IntentAuthorityError("intent monotonic clock must be finite and non-negative")

        with _intent_file_lock(self.path):
            state = self._read_state()
            raw_last_wall = state.get("last_wall_time")
            last_wall = _parse_timestamp(raw_last_wall, field="last_wall_time") if raw_last_wall else None
            logical_now = current_time if last_wall is None else max(current_time, last_wall)
            highest_sequence = int(state["highest_sequence"])
            records = dict(state["intents"])
            sequence_owners = dict(state.get("sequences", {}))
            rejected_sequences = set(state.get("rejected_sequences", []))
            survivors: list[OperatorIntent] = []
            expired_nonces: set[str] = set()
            changed = logical_now != last_wall or False
            for intent in intents:
                record = records.get(intent.nonce)
                # A sequence below the persisted high-water mark is stale,
                # even when it is the same nonce that was previously seen.
                # Allowing that exception would let an old publication be
                # reintroduced after a newer publication had fenced it.
                if intent.sequence < highest_sequence:
                    expired_nonces.add(intent.nonce)
                    logger.warning(
                        "operator intent fenced by higher sequence: nonce=%s sequence=%s highest=%s",
                        intent.nonce,
                        intent.sequence,
                        highest_sequence,
                    )
                    continue
                sequence_key = str(intent.sequence)
                if intent.sequence in rejected_sequences:
                    expired_nonces.add(intent.nonce)
                    logger.warning(
                        "operator intent rejected at previously conflicting sequence: nonce=%s sequence=%s",
                        intent.nonce,
                        intent.sequence,
                    )
                    continue
                if record is not None:
                    publication = record.get("publication")
                    if publication != self._publication(intent):
                        expired_nonces.add(intent.nonce)
                        logger.warning(
                            "operator intent nonce reuse rejected: nonce=%s original_sequence=%s replay_sequence=%s",
                            intent.nonce,
                            record.get("sequence"),
                            intent.sequence,
                        )
                        continue
                    owner = sequence_owners.get(sequence_key)
                    if owner is not None and owner != intent.nonce:
                        rejected_sequences.add(intent.sequence)
                        expired_nonces.add(intent.nonce)
                        previous = [item for item in survivors if item.sequence == intent.sequence]
                        survivors = [item for item in survivors if item.sequence != intent.sequence]
                        expired_nonces.update(item.nonce for item in previous)
                        logger.warning(
                            "operator intent duplicate sequence rejected: sequence=%s nonce=%s owner=%s",
                            intent.sequence,
                            intent.nonce,
                            owner,
                        )
                        changed = True
                        continue
                    if owner is None:
                        sequence_owners[sequence_key] = intent.nonce
                        changed = True
                owner = sequence_owners.get(sequence_key)
                if owner is not None and owner != intent.nonce:
                    rejected_sequences.add(intent.sequence)
                    expired_nonces.add(intent.nonce)
                    previous = [item for item in survivors if item.sequence == intent.sequence]
                    survivors = [item for item in survivors if item.sequence != intent.sequence]
                    expired_nonces.update(item.nonce for item in previous)
                    logger.warning(
                        "operator intent duplicate sequence rejected: sequence=%s nonce=%s owner=%s",
                        intent.sequence,
                        intent.nonce,
                        owner,
                    )
                    changed = True
                    continue
                if record is None:
                    remaining = max(0.0, (intent.expires_at - current_time).total_seconds())
                    records[intent.nonce] = {
                        "sequence": intent.sequence,
                        "expires_at": intent.expires_at.isoformat().replace("+00:00", "Z"),
                        "boot_id": self._boot_id,
                        "monotonic_expires_at": monotonic_now + remaining,
                        "expired": False,
                        "publication": self._publication(intent),
                    }
                    record = records[intent.nonce]
                    sequence_owners[sequence_key] = intent.nonce
                    changed = True
                elif int(record.get("sequence", 0)) != intent.sequence:
                    # The immutable publication check above should make this
                    # unreachable for a valid record.  Keep the fail-closed
                    # branch explicit for hand-edited/corrupt ledgers.
                    expired_nonces.add(intent.nonce)
                    logger.warning(
                        "operator intent nonce ledger sequence mismatch rejected: nonce=%s sequence=%s",
                        intent.nonce,
                        intent.sequence,
                    )
                    continue
                highest_sequence = max(highest_sequence, intent.sequence)
                record_expiry = _parse_timestamp(record["expires_at"], field="expires_at")
                expired = bool(record.get("expired")) or logical_now >= record_expiry
                if (
                    not expired
                    and record.get("boot_id") == self._boot_id
                    and record.get("monotonic_expires_at") is not None
                    and monotonic_now >= float(record["monotonic_expires_at"])
                ):
                    expired = True
                if expired:
                    expired_nonces.add(intent.nonce)
                    if not record.get("expired"):
                        record["expired"] = True
                        changed = True
                    logger.warning(
                        "operator intent expired/fenced: nonce=%s sequence=%s expires_at=%s",
                        intent.nonce,
                        intent.sequence,
                        record_expiry.isoformat(),
                    )
                    continue
                survivors.append(intent)
            if highest_sequence != state["highest_sequence"]:
                state["highest_sequence"] = highest_sequence
                changed = True
            logical_wall_text = logical_now.isoformat().replace("+00:00", "Z")
            if state.get("last_wall_time") != logical_wall_text:
                state["last_wall_time"] = logical_wall_text
                changed = True
            if state.get("intents") != records:
                state["intents"] = records
                changed = True
            serialized_sequences = {str(key): value for key, value in sequence_owners.items()}
            if state.get("sequences") != serialized_sequences:
                state["sequences"] = serialized_sequences
                changed = True
            serialized_rejected = sorted(rejected_sequences)
            if state.get("rejected_sequences") != serialized_rejected:
                state["rejected_sequences"] = serialized_rejected
                changed = True
            if changed:
                _atomic_write_json(self.path, state)
        return survivors, expired_nonces


class DeferredStopStore:
    """Durably retain a STOP intent that was waiting on in-flight work."""

    def __init__(self, path: str | Path = DEFAULT_DEFERRED_STOP_PATH) -> None:
        self.path = Path(path)

    def read(self) -> DeferredStopRecord | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("deferred STOP record unreadable; ignoring it: %s (%s)", self.path, exc)
            return None
        try:
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != _DEFERRED_STOP_SCHEMA_VERSION
                or payload.get("action") != IntentAction.STOP.value
            ):
                raise ValueError("invalid schema or action")
            sequence = payload.get("sequence")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < MIN_INTENT_SEQUENCE:
                raise ValueError("sequence must be a positive integer")
            requested_by = payload.get("requested_by")
            nonce = payload.get("nonce")
            if not isinstance(requested_by, str) or not requested_by.strip():
                raise ValueError("requested_by must be a non-blank string")
            if not isinstance(nonce, str) or not nonce.strip():
                raise ValueError("nonce must be a non-blank string")
            deferred_reason = payload.get("deferred_reason")
            if not isinstance(deferred_reason, str) or not deferred_reason.strip():
                raise ValueError("deferred_reason must be a non-blank string")
            ttl_seconds = payload.get("ttl_seconds")
            if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
                raise ValueError("ttl_seconds must be a positive integer")
            return DeferredStopRecord(
                action=IntentAction.STOP,
                requested_at=_parse_timestamp(payload.get("requested_at"), field="requested_at"),
                expires_at=_parse_timestamp(payload.get("expires_at"), field="expires_at"),
                nonce=nonce,
                requested_by=requested_by,
                ttl_seconds=ttl_seconds,
                sequence=sequence,
                deferred_until=_parse_timestamp(payload.get("deferred_until"), field="deferred_until"),
                deferred_reason=deferred_reason,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            logger.error("deferred STOP record invalid; ignoring it: %s (%s)", self.path, exc)
            return None

    def write(self, record: DeferredStopRecord) -> None:
        if record.action is not IntentAction.STOP:
            raise ValueError("only STOP intents may be deferred")
        payload = {
            "schema_version": _DEFERRED_STOP_SCHEMA_VERSION,
            "action": record.action.value,
            "requested_at": record.requested_at.isoformat().replace("+00:00", "Z"),
            "expires_at": record.expires_at.isoformat().replace("+00:00", "Z"),
            "ttl_seconds": record.ttl_seconds,
            "requested_by": record.requested_by,
            "nonce": record.nonce,
            "sequence": record.sequence,
            "deferred_until": record.deferred_until.isoformat().replace("+00:00", "Z"),
            "deferred_reason": record.deferred_reason,
        }
        with _intent_file_lock(self.path):
            _atomic_write_json(self.path, payload)

    def supersede_if_newer(self, *, sequence: int, nonce: str) -> bool:
        """Atomically clear a deferred STOP superseded by a fencing token."""
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < MIN_INTENT_SEQUENCE:
            raise ValueError("sequence must be a positive integer")
        if not isinstance(nonce, str) or not nonce.strip():
            raise ValueError("nonce must be a non-blank string")
        with _intent_file_lock(self.path):
            record = self.read()
            if record is None:
                return False
            superseded = sequence > record.sequence or (
                sequence == record.sequence and nonce != record.nonce
            )
            if superseded:
                _durable_unlink(self.path)
            return superseded

    def clear(self, *, sequence: int | None = None) -> None:
        with _intent_file_lock(self.path):
            record = self.read()
            if record is None or sequence is None or record.sequence <= sequence:
                _durable_unlink(self.path)


class DecisionLogStore:
    """Append-only durable JSONL audit trail for lifecycle decisions."""

    def __init__(self, path: str | Path = DEFAULT_DECISION_LOG_PATH) -> None:
        self.path = Path(path)

    def append(self, record: dict[str, Any]) -> None:
        encoded = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            self.path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
            0o660,
        )
        try:
            os.fchmod(fd, 0o660)
            written = 0
            while written < len(encoded):
                written += os.write(fd, encoded[written:])
            os.fsync(fd)
        finally:
            os.close(fd)
        directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _intent_order(intent: OperatorIntent) -> tuple[int, datetime, bool, str]:
    """Sort intents by authority first, with wall-clock compatibility ties."""
    return (intent.sequence, intent.requested_at, intent.action is IntentAction.STOP, str(intent.source or ""))


def copy_intents_to_durable_dir(source_dir: str | Path, durable_dir: str | Path) -> None:
    """Migrate valid runtime publications to the persistent intent directory."""
    source = Path(source_dir)
    target_root = Path(durable_dir)
    if not source.exists() or not source.is_dir():
        return
    for source_path in sorted(source.glob("*/gpu-intent.json")):
        parsed = _read_one(source_path)
        if parsed is None:
            continue
        target_path = target_root / source_path.parent.name / source_path.name
        existing = _read_one(target_path) if target_path.exists() else None
        if existing is not None and _intent_order(existing) >= _intent_order(parsed):
            continue
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OSError(f"could not read runtime intent {source_path}: {exc}") from exc
        _atomic_write_json(target_path, payload)


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

    sequence = payload.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < MIN_INTENT_SEQUENCE:
        _invalid(
            path,
            f"sequence must be an integer >= {MIN_INTENT_SEQUENCE}",
            reason_sink=reason_sink,
        )
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
        sequence=sequence,
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


def read_effective_intent(
    intent_dir: str | Path | None,
    now: datetime | float | int | None = None,
    *,
    additional_intent_dirs: Iterable[str | Path] = (),
    authority_store: IntentAuthorityStore | None = None,
) -> EffectiveIntent:
    """Aggregate intent publications and choose the effective publication.

    The highest monotonic ``sequence`` wins.  Wall-clock ``requested_at`` is
    only a tie-breaker for publications that carry the same sequence;
    publications with equal timestamps resolve to STOP, which is the
    conservative tie-breaker.  A
    ``None`` directory means the optional feature is disabled and is silent,
    preserving the legacy lifecycle behavior exactly.
    """
    if intent_dir is None:
        return EffectiveIntent()

    current_time = _coerce_now(now)
    roots = [Path(intent_dir), *(Path(directory) for directory in additional_intent_dirs)]
    unique_roots: list[Path] = []
    for root in roots:
        if root not in unique_roots:
            unique_roots.append(root)
    valid: list[OperatorIntent] = []
    expired = False
    parse_reasons: list[str] = []
    for root in unique_roots:
        for path in _candidate_paths(root):
            intent = _read_one(path, read_time=current_time, reason_sink=parse_reasons)
            if intent is not None:
                valid.append(intent)

    if authority_store is not None:
        valid, authority_expired = authority_store.filter_valid(valid, now=current_time)
        expired = bool(authority_expired)
    else:
        unexpired: list[OperatorIntent] = []
        for intent in valid:
            if intent.expires_at <= current_time:
                expired = True
                _invalid(intent.source or Path("<intent>"), f"intent expired at {intent.expires_at.isoformat()}")
                continue
            unexpired.append(intent)
        valid = unexpired

    if not valid:
        return EffectiveIntent(
            status=IntentStatus.EXPIRED if expired else IntentStatus.NONE,
            reason=(
                parse_reasons[0]
                if parse_reasons
                else ("intent expired" if expired else None)
            ),
        )

    winner = max(
        valid,
        key=lambda item: (
            item.sequence,
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
        sequence=winner.sequence,
        source=winner.source,
        status=IntentStatus.NONE,
        reason=winner.reason,
    )


__all__ = [
    "DEFAULT_DECISION_LOG_PATH",
    "DEFAULT_DEFERRED_STOP_PATH",
    "DEFAULT_GPU_STATE_DIR",
    "DEFAULT_INTENT_AUTHORITY_PATH",
    "DEFAULT_INTENT_DIR",
    "DeferredStopRecord",
    "DecisionLogStore",
    "EffectiveIntent",
    "IntentAction",
    "IntentAuthorityError",
    "IntentAuthorityStore",
    "IntentStatus",
    "MIN_INTENT_SEQUENCE",
    "OperatorIntent",
    "copy_intents_to_durable_dir",
    "read_effective_intent",
]
