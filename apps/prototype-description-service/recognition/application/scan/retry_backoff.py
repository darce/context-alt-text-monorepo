"""Attempt-based retry backoff for scan queue items.

Pure helpers so workers, repositories, and tests share one formula.
"""

from __future__ import annotations

import math
from datetime import timedelta

# Match the process-level crash backoff shape in scan_worker._main (2s base, 60s cap).
DEFAULT_RETRY_BACKOFF_BASE_SECONDS = 2.0
DEFAULT_RETRY_BACKOFF_MAX_SECONDS = 60.0

# Hard ceiling on the growth exponent so pathological attempt counts cannot
# OverflowError inside ``2 ** exp`` (Python int pow is fine; the float
# conversion of a huge int is not). 2**10 * base(2) already exceeds the 60s cap.
_MAX_BACKOFF_EXPONENT = 30


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

    The exponent is clamped **before** exponentiation so huge ``attempts``
    values (e.g. 1100) never raise OverflowError; once the uncapped delay
    would exceed ``max_seconds`` the result is simply the cap.
    """
    if base_seconds < 0:
        raise ValueError("base_seconds must be >= 0")
    if max_seconds < 0:
        raise ValueError("max_seconds must be >= 0")
    n = max(1, int(attempts))
    if base_seconds == 0 or max_seconds == 0:
        return timedelta(seconds=0)

    # Pre-pow clamp: once base * 2^exp >= max_seconds further growth is irrelevant.
    # ceil(log2(max/base)) is the first exponent that reaches the cap.
    ratio = max_seconds / base_seconds
    if ratio <= 1:
        return timedelta(seconds=max_seconds)
    max_useful_exp = min(_MAX_BACKOFF_EXPONENT, max(0, math.ceil(math.log2(ratio))))
    exp = min(n - 1, max_useful_exp)
    seconds = min(base_seconds * (2**exp), max_seconds)
    return timedelta(seconds=seconds)
