"""Attempt-based retry backoff for scan queue items.

Pure helpers so workers, repositories, and tests share one formula.
"""

from __future__ import annotations

from datetime import timedelta

# Match the process-level crash backoff shape in scan_worker._main (2s base, 60s cap).
DEFAULT_RETRY_BACKOFF_BASE_SECONDS = 2.0
DEFAULT_RETRY_BACKOFF_MAX_SECONDS = 60.0


def compute_retry_backoff(
    attempts: int,
    *,
    base_seconds: float = DEFAULT_RETRY_BACKOFF_BASE_SECONDS,
    max_seconds: float = DEFAULT_RETRY_BACKOFF_MAX_SECONDS,
) -> timedelta:
    """Return delay before a released item may be claimed again.

    ``attempts`` is the post-claim attempt count (already incremented on claim).
    Delay is ``base * 2^(attempts-1)``, capped at ``max_seconds``. Attempts below
    1 are treated as 1 so callers never get a zero or negative delay.
    """
    if base_seconds < 0:
        raise ValueError("base_seconds must be >= 0")
    if max_seconds < 0:
        raise ValueError("max_seconds must be >= 0")
    n = max(1, int(attempts))
    seconds = min(base_seconds * (2 ** (n - 1)), max_seconds)
    return timedelta(seconds=seconds)
