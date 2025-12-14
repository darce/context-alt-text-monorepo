"""Tests for user curation event logging."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from recognition.observability import ClusteringLogger, CurationEventType
from recognition.shared.ids import generate_id


class MemoryHandler(logging.Handler):
    """Simple logging handler to capture records."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def logger_with_handler() -> tuple[ClusteringLogger, MemoryHandler]:
    """Create a ClusteringLogger with a memory handler for testing."""
    handler = MemoryHandler()
    py_logger = logging.getLogger("test_curation_logging")
    py_logger.handlers = [handler]
    py_logger.setLevel(logging.INFO)
    return ClusteringLogger(logger=py_logger), handler


def test_log_cluster_renamed_records_old_and_new_labels(
    logger_with_handler: tuple[ClusteringLogger, MemoryHandler],
) -> None:
    """Verify rename events include old and new labels."""
    clustering_logger, handler = logger_with_handler
    cluster_id = str(generate_id())
    tenant_id = str(generate_id())

    result = clustering_logger.log_cluster_renamed(
        cluster_id=cluster_id,
        old_label="Alice",
        new_label="Alice Smith",
        tenant_id=tenant_id,
    )

    assert result.event_type is CurationEventType.RENAME
    assert result.cluster_id == cluster_id
    assert result.tenant_id == tenant_id
    assert result.details["old_label"] == "Alice"
    assert result.details["new_label"] == "Alice Smith"

    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.__dict__["event_type"] == "rename"
    assert record.__dict__["old_label"] == "Alice"
    assert record.__dict__["new_label"] == "Alice Smith"


def test_log_cluster_merged_records_source_target_and_count(
    logger_with_handler: tuple[ClusteringLogger, MemoryHandler],
) -> None:
    """Verify merge events include source, target, and moved count."""
    clustering_logger, handler = logger_with_handler
    source_id = str(generate_id())
    target_id = str(generate_id())
    tenant_id = str(generate_id())

    result = clustering_logger.log_cluster_merged(
        source_cluster_id=source_id,
        target_cluster_id=target_id,
        moved_count=15,
        tenant_id=tenant_id,
    )

    assert result.event_type is CurationEventType.MERGE
    assert result.cluster_id == target_id
    assert result.details["source_cluster_id"] == source_id
    assert result.details["target_cluster_id"] == target_id
    assert result.details["moved_count"] == 15

    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.__dict__["event_type"] == "merge"
    assert record.__dict__["moved_count"] == 15


def test_log_cluster_split_records_new_clusters_and_counts(
    logger_with_handler: tuple[ClusteringLogger, MemoryHandler],
) -> None:
    """Verify split events include new cluster IDs and moved counts."""
    clustering_logger, handler = logger_with_handler
    original_id = str(generate_id())
    new_ids = [str(generate_id()), str(generate_id())]
    moved_counts = [8, 12]
    tenant_id = str(generate_id())

    result = clustering_logger.log_cluster_split(
        original_cluster_id=original_id,
        new_cluster_ids=new_ids,
        moved_counts=moved_counts,
        tenant_id=tenant_id,
    )

    assert result.event_type is CurationEventType.SPLIT
    assert result.cluster_id == original_id
    assert result.details["new_cluster_ids"] == new_ids
    assert result.details["moved_counts"] == moved_counts
    assert result.details["total_moved"] == 20

    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.__dict__["event_type"] == "split"
    assert record.__dict__["total_moved"] == 20
