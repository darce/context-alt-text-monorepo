"""Describe-load sources that combine isolated environment publications."""

from __future__ import annotations

import fcntl
import json
import logging
import math
import os
import re
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from infra.oci.gpu_lifecycle.controller import JobLoadSnapshot

logger = logging.getLogger(__name__)

# Keep this standalone boundary adapter in parity with the snapshot contract in
# docs/workbay/contracts/gpu-lifecycle.md. The lifecycle and API are separate
# deployables, so sharing validation code would create a deployment coupling.
LOAD_SNAPSHOT_FUTURE_SKEW_SECONDS = 5.0
DEFAULT_UNKNOWN_GRACE_SECONDS = 600.0
DEFAULT_DEPLOYMENTS_FILE = Path(__file__).resolve().parents[3] / "scripts/deploy/gpu-snapshot-deployments.conf"

_ENVIRONMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


class LoadEvidence(StrEnum):
    """Confidence in the aggregate's observed load fields."""

    TRUSTWORTHY = "trustworthy"
    UNKNOWN = "unknown"
    ESCALATED = "escalated"


class UnknownReason(StrEnum):
    """Stable reason vocabulary for load-evidence alerts."""

    MISSING = "missing"
    STALE = "stale"
    MALFORMED = "malformed"


@dataclass(frozen=True)
class AggregateJobLoadSnapshot(JobLoadSnapshot):
    """Protocol-compatible snapshot with explicit evidence confidence.

    The inherited counters contain only values a producer actually published;
    they are never inflated to encode an error. The counters and inherited
    ``batch_in_progress`` value are authoritative only when ``evidence`` is
    ``TRUSTWORTHY``.
    """

    evidence: LoadEvidence = LoadEvidence.TRUSTWORTHY
    unknown_environments: tuple[str, ...] = ()
    unknown_reasons: tuple[tuple[str, UnknownReason], ...] = ()
    escalated_environments: tuple[str, ...] = ()


@dataclass(frozen=True)
class _EnvironmentObservation:
    environment: str
    queue_depth: int = 0
    in_flight: int = 0
    batch_in_progress: bool | None = None
    written_at: float | None = None
    evidence: LoadEvidence = LoadEvidence.TRUSTWORTHY
    reason: UnknownReason | None = None
    unknown_since: float | None = None


@dataclass(frozen=True)
class AggregateJobLoadSource:
    """Aggregate the declared environments' ``describe-load.json`` files.

    Missing, stale, and malformed producer evidence is a first-class unknown,
    not invented work and not proof of idleness. Unknown evidence fails closed
    through ``JobLoadSnapshot.untrustworthy`` for the existing reaper protocol.
    Once ``unknown_grace_seconds`` expires it becomes ``ESCALATED`` so the
    caller and monitoring can distinguish a quarantined transient from an
    outage requiring recovery.

    TODO: the reaper should give ``ESCALATED`` a recovery policy that permits a
    conservative START while continuing to fence normal idle STOPs. Its legacy
    ``untrustworthy`` branch deliberately treats UNKNOWN and ESCALATED alike.
    """

    directory: Path
    stale_seconds: float
    stale_grace_seconds: float = 600.0
    unknown_grace_seconds: float = DEFAULT_UNKNOWN_GRACE_SECONDS
    expected_environments: Collection[str] | None = None
    deployments_file: Path = DEFAULT_DEPLOYMENTS_FILE
    _last_state: dict[str, tuple[LoadEvidence, UnknownReason | None]] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )
    _unknown_since: dict[str, float] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "directory", Path(self.directory))
        object.__setattr__(self, "deployments_file", Path(self.deployments_file))
        if not math.isfinite(self.stale_seconds) or self.stale_seconds <= 0:
            raise ValueError("stale_seconds must be a positive finite number")
        if not math.isfinite(self.stale_grace_seconds) or self.stale_grace_seconds <= 0:
            raise ValueError("stale_grace_seconds must be a positive finite number")
        if self.stale_grace_seconds < self.stale_seconds:
            raise ValueError("stale_grace_seconds must be at least stale_seconds")
        if not math.isfinite(self.unknown_grace_seconds) or self.unknown_grace_seconds <= 0:
            raise ValueError("unknown_grace_seconds must be a positive finite number")

        environments = (
            self._read_expected_environments(self.deployments_file)
            if self.expected_environments is None
            else self._validate_expected_environments(self.expected_environments)
        )
        object.__setattr__(self, "expected_environments", environments)

    @property
    def _declared_environments(self) -> Collection[str]:
        """`__post_init__` always resolves the optional field to a concrete tuple."""
        environments = self.expected_environments
        if environments is None:  # pragma: no cover - unreachable after __post_init__
            raise RuntimeError("expected_environments was not resolved in __post_init__")
        return environments

    def snapshot(self) -> AggregateJobLoadSnapshot:
        now = time.time()
        observations = [self._observe_environment(environment, now=now) for environment in self._declared_environments]

        for observation in observations:
            self._log_transition(observation)

        evidence = LoadEvidence.TRUSTWORTHY
        if any(observation.evidence is LoadEvidence.ESCALATED for observation in observations):
            evidence = LoadEvidence.ESCALATED
        elif any(observation.evidence is LoadEvidence.UNKNOWN for observation in observations):
            evidence = LoadEvidence.UNKNOWN

        uncertain = [
            observation for observation in observations if observation.evidence is not LoadEvidence.TRUSTWORTHY
        ]
        return AggregateJobLoadSnapshot(
            queue_depth=sum(observation.queue_depth for observation in observations),
            in_flight=sum(observation.in_flight for observation in observations),
            batch_in_progress=any(observation.batch_in_progress is True for observation in observations),
            untrustworthy=evidence is not LoadEvidence.TRUSTWORTHY,
            evidence=evidence,
            unknown_environments=tuple(observation.environment for observation in uncertain),
            unknown_reasons=tuple(
                (observation.environment, observation.reason)
                for observation in uncertain
                if observation.reason is not None
            ),
            escalated_environments=tuple(
                observation.environment
                for observation in observations
                if observation.evidence is LoadEvidence.ESCALATED
            ),
        )

    def fence_token(self) -> tuple[tuple[str, tuple[int, int, int, int] | None], ...]:
        """Return the atomic-rename generation of every declared producer."""
        generations: list[tuple[str, tuple[int, int, int, int] | None]] = []
        for environment in self._declared_environments:
            path = self.directory / environment / "describe-load.json"
            try:
                stat = path.stat()
            except FileNotFoundError:
                generation = None
            else:
                generation = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            generations.append((environment, generation))
        return tuple(generations)

    def actuate_if_generation(
        self,
        expected_generation: object,
        action: Callable[[], None],
    ) -> bool:
        """Run ``action`` while all producer publication locks stay held.

        Publishers replace snapshots atomically while holding the matching
        per-environment lock. Taking every lock in sorted deployment order
        closes the final compare-to-STOP race without deadlocking concurrent
        publishers. A busy publisher makes this STOP attempt fail closed; the
        next reaper cycle can reconsider the newly published generation.
        """
        lock_fds: list[int] = []
        try:
            for environment in self._declared_environments:
                lock_path = self.directory / environment / "describe-load.json.lock"
                lock_fd = self._open_fence_lock(lock_path)
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BaseException:
                    os.close(lock_fd)
                    raise
                lock_fds.append(lock_fd)
        except OSError as exc:
            logger.warning("describe load publication fence unavailable; cancelling STOP: %s", exc)
            self._release_fence_locks(lock_fds)
            return False

        try:
            if self.fence_token() != expected_generation:
                logger.warning("describe load generation advanced; cancelling STOP")
                return False
            action()
            return True
        finally:
            self._release_fence_locks(lock_fds)

    @staticmethod
    def _open_fence_lock(path: Path) -> int:
        created = False
        try:
            lock_fd = os.open(
                path,
                os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                0o660,
            )
            created = True
        except FileExistsError:
            lock_fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        if created:
            try:
                os.fchmod(lock_fd, 0o660)
            except BaseException:
                os.close(lock_fd)
                raise
        return lock_fd

    @staticmethod
    def _release_fence_locks(lock_fds: list[int]) -> None:
        for lock_fd in reversed(lock_fds):
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def _observe_environment(self, environment: str, *, now: float) -> _EnvironmentObservation:
        path = self.directory / environment / "describe-load.json"
        try:
            path.stat()
        except FileNotFoundError:
            unknown_since = self._filesystem_timestamp(
                path.parent,
                self.directory,
                self.directory.parent,
                now=now,
            )
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.MISSING,
                unknown_since=unknown_since,
                now=now,
            )
        except OSError:
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.MALFORMED,
                unknown_since=self._filesystem_timestamp(path.parent, self.directory, now=now),
                now=now,
            )

        observation = self._read_snapshot(path, environment=environment, now=now)
        if observation.evidence is not LoadEvidence.TRUSTWORTHY:
            return observation

        assert observation.written_at is not None
        age = now - observation.written_at
        if age < -LOAD_SNAPSHOT_FUTURE_SKEW_SECONDS:
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.MALFORMED,
                unknown_since=self._filesystem_timestamp(path, path.parent, now=now),
                now=now,
                observed=observation,
            )
        if age > self.stale_seconds:
            # A stale producer became unknown when it crossed the freshness
            # deadline. stale_grace_seconds remains a minimum quarantine
            # deadline; the snapshot is never discarded after that deadline.
            unknown_since = observation.written_at + self.stale_seconds
            escalation_deadline = max(
                observation.written_at + self.stale_grace_seconds,
                unknown_since + self.unknown_grace_seconds,
            )
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.STALE,
                unknown_since=unknown_since,
                now=now,
                observed=observation,
                escalation_deadline=escalation_deadline,
            )
        return observation

    def _uncertain_observation(
        self,
        environment: str,
        *,
        reason: UnknownReason,
        unknown_since: float,
        now: float,
        observed: _EnvironmentObservation | None = None,
        escalation_deadline: float | None = None,
    ) -> _EnvironmentObservation:
        # CON-11: an unhealthy writer must not renew its own quarantine by
        # repeatedly replacing the file with another malformed generation.
        # Preserve the beginning of uninterrupted uncertainty until a
        # trustworthy observation explicitly clears it in _log_transition.
        unknown_since = min(unknown_since, now)
        previous_unknown_since = self._unknown_since.get(environment)
        if previous_unknown_since is not None:
            unknown_since = min(unknown_since, previous_unknown_since)
        self._unknown_since[environment] = unknown_since

        deadline = unknown_since + self.unknown_grace_seconds if escalation_deadline is None else escalation_deadline
        evidence = LoadEvidence.ESCALATED if now > deadline else LoadEvidence.UNKNOWN
        return _EnvironmentObservation(
            environment=environment,
            queue_depth=0 if observed is None else observed.queue_depth,
            in_flight=0 if observed is None else observed.in_flight,
            batch_in_progress=None if observed is None else observed.batch_in_progress,
            written_at=None if observed is None else observed.written_at,
            evidence=evidence,
            reason=reason,
            unknown_since=unknown_since,
        )

    def _read_snapshot(self, path: Path, *, environment: str, now: float) -> _EnvironmentObservation:
        unknown_since = self._filesystem_timestamp(path, path.parent, now=now)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.MALFORMED,
                unknown_since=unknown_since,
                now=now,
            )
        if not isinstance(payload, dict):
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.MALFORMED,
                unknown_since=unknown_since,
                now=now,
            )

        written_at = payload.get("written_at")
        if isinstance(written_at, bool) or not isinstance(written_at, (int, float)) or not math.isfinite(written_at):
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.MALFORMED,
                unknown_since=unknown_since,
                now=now,
            )
        try:
            queue_depth = payload["queue_depth"]
            in_flight = payload["in_flight"]
        except KeyError:
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.MALFORMED,
                unknown_since=unknown_since,
                now=now,
            )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (queue_depth, in_flight)
        ):
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.MALFORMED,
                unknown_since=unknown_since,
                now=now,
            )

        if "batch_in_progress" not in payload:
            observed = _EnvironmentObservation(
                environment=environment,
                queue_depth=queue_depth,
                in_flight=in_flight,
                batch_in_progress=None,
                written_at=float(written_at),
            )
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.MALFORMED,
                unknown_since=unknown_since,
                now=now,
                observed=observed,
            )
        batch_in_progress = payload["batch_in_progress"]
        if not isinstance(batch_in_progress, bool):
            return self._uncertain_observation(
                environment,
                reason=UnknownReason.MALFORMED,
                unknown_since=unknown_since,
                now=now,
            )
        return _EnvironmentObservation(
            environment=environment,
            queue_depth=queue_depth,
            in_flight=in_flight,
            batch_in_progress=batch_in_progress,
            written_at=float(written_at),
        )

    def _log_transition(self, observation: _EnvironmentObservation) -> None:
        state = (observation.evidence, observation.reason)
        previous = self._last_state.get(observation.environment)
        if previous == state:
            return
        self._last_state[observation.environment] = state
        if observation.evidence is LoadEvidence.TRUSTWORTHY:
            self._unknown_since.pop(observation.environment, None)
            if previous is not None and previous[0] is not LoadEvidence.TRUSTWORTHY:
                logger.warning(
                    "describe load evidence recovered environment=%s previous_reason=%s",
                    observation.environment,
                    previous[1],
                )
            return
        logger.warning(
            "describe load evidence %s environment=%s reason=%s unknown_since=%s",
            observation.evidence,
            observation.environment,
            observation.reason,
            observation.unknown_since,
        )

    @staticmethod
    def _filesystem_timestamp(*paths: Path, now: float) -> float:
        for candidate in paths:
            try:
                return candidate.stat().st_mtime
            except OSError:
                continue
        return now

    @classmethod
    def _read_expected_environments(cls, path: Path) -> tuple[str, ...]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"deployment registry is missing or unreadable: {path} ({exc})") from exc
        return cls._validate_expected_environments(lines, source=path)

    @staticmethod
    def _validate_expected_environments(
        environments: Collection[str],
        *,
        source: Path | None = None,
    ) -> tuple[str, ...]:
        label = f"deployment registry {source}" if source is not None else "expected_environments"
        if isinstance(environments, str):
            raise ValueError(f"{label} must be a collection of environment names, not a string")
        values = tuple(environments)
        if not values:
            raise ValueError(f"{label} must declare at least one environment")
        if any(not isinstance(value, str) or _ENVIRONMENT_NAME.fullmatch(value) is None for value in values):
            raise ValueError(f"{label} contains an invalid environment name")
        if len(set(values)) != len(values):
            raise ValueError(f"{label} contains duplicate environments")
        return tuple(sorted(values))
