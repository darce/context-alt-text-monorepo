"""Host-clock and file-lock primitives shared by the durable lifecycle stores.

Both the running-since lease store and the operator-intent journal need the
same two things: a boot identity that tells them whether a persisted
``time.monotonic()`` origin is still comparable, and a bounded exclusive
flock so a stuck peer cannot pin a systemd unit forever.  They live here
rather than in ``reaper`` so the journal can use them without importing the
module that imports the journal.
"""

from __future__ import annotations

import fcntl
import math
import time
from pathlib import Path

BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
_LOCK_RETRY_SECONDS = 0.05


class BootIdentityUnavailableError(RuntimeError):
    """The host cannot supply the identity that makes a monotonic origin safe."""


def read_host_boot_id(path: Path = BOOT_ID_PATH) -> str:
    """Return this boot's identity, or fail fast.

    A persisted monotonic reading is only comparable within one boot.  A host
    that cannot name its boot must not be allowed to silently fall back to
    wall-clock durations (see ``CorruptRunningSinceLeaseError``).
    """
    try:
        boot_id = path.read_text().strip()
    except OSError as exc:
        raise BootIdentityUnavailableError(
            f"running-since boot identity unavailable: cannot read {path}; supply an explicit boot_id"
        ) from exc
    if not boot_id:
        raise BootIdentityUnavailableError(
            f"running-since boot identity unavailable: {path} is blank; supply an explicit boot_id"
        )
    return boot_id


def acquire_flock_with_timeout(lock_fd: int, *, timeout_seconds: float) -> None:
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
