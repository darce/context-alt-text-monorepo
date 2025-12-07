"""Tests for ClusteringLogger behavior."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, cast

from recognition.observability import ClusteringLogger, DecisionType
from recognition.observability.reports import BatchJobReport
from recognition.shared.ids import generate_id


class MemoryHandler(logging.Handler):
    """Simple logging handler to capture records."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - simple append
        self.records.append(record)


def test_log_decision_returns_decision_log() -> None:
    handler = MemoryHandler()
    logger = logging.getLogger("test_clustering_logger_decision")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    clustering_logger = ClusteringLogger(logger=logger)

    identity_id = str(generate_id())
    cluster_id = str(generate_id())
    result = clustering_logger.log_decision(
        identity_id=identity_id,
        cluster_id=cluster_id,
        decision=DecisionType.ACCEPT,
        similarity=0.9,
        reason=None,
        metadata={"min_similarity": 0.8},
        timestamp=datetime(2025, 1, 1),
    )

    assert result.identity_id == identity_id
    assert result.cluster_id == cluster_id
    assert result.decision is DecisionType.ACCEPT
    assert handler.records
    record = handler.records[0]
    data = record.__dict__
    assert data["decision"] == "accept"
    assert data["identity_id"] == str(identity_id)


def test_log_batch_complete_includes_report_fields() -> None:
    handler = MemoryHandler()
    logger = logging.getLogger("test_clustering_logger_batch")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    clustering_logger = ClusteringLogger(logger=logger)

    report = BatchJobReport(
        job_id=str(generate_id()),
        algorithm="representative",
        started_at=datetime(2025, 1, 1, 0, 0, 0),
        completed_at=datetime(2025, 1, 1, 0, 0, 1),
        total_identities=10,
        accept_count=7,
        suggest_count=2,
        reject_count=1,
        clusters_created=1,
        avg_similarity=0.85,
    )

    clustering_logger.log_batch_complete(report)

    assert handler.records
    record = handler.records[0]
    data = record.__dict__
    assert data["job_id"] == str(report.job_id)
    assert data["duration_ms"] == report.duration_ms()
    assert data["success_rate"] == report.success_rate()
