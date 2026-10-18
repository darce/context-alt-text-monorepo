"""Regression tests for concurrent suggestion expiration."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from recognition.application.suggestions.refresh_service import SuggestionRefreshService
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus
from recognition.infrastructure.repositories.suggestion_repository import SqlAlchemySuggestionRepository


@pytest.mark.asyncio
async def test_expiration_does_not_overwrite_concurrent_resolution() -> None:
    tenant_id = str(uuid4())
    suggestion_id = uuid4()
    model = SimpleNamespace(
        id=suggestion_id,
        identity_id=uuid4(),
        suggested_cluster_id=uuid4(),
        representative_similarity=0.9,
        avg_member_similarity=0.8,
        resolution=SuggestionStatus.ACCEPTED.value,
        evidence_generation=0,
        confidence_score=0.9,
        created_at=datetime.now(tz=UTC),
        expires_at=None,
        source_job_id=None,
    )
    statement_result = SimpleNamespace(rowcount=0, scalar_one_or_none=lambda: model)
    executed_statements = []
    session = AsyncMock()

    async def execute(statement):  # noqa: ANN001
        executed_statements.append(statement)
        return statement_result

    session.execute = AsyncMock(side_effect=execute)
    repository = SqlAlchemySuggestionRepository(session)

    updated = await repository.update_status(tenant_id, str(suggestion_id), SuggestionStatus.EXPIRED)

    assert updated.status is SuggestionStatus.ACCEPTED
    assert len(executed_statements) == 2
    compiled = executed_statements[0].compile()
    assert "resolution" in str(compiled).lower()
    assert SuggestionStatus.PENDING.value in compiled.params.values()


@pytest.mark.asyncio
async def test_refresh_only_counts_suggestions_that_were_expired() -> None:
    tenant_id = str(uuid4())
    suggestion_id = str(uuid4())
    suggestion = AssignmentSuggestion(
        id=suggestion_id,
        identity_id=str(uuid4()),
        cluster_id=str(uuid4()),
        representative_similarity=0.9,
        member_similarity=0.8,
        status=SuggestionStatus.PENDING,
    )
    resolved = AssignmentSuggestion(
        id=suggestion_id,
        identity_id=suggestion.identity_id,
        cluster_id=suggestion.cluster_id,
        representative_similarity=suggestion.representative_similarity,
        member_similarity=suggestion.member_similarity,
        status=SuggestionStatus.ACCEPTED,
    )
    repository = AsyncMock()
    repository.update_status = AsyncMock(return_value=resolved)
    service = SuggestionRefreshService(repository=repository, tenant_id=tenant_id)

    expired = await service._expire_already_owned_suggestion(suggestion)

    assert expired is False
    repository.update_status.assert_awaited_once_with(tenant_id, suggestion_id, SuggestionStatus.EXPIRED)
