"""DEFWAVE-2 regression tests for suggestion refresh state handling."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.refresh_service import SuggestionRefreshService
from recognition.domain.representative import ClusterRepresentative
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus


@pytest.mark.asyncio
async def test_refresh_does_not_reevaluate_rejected_cross_space_suggestion() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    identity_id = uuid4()
    pending = AssignmentSuggestion(
        id=str(uuid4()),
        identity_id=str(identity_id),
        cluster_id=cluster_id,
        representative_similarity=0.99,
        member_similarity=0.99,
        status=SuggestionStatus.PENDING,
    )
    rep = ClusterRepresentative(
        id="r-labeled",
        cluster_id=cluster_id,
        identity_id="i-labeled",
        embedding=np.array([1.0, 0.0], dtype=np.float32),
        created_at=datetime.now(tz=UTC),
        embedding_model="space-a",
    )
    model = SimpleNamespace(
        id=identity_id,
        tenant_id=uuid4(),
        media_id="media-1",
        embedding=np.array([1.0, 0.0], dtype=np.float32),
        confidence=0.99,
        bbox_width=10,
        bbox_height=10,
        bbox_x=0,
        bbox_y=0,
        pose_pitch=None,
        pose_yaw=None,
        pose_roll=None,
        image_phash=None,
        sharpness=None,
        embedding_norm=None,
        occlusion_severity=None,
        moved_by_merge_id=None,
        embedding_model="space-b",
    )
    repository = AsyncMock()
    repository.get_by_cluster = AsyncMock(return_value=[pending])

    async def update_status(
        _tenant_id: str,
        suggestion_id: str,
        status: SuggestionStatus,
    ) -> AssignmentSuggestion:
        assert suggestion_id == pending.id
        pending.status = status
        return pending

    repository.update_status = AsyncMock(side_effect=update_status)
    cluster_repository = AsyncMock()
    cluster_repository.get_by_id = AsyncMock(return_value=SimpleNamespace(id=cluster_id))
    cluster_repository.get_all_representatives = AsyncMock(return_value=[rep])
    session = AsyncMock()
    session.get = AsyncMock(return_value=model)
    service = SuggestionRefreshService(
        repository=repository,
        tenant_id=tenant_id,
        cluster_repository=cluster_repository,
        session=session,
        settings=ClusteringSettings(similarity_threshold=0.5, suggestion_floor=0.5),
    )

    assert await service.refresh_for_cluster(cluster_id) == 0
    assert await service.refresh_for_cluster(cluster_id) == 0
    assert repository.get_by_cluster.await_count == 2
    assert pending.status == SuggestionStatus.REJECTED
    repository.update_status.assert_awaited_once_with(
        tenant_id,
        pending.id,
        SuggestionStatus.REJECTED,
    )
    assert session.get.await_count == 1
