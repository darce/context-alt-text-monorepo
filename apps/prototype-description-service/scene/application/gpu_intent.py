"""Single-writer operator intent persistence for the burst GPU (GPUOPS-1 C1)."""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import math
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from scene.application.describe_load import resolve_load_path

_logger = logging.getLogger(__name__)

GPU_INTENT_PATH_ENV = "ACX_GPU_INTENT_PATH"
GPU_INTENT_DURABLE_PATH_ENV = "ACX_GPU_INTENT_DURABLE_PATH"
DEFAULT_GPU_INTENT_FILENAME = "gpu-intent.json"
DEFAULT_INTENT_TTL_SECONDS = 1800
MIN_INTENT_TTL_SECONDS = 60
MAX_INTENT_TTL_SECONDS = 7200
INTENT_SCHEMA_VERSION = 1
INTENT_FILE_MODE = 0o660
DEFAULT_GPU_INTENT_DURABLE_DIR = Path("/var/lib/acx-gpu/intents")
RUNTIME_GPU_INTENT_DIR = Path("/run/acx-write")
GPU_INTENT_LOCK_TIMEOUT_SECONDS = 5.0
GPU_INTENT_LOCK_RETRY_SECONDS = 0.01

_GPU_INTENT_WRITE_LOCK = threading.Lock()


class IntentAction(StrEnum):
    """Operator-requested burst-GPU lifecycle mode."""

    START = "start"
    STOP = "stop"
    AUTO = "auto"


@dataclass(frozen=True)
class OperatorIntent:
    """Validated operator intent as represented in the C1 file."""

    schema_version: int
    sequence: int
    action: IntentAction
    requested_at: datetime
    expires_at: datetime
    ttl_seconds: int
    requested_by: str
    nonce: str

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON representation used by the atomic writer."""
        return {
            "schema_version": self.schema_version,
            "action": self.action.value,
            "requested_at": _format_timestamp(self.requested_at),
            "expires_at": _format_timestamp(self.expires_at),
            "ttl_seconds": self.ttl_seconds,
            "requested_by": self.requested_by,
            "nonce": self.nonce,
            "sequence": self.sequence,
        }


def resolve_gpu_intent_path() -> str:
    """Resolve the intent path, defaulting beside the configured load file."""
    configured_path = os.environ.get(GPU_INTENT_PATH_ENV)
    if configured_path is not None and configured_path.strip():
        return configured_path
    return str(Path(resolve_load_path()).with_name(DEFAULT_GPU_INTENT_FILENAME))


def resolve_gpu_intent_durable_path(path: str | Path) -> Path:
    """Resolve the durable publication path corresponding to ``path``.

    The API normally publishes into the per-environment ``/run/acx-write``
    mount.  That mount is a runtime cache, so mirror those publications into
    the lifecycle state directory before reporting success.  A path that is
    already outside the runtime mount is treated as its own durable target;
    this keeps local/test deployments and explicitly provisioned persistent
    paths useful without a second copy.
    """
    configured_path = os.environ.get(GPU_INTENT_DURABLE_PATH_ENV)
    if configured_path is not None and configured_path.strip():
        return Path(configured_path)

    target = Path(path)
    try:
        relative = target.relative_to(RUNTIME_GPU_INTENT_DIR)
    except ValueError:
        return target
    return DEFAULT_GPU_INTENT_DURABLE_DIR / relative


def write_gpu_intent(
    path: str | Path,
    *,
    action: IntentAction | str,
    ttl_seconds: int | None = None,
    requested_by: str | None = None,
    now: datetime | int | float | None = None,
    durable_path: str | Path | None = None,
) -> OperatorIntent:
    """Publish one operator intent under the lifecycle fence.

    The lock file is persistent so the lifecycle reader can coordinate with
    the service across processes. A unique temporary file in the destination
    directory plus ``os.replace`` keeps readers from observing a partial JSON
    document.
    """
    target = Path(path)
    durable_target = Path(durable_path) if durable_path is not None else resolve_gpu_intent_durable_path(target)
    requested_at = _coerce_datetime(now)
    ttl = _clamp_ttl(ttl_seconds)
    coerced_action = _coerce_action(action)
    coerced_requested_by = _coerce_requested_by(requested_by)
    target.parent.mkdir(parents=True, exist_ok=True)

    with _GPU_INTENT_WRITE_LOCK:
        lock_fd = _open_gpu_intent_fence(target)
        locked = False
        try:
            _acquire_gpu_intent_lock(lock_fd, target)
            locked = True
            sequence = _allocate_sequence(target, durable_target)
            intent = OperatorIntent(
                schema_version=INTENT_SCHEMA_VERSION,
                sequence=sequence,
                action=coerced_action,
                requested_at=requested_at,
                expires_at=requested_at + timedelta(seconds=ttl),
                ttl_seconds=ttl,
                requested_by=coerced_requested_by,
                nonce=str(uuid.uuid4()),
            )
            payload = json.dumps(intent.to_payload(), separators=(",", ":"))
            # Write the durable copy first.  The runtime publication is a
            # cache used by the lifecycle path watcher; the durable copy is
            # the write-ahead record that makes an accepted intent survive a
            # restart or power loss.
            _publish_atomic_json(durable_target, payload)
            if durable_target != target:
                _publish_atomic_json(target, payload)
        finally:
            if locked:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)
            else:
                os.close(lock_fd)
    return intent


def _acquire_gpu_intent_lock(lock_fd: int, target: Path) -> None:
    """Acquire the lifecycle fence without blocking forever in ``flock``."""
    deadline = time.monotonic() + _gpu_intent_lock_timeout_seconds()
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for GPU intent lock: {target}") from None
            time.sleep(min(GPU_INTENT_LOCK_RETRY_SECONDS, remaining))


def _gpu_intent_lock_timeout_seconds() -> float:
    raw = os.environ.get("ACX_GPU_INTENT_LOCK_TIMEOUT_SECONDS")
    if raw is None:
        return GPU_INTENT_LOCK_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        _logger.warning(
            "invalid ACX_GPU_INTENT_LOCK_TIMEOUT_SECONDS=%r; using %.3fs", raw, GPU_INTENT_LOCK_TIMEOUT_SECONDS
        )
        return GPU_INTENT_LOCK_TIMEOUT_SECONDS
    if not math.isfinite(value) or value < 0:
        _logger.warning(
            "invalid ACX_GPU_INTENT_LOCK_TIMEOUT_SECONDS=%r; using %.3fs", raw, GPU_INTENT_LOCK_TIMEOUT_SECONDS
        )
        return GPU_INTENT_LOCK_TIMEOUT_SECONDS
    return min(value, GPU_INTENT_LOCK_TIMEOUT_SECONDS)


def _allocate_sequence(target: Path, durable_target: Path) -> int:
    """Allocate the next sequence from the highest persisted publication."""
    highest = 0
    candidates = (target,) if target == durable_target else (target, durable_target)
    for candidate in candidates:
        highest = max(highest, _read_persisted_sequence(candidate))
    return highest + 1


def _read_persisted_sequence(path: Path) -> int:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0
    except (OSError, UnicodeError) as exc:
        raise OSError(f"could not read persisted GPU intent sequence from {path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise OSError(f"could not allocate GPU intent sequence from {path}: invalid JSON") from exc
    if not isinstance(payload, dict):
        raise OSError(f"could not allocate GPU intent sequence from {path}: payload is not an object")
    sequence = payload.get("sequence")
    if sequence is None:
        # A pre-GPUOPS publication has no sequence.  It cannot be used as
        # authority, but replacing it with the first sequenced publication is
        # safe because the lifecycle reader already treats it as malformed.
        return 0
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise OSError(f"could not allocate GPU intent sequence from {path}: invalid sequence")
    return sequence


def _publish_atomic_json(path: Path, payload: str) -> None:
    """Publish JSON with file and containing-directory durability barriers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    fd = -1
    try:
        fd, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        temporary = Path(temporary_name)
        with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
            fd = -1
            temporary_file.write(payload)
            temporary_file.flush()
            os.fchmod(temporary_file.fileno(), INTENT_FILE_MODE)
            os.fsync(temporary_file.fileno())
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_gpu_intent(path: str | Path) -> OperatorIntent | None:
    """Read and validate an intent, returning ``None`` on malformed input."""
    target = Path(path)
    durable_target = resolve_gpu_intent_durable_path(target)
    candidates = (target,) if target == durable_target else (target, durable_target)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            raw = candidate.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except (OSError, UnicodeDecodeError) as exc:
            last_error = exc
            continue
        try:
            payload = json.loads(raw)
            return _intent_from_payload(payload)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            last_error = exc
            continue
    if last_error is not None:
        _logger.warning("malformed GPU intent path=%s: %s", target, last_error)
    return None


def _open_gpu_intent_fence(target: Path) -> int:
    """Open the persistent lock coordinated with the lifecycle controller."""
    lock_path = target.with_name(f"{target.name}.lock")
    created = False
    try:
        lock_fd = os.open(
            lock_path,
            os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            INTENT_FILE_MODE,
        )
        created = True
    except FileExistsError:
        lock_fd = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC)
    if created:
        try:
            os.fchmod(lock_fd, INTENT_FILE_MODE)
        except BaseException:
            os.close(lock_fd)
            raise
    return lock_fd


def _coerce_action(action: IntentAction | str) -> IntentAction:
    if isinstance(action, IntentAction):
        return action
    try:
        return IntentAction(action)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported GPU intent action: {action!r}") from exc


def _clamp_ttl(ttl_seconds: int | None) -> int:
    if ttl_seconds is None:
        return DEFAULT_INTENT_TTL_SECONDS
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise TypeError("ttl_seconds must be an integer")
    return max(MIN_INTENT_TTL_SECONDS, min(MAX_INTENT_TTL_SECONDS, ttl_seconds))


def _coerce_requested_by(requested_by: str | None) -> str:
    if requested_by is None:
        return "unknown"
    if not isinstance(requested_by, str):
        raise TypeError("requested_by must be a string")
    return requested_by.strip() or "unknown"


def _coerce_datetime(value: datetime | int | float | None) -> datetime:
    if value is None:
        return datetime.now(tz=UTC)
    if isinstance(value, datetime):
        result = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return result.astimezone(UTC)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise TypeError("now must be an aware datetime or finite Unix timestamp")
    return datetime.fromtimestamp(value, tz=UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _intent_from_payload(payload: Any) -> OperatorIntent:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    schema_version = payload["schema_version"]
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != INTENT_SCHEMA_VERSION
    ):
        raise ValueError(f"schema_version must be {INTENT_SCHEMA_VERSION}")
    action = _coerce_action(payload["action"])
    sequence = payload["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("sequence must be an integer >= 1")
    requested_at = _parse_timestamp(payload["requested_at"], field_name="requested_at")
    expires_at = _parse_timestamp(payload["expires_at"], field_name="expires_at")
    ttl_seconds = payload["ttl_seconds"]
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise ValueError("ttl_seconds must be an integer")
    if not MIN_INTENT_TTL_SECONDS <= ttl_seconds <= MAX_INTENT_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be in {MIN_INTENT_TTL_SECONDS}..{MAX_INTENT_TTL_SECONDS}")
    if expires_at != requested_at + timedelta(seconds=ttl_seconds):
        raise ValueError("expires_at must match requested_at + ttl_seconds")
    requested_by = payload["requested_by"]
    if not isinstance(requested_by, str) or not requested_by.strip():
        raise ValueError("requested_by must be a non-empty string")
    nonce = payload["nonce"]
    if not isinstance(nonce, str):
        raise ValueError("nonce must be a UUID4 string")
    try:
        parsed_nonce = uuid.UUID(nonce)
    except ValueError as exc:
        raise ValueError("nonce must be a UUID4 string") from exc
    if parsed_nonce.version != 4:
        raise ValueError("nonce must be a UUID4 string")
    return OperatorIntent(
        schema_version=schema_version,
        sequence=sequence,
        action=action,
        requested_at=requested_at,
        expires_at=expires_at,
        ttl_seconds=ttl_seconds,
        requested_by=requested_by,
        nonce=nonce,
    )


__all__ = [
    "DEFAULT_GPU_INTENT_DURABLE_DIR",
    "DEFAULT_GPU_INTENT_FILENAME",
    "DEFAULT_INTENT_TTL_SECONDS",
    "GPU_INTENT_DURABLE_PATH_ENV",
    "GPU_INTENT_LOCK_RETRY_SECONDS",
    "GPU_INTENT_LOCK_TIMEOUT_SECONDS",
    "GPU_INTENT_PATH_ENV",
    "INTENT_FILE_MODE",
    "IntentAction",
    "MAX_INTENT_TTL_SECONDS",
    "MIN_INTENT_TTL_SECONDS",
    "OperatorIntent",
    "read_gpu_intent",
    "resolve_gpu_intent_durable_path",
    "resolve_gpu_intent_path",
    "write_gpu_intent",
]
