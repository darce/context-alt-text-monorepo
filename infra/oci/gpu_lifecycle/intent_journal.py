"""Durable, append-only journal for operator GPU lifecycle intents.

Why this exists
---------------

The operator intent file lives on tmpfs (``/run/acx-write/<env>/gpu-intent.json``),
is overwritten by every POST, and is recreated empty on every boot.  What it
authorises is not ephemeral: the A10 keeps billing in OCI and the lease record
is durable at ``/var/lib/acx-gpu/running-since.json``.  Three consequences
followed from that asymmetry, and this module answers all three.

1. **The grant had no fence.** ``expires_at`` and ``requested_at`` are both
   wall-clock strings written by the description service, and precedence was
   "newest unexpired ``requested_at`` wins" -- also wall clock.  A backwards
   NTP correction on the backend silently re-armed an already-dead ``start``
   grant, which is precisely the arm that suppresses idle reap and disables the
   cost governor.  ``RunningSinceLeaseStore`` already refuses a non-monotonic
   duration origin; this journal applies the same discipline to intent expiry
   and additionally burns a nonce once it is spent, so no clock correction can
   resurrect it (RES-10 fencing tokens).

2. **The record was not durable.** After a backend reboot the durable half
   survived while the intent and its ``requested_by`` vanished, so a ``start``
   that was suppressing idle reap reverted to ``auto`` with nothing to replay
   and nothing to explain the transition.  The journal is written on durable
   storage *before* the cycle decides (RES-17 write-ahead of intent), and the
   outcome is appended after it, so a cycle can be reconstructed after the fact.

3. **A deferred stop was dropped without a trace.** A ``stop`` held off because
   work was in flight simply expired at its TTL and the GPU ran to the lease
   cap.  The declared late-event policy (FLOW-08) is now explicit: a deferred
   stop is re-armed past its wall-clock expiry for a bounded budget, and if
   that budget is exhausted the drop is journalled and logged at WARNING rather
   than being an enum value in a tmpfs file nobody watches.

Cross-boot policy
-----------------

A persisted ``time.monotonic()`` reading is only comparable within one boot.
Across a reboot the journal deliberately does **not** fall back to the wall
clock to keep a grant alive -- that is the hazard in (1) wearing a different
hat.  It revokes the grant, records the revocation with the original
``requested_by``, and logs at ERROR, so the transition is attributable to the
reboot instead of silently reappearing as an idle reap.
"""

from __future__ import annotations

import fcntl
import json
import logging
import math
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from infra.oci.gpu_lifecycle.hostclock import (
    BootIdentityUnavailableError,
    acquire_flock_with_timeout,
    read_host_boot_id,
)
from infra.oci.gpu_lifecycle.intent import (
    EffectiveIntent,
    IntentAction,
    IntentFenceVerdict,
    IntentStatus,
    OperatorIntent,
)

logger = logging.getLogger(__name__)

JOURNAL_SCHEMA_VERSION = 1
DEFAULT_INTENT_JOURNAL_PATH = Path("/var/lib/acx-gpu/intent-journal.jsonl")
#: Records kept on disk. The journal is a forensic tail, not an archive: it is
#: truncated from the front so an unattended host cannot fill /var (rg-007).
DEFAULT_MAX_JOURNAL_RECORDS = 2000
#: How long a deferred `stop` stays armed past its own expiry before the drop
#: is declared. Bounded so a stop request cannot pin the controller forever.
DEFAULT_DEFERRED_STOP_REARM_SECONDS = 3600.0
DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0

_REQUIRED_KEYS = ("schema_version", "kind", "nonce", "recorded_at")


class JournalRecordKind(StrEnum):
    """The vocabulary of the journal, kept in one place (sr-007)."""

    #: Write-ahead: the first cycle that ever saw this nonce, with the
    #: monotonic origin the fence measures every later cycle against.
    OBSERVED = "observed"
    #: The controller held a `stop` back because work was in flight.
    DEFERRED = "deferred"
    #: A deferred `stop` outlived its wall-clock expiry and stayed armed.
    REARMED = "rearmed"
    #: A deferred `stop` exhausted its re-arm budget and was abandoned.
    DROPPED = "dropped"
    #: The grant is spent and can never be honoured again.
    BURNED = "burned"
    #: One completed lifecycle cycle and what it did with the intent.
    CYCLE = "cycle"


#: Kinds that make a nonce permanently unusable.
_TERMINAL_KINDS = frozenset({JournalRecordKind.BURNED, JournalRecordKind.DROPPED})


class CorruptIntentJournalError(ValueError):
    """Persisted journal metadata is unsafe to use as an authority record."""


@dataclass(frozen=True)
class JournalRecord:
    """One validated journal line."""

    kind: JournalRecordKind
    nonce: str
    recorded_at: datetime
    boot_id: str | None = None
    monotonic: float | None = None
    action: str | None = None
    requested_by: str | None = None
    ttl_seconds: int | None = None
    reason: str | None = None
    payload: dict[str, Any] | None = None


def _parse_record(raw: object, *, source: Path, line_number: int) -> JournalRecord:
    if not isinstance(raw, dict):
        raise CorruptIntentJournalError(f"{source}:{line_number}: record must be a JSON object")
    missing = [key for key in _REQUIRED_KEYS if key not in raw]
    if missing:
        raise CorruptIntentJournalError(f"{source}:{line_number}: record is missing {missing}")
    if raw["schema_version"] != JOURNAL_SCHEMA_VERSION:
        raise CorruptIntentJournalError(
            f"{source}:{line_number}: schema_version must be {JOURNAL_SCHEMA_VERSION}"
        )
    try:
        kind = JournalRecordKind(raw["kind"])
    except (TypeError, ValueError) as exc:
        raise CorruptIntentJournalError(f"{source}:{line_number}: unknown kind ({exc})") from exc
    nonce = raw["nonce"]
    if not isinstance(nonce, str) or not nonce.strip():
        raise CorruptIntentJournalError(f"{source}:{line_number}: nonce must be a non-blank string")
    recorded_at = raw["recorded_at"]
    if not isinstance(recorded_at, (int, float)) or isinstance(recorded_at, bool) or not math.isfinite(recorded_at):
        raise CorruptIntentJournalError(f"{source}:{line_number}: recorded_at must be epoch seconds")
    monotonic = raw.get("monotonic")
    if monotonic is not None and (
        isinstance(monotonic, bool) or not isinstance(monotonic, (int, float)) or not math.isfinite(monotonic)
    ):
        raise CorruptIntentJournalError(f"{source}:{line_number}: monotonic must be finite seconds")
    ttl_seconds = raw.get("ttl_seconds")
    if ttl_seconds is not None and (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int)):
        raise CorruptIntentJournalError(f"{source}:{line_number}: ttl_seconds must be an integer")
    return JournalRecord(
        kind=kind,
        nonce=nonce.strip(),
        recorded_at=datetime.fromtimestamp(float(recorded_at), tz=UTC),
        boot_id=raw.get("boot_id"),
        monotonic=None if monotonic is None else float(monotonic),
        action=raw.get("action"),
        requested_by=raw.get("requested_by"),
        ttl_seconds=ttl_seconds,
        reason=raw.get("reason"),
        payload=raw,
    )


class IntentJournal:
    """Append-only operator-intent record on durable storage.

    Doubles as the :class:`~infra.oci.gpu_lifecycle.intent.IntentFence` the
    reader consults, because the fence and the audit trail are the same set of
    facts read two ways (DATA-14: one writer, one file, one vocabulary).
    """

    def __init__(
        self,
        *,
        path: Path | str = DEFAULT_INTENT_JOURNAL_PATH,
        boot_id: str | None = None,
        monotonic: Callable[[], float] | None = None,
        now: Callable[[], datetime] | None = None,
        max_records: int = DEFAULT_MAX_JOURNAL_RECORDS,
        deferred_stop_rearm_seconds: float = DEFAULT_DEFERRED_STOP_REARM_SECONDS,
        lock_timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.path = Path(path)
        self._monotonic = monotonic or time.monotonic
        self._now = now or (lambda: datetime.now(UTC))
        if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        self._max_records = max_records
        if (
            isinstance(deferred_stop_rearm_seconds, bool)
            or not isinstance(deferred_stop_rearm_seconds, (int, float))
            or not math.isfinite(deferred_stop_rearm_seconds)
            or deferred_stop_rearm_seconds < 0
        ):
            raise ValueError("deferred_stop_rearm_seconds must be finite and non-negative")
        self._rearm_seconds = float(deferred_stop_rearm_seconds)
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(lock_timeout_seconds)
            or lock_timeout_seconds < 0
        ):
            raise ValueError("lock_timeout_seconds must be finite and non-negative")
        self._lock_timeout_seconds = float(lock_timeout_seconds)
        if boot_id is None:
            boot_id = read_host_boot_id()
        elif not isinstance(boot_id, str) or not boot_id.strip():
            raise ValueError("boot_id must be a non-blank string or None")
        self._boot_id = boot_id.strip()

    # ------------------------------------------------------------------ io --

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        with lock_path.open("a+") as lock_file:
            acquire_flock_with_timeout(lock_file.fileno(), timeout_seconds=self._lock_timeout_seconds)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_all(self) -> list[JournalRecord]:
        """Parse the whole journal, failing fast on structural damage (rg-008).

        A torn *trailing* line is the one corruption this accepts: it is the
        expected shape of a crash mid-append.  Damage anywhere earlier means
        the ledger cannot be trusted to say which grants are spent, and the
        caller turns that into a refusal rather than an empty default.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError) as exc:
            raise CorruptIntentJournalError(f"intent journal unreadable: {self.path}: {exc}") from exc
        lines = [line for line in text.splitlines() if line.strip()]
        records: list[JournalRecord] = []
        for index, line in enumerate(lines, start=1):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                if index == len(lines):
                    logger.warning("intent journal has a torn trailing line; ignoring it: %s", self.path)
                    break
                raise CorruptIntentJournalError(
                    f"{self.path}:{index}: journal line is not JSON ({exc})"
                ) from exc
            records.append(_parse_record(raw, source=self.path, line_number=index))
        return records

    def _append(self, kind: JournalRecordKind, **fields: Any) -> None:
        record = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "kind": str(kind),
            "recorded_at": self._now().timestamp(),
            "boot_id": self._boot_id,
            "monotonic": self._monotonic(),
            **fields,
        }
        line = json.dumps(record, sort_keys=True, default=str)
        with self._locked():
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(f"{line}\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._truncate_locked()

    def _truncate_locked(self) -> None:
        """Keep the newest ``max_records`` lines. Called with the lock held."""
        try:
            lines = [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, UnicodeError) as exc:
            logger.warning("intent journal could not be measured for truncation: %s", exc)
            return
        if len(lines) <= self._max_records:
            return
        kept = lines[-self._max_records :]
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text("\n".join(kept) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    # --------------------------------------------------------------- fence --

    def evaluate(
        self,
        intent: OperatorIntent,
        *,
        wall_clock_expired: bool,
        now: datetime,
    ) -> IntentFenceVerdict:
        """Rule on one publication against the durable record.

        Raises :class:`CorruptIntentJournalError` when the ledger cannot be
        read; the reader turns that into a refusal (fail closed).
        """
        records = [record for record in self._read_all() if record.nonce == intent.nonce]
        terminal = next((record for record in records if record.kind in _TERMINAL_KINDS), None)
        if terminal is not None:
            return IntentFenceVerdict(
                expired=True,
                reason=(
                    f"operator grant {intent.nonce} is spent "
                    f"({terminal.kind}: {terminal.reason or 'no reason recorded'})"
                ),
            )

        observed = next((record for record in records if record.kind is JournalRecordKind.OBSERVED), None)
        if observed is None:
            # Write-ahead: anchor the monotonic origin before this grant can
            # influence a single decision (RES-17).
            self._append(
                JournalRecordKind.OBSERVED,
                nonce=intent.nonce,
                action=str(intent.action),
                requested_by=intent.requested_by,
                ttl_seconds=intent.ttl_seconds,
                requested_at=intent.requested_at.isoformat(),
                expires_at=intent.expires_at.isoformat(),
                source=str(intent.source) if intent.source else None,
            )
            if wall_clock_expired:
                return IntentFenceVerdict(
                    expired=True,
                    reason=f"intent expired at {intent.expires_at.isoformat()}",
                )
            return IntentFenceVerdict(expired=False)

        if observed.boot_id != self._boot_id:
            reason = (
                f"operator grant {intent.nonce} from {observed.requested_by!r} lost its monotonic "
                f"origin across a reboot (boot {observed.boot_id} -> {self._boot_id}); revoked"
            )
            logger.error("%s", reason)
            self._append(JournalRecordKind.BURNED, nonce=intent.nonce, reason=reason)
            return IntentFenceVerdict(expired=True, reason=reason)

        elapsed = self._monotonic() - (observed.monotonic if observed.monotonic is not None else 0.0)
        if elapsed < 0:
            reason = (
                f"operator grant {intent.nonce} has a monotonic origin in the future "
                f"({elapsed:.1f}s); revoked"
            )
            logger.error("%s", reason)
            self._append(JournalRecordKind.BURNED, nonce=intent.nonce, reason=reason)
            return IntentFenceVerdict(expired=True, reason=reason)

        ttl_seconds = float(observed.ttl_seconds if observed.ttl_seconds is not None else intent.ttl_seconds)
        monotonic_expired = elapsed >= ttl_seconds
        if not monotonic_expired and not wall_clock_expired:
            return IntentFenceVerdict(expired=False)

        deferred = any(record.kind is JournalRecordKind.DEFERRED for record in records)
        if deferred and intent.action is IntentAction.STOP:
            if elapsed < ttl_seconds + self._rearm_seconds:
                reason = (
                    f"deferred stop {intent.nonce} re-armed {elapsed - ttl_seconds:.0f}s past expiry "
                    f"(budget {self._rearm_seconds:.0f}s)"
                )
                logger.warning("%s", reason)
                self._append(JournalRecordKind.REARMED, nonce=intent.nonce, reason=reason)
                return IntentFenceVerdict(expired=False, reason=reason)
            reason = (
                f"deferred stop {intent.nonce} from {observed.requested_by!r} was dropped after "
                f"{elapsed:.0f}s: work stayed in flight past the {self._rearm_seconds:.0f}s re-arm budget"
            )
            logger.warning("%s", reason)
            self._append(JournalRecordKind.DROPPED, nonce=intent.nonce, reason=reason)
            return IntentFenceVerdict(expired=True, reason=reason)

        if monotonic_expired:
            reason = (
                f"operator grant {intent.nonce} expired {elapsed:.0f}s after its monotonic origin "
                f"(ttl {ttl_seconds:.0f}s); burned so no clock correction can re-arm it"
            )
            self._append(JournalRecordKind.BURNED, nonce=intent.nonce, reason=reason)
            return IntentFenceVerdict(expired=True, reason=reason)

        # Wall clock says expired, the trustworthy origin does not yet agree.
        # Refuse this cycle without burning: the monotonic reading is the one
        # allowed to make the revocation permanent.
        return IntentFenceVerdict(
            expired=True,
            reason=(
                f"intent expired at {intent.expires_at.isoformat()} by wall clock "
                f"({elapsed:.0f}s of {ttl_seconds:.0f}s elapsed monotonically)"
            ),
        )

    # --------------------------------------------------------------- audit --

    def record_cycle(
        self,
        *,
        mode: str,
        intent: EffectiveIntent,
        intent_status: IntentStatus,
        actuated: list[tuple[str, str]] | tuple[tuple[str, str], ...] = (),
        lease_expired: list[tuple[str, str]] | tuple[tuple[str, str], ...] = (),
        last_transition_reason: str | None = None,
        errors: list[str] | tuple[str, ...] = (),
    ) -> None:
        """Append the outcome half of the cycle: who asked, what happened.

        Answers "who started the $2/hr A10 at 03:00, and did the controller
        honour it?" after the tmpfs intent has been overwritten or lost to a
        reboot (HAI-06).
        """
        nonce = intent.nonce
        if nonce is None:
            # An `auto` cycle with no grant has no operator decision to
            # reconstruct; journalling every idle tick would evict the records
            # that matter.
            return
        if intent_status is IntentStatus.BLOCKED_WORK_IN_FLIGHT:
            self._mark_deferred(nonce, intent)
        self._append(
            JournalRecordKind.CYCLE,
            nonce=nonce,
            mode=mode,
            action=str(intent.action),
            requested_by=intent.requested_by,
            intent_status=str(intent_status),
            actuated=[list(item) for item in actuated],
            lease_expired=[list(item) for item in lease_expired],
            last_transition_reason=None if last_transition_reason is None else str(last_transition_reason),
            errors=list(errors),
        )

    def _mark_deferred(self, nonce: str, intent: EffectiveIntent) -> None:
        try:
            records = [record for record in self._read_all() if record.nonce == nonce]
        except CorruptIntentJournalError as exc:
            logger.error("could not read intent journal to record a deferred stop: %s", exc)
            return
        if any(record.kind is JournalRecordKind.DEFERRED for record in records):
            return
        self._append(
            JournalRecordKind.DEFERRED,
            nonce=nonce,
            action=str(intent.action),
            requested_by=intent.requested_by,
            reason="stop deferred while work was in flight",
        )

    def history(self, nonce: str | None = None) -> list[JournalRecord]:
        """Replay the journal, optionally for one grant."""
        records = self._read_all()
        if nonce is None:
            return records
        return [record for record in records if record.nonce == nonce]


__all__ = [
    "BootIdentityUnavailableError",
    "CorruptIntentJournalError",
    "DEFAULT_DEFERRED_STOP_REARM_SECONDS",
    "DEFAULT_INTENT_JOURNAL_PATH",
    "DEFAULT_MAX_JOURNAL_RECORDS",
    "IntentJournal",
    "JOURNAL_SCHEMA_VERSION",
    "JournalRecord",
    "JournalRecordKind",
]
