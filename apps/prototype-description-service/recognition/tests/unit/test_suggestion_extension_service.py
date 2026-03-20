"""Unit tests for the Phase 5 suggestion extension domain scaffold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from recognition.domain.services.suggestion_extension_service import SuggestionExtensionService
from recognition.domain.suggestion import (
    AssignmentSuggestion,
    BulkAcceptResult,
    MergeSuggestion,
    NameSuggestion,
    SuggestedLabelSource,
    SuggestionStatus,
)


def test_extended_assignment_and_merge_suggestions_expose_phase5_metadata() -> None:
    created_at = datetime.now(tz=UTC)
    expires_at = created_at + timedelta(days=7)

    assignment = AssignmentSuggestion(
        id="assignment-1",
        identity_id="identity-1",
        cluster_id="cluster-1",
        representative_similarity=0.91,
        member_similarity=0.87,
        status=SuggestionStatus.PENDING,
        confidence_score=0.9,
        expires_at=expires_at,
        source_job_id="job-1",
        created_at=created_at,
        source="identity",
    )
    merge = MergeSuggestion(
        id="merge-1",
        cluster_a_id="cluster-a",
        cluster_b_id="cluster-b",
        similarity=0.74,
        status=SuggestionStatus.PENDING,
        confidence_score=0.71,
        expires_at=expires_at,
        source_job_id="job-2",
        created_at=created_at,
        source="cluster_merge",
    )

    assert assignment.confidence_score == pytest.approx(0.9)
    assert assignment.expires_at == expires_at
    assert assignment.source_job_id == "job-1"
    assert merge.confidence_score == pytest.approx(0.71)
    assert merge.expires_at == expires_at
    assert merge.source_job_id == "job-2"


def test_name_suggestion_and_bulk_accept_result_capture_phase5_contract() -> None:
    created_at = datetime.now(tz=UTC)
    suggestion = NameSuggestion(
        id="name-1",
        cluster_id="cluster-1",
        suggested_name="Daniel",
        confidence_score=0.91,
        source=SuggestedLabelSource.IDENTITY,
        status=SuggestionStatus.PENDING,
        created_at=created_at,
        source_job_id="job-1",
    )
    result = BulkAcceptResult(accepted_count=12, skipped_count=3)

    assert suggestion.suggested_name == "Daniel"
    assert suggestion.source is SuggestedLabelSource.IDENTITY
    assert result.accepted_count == 12
    assert result.skipped_count == 3


@pytest.mark.asyncio
async def test_suggestion_extension_service_methods_remain_explicit_stubs() -> None:
    service = SuggestionExtensionService()

    with pytest.raises(NotImplementedError):
        await service.list_name_suggestions("tenant-1")
    with pytest.raises(NotImplementedError):
        await service.accept_name_suggestion("tenant-1", "suggestion-1")
    with pytest.raises(NotImplementedError):
        await service.reject_name_suggestion("tenant-1", "suggestion-1")
    with pytest.raises(NotImplementedError):
        await service.bulk_accept("tenant-1", suggestion_type="name", min_confidence=0.8)
    with pytest.raises(NotImplementedError):
        await service.expire_stale("tenant-1")
