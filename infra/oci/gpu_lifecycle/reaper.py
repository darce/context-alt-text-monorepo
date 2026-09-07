"""Runnable idle-reaper: decision → fence → OCI STOP actuation.

Production entrypoint (load from the describe job store dump):

  python -m infra.oci.gpu_lifecycle \\
    --instance-id ocid1.instance... \\
    --idle-seconds 300 \\
    --load-dir /run/acx-write

Each environment's describe service writes
``/run/acx-write/<environment>/describe-load.json`` on enqueue / terminal poll.
The lifecycle aggregates every fresh environment snapshot. A stale dump is
treated as busy through a bounded grace period so a dead writer cannot cause a
premature STOP or pin the GPU forever.

Static ``--queue-depth`` / ``--in-flight`` flags are for unit tests only; the
fence delay re-samples the load source, so a constant static source is a no-op
fence and must not be the operator default.

Auth assumption (VLMFIX-S2-03): ``OciCliStopActuator`` uses the OCI CLI with the
host's default API-key profile (``~/.oci/config``) unless ``--oci-auth`` /
``OCI_CLI_AUTH`` selects another mode (e.g. ``instance_principal`` on
acx-backend). No dynamic-group policy is provisioned here — operators must
grant ``INSTANCE_POWER_ACTIONS`` for the GPU compartment.

The fencing guard re-samples load after ``--fence-delay-seconds`` and requires
a mutable source to compare its writer-issued generation atomically with STOP.
Sources without that end-to-end capability fail closed. The default delay is
2.0s so the preliminary samples are meaningfully separated in time.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from infra.oci.gpu_lifecycle.controller import (
    FallbackDecision,
    GpuInstance,
    GpuLifecycleController,
    JobLoadSnapshot,
    LifecycleAction,
)
from infra.oci.gpu_lifecycle.intent import (
    DEFAULT_GPU_STATE_DIR,
    DeferredStopRecord,
    DeferredStopStore,
    DecisionLogStore,
    EffectiveIntent,
    IntentAction,
    IntentAuthorityError,
    IntentAuthorityStore,
    IntentStatus,
    read_effective_intent,
    copy_intents_to_durable_dir,
    _atomic_write_json,
    _durable_unlink,
)
from infra.oci.gpu_lifecycle.load_source import AggregateJobLoadSource
from infra.oci.gpu_lifecycle.probe import (
    HttpReadinessProbe,
    InstanceReadinessProbe,
    ReadinessWaitResult,
    WarmReadinessWait,
)
from infra.oci.gpu_lifecycle.state_snapshot import (
    DEFAULT_GPU_STATE_PATH,
    GpuLifecycleState,
    LastTransitionReason,
    read_previous_gpu_state,
    resolve_gpu_state_path,
    state_for_instances,
    write_gpu_state_snapshot,
)

logger = logging.getLogger(__name__)

# Fail-closed STOP sentinel when load data is untrustworthy. START must not
# treat this as real work (untrustworthy=True → refuse START).
_BUSY_LOAD = JobLoadSnapshot(queue_depth=1, in_flight=1, batch_in_progress=True, untrustworthy=True)
_DEFAULT_LOAD_MAX_AGE_SECONDS = 120.0
_DEFAULT_OCI_TIMEOUT_SECONDS = 120
_DEFAULT_MAX_WAIT_SECONDS = 600
_DEFAULT_FENCE_DELAY_SECONDS = 2.0
# A10 ~$2/GPU-hr; 100-image library ≈ 5 min boot+load + ~4s/img ≈ 12 min ≈ $0.40.
# Boot amortization dominates: bound the wait so a hung START cannot bill the hour.
_DEFAULT_READY_MAX_CYCLES = 30
_DEFAULT_READY_STALL_CYCLES = 3
_DEFAULT_READY_SLEEP_SECONDS = 10.0
_DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0
_LOCK_RETRY_SECONDS = 0.05
_DEFAULT_RUNNING_SINCE_PATH = Path("/var/lib/acx-gpu/running-since.json")
_RUNNING_SINCE_READ_FAILURE_RECOVERY_CYCLES = 3
_RUNNING_SINCE_FUTURE_SKEW_SECONDS = 5.0
_HONOURED_NONCES_SCHEMA_VERSION = 1
_PENDING_START_SCHEMA_VERSION = 1
# A deferred STOP is re-armed for a bounded interval on every blocked cycle.
# Repeated lifecycle cycles therefore preserve the instruction for arbitrarily
# long work, while a single stale record never pins the machine forever.
_MIN_DEFERRED_STOP_EXTENSION_SECONDS = 60
_MAX_DEFERRED_STOP_EXTENSION_SECONDS = 7200
# Live describe dumps omit batch_in_progress; warn once per process, not per poll.
_ABSENT_BATCH_KEY_WARNED = False


def _acquire_flock_with_timeout(
    lock_fd: int,
    *,
    timeout_seconds: float,
) -> None:
    """Acquire an exclusive flock without allowing a stuck peer to pin a unit."""
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds < 0
    ):
        raise ValueError("lock timeout must be finite and non-negative")
    deadline = time.monotonic() + float(timeout_seconds)
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"timed out after {float(timeout_seconds):.1f}s waiting for lifecycle lock"
                ) from None
            time.sleep(min(_LOCK_RETRY_SECONDS, remaining))


@contextmanager
def _serialized_gpu_state_publish(
    path: str | Path | None,
    *,
    lock_timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize snapshot read-modify-write across the two systemd units."""
    target = resolve_gpu_state_path() if path is None else Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(f"{target.name}.lock")
    created = False
    try:
        lock_fd = os.open(
            lock_path,
            os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o660,
        )
        created = True
    except FileExistsError:
        # A lock never needs write access: opening the provisioned 0660 file
        # read-only also lets either lifecycle uid recover if an older deploy
        # left a merely group-readable file behind.
        lock_fd = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        if created:
            # os.open's mode is filtered through umask. Repair it before use;
            # production pre-provisions the same path as root:10001/0660 so the
            # normal cross-unit path never depends on this creation fallback.
            os.fchmod(lock_fd, 0o660)
        _acquire_flock_with_timeout(
            lock_fd,
            timeout_seconds=lock_timeout_seconds,
        )
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


class JobLoadSource(Protocol):
    def snapshot(self) -> JobLoadSnapshot: ...


class AtomicStopFenceLoadSource(JobLoadSource, Protocol):
    """Load source whose producer fencing covers validation through STOP."""

    def fence_token(self) -> object: ...

    def actuate_if_generation(
        self,
        expected_generation: object,
        action: Callable[[], None],
    ) -> bool: ...


class InstanceStopActuator(Protocol):
    def stop_instance(self, instance_id: str) -> None: ...


class InstanceStartActuator(Protocol):
    def start_instance(self, instance_id: str) -> None: ...


def build_instance_action_cmd(
    *,
    oci_bin: str,
    instance_id: str,
    action: str,
    wait_state: str,
    auth: str | None = None,
    max_wait_seconds: int = _DEFAULT_MAX_WAIT_SECONDS,
) -> list[str]:
    """OCI CLI power-action argv. START/STOP twins share this builder."""
    cmd = [
        oci_bin,
        "compute",
        "instance",
        "action",
        "--instance-id",
        instance_id,
        "--action",
        action,
        "--wait-for-state",
        wait_state,
        "--max-wait-seconds",
        str(max_wait_seconds),
    ]
    if auth:
        cmd.extend(["--auth", auth])
    return cmd


@dataclass(frozen=True)
class StaticJobLoadSource:
    """CLI / test load source with fixed queue_depth and in_flight.

    Not suitable as a production fence — both samples return the same constants.
    """

    queue_depth: int
    in_flight: int
    batch_in_progress: bool = False

    def snapshot(self) -> JobLoadSnapshot:
        return JobLoadSnapshot(
            queue_depth=self.queue_depth,
            in_flight=self.in_flight,
            batch_in_progress=self.batch_in_progress,
        )


@dataclass(frozen=True)
class JsonFileJobLoadSource:
    """Load snapshot from a JSON file written by the describe service.

    Expected shape (mirrors InMemoryDescribeJobStore.load_snapshot):
      {"queue_depth": <int>, "in_flight": <int>, "written_at": <unix float optional>}

    Optional ``batch_in_progress`` (bool) is honoured only when the producer
    writes it. Absent key → False: the fence covers only queue_depth/in_flight
    that the snapshot proves. Bulk/multi-job runs are unprotected until the
    producer writes ``batch_in_progress``. Present but not a bool → busy
    (fail closed).

    Stale files (mtime or written_at older than max_age_seconds) are treated as
    busy so the reaper never STOPs on silent writer failure (VLMFIX-S2-02).
    """

    path: Path
    max_age_seconds: float = _DEFAULT_LOAD_MAX_AGE_SECONDS

    def snapshot(self) -> JobLoadSnapshot:
        if not self.path.is_file():
            logger.warning("load json missing; treating as busy: %s", self.path)
            return _BUSY_LOAD
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            logger.warning("load json unstatable; treating as busy: %s", self.path)
            return _BUSY_LOAD
        if age > self.max_age_seconds:
            logger.warning(
                "load json stale (mtime age=%.1fs > %.1fs); treating as busy: %s",
                age,
                self.max_age_seconds,
                self.path,
            )
            return _BUSY_LOAD
        try:
            payload = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("load json unreadable; treating as busy: %s (%s)", self.path, exc)
            return _BUSY_LOAD
        if not isinstance(payload, dict):
            logger.warning("load json not an object; treating as busy: %s", self.path)
            return _BUSY_LOAD
        written_at = payload.get("written_at")
        if isinstance(written_at, (int, float)):
            written_age = time.time() - float(written_at)
            if written_age > self.max_age_seconds:
                logger.warning(
                    "load json written_at stale (age=%.1fs); treating as busy: %s",
                    written_age,
                    self.path,
                )
                return _BUSY_LOAD
        try:
            queue_depth = int(payload["queue_depth"])
            in_flight = int(payload["in_flight"])
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "load json missing queue_depth/in_flight; treating as busy: %s",
                self.path,
            )
            return _BUSY_LOAD
        if "batch_in_progress" in payload and not isinstance(payload["batch_in_progress"], bool):
            logger.warning(
                "load json batch_in_progress not bool; treating as busy: %s",
                self.path,
            )
            return _BUSY_LOAD
        # Consumer-only flag. Producer today writes {queue_depth,in_flight,written_at}
        # without this key. Absent → False: do not claim batch protection; bulk
        # runs are unprotected until the producer writes batch_in_progress.
        if "batch_in_progress" not in payload:
            global _ABSENT_BATCH_KEY_WARNED
            level = logging.DEBUG if _ABSENT_BATCH_KEY_WARNED else logging.WARNING
            logger.log(
                level,
                "load json missing batch_in_progress; bulk runs are unprotected until the producer writes this key: %s",
                self.path,
            )
            _ABSENT_BATCH_KEY_WARNED = True
            batch_in_progress = False
        else:
            batch_in_progress = bool(payload["batch_in_progress"])
        return JobLoadSnapshot(
            queue_depth=queue_depth,
            in_flight=in_flight,
            batch_in_progress=batch_in_progress,
        )


class OciCliStopActuator:
    """STOP via OCI CLI (`oci compute instance action --action STOP`).

    Auth: default API key from ``~/.oci/config``. Pass ``auth`` (or set
    ``OCI_CLI_AUTH``) for ``instance_principal`` / ``resource_principal`` when
    the reaper runs on a principal-enabled host. ``subprocess`` timeout bounds
    CLI hangs independent of ``--max-wait-seconds`` (VLMFIX-S2-03).
    """

    def __init__(
        self,
        *,
        oci_bin: str | None = None,
        dry_run: bool = False,
        auth: str | None = None,
        timeout_seconds: int = _DEFAULT_OCI_TIMEOUT_SECONDS,
    ) -> None:
        self._oci_bin = oci_bin or shutil.which("oci") or "oci"
        self._dry_run = dry_run
        self._auth = auth
        self._timeout_seconds = timeout_seconds

    def build_cmd(self, instance_id: str) -> list[str]:
        return build_instance_action_cmd(
            oci_bin=self._oci_bin,
            instance_id=instance_id,
            action=LifecycleAction.STOP,
            wait_state="STOPPED",
            auth=self._auth,
        )

    def stop_instance(self, instance_id: str) -> None:
        cmd = self.build_cmd(instance_id)
        if self._dry_run:
            logger.info("dry-run STOP %s: %s", instance_id, " ".join(cmd))
            return
        if self.get_instance_state(instance_id) == "STOPPED":
            logger.info("STOP already converged for %s", instance_id)
            return
        logger.info("actuating STOP for %s", instance_id)
        subprocess.run(cmd, check=True, timeout=self._timeout_seconds)

    def get_instance_state(self, instance_id: str) -> str | None:
        observed = fetch_instance_idle_seconds(
            instance_id=instance_id,
            oci_bin=self._oci_bin,
            auth=self._auth,
            timeout_seconds=self._timeout_seconds,
        )
        return None if observed is None else observed[0]


class OciCliStartActuator:
    """START via OCI CLI (`oci compute instance action --action START`).

    Symmetric twin of ``OciCliStopActuator`` except START must not kill the
    waiter before ``--max-wait-seconds``: subprocess timeout is
    ``max(timeout_seconds, max_wait_seconds)`` (W3-D-03).
    """

    def __init__(
        self,
        *,
        oci_bin: str | None = None,
        dry_run: bool = False,
        auth: str | None = None,
        timeout_seconds: int = _DEFAULT_OCI_TIMEOUT_SECONDS,
        max_wait_seconds: int = _DEFAULT_MAX_WAIT_SECONDS,
    ) -> None:
        self._oci_bin = oci_bin or shutil.which("oci") or "oci"
        self._dry_run = dry_run
        self._auth = auth
        self._max_wait_seconds = max_wait_seconds
        self._timeout_seconds = max(timeout_seconds, max_wait_seconds)

    def build_cmd(self, instance_id: str) -> list[str]:
        return build_instance_action_cmd(
            oci_bin=self._oci_bin,
            instance_id=instance_id,
            action=LifecycleAction.START,
            wait_state="RUNNING",
            auth=self._auth,
            max_wait_seconds=self._max_wait_seconds,
        )

    def start_instance(self, instance_id: str) -> None:
        cmd = self.build_cmd(instance_id)
        if self._dry_run:
            logger.info("dry-run START %s: %s", instance_id, " ".join(cmd))
            return
        if self.get_instance_state(instance_id) == "RUNNING":
            logger.info("START already converged for %s", instance_id)
            return
        logger.info("actuating START for %s", instance_id)
        subprocess.run(cmd, check=True, timeout=self._timeout_seconds)

    def get_instance_state(self, instance_id: str) -> str | None:
        observed = fetch_instance_idle_seconds(
            instance_id=instance_id,
            oci_bin=self._oci_bin,
            auth=self._auth,
            timeout_seconds=self._timeout_seconds,
        )
        return None if observed is None else observed[0]


@dataclass(frozen=True)
class RunningSinceRecord:
    instance_id: str
    since: datetime
    source: str
    monotonic_since: float | None = None
    boot_id: str | None = None
    honoured_nonce: str | None = None


@dataclass(frozen=True)
class PendingStartRecord:
    """Write-ahead authority for an OCI START that has not committed yet."""

    instance_id: str
    since: datetime
    monotonic_since: float
    boot_id: str
    honoured_nonce: str | None = None


class CorruptRunningSinceLeaseError(ValueError):
    """Persisted lease metadata is unsafe to use as a duration origin."""


class CorruptHonouredNonceError(ValueError):
    """Persisted START idempotency metadata is unreadable or invalid."""


class BootIdentityUnavailableError(RuntimeError):
    """The host cannot supply a boot identity for monotonic lease records."""


class RunningSinceLeaseStore:
    """Controller-owned grant times for RUNNING leases, keyed by instance."""

    _SOURCES = frozenset({"start_actuator", "first_observed"})
    _SCHEMA_VERSION = 2
    _FAILURE_SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        path: Path = _DEFAULT_RUNNING_SINCE_PATH,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        boot_id: str | None = None,
        max_future_skew_seconds: float = _RUNNING_SINCE_FUTURE_SKEW_SECONDS,
        lock_timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.path = path
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        if (
            isinstance(max_future_skew_seconds, bool)
            or not isinstance(max_future_skew_seconds, (int, float))
            or not math.isfinite(max_future_skew_seconds)
            or max_future_skew_seconds < 0
        ):
            raise ValueError("max_future_skew_seconds must be finite and non-negative")
        self._max_future_skew_seconds = float(max_future_skew_seconds)
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(lock_timeout_seconds)
            or lock_timeout_seconds < 0
        ):
            raise ValueError("lock_timeout_seconds must be finite and non-negative")
        self._lock_timeout_seconds = float(lock_timeout_seconds)
        if boot_id is None:
            try:
                boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            except OSError as exc:
                raise BootIdentityUnavailableError(
                    "running-since boot identity unavailable: cannot read "
                    "/proc/sys/kernel/random/boot_id; supply an explicit boot_id"
                ) from exc
            if not boot_id:
                raise BootIdentityUnavailableError(
                    "running-since boot identity unavailable: "
                    "/proc/sys/kernel/random/boot_id is blank; supply an explicit boot_id"
                )
        elif not isinstance(boot_id, str) or not boot_id.strip():
            raise ValueError("boot_id must be a non-blank string or None")
        self._boot_id = boot_id

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _monotonic_now(self) -> float:
        value = self._monotonic()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("monotonic clock must return finite non-negative seconds")
        return float(value)

    @contextmanager
    def _locked_for_update(self) -> Iterator[None]:
        """Serialize read-modify-write updates across start/reap processes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        with lock_path.open("a+") as lock_file:
            _acquire_flock_with_timeout(
                lock_file.fileno(),
                timeout_seconds=self._lock_timeout_seconds,
            )
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @property
    def honoured_nonces_path(self) -> Path:
        """Durable START nonce ledger kept independently from lease lifetimes."""
        return self.path.with_name(f".{self.path.name}.honoured-nonces.json")

    @property
    def pending_starts_path(self) -> Path:
        """Durable write-ahead records for STARTs between prepare and commit."""
        return self.path.with_name(f".{self.path.name}.pending.json")

    @staticmethod
    def _validate_instance_id(instance_id: str) -> None:
        if not isinstance(instance_id, str) or not instance_id.strip():
            raise ValueError("instance_id must be a non-blank string")

    @staticmethod
    def _validate_nonce(nonce: str | None) -> None:
        if nonce is not None and (not isinstance(nonce, str) or not nonce.strip()):
            raise ValueError("honoured_nonce must be a non-blank string or None")

    def _write_instances_locked(self, instances: dict[str, dict[str, object]]) -> None:
        _atomic_write_json(
            self.path,
            {
                "schema_version": self._SCHEMA_VERSION,
                "instances": instances,
            },
        )

    def _read_pending_starts(self) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads(self.pending_starts_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CorruptRunningSinceLeaseError(
                f"pending START authority is unreadable: {self.pending_starts_path}: {exc}"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != _PENDING_START_SCHEMA_VERSION
            or not isinstance(payload.get("instances"), dict)
        ):
            raise CorruptRunningSinceLeaseError(
                f"pending START authority is invalid: {self.pending_starts_path}"
            )
        pending: dict[str, dict[str, object]] = {}
        for instance_id, raw_record in payload["instances"].items():
            if not isinstance(instance_id, str) or not instance_id.strip() or not isinstance(raw_record, dict):
                raise CorruptRunningSinceLeaseError(
                    f"pending START authority is invalid: {self.pending_starts_path}"
                )
            if raw_record.get("state") != "pending":
                raise CorruptRunningSinceLeaseError(
                    f"pending START authority is invalid: {self.pending_starts_path}"
                )
            since = raw_record.get("since")
            try:
                parsed_since = datetime.fromisoformat(since) if isinstance(since, str) else None
            except ValueError as exc:
                raise CorruptRunningSinceLeaseError(
                    f"pending START timestamp is invalid: {self.pending_starts_path}"
                ) from exc
            monotonic_since = raw_record.get("monotonic_since")
            boot_id = raw_record.get("boot_id")
            nonce = raw_record.get("honoured_nonce")
            if (
                parsed_since is None
                or parsed_since.tzinfo is None
                or parsed_since.utcoffset() is None
                or isinstance(monotonic_since, bool)
                or not isinstance(monotonic_since, (int, float))
                or not math.isfinite(monotonic_since)
                or monotonic_since < 0
                or not isinstance(boot_id, str)
                or not boot_id.strip()
                or (nonce is not None and (not isinstance(nonce, str) or not nonce.strip()))
            ):
                raise CorruptRunningSinceLeaseError(
                    f"pending START authority is invalid: {self.pending_starts_path}"
                )
            pending[instance_id] = {
                "state": "pending",
                "since": parsed_since.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "monotonic_since": float(monotonic_since),
                "boot_id": boot_id,
                "honoured_nonce": nonce,
            }
        return pending

    def _write_pending_starts_locked(self, pending: dict[str, dict[str, object]]) -> None:
        if not pending:
            _durable_unlink(self.pending_starts_path)
            return
        _atomic_write_json(
            self.pending_starts_path,
            {
                "schema_version": _PENDING_START_SCHEMA_VERSION,
                "instances": pending,
            },
        )

    @staticmethod
    def _pending_record_to_origin(
        instance_id: str,
        raw_record: dict[str, object],
    ) -> PendingStartRecord:
        parsed_since = datetime.fromisoformat(str(raw_record["since"])).astimezone(UTC)
        return PendingStartRecord(
            instance_id=instance_id,
            since=parsed_since,
            monotonic_since=float(raw_record["monotonic_since"]),
            boot_id=str(raw_record["boot_id"]),
            honoured_nonce=(
                raw_record["honoured_nonce"]
                if isinstance(raw_record.get("honoured_nonce"), str)
                else None
            ),
        )

    def read(self, instance_id: str) -> RunningSinceRecord | None:
        try:
            payload = json.loads(self.path.read_text())
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as exc:
            logger.warning("running-since record unreadable; replacing it: %s", exc)
            return None
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self._SCHEMA_VERSION
            or not isinstance(payload.get("instances"), dict)
        ):
            # Greenfield policy: the old single-instance schema is stale state,
            # not something whose ownership can safely be inferred.
            return None
        raw_record = payload["instances"].get(instance_id)
        if not isinstance(raw_record, dict):
            return None
        source = raw_record.get("source")
        since = raw_record.get("since")
        if source not in self._SOURCES or not isinstance(since, str):
            logger.warning("running-since record invalid; replacing it: %s", self.path)
            return None
        try:
            parsed = datetime.fromisoformat(since)
        except ValueError:
            logger.warning("running-since timestamp invalid; replacing it: %s", self.path)
            return None
        honoured_nonce = raw_record.get("honoured_nonce")
        if honoured_nonce is not None and (not isinstance(honoured_nonce, str) or not honoured_nonce.strip()):
            logger.warning("running-since honoured_nonce invalid; replacing it: %s", self.path)
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            message = f"running-since timestamp has no timezone: {self.path}"
            logger.warning("%s; treating lease as expired", message)
            raise CorruptRunningSinceLeaseError(message)
        parsed = parsed.astimezone(UTC)
        monotonic_since = raw_record.get("monotonic_since")
        record_boot_id = raw_record.get("boot_id")
        has_valid_monotonic_origin = not (
            isinstance(monotonic_since, bool)
            or not isinstance(monotonic_since, (int, float))
            or not math.isfinite(monotonic_since)
            or monotonic_since < 0
            or not isinstance(record_boot_id, str)
            or not record_boot_id.strip()
        )
        if not has_valid_monotonic_origin or record_boot_id != self._boot_id:
            future_skew = (parsed - self._utc_now()).total_seconds()
            if future_skew > self._max_future_skew_seconds:
                message = (
                    "running-since timestamp is future-dated "
                    f"by {future_skew:.1f}s (allowance={self._max_future_skew_seconds:.1f}s): "
                    f"{self.path}"
                )
                logger.warning("%s; treating lease as expired", message)
                raise CorruptRunningSinceLeaseError(message)
            message = f"running-since monotonic origin is missing or belongs to a different boot: {self.path}"
            logger.warning("%s; treating lease as expired", message)
            raise CorruptRunningSinceLeaseError(message)
        return RunningSinceRecord(
            instance_id=instance_id,
            since=parsed,
            source=source,
            monotonic_since=(None if monotonic_since is None else float(monotonic_since)),
            boot_id=record_boot_id,
            honoured_nonce=honoured_nonce,
        )

    def write(
        self,
        instance_id: str,
        *,
        source: str,
        honoured_nonce: str | None = None,
    ) -> RunningSinceRecord:
        if source not in self._SOURCES:
            raise ValueError(f"unsupported running-since source: {source}")
        self._validate_instance_id(instance_id)
        self._validate_nonce(honoured_nonce)
        now = self._utc_now()
        monotonic_now = self._monotonic_now()
        with self._locked_for_update():
            instances = self._read_instances_for_update()
            previous_record = instances.get(instance_id)
            record_payload: dict[str, object] = {
                "since": now.isoformat().replace("+00:00", "Z"),
                "source": source,
            }
            if self._boot_id is not None:
                record_payload.update(
                    monotonic_since=monotonic_now,
                    boot_id=self._boot_id,
                )
            if honoured_nonce is not None:
                record_payload["honoured_nonce"] = honoured_nonce
            elif isinstance(previous_record, dict):
                previous_nonce = previous_record.get("honoured_nonce")
                if isinstance(previous_nonce, str) and previous_nonce.strip():
                    record_payload["honoured_nonce"] = previous_nonce
            instances[instance_id] = record_payload
            self._write_instances_locked(instances)
        return RunningSinceRecord(
            instance_id=instance_id,
            since=now,
            source=source,
            monotonic_since=(monotonic_now if self._boot_id is not None else None),
            boot_id=self._boot_id,
            honoured_nonce=honoured_nonce,
        )

    def prepare_start(self, instance_id: str, *, honoured_nonce: str | None = None) -> PendingStartRecord:
        """Durably record the lease authority before issuing OCI START."""
        self._validate_instance_id(instance_id)
        self._validate_nonce(honoured_nonce)
        origin = PendingStartRecord(
            instance_id=instance_id,
            since=self._utc_now(),
            monotonic_since=self._monotonic_now(),
            boot_id=self._boot_id,
            honoured_nonce=honoured_nonce,
        )
        with self._locked_for_update():
            pending = self._read_pending_starts()
            existing = pending.get(instance_id)
            if existing is not None:
                existing_origin = self._pending_record_to_origin(instance_id, existing)
                if existing_origin.honoured_nonce != honoured_nonce:
                    raise CorruptRunningSinceLeaseError(
                        f"pending START authority for {instance_id} has a different nonce"
                    )
                return existing_origin
            pending[instance_id] = {
                "state": "pending",
                "since": origin.since.isoformat().replace("+00:00", "Z"),
                "monotonic_since": origin.monotonic_since,
                "boot_id": origin.boot_id,
                "honoured_nonce": origin.honoured_nonce,
            }
            self._write_pending_starts_locked(pending)
        return origin

    def _write_honoured_nonce_locked(self, instance_id: str, nonce: str) -> None:
        instances = self._read_honoured_nonces()
        nonces = instances.setdefault(instance_id, set())
        if nonce in nonces:
            return
        nonces.add(nonce)
        _atomic_write_json(
            self.honoured_nonces_path,
            {
                "schema_version": _HONOURED_NONCES_SCHEMA_VERSION,
                "instances": {key: sorted(values) for key, values in instances.items()},
            },
        )

    def _commit_start_locked(
        self,
        instance_id: str,
        *,
        origin: PendingStartRecord,
    ) -> RunningSinceRecord:
        instances = self._read_instances_for_update()
        previous_record = instances.get(instance_id)
        record_payload: dict[str, object] = {
            "since": origin.since.isoformat().replace("+00:00", "Z"),
            "source": "start_actuator",
            "monotonic_since": origin.monotonic_since,
            "boot_id": origin.boot_id,
        }
        if origin.honoured_nonce is not None:
            self._write_honoured_nonce_locked(instance_id, origin.honoured_nonce)
            record_payload["honoured_nonce"] = origin.honoured_nonce
        elif isinstance(previous_record, dict):
            previous_nonce = previous_record.get("honoured_nonce")
            if isinstance(previous_nonce, str) and previous_nonce.strip():
                record_payload["honoured_nonce"] = previous_nonce
        instances[instance_id] = record_payload
        self._write_instances_locked(instances)
        return RunningSinceRecord(
            instance_id=instance_id,
            since=origin.since,
            source="start_actuator",
            monotonic_since=origin.monotonic_since,
            boot_id=origin.boot_id,
            honoured_nonce=origin.honoured_nonce,
        )

    def commit_start(self, instance_id: str, *, honoured_nonce: str | None = None) -> RunningSinceRecord:
        """Commit a prepared START, retaining the write-ahead record on failure."""
        self._validate_instance_id(instance_id)
        self._validate_nonce(honoured_nonce)
        with self._locked_for_update():
            pending = self._read_pending_starts()
            raw_origin = pending.get(instance_id)
            if raw_origin is None:
                origin = PendingStartRecord(
                    instance_id=instance_id,
                    since=self._utc_now(),
                    monotonic_since=self._monotonic_now(),
                    boot_id=self._boot_id,
                    honoured_nonce=honoured_nonce,
                )
            else:
                origin = self._pending_record_to_origin(instance_id, raw_origin)
                if honoured_nonce is not None and origin.honoured_nonce != honoured_nonce:
                    raise CorruptRunningSinceLeaseError(
                        f"pending START authority for {instance_id} has a different nonce"
                    )
            record = self._commit_start_locked(instance_id, origin=origin)
            if raw_origin is not None:
                del pending[instance_id]
                self._write_pending_starts_locked(pending)
            return record

    def reconcile_pending_start(self, instance_id: str, observed_state: str) -> bool:
        """Recover a START left between OCI mutation and durable commit.

        RUNNING/STARTING proves the mutation is in flight or complete, so the
        pre-recorded lease is committed. STOPPED proves the mutation did not
        take effect, so the pending record is discarded. Other states remain
        ambiguous and block further actuation.
        """
        self._validate_instance_id(instance_id)
        if observed_state not in {"RUNNING", "STARTING", "STOPPED", "STOPPING", "UNKNOWN"}:
            raise ValueError(f"unsupported instance state for pending START: {observed_state}")
        with self._locked_for_update():
            pending = self._read_pending_starts()
            raw_origin = pending.get(instance_id)
            if raw_origin is None:
                return False
            if observed_state in {"RUNNING", "STARTING"}:
                origin = self._pending_record_to_origin(instance_id, raw_origin)
                self._commit_start_locked(instance_id, origin=origin)
                del pending[instance_id]
                self._write_pending_starts_locked(pending)
                logger.warning(
                    "reconciled pending START for %s from observed %s",
                    instance_id,
                    observed_state,
                )
                return True
            if observed_state == "STOPPED":
                del pending[instance_id]
                self._write_pending_starts_locked(pending)
                logger.info("discarded pending START for %s after observed STOPPED", instance_id)
                return False
            raise CorruptRunningSinceLeaseError(
                f"pending START outcome is ambiguous for {instance_id}: observed {observed_state}"
            )

    def record_start(self, instance_id: str, *, honoured_nonce: str | None = None) -> RunningSinceRecord:
        if honoured_nonce is not None:
            self.prepare_start(instance_id, honoured_nonce=honoured_nonce)
        return self.commit_start(instance_id, honoured_nonce=honoured_nonce)

    def has_honoured_nonce(self, instance_id: str, nonce: str) -> bool:
        """Return whether this instance has already honoured ``nonce``.

        A missing ledger is the normal pre-first-START state.  Once a ledger
        exists, any unreadable or malformed contents are unsafe to interpret;
        callers deliberately handle ``CorruptHonouredNonceError`` as already
        honoured so a storage fault cannot cause a duplicate billable START.
        """
        if not isinstance(instance_id, str) or not instance_id.strip():
            raise ValueError("instance_id must be a non-blank string")
        if not isinstance(nonce, str) or not nonce.strip():
            raise ValueError("nonce must be a non-blank string")
        instances = self._read_honoured_nonces()
        return nonce in instances.get(instance_id, set())

    def record_honoured_nonce(self, instance_id: str, nonce: str) -> None:
        """Persist a successful operator START nonce independently of leases."""
        self._validate_instance_id(instance_id)
        if not isinstance(nonce, str) or not nonce.strip():
            raise ValueError("nonce must be a non-blank string")
        with self._locked_for_update():
            self._write_honoured_nonce_locked(instance_id, nonce)

    def _read_honoured_nonces(self) -> dict[str, set[str]]:
        try:
            payload = json.loads(self.honoured_nonces_path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CorruptHonouredNonceError(
                f"honoured nonce marker is unreadable: {self.honoured_nonces_path}: {exc}"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != _HONOURED_NONCES_SCHEMA_VERSION
            or not isinstance(payload.get("instances"), dict)
        ):
            raise CorruptHonouredNonceError(
                f"honoured nonce marker is invalid: {self.honoured_nonces_path}"
            )
        instances: dict[str, set[str]] = {}
        for instance_id, raw_nonces in payload["instances"].items():
            if (
                not isinstance(instance_id, str)
                or not instance_id.strip()
                or not isinstance(raw_nonces, list)
                or any(not isinstance(nonce, str) or not nonce.strip() for nonce in raw_nonces)
            ):
                raise CorruptHonouredNonceError(
                    f"honoured nonce marker is invalid: {self.honoured_nonces_path}"
                )
            instances[instance_id] = set(raw_nonces)
        return instances

    def observe_running(self, instance_id: str) -> RunningSinceRecord:
        record = self.read(instance_id)
        if record is None:
            raise CorruptRunningSinceLeaseError(
                f"RUNNING instance {instance_id} has no trustworthy durable lease origin; treating lease as expired"
            )
        return record

    @property
    def _read_failures_path(self) -> Path:
        return self.path.with_name(f".{self.path.name}.read-failures.json")

    def record_read_failure(self, instance_id: str) -> int:
        """Durably count consecutive read failures across oneshot invocations."""
        with self._locked_for_update():
            failures = self._read_failure_counts()
            count = failures.get(instance_id, 0) + 1
            failures[instance_id] = count
            self._write_failure_counts(failures)
        return count

    def clear_read_failures(self, instance_id: str) -> None:
        if not self._read_failures_path.exists():
            return
        with self._locked_for_update():
            failures = self._read_failure_counts()
            if instance_id not in failures:
                return
            del failures[instance_id]
            self._write_failure_counts(failures)

    def _read_failure_counts(self) -> dict[str, int]:
        try:
            payload = json.loads(self._read_failures_path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # An unreadable recovery counter cannot safely extend the lease.
            raise CorruptRunningSinceLeaseError(
                f"running-since recovery counter is unreadable: {self._read_failures_path}"
            )
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self._FAILURE_SCHEMA_VERSION
            or not isinstance(payload.get("instances"), dict)
        ):
            raise CorruptRunningSinceLeaseError(
                f"running-since recovery counter is invalid: {self._read_failures_path}"
            )
        failures: dict[str, int] = {}
        for key, value in payload["instances"].items():
            if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise CorruptRunningSinceLeaseError(
                    f"running-since recovery counter is invalid: {self._read_failures_path}"
                )
            failures[key] = value
        return failures

    def _write_failure_counts(self, failures: dict[str, int]) -> None:
        if not failures:
            _durable_unlink(self._read_failures_path)
            return
        payload = {
            "schema_version": self._FAILURE_SCHEMA_VERSION,
            "instances": failures,
        }
        _atomic_write_json(self._read_failures_path, payload)

    def remove(self, instance_id: str) -> None:
        with self._locked_for_update():
            instances = self._read_instances_for_update()
            if instance_id not in instances:
                return
            del instances[instance_id]
            if not instances:
                _durable_unlink(self.path)
                return
            self._write_instances_locked(instances)

    def _read_instances_for_update(self) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            logger.warning("running-since record unreadable; replacing it: %s", exc)
            return {}
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self._SCHEMA_VERSION
            or not isinstance(payload.get("instances"), dict)
        ):
            return {}
        return dict(payload["instances"])

    def age_seconds(self, record: RunningSinceRecord) -> int:
        monotonic_now = self._monotonic_now()
        if record.boot_id != self._boot_id or record.monotonic_since is None:
            raise CorruptRunningSinceLeaseError(
                f"monotonic lease origin for {record.instance_id} is unavailable; treating lease as expired"
            )
        if monotonic_now < record.monotonic_since:
            raise CorruptRunningSinceLeaseError(
                f"monotonic lease origin for {record.instance_id} is in the future; treating lease as expired"
            )
        return int(monotonic_now - record.monotonic_since)


def fetch_instance_idle_seconds(
    *,
    instance_id: str,
    oci_bin: str | None = None,
    auth: str | None = None,
    timeout_seconds: int = _DEFAULT_OCI_TIMEOUT_SECONDS,
) -> tuple[str, int] | None:
    """Best-effort lifecycle state from OCI CLI.

    The returned age is always zero. OCI's instance payload has no last
    lifecycle-transition timestamp, and ``time-created`` must never be treated
    as the age of the current RUNNING lease. The caller replaces zero with the
    controller-owned running-since age (or an explicit test override).
    """
    bin_path = oci_bin or shutil.which("oci") or "oci"
    cmd = [
        bin_path,
        "compute",
        "instance",
        "get",
        "--instance-id",
        instance_id,
        "--output",
        "json",
    ]
    if auth:
        cmd.extend(["--auth", auth])
    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        payload = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        logger.warning("oci instance get failed for %s: %s", instance_id, exc)
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    state = str(data.get("lifecycle-state") or data.get("lifecycle_state") or "UNKNOWN")
    return state, 0


@dataclass(frozen=True)
class ReapCycleResult:
    decided: list[tuple[str, str]]
    actuated: list[tuple[str, str]]
    fenced_off: bool
    errors: list[str]
    # STOPs forced by the max-lease cost cap, including when the load boundary
    # is untrustworthy. Reported separately so an operator can distinguish the
    # queue draining from the cost backstop firing.
    lease_expired: list[tuple[str, str]] = field(default_factory=list)
    snapshot_persisted: bool = True
    intent: EffectiveIntent = field(default_factory=EffectiveIntent)
    intent_status: IntentStatus = IntentStatus.NONE
    honoured_nonce: str | None = None
    instance_running_since: datetime | None = None
    lease_expires_at: datetime | None = None
    last_transition_reason: LastTransitionReason = LastTransitionReason.UNKNOWN


@dataclass(frozen=True)
class StartCycleResult:
    decided: list[tuple[str, str]]
    actuated: list[tuple[str, str]]
    errors: list[str]
    wait_result: ReadinessWaitResult | None = None
    fallbacks: tuple[FallbackDecision, ...] = ()
    snapshot_persisted: bool = True
    intent: EffectiveIntent = field(default_factory=EffectiveIntent)
    intent_status: IntentStatus = IntentStatus.NONE
    honoured_nonce: str | None = None
    instance_running_since: datetime | None = None
    lease_expires_at: datetime | None = None
    last_transition_reason: LastTransitionReason = LastTransitionReason.UNKNOWN


def _intent_store_paths(
    durable_state_dir: str | Path | None,
) -> tuple[Path, Path, Path, Path]:
    """Return the persistent intent paths, keeping the production defaults centralized."""
    root = DEFAULT_GPU_STATE_DIR if durable_state_dir is None else Path(durable_state_dir)
    return (
        root / "intents",
        root / "intent-authority.json",
        root / "deferred-stop.json",
        root / "decision-log.jsonl",
    )


def _intent_source_dir(
    *,
    intent_dir: str | Path | None,
    durable_intent_dir: str | Path | None,
    durable_state_dir: str | Path | None,
) -> Path | None:
    if intent_dir is not None:
        return Path(intent_dir)
    if durable_intent_dir is not None:
        return Path(durable_intent_dir)
    if durable_state_dir is not None:
        return _intent_store_paths(durable_state_dir)[0]
    return None


def _intent_stores(
    *,
    intent_dir: str | Path | None,
    durable_intent_dir: str | Path | None,
    durable_state_dir: str | Path | None,
    authority_store: IntentAuthorityStore | None,
    deferred_stop_store: DeferredStopStore | None,
    decision_log_store: DecisionLogStore | None,
) -> tuple[
    Path | None,
    IntentAuthorityStore | None,
    DeferredStopStore | None,
    DecisionLogStore | None,
]:
    """Build stores only when the caller opted into operator intent handling.

    Existing callers that omit ``intent_dir`` retain the legacy in-memory
    behavior. Production and call-site tests that provide an intent directory
    get the durable stores automatically, with the state root override making
    the same wiring testable without touching ``/var/lib``.
    """
    source_dir = _intent_source_dir(
        intent_dir=intent_dir,
        durable_intent_dir=durable_intent_dir,
        durable_state_dir=durable_state_dir,
    )
    if source_dir is None and not any(
        store is not None for store in (authority_store, deferred_stop_store, decision_log_store)
    ):
        return None, authority_store, deferred_stop_store, decision_log_store
    if source_dir is None:
        # A caller may inject one store for a focused test or an alternate
        # deployment without implicitly creating the other production stores.
        return None, authority_store, deferred_stop_store, decision_log_store
    durable_default, authority_default, deferred_default, decision_default = _intent_store_paths(
        durable_state_dir
    )
    durable_dir = Path(durable_intent_dir) if durable_intent_dir is not None else durable_default
    return (
        durable_dir,
        authority_store or IntentAuthorityStore(authority_default),
        deferred_stop_store or DeferredStopStore(deferred_default),
        decision_log_store or DecisionLogStore(decision_default),
    )


def _coerce_cycle_time(now: datetime | float | int | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if isinstance(now, datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return now.astimezone(UTC)
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
        raise ValueError("now must be a finite epoch timestamp or timezone-aware datetime")
    return datetime.fromtimestamp(float(now), tz=UTC)


def _deferred_extension_seconds(ttl_seconds: int) -> int:
    return max(
        _MIN_DEFERRED_STOP_EXTENSION_SECONDS,
        min(_MAX_DEFERRED_STOP_EXTENSION_SECONDS, int(ttl_seconds)),
    )


def _deferred_record_for_intent(
    effective_intent: EffectiveIntent,
    *,
    now: datetime,
) -> DeferredStopRecord | None:
    if effective_intent.action is not IntentAction.STOP:
        return None
    if (
        not isinstance(effective_intent.requested_at, datetime)
        or not isinstance(effective_intent.expires_at, datetime)
        or not isinstance(effective_intent.nonce, str)
        or not effective_intent.nonce.strip()
        or isinstance(effective_intent.sequence, bool)
        or not isinstance(effective_intent.sequence, int)
        or effective_intent.sequence < 1
    ):
        return None
    requested_at = effective_intent.requested_at.astimezone(UTC)
    expires_at = effective_intent.expires_at.astimezone(UTC)
    ttl_seconds = max(1, int((expires_at - requested_at).total_seconds()))
    extension = _deferred_extension_seconds(ttl_seconds)
    deferred_until = max(now, expires_at) + timedelta(seconds=extension)
    return DeferredStopRecord(
        action=IntentAction.STOP,
        requested_at=requested_at,
        expires_at=expires_at,
        nonce=effective_intent.nonce.strip(),
        requested_by=(effective_intent.requested_by or "unknown").strip() or "unknown",
        ttl_seconds=ttl_seconds,
        sequence=effective_intent.sequence,
        deferred_until=deferred_until,
        deferred_reason="STOP deferred while work is in flight",
    )


def _rearm_deferred_record(
    store: DeferredStopStore,
    record: DeferredStopRecord,
    *,
    now: datetime,
) -> DeferredStopRecord:
    if record.deferred_until > now:
        return record
    extension = _deferred_extension_seconds(record.ttl_seconds)
    rearmed = replace(record, deferred_until=now + timedelta(seconds=extension))
    store.write(rearmed)
    logger.warning(
        "re-armed expired deferred STOP nonce=%s sequence=%s until=%s",
        rearmed.nonce,
        rearmed.sequence,
        rearmed.deferred_until.isoformat(),
    )
    return rearmed


def _blocked_deferred_intent(
    effective_intent: EffectiveIntent,
    record: DeferredStopRecord,
    *,
    reason: str,
    error: Exception,
    decision_log_store: DecisionLogStore | None,
) -> EffectiveIntent:
    """Retain a failed deferred decision as a fail-closed STOP sentinel."""
    error_text = f"{type(error).__name__}: {error}"
    message = (
        f"deferred STOP {reason} failed; automatic actuation blocked for "
        f"nonce={record.nonce} sequence={record.sequence}: {error_text}"
    )
    audit = {
        "event": "dropped",
        "reason": reason,
        "action": IntentAction.STOP.value,
        "nonce": record.nonce,
        "sequence": record.sequence,
        "requested_by": record.requested_by,
        "error": error_text,
        "deferred_reason": record.deferred_reason,
    }
    if decision_log_store is not None:
        try:
            decision_log_store.append(audit)
        except Exception as audit_error:  # noqa: BLE001 - preserve the fail-closed sentinel
            message = f"{message}; deferred audit append failed: {type(audit_error).__name__}: {audit_error}"
            logger.error(message)
    logger.error(message)
    return EffectiveIntent(
        action=IntentAction.STOP,
        requested_at=record.requested_at,
        expires_at=record.deferred_until,
        nonce=record.nonce,
        requested_by=record.requested_by,
        sequence=record.sequence,
        source=effective_intent.source,
        status=IntentStatus.BLOCKED_WORK_IN_FLIGHT,
        reason=message,
        deferred_until=record.deferred_until,
        deferred_reason=record.deferred_reason,
        deferred_rearm_failed=True,
    )


def _apply_deferred_stop(
    effective_intent: EffectiveIntent,
    *,
    store: DeferredStopStore | None,
    now: datetime,
    decision_log_store: DecisionLogStore | None = None,
) -> EffectiveIntent:
    if store is None:
        return effective_intent
    if decision_log_store is None:
        decision_log_store = DecisionLogStore(store.path.with_name("decision-log.jsonl"))
    record = store.read()
    if record is None:
        return effective_intent
    if (
        isinstance(effective_intent.sequence, int)
        and not isinstance(effective_intent.sequence, bool)
        and isinstance(effective_intent.nonce, str)
        and effective_intent.nonce.strip()
        and (
            effective_intent.sequence > record.sequence
            or (
                effective_intent.sequence == record.sequence
                and effective_intent.nonce != record.nonce
            )
        )
    ):
        try:
            if store.supersede_if_newer(
                sequence=effective_intent.sequence,
                nonce=effective_intent.nonce,
            ):
                return effective_intent
            refreshed = store.read()
            if refreshed is None:
                return effective_intent
            record = refreshed
        except (OSError, ValueError) as exc:
            return _blocked_deferred_intent(
                effective_intent,
                record,
                reason="supersession_failed",
                error=exc,
                decision_log_store=decision_log_store,
            )
    try:
        record = _rearm_deferred_record(store, record, now=now)
    except (OSError, ValueError) as exc:
        return _blocked_deferred_intent(
            effective_intent,
            record,
            reason="rearm_failed",
            error=exc,
            decision_log_store=decision_log_store,
        )
    return record.to_effective_intent(source=effective_intent.source)


def _resolve_effective_intent(
    *,
    intent_dir: str | Path | None,
    intent: EffectiveIntent | IntentAction | str | None,
    now: datetime | float | int | None,
    durable_intent_dir: str | Path | None = None,
    authority_store: IntentAuthorityStore | None = None,
    deferred_stop_store: DeferredStopStore | None = None,
    decision_log_store: DecisionLogStore | None = None,
) -> EffectiveIntent:
    if isinstance(intent, EffectiveIntent):
        return _apply_deferred_stop(
            intent,
            store=deferred_stop_store,
            now=_coerce_cycle_time(now),
            decision_log_store=decision_log_store,
        )
    if intent is not None:
        return _apply_deferred_stop(
            EffectiveIntent(action=IntentAction(intent)),
            store=deferred_stop_store,
            now=_coerce_cycle_time(now),
            decision_log_store=decision_log_store,
        )
    source_dir = _intent_source_dir(
        intent_dir=intent_dir,
        durable_intent_dir=durable_intent_dir,
        durable_state_dir=None,
    )
    if source_dir is None:
        return _apply_deferred_stop(
            EffectiveIntent(),
            store=deferred_stop_store,
            now=_coerce_cycle_time(now),
            decision_log_store=decision_log_store,
        )
    current_time = _coerce_cycle_time(now)
    durable_dir = (
        Path(durable_intent_dir)
        if durable_intent_dir is not None
        else _intent_store_paths(None)[0]
    )
    read_dir = source_dir
    if durable_dir != source_dir:
        try:
            copy_intents_to_durable_dir(source_dir, durable_dir)
        except OSError as exc:
            # A first boot can legitimately lack the provisioned durable
            # directory.  Use the runtime publication until it is available;
            # once a durable directory exists it remains authoritative.
            logger.warning("could not copy runtime intents to durable storage: %s", exc)
        try:
            if durable_dir.is_dir():
                read_dir = durable_dir
        except OSError as exc:
            logger.warning("could not inspect durable intent directory %s: %s", durable_dir, exc)
    try:
        effective = read_effective_intent(
            read_dir,
            current_time,
            authority_store=authority_store,
        )
    except (IntentAuthorityError, OSError, ValueError) as exc:
        # Never honour an intent when its durable authority cannot be read.
        # Returning AUTO preserves the existing lifecycle safety policy while
        # making the authority failure visible in the cycle result/log.
        logger.error("operator intent authority unavailable; using auto: %s", exc)
        effective = EffectiveIntent(reason=f"intent authority unavailable: {exc}")
    return _apply_deferred_stop(
        effective,
        store=deferred_stop_store,
        now=current_time,
        decision_log_store=decision_log_store,
    )


def _honoured_instance_ids(
    instances: list[GpuInstance],
    store: RunningSinceLeaseStore | None,
    nonce: str | None,
) -> set[str]:
    if store is None or nonce is None:
        return set()
    read_record = getattr(store, "read", None)
    has_honoured_nonce = getattr(store, "has_honoured_nonce", None)
    if not callable(read_record) and not callable(has_honoured_nonce):
        return set()
    honoured: set[str] = set()
    for instance in instances:
        if callable(has_honoured_nonce):
            try:
                if has_honoured_nonce(instance.instance_id, nonce):
                    honoured.add(instance.instance_id)
                    continue
            except (AttributeError, OSError, ValueError) as exc:
                logger.warning(
                    "could not read honoured operator nonce for %s: %s",
                    instance.instance_id,
                    exc,
                )
                # A corrupt idempotency marker is safer as a deny-all result
                # for the current nonce than as an empty ledger.
                honoured.add(instance.instance_id)
                continue
        if not callable(read_record):
            continue
        try:
            record = read_record(instance.instance_id)
        except (AttributeError, OSError, ValueError) as exc:
            logger.warning(
                "could not read honoured operator nonce for %s: %s",
                instance.instance_id,
                exc,
            )
            continue
        if record is not None and getattr(record, "honoured_nonce", None) == nonce:
            honoured.add(instance.instance_id)
    return honoured


def _lease_snapshot_metadata(
    instances: list[GpuInstance],
    store: RunningSinceLeaseStore | None,
    *,
    max_lease_seconds: int,
    stopped_instance_ids: set[str] | None = None,
) -> tuple[datetime | None, datetime | None, str | None]:
    """Return C2 lease fields and the persisted START nonce for one subject."""
    if store is None:
        return None, None, None
    instance_id = _snapshot_instance_id(instances)
    if instance_id is None:
        return None, None, None
    read_record = getattr(store, "read", None)
    if not callable(read_record):
        return None, None, None
    try:
        record = read_record(instance_id)
    except (AttributeError, OSError, ValueError) as exc:
        logger.warning("could not read lease metadata for %s: %s", instance_id, exc)
        return None, None, None
    if record is None:
        return None, None, None
    honoured_nonce = getattr(record, "honoured_nonce", None)
    since = getattr(record, "since", None)
    if not isinstance(since, datetime):
        return None, None, honoured_nonce if isinstance(honoured_nonce, str) else None
    if stopped_instance_ids is not None and instance_id in stopped_instance_ids:
        return None, None, honoured_nonce if isinstance(honoured_nonce, str) else None
    lease_expires_at = (
        since + timedelta(seconds=max_lease_seconds)
        if max_lease_seconds > 0
        else None
    )
    return since, lease_expires_at, honoured_nonce if isinstance(honoured_nonce, str) else None


def _reconcile_ambiguous_action(
    actuator: InstanceStartActuator | InstanceStopActuator,
    instance_id: str,
    *,
    desired_state: str,
) -> bool:
    """Return whether a read-after-timeout proves the desired state."""
    state_getter = getattr(actuator, "get_instance_state", None)
    if not callable(state_getter):
        logger.error(
            "%s outcome unknown for %s; actuator has no reconciliation probe",
            desired_state,
            instance_id,
        )
        return False
    try:
        observed_state = state_getter(instance_id)
    except Exception as exc:  # noqa: BLE001 - reconciliation itself is best effort
        logger.error(
            "%s outcome unknown for %s; reconciliation failed: %s",
            desired_state,
            instance_id,
            exc,
        )
        return False
    if observed_state == desired_state:
        logger.warning(
            "%s response was lost for %s, but reconciliation observed %s",
            desired_state,
            instance_id,
            desired_state,
        )
        return True
    logger.error(
        "%s outcome remains unknown for %s after reconciliation observed %s",
        desired_state,
        instance_id,
        observed_state or "UNKNOWN",
    )
    return False


def _path_generation(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _load_generation(load_source: JobLoadSource) -> object:
    """Capture a best-effort monotonic identity for on-disk load evidence."""
    fence_token = getattr(load_source, "fence_token", None)
    if callable(fence_token):
        return fence_token()
    generation = getattr(load_source, "generation", None)
    if generation is not None:
        return generation
    directory = getattr(load_source, "directory", None)
    if isinstance(directory, Path):
        return tuple(
            (str(path.relative_to(directory)), _path_generation(path))
            for path in sorted(directory.glob("*/describe-load.json"))
        )
    path = getattr(load_source, "path", None)
    if isinstance(path, Path):
        return _path_generation(path)
    return None


def _validated_stop_observation(
    load_source: JobLoadSource,
    *,
    expected_generation: object,
) -> JobLoadSnapshot | None:
    """Revalidate load and its generation immediately before a STOP."""
    try:
        before = _load_generation(load_source)
        load = load_source.snapshot()
        after = _load_generation(load_source)
    except Exception as exc:  # noqa: BLE001 - an unusable fence fails closed
        logger.error("load fence validation failed; cancelling STOP: %s", exc)
        return None
    if not isinstance(load, JobLoadSnapshot) or load.untrustworthy:
        logger.error("load fence validation is untrustworthy; cancelling STOP")
        return None
    if before != after or (expected_generation is not None and before != expected_generation):
        logger.warning("load generation advanced after STOP decision; cancelling STOP")
        return None
    return load


def _actuate_stop_with_generation_fence(
    load_source: JobLoadSource,
    actuator: InstanceStopActuator,
    *,
    instance_id: str,
    expected_generation: object,
) -> tuple[bool, bool]:
    """Actuate only while a writer-coordinated generation remains current.

    A consumer-side stat/read/stat check cannot close the final process-boundary
    race. Mutable production sources must therefore supply compare-and-act
    semantics coordinated with their writer. Static test sources are immutable
    by construction and need no such handshake.
    """
    if isinstance(load_source, StaticJobLoadSource):
        actuator.stop_instance(instance_id)
        return True, True
    compare_and_act = getattr(load_source, "actuate_if_generation", None)
    if not callable(compare_and_act):
        logger.error(
            "load source has no writer-coordinated generation fence; cancelling STOP for %s",
            instance_id,
        )
        return False, False
    return (
        bool(
            compare_and_act(
                expected_generation,
                lambda: actuator.stop_instance(instance_id),
            )
        ),
        True,
    )


def _snapshot_instance_id(instances: list[GpuInstance]) -> str | None:
    """Return the instance id when an aggregate snapshot has one subject."""
    instance_ids = {instance.instance_id for instance in instances}
    if len(instance_ids) == 1:
        return next(iter(instance_ids))
    return None


def _state_reason(
    state: GpuLifecycleState,
    *,
    instances: list[GpuInstance],
    fallback_reason: str | None = None,
    has_errors: bool = False,
) -> str | None:
    """Supply the contract-required reason for every degraded snapshot."""
    if state is not GpuLifecycleState.DEGRADED:
        return None
    if fallback_reason is not None:
        return fallback_reason
    if not instances or any(instance.state == "UNKNOWN" for instance in instances):
        return "instance_state_unknown"
    if has_errors:
        return "lifecycle_error"
    return "readiness_failure"


def _decision_action_pairs(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "action": getattr(action, "value", str(action)),
            "instance_id": instance_id,
        }
        for action, instance_id in pairs
    ]


def _record_decision(
    result: ReapCycleResult | StartCycleResult,
    *,
    mode: str,
    now: datetime | float | int | None,
    store: DecisionLogStore | None,
) -> ReapCycleResult | StartCycleResult:
    """Append one durable record for every cycle that made a spend decision."""
    if store is None:
        return result
    lease_expired = getattr(result, "lease_expired", [])
    blocked = result.intent_status is IntentStatus.BLOCKED_WORK_IN_FLIGHT
    if not (result.decided or result.actuated or lease_expired or blocked):
        return result
    if result.actuated:
        outcome = "honoured" if not result.errors else "partial"
    elif blocked:
        outcome = "deferred"
    elif result.errors:
        outcome = "failed"
    elif getattr(result, "fenced_off", False):
        outcome = "fenced_off"
    else:
        outcome = "not_actuated"
    intent = result.intent
    record = {
        "timestamp": _coerce_cycle_time(now).isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "requested_by": intent.requested_by,
        "nonce": intent.nonce,
        "sequence": intent.sequence,
        "effective_intent": intent.action.value,
        "intent_status": result.intent_status.value,
        "intent_expires_at": (
            intent.expires_at.isoformat().replace("+00:00", "Z")
            if intent.expires_at is not None
            else None
        ),
        "decided": _decision_action_pairs(result.decided),
        "lease_expired": _decision_action_pairs(lease_expired),
        "actuated": _decision_action_pairs(result.actuated),
        "actuation_outcome": outcome,
        "errors": list(result.errors),
    }
    try:
        store.append(record)
    except Exception as exc:  # noqa: BLE001 - audit failure must surface in result
        message = f"decision log append failed: {type(exc).__name__}: {exc}"
        logger.error(message)
        return replace(result, errors=[*result.errors, message])
    return result


def _apply_running_since_leases(
    instances: list[GpuInstance],
    store: RunningSinceLeaseStore,
    *,
    use_recorded_age: bool,
    dry_run: bool,
) -> tuple[list[GpuInstance], list[str]]:
    observed: list[GpuInstance] = []
    errors: list[str] = []
    for instance in instances:
        if instance.state in ("STOPPED", "STOPPING"):
            if dry_run:
                logger.info("dry-run would remove RUNNING lease instance=%s", instance.instance_id)
                observed.append(instance)
                continue
            try:
                store.remove(instance.instance_id)
                store.clear_read_failures(instance.instance_id)
            except (OSError, ValueError) as exc:
                msg = (
                    f"{instance.instance_id}: running-since removal failed; lease cap disabled: "
                    f"{type(exc).__name__}: {exc}"
                )
                logger.error(msg)
                errors.append(msg)
            observed.append(instance)
            continue
        if instance.state != "RUNNING":
            observed.append(instance)
            continue
        if not use_recorded_age:
            logger.info(
                "evaluating RUNNING lease instance=%s source=instance_idle_for_override age_seconds=%s",
                instance.instance_id,
                instance.idle_for_seconds,
            )
            observed.append(instance)
            continue
        try:
            if dry_run:
                record = store.read(instance.instance_id)
                if record is None:
                    raise CorruptRunningSinceLeaseError(
                        f"RUNNING instance {instance.instance_id} has no trustworthy "
                        "durable lease origin; treating lease as expired"
                    )
            else:
                record = store.observe_running(instance.instance_id)
            age_seconds = store.age_seconds(record)
        except CorruptRunningSinceLeaseError as exc:
            msg = f"{instance.instance_id}: corrupt running-since lease; forcing cost-cap expiry: {exc}"
            logger.warning(msg)
            errors.append(msg)
            observed.append(
                GpuInstance(
                    instance_id=instance.instance_id,
                    state=instance.state,
                    idle_for_seconds=sys.maxsize,
                )
            )
            continue
        except (OSError, ValueError) as exc:
            failure_count = 0
            counter_error: Exception | None = None
            if not dry_run:
                try:
                    failure_count = store.record_read_failure(instance.instance_id)
                except (OSError, ValueError) as recovery_exc:
                    counter_error = recovery_exc
            if counter_error is not None or failure_count >= _RUNNING_SINCE_READ_FAILURE_RECOVERY_CYCLES:
                detail = (
                    f"recovery counter unavailable ({type(counter_error).__name__}: {counter_error})"
                    if counter_error is not None
                    else (f"failure {failure_count}/{_RUNNING_SINCE_READ_FAILURE_RECOVERY_CYCLES}")
                )
                msg = (
                    f"{instance.instance_id}: running-since observation failed; bounded RES-13 "
                    f"recovery exhausted ({detail}); forcing cost-cap expiry: "
                    f"{type(exc).__name__}: {exc}"
                )
                logger.error(msg)
                errors.append(msg)
                observed.append(
                    GpuInstance(
                        instance_id=instance.instance_id,
                        state=instance.state,
                        idle_for_seconds=sys.maxsize,
                    )
                )
                continue
            msg = (
                f"{instance.instance_id}: running-since observation failed; lease cap disabled "
                f"only during bounded RES-13 recovery "
                f"({failure_count}/{_RUNNING_SINCE_READ_FAILURE_RECOVERY_CYCLES}): "
                f"{type(exc).__name__}: {exc}"
            )
            logger.warning(msg)
            errors.append(msg)
            # The age this instance carries came from OCI, not from the lease, so
            # feeding it to the absolute cost cap would STOP a machine whose lease
            # age is unknown. Zero is the only value that keeps the log honest.
            observed.append(
                GpuInstance(
                    instance_id=instance.instance_id,
                    state=instance.state,
                    idle_for_seconds=0,
                )
            )
            continue
        else:
            source = record.source
            if not dry_run:
                try:
                    store.clear_read_failures(instance.instance_id)
                except (OSError, ValueError) as exc:
                    # The authoritative lease remains usable. A stale recovery
                    # count can only shorten a later degraded lease, never
                    # extend the cost cap.
                    logger.warning(
                        "%s: could not clear running-since recovery state: %s: %s",
                        instance.instance_id,
                        type(exc).__name__,
                        exc,
                    )
        logger.info(
            "evaluating RUNNING lease instance=%s source=%s age_seconds=%s",
            instance.instance_id,
            source,
            age_seconds,
        )
        observed.append(
            GpuInstance(
                instance_id=instance.instance_id,
                state=instance.state,
                idle_for_seconds=age_seconds,
            )
        )
    return observed, errors


def _run_reap_cycle(
    *,
    controller: GpuLifecycleController,
    instances: list[GpuInstance],
    load_source: JobLoadSource,
    actuator: InstanceStopActuator,
    fence_delay_seconds: float = _DEFAULT_FENCE_DELAY_SECONDS,
    max_lease_seconds: int = 0,
    running_since_store: RunningSinceLeaseStore | None = None,
    use_recorded_lease_age: bool = True,
    dry_run: bool = False,
    effective_intent: EffectiveIntent | None = None,
    deferred_stop_store: DeferredStopStore | None = None,
    now: datetime | float | int | None = None,
) -> ReapCycleResult:
    """Decision → fence delay → re-sample → STOP only if still idle.

    Per-instance STOP failures are collected; the loop continues (rg-007).

    The max-lease cost cap is absolute: it may STOP a RUNNING instance when the
    load boundary is busy, untrustworthy, unavailable, or fails to sample. The
    idle-STOP path remains fail-closed and refuses STOP on untrustworthy load.
    """
    effective_intent = effective_intent or EffectiveIntent()
    cycle_time = _coerce_cycle_time(now)
    intent_status = effective_intent.status
    if intent_status is IntentStatus.NONE and effective_intent.action is not IntentAction.AUTO:
        intent_status = IntentStatus.PENDING
    lease_expired: list[tuple[str, str]] = []
    lease_errors: list[str] = []
    if running_since_store is not None:
        instances, lease_errors = _apply_running_since_leases(
            instances,
            running_since_store,
            use_recorded_age=use_recorded_lease_age,
            dry_run=dry_run,
        )
    try:
        load = load_source.snapshot()
    except Exception as exc:  # noqa: BLE001 - an unusable load fence fails closed
        logger.error("load snapshot failed; treating load as untrustworthy: %s", exc)
        load = None

    load_trustworthy = isinstance(load, JobLoadSnapshot) and not load.untrustworthy
    honoured_ids = _honoured_instance_ids(instances, running_since_store, effective_intent.nonce)

    forced = controller.lease_expired_instances(instances, max_lease_seconds=max_lease_seconds)
    for action, instance_id in forced:
        if load_trustworthy:
            logger.warning(
                "max lease %ss exceeded; forcing STOP despite trustworthy busy load: %s",
                max_lease_seconds,
                instance_id,
            )
        else:
            logger.error(
                "max lease exceeded with untrustworthy load; forcing STOP (cost cap is absolute): %s",
                instance_id,
            )
        if dry_run:
            logger.info("dry-run would force STOP for expired lease: %s", instance_id)
            lease_expired.append((action, instance_id))
            continue
        try:
            actuator.stop_instance(instance_id)
            lease_expired.append((action, instance_id))
        except subprocess.SubprocessError as exc:
            if _reconcile_ambiguous_action(
                actuator,
                instance_id,
                desired_state="STOPPED",
            ):
                lease_expired.append((action, instance_id))
                continue
            msg = f"{instance_id}: STOP outcome unknown after {type(exc).__name__}: {exc}"
            lease_errors.append(msg)
        except Exception as exc:  # noqa: BLE001 - isolate per-instance (rg-007)
            msg = f"{instance_id}: {type(exc).__name__}: {exc}"
            logger.error("lease-expiry STOP failed: %s", msg)
            lease_errors.append(msg)
    if lease_expired and effective_intent.action is IntentAction.STOP and deferred_stop_store is not None:
        try:
            deferred_stop_store.clear(sequence=effective_intent.sequence)
        except OSError as exc:
            lease_errors.append(f"deferred STOP clear failed: {type(exc).__name__}: {exc}")
    # Anything already stopped by the cap must not be considered again below.
    forced_ids = {instance_id for _, instance_id in lease_expired}
    if forced_ids:
        instances = [i for i in instances if i.instance_id not in forced_ids]

    if lease_expired:
        last_transition_reason = LastTransitionReason.LEASE_CAP
    else:
        last_transition_reason = LastTransitionReason.UNKNOWN
    if honoured_ids and effective_intent.action is IntentAction.START:
        intent_status = IntentStatus.HONOURED

    if effective_intent.deferred_rearm_failed:
        message = effective_intent.reason or "deferred STOP rearm failed; automatic actuation blocked"
        logger.error(message)
        return ReapCycleResult(
            decided=[],
            actuated=[],
            fenced_off=True,
            errors=[*lease_errors, message],
            lease_expired=lease_expired,
            intent=effective_intent,
            intent_status=IntentStatus.BLOCKED_WORK_IN_FLIGHT,
            last_transition_reason=last_transition_reason,
        )

    if not load_trustworthy:
        msg = "load snapshot untrustworthy; refusing STOP (fail closed)"
        logger.error(msg)
        return ReapCycleResult(
            decided=[],
            actuated=[],
            fenced_off=True,
            errors=[*lease_errors, msg],
            lease_expired=lease_expired,
            intent=effective_intent,
            intent_status=intent_status,
            last_transition_reason=last_transition_reason,
        )

    assert isinstance(load, JobLoadSnapshot)
    decided = controller.reap_idle_instances(
        instances,
        queue_depth=load.queue_depth,
        in_flight=load.in_flight,
        batch_in_progress=load.batch_in_progress,
        intent=effective_intent.action,
    )
    if effective_intent.action is IntentAction.STOP and load.has_work:
        blocked_errors = list(lease_errors)
        if deferred_stop_store is not None:
            deferred_record = _deferred_record_for_intent(effective_intent, now=cycle_time)
            if deferred_record is None:
                blocked_errors.append(
                    "deferred STOP could not be persisted: intent is missing requested_at, nonce, or sequence"
                )
                logger.error(blocked_errors[-1])
            else:
                try:
                    deferred_stop_store.write(deferred_record)
                except (OSError, ValueError) as exc:
                    blocked_errors.append(
                        f"deferred STOP write failed: {type(exc).__name__}: {exc}"
                    )
                    logger.error(blocked_errors[-1])
                else:
                    effective_intent = replace(
                        effective_intent,
                        expires_at=deferred_record.deferred_until,
                        status=IntentStatus.BLOCKED_WORK_IN_FLIGHT,
                        reason="STOP re-armed while work is in flight",
                        deferred_until=deferred_record.deferred_until,
                        deferred_reason=deferred_record.deferred_reason,
                    )
        return ReapCycleResult(
            decided=[],
            actuated=[],
            fenced_off=False,
            errors=blocked_errors,
            lease_expired=lease_expired,
            intent=effective_intent,
            intent_status=IntentStatus.BLOCKED_WORK_IN_FLIGHT,
            last_transition_reason=last_transition_reason,
        )
    if not decided:
        return ReapCycleResult(
            decided=[],
            actuated=[],
            fenced_off=False,
            errors=lease_errors,
            lease_expired=lease_expired,
            intent=effective_intent,
            intent_status=intent_status,
            last_transition_reason=last_transition_reason,
        )

    fence_expired = False
    pre_stop: JobLoadSnapshot | None = None
    pre_stop_generation: object = None
    try:
        if fence_delay_seconds > 0:
            time.sleep(fence_delay_seconds)
        generation_before = _load_generation(load_source)
        observed_load = load_source.snapshot()
        if not isinstance(observed_load, JobLoadSnapshot):
            raise ValueError("load source abstained from the fence observation")
        pre_stop = observed_load
        pre_stop_generation = _load_generation(load_source)
        if generation_before != pre_stop_generation:
            logger.warning("load generation changed during fence observation")
            fence_expired = True
    except Exception as exc:  # noqa: BLE001 - fence expiry fails closed
        logger.error("fence resample failed; cancelling STOP: %s", exc)
        fence_expired = True

    fenced = controller.fence_stop_actions(decided, pre_stop_load=pre_stop, fence_expired=fence_expired)
    if not fenced:
        logger.info(
            "fence cancelled STOP (queue_depth=%s in_flight=%s batch=%s expired=%s)",
            None if pre_stop is None else pre_stop.queue_depth,
            None if pre_stop is None else pre_stop.in_flight,
            None if pre_stop is None else pre_stop.batch_in_progress,
            fence_expired,
        )
        return ReapCycleResult(
            decided=decided,
            actuated=[],
            fenced_off=True,
            errors=lease_errors,
            lease_expired=lease_expired,
            intent=effective_intent,
            intent_status=intent_status,
            last_transition_reason=last_transition_reason,
        )

    actuated: list[tuple[str, str]] = []
    errors: list[str] = []
    for action, instance_id in fenced:
        if action != "STOP":
            continue
        current_load = _validated_stop_observation(
            load_source,
            expected_generation=pre_stop_generation,
        )
        if not controller.fence_stop_actions(
            [(action, instance_id)],
            pre_stop_load=current_load,
            fence_expired=current_load is None,
        ):
            logger.info("generation fence cancelled STOP for %s", instance_id)
            return ReapCycleResult(
                decided=decided,
                actuated=actuated,
                fenced_off=True,
                errors=[*lease_errors, *errors],
                lease_expired=lease_expired,
                intent=effective_intent,
                intent_status=intent_status,
                last_transition_reason=last_transition_reason,
            )
        if dry_run:
            logger.info("dry-run would STOP idle instance: %s", instance_id)
            actuated.append((action, instance_id))
            continue
        try:
            stopped, fence_supported = _actuate_stop_with_generation_fence(
                load_source,
                actuator,
                instance_id=instance_id,
                expected_generation=pre_stop_generation,
            )
            if not stopped:
                logger.info("atomic generation fence cancelled STOP for %s", instance_id)
                fence_errors = (
                    [] if fence_supported else [f"{instance_id}: writer-coordinated STOP generation fence unavailable"]
                )
                return ReapCycleResult(
                    decided=decided,
                    actuated=actuated,
                    fenced_off=True,
                    errors=[*lease_errors, *errors, *fence_errors],
                    lease_expired=lease_expired,
                    intent=effective_intent,
                    intent_status=intent_status,
                    last_transition_reason=last_transition_reason,
                )
            actuated.append((action, instance_id))
        except subprocess.SubprocessError as exc:
            if _reconcile_ambiguous_action(
                actuator,
                instance_id,
                desired_state="STOPPED",
            ):
                actuated.append((action, instance_id))
                continue
            msg = f"{instance_id}: STOP outcome unknown after {type(exc).__name__}: {exc}"
            errors.append(msg)
        except Exception as exc:  # noqa: BLE001 - isolate per-instance (VLMFIX-S2-03)
            msg = f"{instance_id}: {type(exc).__name__}: {exc}"
            logger.error("STOP failed: %s", msg)
            errors.append(msg)
    if actuated and effective_intent.action is IntentAction.STOP:
        intent_status = IntentStatus.HONOURED
        last_transition_reason = LastTransitionReason.OPERATOR
        if deferred_stop_store is not None:
            try:
                deferred_stop_store.clear(sequence=effective_intent.sequence)
            except OSError as exc:
                errors.append(f"deferred STOP clear failed: {type(exc).__name__}: {exc}")
    elif actuated:
        last_transition_reason = LastTransitionReason.IDLE
    return ReapCycleResult(
        decided=decided,
        actuated=actuated,
        fenced_off=False,
        errors=[*lease_errors, *errors],
        lease_expired=lease_expired,
        intent=effective_intent,
        intent_status=intent_status,
        last_transition_reason=last_transition_reason,
    )


def run_reap_cycle(
    *,
    controller: GpuLifecycleController,
    instances: list[GpuInstance],
    load_source: JobLoadSource,
    actuator: InstanceStopActuator,
    fence_delay_seconds: float = _DEFAULT_FENCE_DELAY_SECONDS,
    max_lease_seconds: int = 0,
    running_since_store: RunningSinceLeaseStore | None = None,
    use_recorded_lease_age: bool = True,
    dry_run: bool = False,
    gpu_state_path: str | Path | None = None,
    intent_dir: str | Path | None = None,
    intent: EffectiveIntent | IntentAction | str | None = None,
    now: datetime | float | int | None = None,
    durable_state_dir: str | Path | None = None,
    durable_intent_dir: str | Path | None = None,
    authority_store: IntentAuthorityStore | None = None,
    deferred_stop_store: DeferredStopStore | None = None,
    decision_log_store: DecisionLogStore | None = None,
) -> ReapCycleResult:
    """Serialize observe/decide/actuate/publish as one lifecycle transition."""
    resolved_durable_dir, resolved_authority, resolved_deferred, resolved_log = _intent_stores(
        intent_dir=intent_dir,
        durable_intent_dir=durable_intent_dir,
        durable_state_dir=durable_state_dir,
        authority_store=authority_store,
        deferred_stop_store=deferred_stop_store,
        decision_log_store=decision_log_store,
    )
    effective_intent = _resolve_effective_intent(
        intent_dir=intent_dir,
        intent=intent,
        now=now,
        durable_intent_dir=resolved_durable_dir,
        authority_store=resolved_authority,
        deferred_stop_store=resolved_deferred,
        decision_log_store=resolved_log,
    )
    if dry_run:
        result = _run_reap_cycle(
            controller=controller,
            instances=instances,
            load_source=load_source,
            actuator=actuator,
            fence_delay_seconds=fence_delay_seconds,
            max_lease_seconds=max_lease_seconds,
            running_since_store=running_since_store,
            use_recorded_lease_age=use_recorded_lease_age,
            dry_run=True,
            effective_intent=effective_intent,
            deferred_stop_store=resolved_deferred,
            now=now,
        )
        return _record_decision(result, mode="reap", now=now, store=resolved_log)
    with _serialized_gpu_state_publish(gpu_state_path):
        result = _run_reap_cycle(
            controller=controller,
            instances=instances,
            load_source=load_source,
            actuator=actuator,
            fence_delay_seconds=fence_delay_seconds,
            max_lease_seconds=max_lease_seconds,
            running_since_store=running_since_store,
            use_recorded_lease_age=use_recorded_lease_age,
            dry_run=False,
            effective_intent=effective_intent,
            deferred_stop_store=resolved_deferred,
            now=now,
        )
        result = _record_decision(result, mode="reap", now=now, store=resolved_log)
        stopped_instance_ids = {
            instance_id for action, instance_id in [*result.actuated, *result.lease_expired] if action == "STOP"
        }
        post_actuation_instances = [
            GpuInstance(
                instance_id=instance.instance_id,
                state=("STOPPED" if instance.instance_id in stopped_instance_ids else instance.state),
                idle_for_seconds=instance.idle_for_seconds,
            )
            for instance in instances
        ]
        snapshot_instance_id = _snapshot_instance_id(post_actuation_instances)
        state = state_for_instances(
            [instance.state for instance in post_actuation_instances],
            previous_state=read_previous_gpu_state(
                gpu_state_path,
                expected_instance_id=snapshot_instance_id,
            ),
        )
        if result.errors:
            state = GpuLifecycleState.DEGRADED
        instance_running_since, lease_expires_at, persisted_nonce = _lease_snapshot_metadata(
            post_actuation_instances,
            running_since_store,
            max_lease_seconds=max_lease_seconds,
            stopped_instance_ids=stopped_instance_ids,
        )
        snapshot_kwargs: dict[str, object] = {}
        if snapshot_instance_id is not None:
            snapshot_kwargs = {
                "intent": result.intent.action,
                "intent_expires_at": result.intent.expires_at,
                "intent_status": result.intent_status,
                "honoured_nonce": result.honoured_nonce or persisted_nonce,
                "lease_expires_at": lease_expires_at,
                "instance_running_since": instance_running_since,
                "last_transition_reason": result.last_transition_reason,
            }
        snapshot_persisted = write_gpu_state_snapshot(
            state,
            instance_id=snapshot_instance_id,
            reason=_state_reason(
                state,
                instances=post_actuation_instances,
                has_errors=bool(result.errors),
            ),
            path=gpu_state_path,
            **snapshot_kwargs,
        )
    return replace(
        result,
        snapshot_persisted=snapshot_persisted,
        honoured_nonce=result.honoured_nonce or persisted_nonce,
        instance_running_since=instance_running_since,
        lease_expires_at=lease_expires_at,
    )


def _run_start_cycle(
    *,
    controller: GpuLifecycleController,
    instances: list[GpuInstance],
    load_source: JobLoadSource,
    actuator: InstanceStartActuator,
    probe: InstanceReadinessProbe | None = None,
    readiness_wait: WarmReadinessWait | None = None,
    running_since_store: RunningSinceLeaseStore | None = None,
    dry_run: bool = False,
    effective_intent: EffectiveIntent | None = None,
) -> StartCycleResult:
    """Emit START for STOPPED instances when the job store has work.

    Per-instance START failures are collected; the loop continues (rg-007).
    When a readiness probe is supplied, wait is bounded; timeout/stall is loud.
    """
    effective_intent = effective_intent or EffectiveIntent()
    errors: list[str] = []
    if effective_intent.deferred_rearm_failed:
        message = effective_intent.reason or "deferred STOP rearm failed; automatic actuation blocked"
        logger.error(message)
        return StartCycleResult(
            decided=[],
            actuated=[],
            errors=[message],
            intent=effective_intent,
            intent_status=IntentStatus.BLOCKED_WORK_IN_FLIGHT,
        )
    reconcile_pending = getattr(running_since_store, "reconcile_pending_start", None)
    if callable(reconcile_pending) and not dry_run:
        for instance in instances:
            try:
                reconcile_pending(instance.instance_id, instance.state)
            except (OSError, ValueError) as exc:
                msg = (
                    f"{instance.instance_id}: pending START recovery failed; refusing START: "
                    f"{type(exc).__name__}: {exc}"
                )
                logger.error(msg)
                errors.append(msg)
    if errors:
        intent_status = effective_intent.status
        if intent_status is IntentStatus.NONE and effective_intent.action is not IntentAction.AUTO:
            intent_status = IntentStatus.PENDING
        return StartCycleResult(
            decided=[],
            actuated=[],
            errors=errors,
            intent=effective_intent,
            intent_status=intent_status,
        )
    load = load_source.snapshot()
    honoured_ids = _honoured_instance_ids(instances, running_since_store, effective_intent.nonce)
    if not isinstance(load, JobLoadSnapshot) or load.untrustworthy:
        msg = "load snapshot untrustworthy; refusing START"
        logger.error("%s to avoid unfenced GPU burn", msg)
        errors.append(msg)
        decided: list[tuple[str, str]] = []
        waiting_ids: list[str] = []
    else:
        decided = controller.start_needed_instances(
            instances,
            queue_depth=load.queue_depth,
            in_flight=load.in_flight,
            batch_in_progress=load.batch_in_progress,
            intent=effective_intent.action,
            honoured_instance_ids=honoured_ids,
        )
        waiting_ids = (
            controller.instances_waiting_on_boot(instances)
            if load.has_work and effective_intent.action is not IntentAction.STOP
            else []
        )
    running_ids = [instance.instance_id for instance in instances if instance.state == "RUNNING"]
    blocked = (
        controller.instances_blocking_start(instances)
        if isinstance(load, JobLoadSnapshot)
        and not load.untrustworthy
        and load.has_work
        and effective_intent.action is not IntentAction.STOP
        else []
    )
    for instance in blocked:
        msg = f"{instance.instance_id}: fail-closed START refused; state={instance.state} while work waits"
        logger.error(msg)
        errors.append(msg)
    should_probe_running = probe is not None and readiness_wait is not None and bool(running_ids)
    if not decided and not waiting_ids and not errors and not should_probe_running:
        status = effective_intent.status
        if status is IntentStatus.NONE and effective_intent.action is not IntentAction.AUTO:
            status = (
                IntentStatus.HONOURED
                if effective_intent.action is IntentAction.START and honoured_ids
                else IntentStatus.PENDING
            )
        return StartCycleResult(
            decided=[],
            actuated=[],
            errors=[],
            intent=effective_intent,
            intent_status=status,
            honoured_nonce=(effective_intent.nonce if honoured_ids else None),
        )

    start_ids = [instance_id for action, instance_id in decided if action == LifecycleAction.START]
    wait_ids = list(dict.fromkeys([*start_ids, *waiting_ids, *running_ids]))
    if isinstance(probe, HttpReadinessProbe) and not probe.is_per_instance and len(wait_ids) > 1:
        msg = (
            "HttpReadinessProbe URL is a single shared endpoint; refusing "
            "multi-id wait (template {instance_id} required)"
        )
        logger.error(msg)
        errors.append(msg)
        return StartCycleResult(
            decided=decided,
            actuated=[],
            errors=errors,
            wait_result=None,
            intent=effective_intent,
            intent_status=(
                IntentStatus.PENDING
                if effective_intent.status is IntentStatus.NONE and effective_intent.action is not IntentAction.AUTO
                else effective_intent.status
            ),
            honoured_nonce=(effective_intent.nonce if honoured_ids else None),
        )

    actuated: list[tuple[str, str]] = []
    start_failed: list[str] = []
    prepare_start = getattr(running_since_store, "prepare_start", None)
    commit_start = getattr(running_since_store, "commit_start", None)
    use_write_ahead_start = callable(prepare_start) and callable(commit_start)
    for action, instance_id in decided:
        if action != LifecycleAction.START:
            continue
        prepared = False
        if running_since_store is not None and not dry_run and use_write_ahead_start:
            try:
                prepare_start(
                    instance_id,
                    honoured_nonce=(
                        effective_intent.nonce
                        if effective_intent.action is IntentAction.START
                        else None
                    ),
                )
                prepared = True
            except (OSError, ValueError) as exc:
                msg = (
                    f"{instance_id}: durable START authority prepare failed; refusing OCI START: "
                    f"{type(exc).__name__}: {exc}"
                )
                logger.error(msg)
                errors.append(msg)
                start_failed.append(instance_id)
                continue
        try:
            actuator.start_instance(instance_id)
        except subprocess.SubprocessError as exc:
            if not _reconcile_ambiguous_action(
                actuator,
                instance_id,
                desired_state="RUNNING",
            ):
                msg = f"{instance_id}: START outcome unknown after {type(exc).__name__}: {exc}"
                errors.append(msg)
                start_failed.append(instance_id)
                continue
            actuated.append((action, instance_id))
        except Exception as exc:  # noqa: BLE001 - isolate per-instance (rg-007)
            msg = f"{instance_id}: {type(exc).__name__}: {exc}"
            logger.error("START failed: %s", msg)
            errors.append(msg)
            start_failed.append(instance_id)
            continue
        else:
            actuated.append((action, instance_id))
        if running_since_store is not None:
            if dry_run:
                logger.info(
                    "dry-run would record RUNNING lease instance=%s source=start_actuator",
                    instance_id,
                )
                continue
            try:
                if use_write_ahead_start and prepared:
                    record = commit_start(
                        instance_id,
                        honoured_nonce=(
                            effective_intent.nonce
                            if effective_intent.action is IntentAction.START
                            else None
                        ),
                    )
                elif effective_intent.action is IntentAction.START:
                    # Compatibility path for injected stores from older callers.
                    record = running_since_store.record_start(
                        instance_id,
                        honoured_nonce=effective_intent.nonce,
                    )
                else:
                    # Keep the legacy call shape for custom lease-store fakes.
                    record = running_since_store.record_start(instance_id)
            except (OSError, ValueError) as exc:
                msg = (
                    f"{instance_id}: START issued but durable lease commit failed; pending authority retained: "
                    f"{type(exc).__name__}: {exc}"
                )
                logger.error(msg)
                errors.append(msg)
            else:
                logger.info(
                    "recorded RUNNING lease instance=%s source=%s since=%s",
                    instance_id,
                    record.source,
                    record.since.isoformat(),
                )

    wait_result: ReadinessWaitResult | None = None
    fallbacks: list[FallbackDecision] = list(
        controller.fallback_on_boot_failure(start_failed, reason="start_failed") if start_failed else ()
    )
    wait_ids = list(
        dict.fromkeys(
            [
                *(instance_id for _, instance_id in actuated),
                *waiting_ids,
                *running_ids,
            ]
        )
    )
    if probe is not None and readiness_wait is not None and wait_ids:
        wait_result = readiness_wait.wait(wait_ids, probe)
        if wait_result.errors:
            errors.extend(wait_result.errors)
        if wait_result.failed:
            fallbacks.extend(
                controller.fallback_on_boot_failure(list(wait_result.timed_out), reason="readiness_timeout")
                + controller.fallback_on_boot_failure(list(wait_result.stalled), reason="readiness_stall")
            )
    intent_status = effective_intent.status
    if intent_status is IntentStatus.NONE and effective_intent.action is not IntentAction.AUTO:
        intent_status = IntentStatus.PENDING
    honoured_nonce = effective_intent.nonce if honoured_ids else None
    last_transition_reason = LastTransitionReason.UNKNOWN
    if actuated:
        honoured_nonce = effective_intent.nonce if effective_intent.action is IntentAction.START else honoured_nonce
        intent_status = IntentStatus.HONOURED if effective_intent.action is IntentAction.START else intent_status
        last_transition_reason = (
            LastTransitionReason.OPERATOR
            if effective_intent.action is IntentAction.START
            else LastTransitionReason.WORK
        )
    if start_failed:
        last_transition_reason = LastTransitionReason.START_FAILED
    return StartCycleResult(
        decided=decided,
        actuated=actuated,
        errors=errors,
        wait_result=wait_result,
        fallbacks=tuple(fallbacks),
        intent=effective_intent,
        intent_status=intent_status,
        honoured_nonce=honoured_nonce,
        last_transition_reason=last_transition_reason,
    )


def run_start_cycle(
    *,
    controller: GpuLifecycleController,
    instances: list[GpuInstance],
    load_source: JobLoadSource,
    actuator: InstanceStartActuator,
    probe: InstanceReadinessProbe | None = None,
    readiness_wait: WarmReadinessWait | None = None,
    running_since_store: RunningSinceLeaseStore | None = None,
    max_lease_seconds: int = 0,
    dry_run: bool = False,
    gpu_state_path: str | Path | None = None,
    intent_dir: str | Path | None = None,
    intent: EffectiveIntent | IntentAction | str | None = None,
    now: datetime | float | int | None = None,
    durable_state_dir: str | Path | None = None,
    durable_intent_dir: str | Path | None = None,
    authority_store: IntentAuthorityStore | None = None,
    deferred_stop_store: DeferredStopStore | None = None,
    decision_log_store: DecisionLogStore | None = None,
) -> StartCycleResult:
    """Serialize observe/decide/actuate/publish as one lifecycle transition."""
    resolved_durable_dir, resolved_authority, resolved_deferred, resolved_log = _intent_stores(
        intent_dir=intent_dir,
        durable_intent_dir=durable_intent_dir,
        durable_state_dir=durable_state_dir,
        authority_store=authority_store,
        deferred_stop_store=deferred_stop_store,
        decision_log_store=decision_log_store,
    )
    effective_intent = _resolve_effective_intent(
        intent_dir=intent_dir,
        intent=intent,
        now=now,
        durable_intent_dir=resolved_durable_dir,
        authority_store=resolved_authority,
        deferred_stop_store=resolved_deferred,
        decision_log_store=resolved_log,
    )
    if dry_run:
        result = _run_start_cycle(
            controller=controller,
            instances=instances,
            load_source=load_source,
            actuator=actuator,
            probe=probe,
            readiness_wait=readiness_wait,
            running_since_store=running_since_store,
            dry_run=True,
            effective_intent=effective_intent,
        )
        return _record_decision(result, mode="start", now=now, store=resolved_log)
    with _serialized_gpu_state_publish(gpu_state_path):
        result = _run_start_cycle(
            controller=controller,
            instances=instances,
            load_source=load_source,
            actuator=actuator,
            probe=probe,
            readiness_wait=readiness_wait,
            running_since_store=running_since_store,
            dry_run=False,
            effective_intent=effective_intent,
        )
        result = _record_decision(result, mode="start", now=now, store=resolved_log)
        snapshot_instance_id = _snapshot_instance_id(instances)
        if result.fallbacks:
            state = GpuLifecycleState.DEGRADED
        elif result.wait_result is not None and result.wait_result.ready:
            state = GpuLifecycleState.READY
        elif result.actuated:
            state = GpuLifecycleState.STARTING
        elif result.errors:
            state = GpuLifecycleState.DEGRADED
        else:
            state = state_for_instances(
                [instance.state for instance in instances],
                previous_state=read_previous_gpu_state(
                    gpu_state_path,
                    expected_instance_id=snapshot_instance_id,
                ),
            )
        fallback_reason = result.fallbacks[0].reason if result.fallbacks else None
        instance_running_since, lease_expires_at, persisted_nonce = _lease_snapshot_metadata(
            instances,
            running_since_store,
            max_lease_seconds=max_lease_seconds,
        )
        snapshot_persisted = write_gpu_state_snapshot(
            state,
            instance_id=snapshot_instance_id,
            reason=_state_reason(
                state,
                instances=instances,
                fallback_reason=fallback_reason,
                has_errors=bool(result.errors),
            ),
            path=gpu_state_path,
            intent=result.intent.action,
            intent_expires_at=result.intent.expires_at,
            intent_status=result.intent_status,
            honoured_nonce=result.honoured_nonce or persisted_nonce,
            lease_expires_at=lease_expires_at,
            instance_running_since=instance_running_since,
            last_transition_reason=result.last_transition_reason,
        )
    return replace(
        result,
        snapshot_persisted=snapshot_persisted,
        honoured_nonce=result.honoured_nonce or persisted_nonce,
        instance_running_since=instance_running_since,
        lease_expires_at=lease_expires_at,
    )


def _positive_integer(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise argparse.ArgumentTypeError("must be a positive integer")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ACX GPU idle reaper (STOP actuator)")
    parser.add_argument(
        "--instance-id",
        action="append",
        dest="instance_ids",
        required=True,
        help="OCI instance OCID to consider (exactly one is supported)",
    )
    parser.add_argument(
        "--mode",
        choices=("reap", "start"),
        default="reap",
        help="reap=STOP idle GPUs (default); start=START stopped GPUs when work waits",
    )
    parser.add_argument(
        "--max-lease-seconds",
        type=int,
        default=3600,
        help=(
            "Cost backstop: force STOP of a RUNNING instance this old despite "
            "reported work or an untrustworthy load boundary. Idle STOP still "
            "fails closed when load evidence is untrustworthy. "
            "0 disables (not recommended). Default 3600 (1h)."
        ),
    )
    parser.add_argument(
        "--idle-seconds",
        type=_positive_integer,
        default=300,
        help="Idle threshold before STOP is considered (default 300)",
    )
    parser.add_argument(
        "--instance-idle-for",
        type=int,
        default=None,
        help=(
            "Explicit test override for lease/idle age for all instances "
            "(default: controller-owned --running-since-path)"
        ),
    )
    parser.add_argument(
        "--running-since-path",
        type=Path,
        default=_DEFAULT_RUNNING_SINCE_PATH,
        help=(f"Controller-owned current RUNNING lease record (default: {_DEFAULT_RUNNING_SINCE_PATH})"),
    )
    parser.add_argument(
        "--instance-state",
        default=None,
        help="Override lifecycle state for all instances (default: probe OCI or RUNNING)",
    )
    parser.add_argument(
        "--probe-oci",
        action="store_true",
        help=("Fetch lifecycle state via `oci compute instance get`; lease age always comes from --running-since-path"),
    )
    parser.add_argument(
        "--gpu-state-json",
        type=Path,
        default=None,
        help=(f"GPU state snapshot path (default: ACX_GPU_STATE_PATH or {DEFAULT_GPU_STATE_PATH})"),
    )
    parser.add_argument(
        "--intent-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory containing <environment>/gpu-intent.json files. "
            "The newest unexpired operator intent wins; omitted keeps legacy automatic behavior."
        ),
    )
    load = parser.add_mutually_exclusive_group()
    load.add_argument(
        "--load-dir",
        type=Path,
        help=(
            "Directory containing <environment>/describe-load.json snapshots. "
            "Each JSON contains queue_depth, in_flight, and optional "
            "batch_in_progress. Fresh snapshots are aggregated; stale or invalid "
            "inputs fail closed. Absent batch_in_progress leaves bulk runs unprotected"
        ),
    )
    load.add_argument(
        "--queue-depth",
        type=int,
        default=None,
        help="Static queue depth (tests only; prefer --load-dir in production)",
    )
    parser.add_argument(
        "--in-flight",
        type=int,
        default=None,
        help="Static in-flight count (tests only; prefer --load-dir in production)",
    )
    parser.add_argument(
        "--load-max-age-seconds",
        type=float,
        default=_DEFAULT_LOAD_MAX_AGE_SECONDS,
        help="Freshness age for per-environment load files (default 120)",
    )
    parser.add_argument(
        "--load-stale-grace-seconds",
        type=float,
        default=os.environ.get("ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS", "600"),
        help=(
            "Bounded age through which a stale environment remains busy "
            "(default: ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS or 600)"
        ),
    )
    parser.add_argument(
        "--fence-delay-seconds",
        type=float,
        default=_DEFAULT_FENCE_DELAY_SECONDS,
        help="Grace window between decision and STOP re-sample (default 2.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log STOP commands without calling the OCI CLI",
    )
    parser.add_argument(
        "--oci-bin",
        default=None,
        help="Path to oci CLI binary (default: PATH lookup)",
    )
    parser.add_argument(
        "--oci-auth",
        default=None,
        help="OCI CLI --auth mode (e.g. api_key, instance_principal)",
    )
    parser.add_argument(
        "--oci-timeout-seconds",
        type=int,
        default=_DEFAULT_OCI_TIMEOUT_SECONDS,
        help="Subprocess timeout for OCI CLI calls (default 120; START uses max of this and --max-wait-seconds)",
    )
    parser.add_argument(
        "--max-wait-seconds",
        type=int,
        default=_DEFAULT_MAX_WAIT_SECONDS,
        help="OCI --max-wait-seconds for instance action (default 600); START subprocess timeout is at least this",
    )
    parser.add_argument(
        "--ready-url",
        default=None,
        help=(
            "HTTP health URL polled after START (omit to skip readiness wait). "
            "Include {instance_id} for per-instance URLs; a shared endpoint "
            "refuses multi-id waits"
        ),
    )
    parser.add_argument(
        "--ready-max-cycles",
        type=int,
        default=_DEFAULT_READY_MAX_CYCLES,
        help="Bounded readiness poll cycles (default 30; 30*10s ≈ 5 min boot budget)",
    )
    parser.add_argument(
        "--ready-stall-cycles",
        type=int,
        default=_DEFAULT_READY_STALL_CYCLES,
        help="Consecutive ERROR/exception cycles before stall fail (default 3; NOT_READY does not count)",
    )
    parser.add_argument(
        "--ready-sleep-seconds",
        type=float,
        default=_DEFAULT_READY_SLEEP_SECONDS,
        help="Sleep between readiness polls (default 10s)",
    )
    return parser


def _publish_initial_probe_failure(
    *,
    instance_id: str,
    gpu_state_path: str | Path | None,
) -> bool:
    """Revoke stale positive readiness evidence after an OCI boundary failure."""
    try:
        with _serialized_gpu_state_publish(gpu_state_path):
            return write_gpu_state_snapshot(
                GpuLifecycleState.DEGRADED,
                instance_id=instance_id,
                reason="oci_probe_failed",
                path=gpu_state_path,
            )
    except (OSError, TimeoutError) as exc:
        logger.warning(
            "failed to publish degraded state after OCI probe failure for %s: %s",
            instance_id,
            exc,
        )
        return False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    if len(args.instance_ids) != 1:
        print(
            "error: exactly one --instance-id is supported; run one lifecycle unit per instance",
            file=sys.stderr,
        )
        return 2
    if (
        args.oci_timeout_seconds <= 0
        or args.max_wait_seconds <= 0
        or not math.isfinite(args.fence_delay_seconds)
        or args.fence_delay_seconds < 0
        or not math.isfinite(args.ready_sleep_seconds)
        or args.ready_sleep_seconds < 0
    ):
        print(
            "error: OCI timeouts must be positive and lifecycle delays must be finite and non-negative",
            file=sys.stderr,
        )
        return 2
    try:
        running_since_store = RunningSinceLeaseStore(path=args.running_since_path)
    except BootIdentityUnavailableError as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1
    explicit_idle_override = args.instance_idle_for is not None

    if args.load_dir is not None:
        try:
            load_source: JobLoadSource = AggregateJobLoadSource(
                directory=args.load_dir,
                stale_seconds=args.load_max_age_seconds,
                stale_grace_seconds=args.load_stale_grace_seconds,
            )
        except ValueError as exc:
            print(f"error: invalid load age configuration: {exc}", file=sys.stderr)
            return 2
    else:
        if args.queue_depth is None or args.in_flight is None:
            print(
                "error: provide --load-dir (production) or both --queue-depth and --in-flight (tests only)",
                file=sys.stderr,
            )
            return 2
        if args.fence_delay_seconds <= 0:
            print(
                "warning: static load + zero fence delay makes fencing a no-op",
                file=sys.stderr,
            )
        load_source = StaticJobLoadSource(
            queue_depth=args.queue_depth,
            in_flight=args.in_flight,
        )

    instances: list[GpuInstance] = []
    for instance_id in args.instance_ids:
        state = args.instance_state
        idle_for = args.instance_idle_for
        if args.probe_oci or state is None:
            probed = fetch_instance_idle_seconds(
                instance_id=instance_id,
                oci_bin=args.oci_bin,
                auth=args.oci_auth,
                timeout_seconds=args.oci_timeout_seconds,
            )
            if probed is not None:
                probed_state, probed_idle = probed
                if state is None:
                    state = probed_state
                if idle_for is None:
                    idle_for = probed_idle
            elif args.probe_oci or state is None:
                if not args.dry_run:
                    _publish_initial_probe_failure(
                        instance_id=instance_id,
                        gpu_state_path=args.gpu_state_json,
                    )
                print(
                    f"error: could not probe {instance_id}; pass --instance-state "
                    "or use --probe-oci with a working OCI CLI",
                    file=sys.stderr,
                )
                return 2
        if idle_for is None:
            idle_for = 0
        assert state is not None and idle_for is not None
        instances.append(
            GpuInstance(
                instance_id=instance_id,
                state=state,
                idle_for_seconds=idle_for,
            )
        )

    controller = GpuLifecycleController(idle_seconds=args.idle_seconds)
    if args.mode == "start":
        start_actuator = OciCliStartActuator(
            oci_bin=args.oci_bin,
            dry_run=args.dry_run,
            auth=args.oci_auth,
            timeout_seconds=args.oci_timeout_seconds,
            max_wait_seconds=args.max_wait_seconds,
        )
        readiness_wait = None
        probe = None
        if args.ready_url:
            probe = HttpReadinessProbe(url=args.ready_url)
            readiness_wait = WarmReadinessWait(
                max_cycles=args.ready_max_cycles,
                stall_cycles=args.ready_stall_cycles,
                sleep_seconds=args.ready_sleep_seconds,
            )
        start_result = run_start_cycle(
            controller=controller,
            instances=instances,
            load_source=load_source,
            actuator=start_actuator,
            probe=probe,
            readiness_wait=readiness_wait,
            gpu_state_path=args.gpu_state_json,
            running_since_store=running_since_store,
            max_lease_seconds=args.max_lease_seconds,
            dry_run=args.dry_run,
            intent_dir=args.intent_dir,
        )
        logger.info(
            "start cycle decided=%s actuated=%s errors=%s wait=%s fallbacks=%s",
            start_result.decided,
            start_result.actuated,
            start_result.errors,
            None if start_result.wait_result is None else start_result.wait_result.exit_code,
            start_result.fallbacks,
        )
        return 1 if start_result.errors or not start_result.snapshot_persisted else 0

    actuator = OciCliStopActuator(
        oci_bin=args.oci_bin,
        dry_run=args.dry_run,
        auth=args.oci_auth,
        timeout_seconds=args.oci_timeout_seconds,
    )
    result = run_reap_cycle(
        controller=controller,
        instances=instances,
        load_source=load_source,
        actuator=actuator,
        fence_delay_seconds=args.fence_delay_seconds,
        max_lease_seconds=args.max_lease_seconds,
        gpu_state_path=args.gpu_state_json,
        running_since_store=running_since_store,
        use_recorded_lease_age=not explicit_idle_override,
        dry_run=args.dry_run,
        intent_dir=args.intent_dir,
    )
    logger.info(
        "reap cycle decided=%s actuated=%s fenced_off=%s lease_expired=%s errors=%s",
        result.decided,
        result.actuated,
        result.fenced_off,
        result.lease_expired,
        result.errors,
    )
    return 1 if result.errors or not result.snapshot_persisted else 0


if __name__ == "__main__":
    raise SystemExit(main())
