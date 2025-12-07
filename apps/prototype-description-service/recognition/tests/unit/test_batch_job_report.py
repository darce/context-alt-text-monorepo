"""Tests for BatchJobReport metrics and serialization (Phase 4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from recognition.observability.reports import BatchJobReport


def _report() -> BatchJobReport:
    now = datetime.now(tz=UTC)
    return BatchJobReport(
        job_id="job-1",
        algorithm="graph",
        started_at=now,
        completed_at=now,
        total_identities=0,
        accept_count=0,
        suggest_count=0,
        reject_count=0,
        clusters_created=0,
    )


def test_add_decision_increments_counters() -> None:
    report = _report()

    report.add_decision("accept", similarity=0.9)
    report.add_decision("suggest", similarity=0.7)
    report.add_decision("reject", similarity=None)

    assert report.total_identities == 3
    assert report.accept_count == 1
    assert report.suggest_count == 1
    assert report.reject_count == 1
    assert report.avg_similarity is not None
    assert report.avg_similarity > 0.7


def test_duration_ms_calculation() -> None:
    now = datetime.now(tz=UTC)
    report = BatchJobReport(
        job_id="job-1",
        algorithm="graph",
        started_at=now,
        completed_at=now + timedelta(seconds=1),
        total_identities=0,
        accept_count=0,
        suggest_count=0,
        reject_count=0,
        clusters_created=0,
    )

    assert 900 <= report.duration_ms() <= 1100


def test_success_rate_calculation() -> None:
    report = _report()
    report.total_identities = 4
    report.accept_count = 2

    assert report.success_rate() == 0.5


def test_to_json_serialization_contains_metrics() -> None:
    report = _report()
    report.completed_at = report.started_at + timedelta(seconds=2)
    report.add_decision("accept", similarity=0.8)

    payload = json.loads(report.to_json())

    assert payload["job_id"] == "job-1"
    assert payload["duration_ms"] > 0
    assert payload["success_rate"] > 0
    assert payload["started_at"]
    assert payload["completed_at"]
