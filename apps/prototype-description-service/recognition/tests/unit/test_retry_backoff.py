"""Discriminating tests for attempt-based scan retry backoff."""

from __future__ import annotations

from datetime import timedelta

import pytest

from recognition.application.scan.retry_backoff import (
    DEFAULT_RETRY_BACKOFF_BASE_SECONDS,
    DEFAULT_RETRY_BACKOFF_MAX_SECONDS,
    compute_retry_backoff,
)


def test_compute_retry_backoff_grows_with_attempts() -> None:
    first = compute_retry_backoff(1)
    second = compute_retry_backoff(2)
    third = compute_retry_backoff(3)
    assert first == timedelta(seconds=DEFAULT_RETRY_BACKOFF_BASE_SECONDS)
    assert second == timedelta(seconds=DEFAULT_RETRY_BACKOFF_BASE_SECONDS * 2)
    assert third == timedelta(seconds=DEFAULT_RETRY_BACKOFF_BASE_SECONDS * 4)
    assert first < second < third


def test_compute_retry_backoff_caps_at_max() -> None:
    huge = compute_retry_backoff(20)
    assert huge == timedelta(seconds=DEFAULT_RETRY_BACKOFF_MAX_SECONDS)
    # attempts=6: 2 * 2^5 = 64 -> capped to 60
    assert compute_retry_backoff(6) == timedelta(seconds=DEFAULT_RETRY_BACKOFF_MAX_SECONDS)


def test_compute_retry_backoff_treats_non_positive_as_one() -> None:
    assert compute_retry_backoff(0) == compute_retry_backoff(1)
    assert compute_retry_backoff(-3) == compute_retry_backoff(1)


def test_compute_retry_backoff_rejects_negative_knobs() -> None:
    with pytest.raises(ValueError, match="base_seconds"):
        compute_retry_backoff(1, base_seconds=-1)
    with pytest.raises(ValueError, match="max_seconds"):
        compute_retry_backoff(1, max_seconds=-1)
