"""Tests for clustering structured logging utilities."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

import pytest

from recognition.application.clustering.clustering_logger import (
    ClusteringEvent,
    ClusteringLogEntry,
    get_complete_link_stats,
    log_algorithm_selected,
    log_batch_complete,
    log_batch_start,
    log_cluster_created,
    log_cluster_merged,
    log_complete_link_check,
    log_rep_match,
    log_threshold_adjusted,
    log_validation_result,
    reset_complete_link_stats,
)


class TestClusteringLogEntry:
    """Tests for ClusteringLogEntry dataclass."""

    def test_to_dict_excludes_none_values(self) -> None:
        """None values should be excluded from dict output."""
        entry = ClusteringLogEntry(
            event=ClusteringEvent.BATCH_START,
            tenant_id=uuid4(),
            batch_size=100,
        )

        data = entry.to_dict()

        assert "batch_size" in data
        assert "cluster_id" not in data  # None should be excluded
        assert "similarity" not in data

    def test_to_dict_converts_uuids_to_strings(self) -> None:
        """UUIDs should be converted to strings."""
        tenant_id = uuid4()
        identity_id = uuid4()

        entry = ClusteringLogEntry(
            event=ClusteringEvent.REP_MATCH_ACCEPT,
            tenant_id=tenant_id,
            identity_id=identity_id,
        )

        data = entry.to_dict()

        assert data["tenant_id"] == str(tenant_id)
        assert data["identity_id"] == str(identity_id)

    def test_to_dict_converts_datetime_to_isoformat(self) -> None:
        """Datetime should be converted to ISO format string."""
        ts = datetime(2025, 1, 15, 10, 30, 45)
        entry = ClusteringLogEntry(
            event=ClusteringEvent.BATCH_START,
            tenant_id=uuid4(),
            timestamp=ts,
        )

        data = entry.to_dict()

        assert data["timestamp"] == "2025-01-15T10:30:45"

    def test_to_dict_converts_event_to_value(self) -> None:
        """Event enum should be converted to string value."""
        entry = ClusteringLogEntry(
            event=ClusteringEvent.CLUSTER_CREATED,
            tenant_id=uuid4(),
        )

        data = entry.to_dict()

        assert data["event"] == "cluster_created"

    def test_timestamp_auto_populated(self) -> None:
        """Timestamp should be auto-populated if not provided."""
        before = datetime.utcnow()
        entry = ClusteringLogEntry(
            event=ClusteringEvent.BATCH_START,
            tenant_id=uuid4(),
        )
        after = datetime.utcnow()

        assert before <= entry.timestamp <= after

    def test_extra_fields_included(self) -> None:
        """Extra dict fields should be included in output."""
        entry = ClusteringLogEntry(
            event=ClusteringEvent.CLUSTER_MERGED,
            tenant_id=uuid4(),
            extra={"source_cluster_id": "abc123", "moved_count": 5},
        )

        data = entry.to_dict()

        assert data["extra"]["source_cluster_id"] == "abc123"
        assert data["extra"]["moved_count"] == 5


class TestClusteringLogEntryLog:
    """Tests for ClusteringLogEntry.log() method."""

    def test_log_emits_structured_message(self, caplog) -> None:
        """Log should emit structured message with event name."""
        tenant_id = uuid4()

        with caplog.at_level(logging.INFO):
            ClusteringLogEntry(
                event=ClusteringEvent.BATCH_START,
                tenant_id=tenant_id,
                batch_size=100,
                cluster_count=25,
            ).log()

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "clustering_batch_start" in record.message
        assert str(tenant_id) in record.message
        assert "batch_size=100" in record.message
        assert "cluster_count=25" in record.message


class TestLogHelperFunctions:
    """Tests for convenience logging functions."""

    def test_log_batch_start(self, caplog) -> None:
        """log_batch_start should emit BATCH_START event."""
        tenant_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_batch_start(
                tenant_id=tenant_id,
                batch_size=50,
                existing_clusters=10,
                algorithm="incremental",
            )

        assert "clustering_batch_start" in caplog.text
        assert "batch_size=50" in caplog.text
        assert "cluster_count=10" in caplog.text

    def test_log_batch_complete(self, caplog) -> None:
        """log_batch_complete should emit BATCH_COMPLETE event."""
        tenant_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_batch_complete(
                tenant_id=tenant_id,
                batch_size=50,
                assigned_count=35,
                created_count=15,
                singleton_count=8,
                duration_ms=150.5,
            )

        assert "clustering_batch_complete" in caplog.text
        assert "assigned_count=35" in caplog.text
        assert "created_count=15" in caplog.text
        assert "singleton_count=8" in caplog.text
        assert "duration_ms=150.5" in caplog.text

    def test_log_rep_match_accept(self, caplog) -> None:
        """log_rep_match should emit REP_MATCH_ACCEPT when accepted."""
        tenant_id = uuid4()
        identity_id = uuid4()
        cluster_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_rep_match(
                tenant_id=tenant_id,
                identity_id=identity_id,
                cluster_id=cluster_id,
                similarity=0.75,
                threshold=0.65,
                accepted=True,
            )

        assert "rep_match_accept" in caplog.text
        assert "similarity=0.75" in caplog.text

    def test_log_rep_match_reject(self, caplog) -> None:
        """log_rep_match should emit REP_MATCH_REJECT when rejected."""
        tenant_id = uuid4()
        identity_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_rep_match(
                tenant_id=tenant_id,
                identity_id=identity_id,
                cluster_id=None,
                similarity=0.55,
                threshold=0.65,
                accepted=False,
            )

        assert "rep_match_reject" in caplog.text

    def test_log_rep_match_borderline(self, caplog) -> None:
        """log_rep_match should emit REP_MATCH_BORDERLINE when borderline."""
        tenant_id = uuid4()
        identity_id = uuid4()
        cluster_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_rep_match(
                tenant_id=tenant_id,
                identity_id=identity_id,
                cluster_id=cluster_id,
                similarity=0.67,
                threshold=0.65,
                accepted=True,
                is_borderline=True,
            )

        assert "rep_match_borderline" in caplog.text

    def test_log_threshold_adjusted(self, caplog) -> None:
        """log_threshold_adjusted should include confidence weighting details."""
        tenant_id = uuid4()
        identity_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_threshold_adjusted(
                tenant_id=tenant_id,
                identity_id=identity_id,
                base_threshold=0.65,
                effective_threshold=0.58,
                confidence=0.92,
                det_score=0.95,
                bbox_area=40000,
            )

        assert "threshold_adjusted" in caplog.text
        assert "threshold=0.65" in caplog.text
        assert "effective_threshold=0.58" in caplog.text
        assert "confidence=0.92" in caplog.text
        assert "det_score=0.95" in caplog.text
        assert "bbox_area=40000" in caplog.text

    def test_log_complete_link_check(self, caplog) -> None:
        """log_complete_link_check should emit COMPLETE_LINK_CHECK event with details."""
        tenant_id = uuid4()
        identity_id = uuid4()
        cluster_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_complete_link_check(
                tenant_id=tenant_id,
                identity_id=identity_id,
                cluster_id=cluster_id,
                min_similarity=0.74,
                avg_similarity=0.81,
                passed=False,
                num_reps=3,
            )

        assert "complete_link_check" in caplog.text
        assert "min_similarity=0.74" in caplog.text
        assert "avg_similarity=0.81" in caplog.text
        assert "num_representatives=3" in caplog.text
        assert "passed=False" in caplog.text

    def test_complete_link_stats_accumulate(self) -> None:
        """Complete-link stats should track pass/fail counts and samples."""
        reset_complete_link_stats()

        log_complete_link_check(
            tenant_id=uuid4(),
            identity_id=uuid4(),
            cluster_id=uuid4(),
            min_similarity=0.70,
            avg_similarity=0.80,
            passed=False,
            num_reps=4,
        )

        log_complete_link_check(
            tenant_id=uuid4(),
            identity_id=uuid4(),
            cluster_id=uuid4(),
            min_similarity=0.90,
            avg_similarity=0.93,
            passed=True,
            num_reps=5,
        )

        stats = get_complete_link_stats()
        assert stats["checks"] == 2
        assert stats["passes"] == 1
        assert stats["fails"] == 1
        assert stats["min_samples"] == [0.70, 0.90]
        assert stats["avg_samples"] == [0.80, 0.93]

    def test_log_validation_result_pass(self, caplog) -> None:
        """log_validation_result should emit correct event for pass."""
        tenant_id = uuid4()
        identity_id = uuid4()
        cluster_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_validation_result(
                tenant_id=tenant_id,
                identity_id=identity_id,
                cluster_id=cluster_id,
                validation_type="member",
                passed=True,
                similarity=0.72,
                threshold=0.68,
            )

        assert "member_validation_pass" in caplog.text

    def test_log_validation_result_fail(self, caplog) -> None:
        """log_validation_result should emit correct event for fail."""
        tenant_id = uuid4()
        identity_id = uuid4()
        cluster_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_validation_result(
                tenant_id=tenant_id,
                identity_id=identity_id,
                cluster_id=cluster_id,
                validation_type="borderline",
                passed=False,
                similarity=0.58,
                threshold=0.60,
            )

        assert "borderline_validation_fail" in caplog.text

    def test_log_cluster_created(self, caplog) -> None:
        """log_cluster_created should emit CLUSTER_CREATED event."""
        tenant_id = uuid4()
        cluster_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_cluster_created(
                tenant_id=tenant_id,
                cluster_id=cluster_id,
                member_count=1,
            )

        assert "cluster_created" in caplog.text
        assert str(cluster_id) in caplog.text

    def test_log_cluster_merged(self, caplog) -> None:
        """log_cluster_merged should emit CLUSTER_MERGED event."""
        tenant_id = uuid4()
        source_id = uuid4()
        target_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_cluster_merged(
                tenant_id=tenant_id,
                source_cluster_id=source_id,
                target_cluster_id=target_id,
                moved_count=5,
                similarity=0.85,
            )

        assert "cluster_merged" in caplog.text
        assert "moved_count=5" in caplog.text
        assert "similarity=0.85" in caplog.text

    def test_log_algorithm_selected(self, caplog) -> None:
        """log_algorithm_selected should emit ALGORITHM_SELECTED event."""
        tenant_id = uuid4()

        with caplog.at_level(logging.INFO):
            log_algorithm_selected(
                tenant_id=tenant_id,
                algorithm="hdbscan",
                batch_size=500,
                reason="batch_size_threshold",
            )

        assert "algorithm_selected" in caplog.text
        assert "algorithm=hdbscan" in caplog.text
        assert "batch_size=500" in caplog.text
        assert "reason=batch_size_threshold" in caplog.text
