"""CVUP1-R3-17: post_merge_retry_matching must stay inside one embedding space."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.assignment import AssignmentDecision, AssignmentOutcome
from recognition.application.orchestration.cluster_merge import post_merge_retry_matching
from recognition.domain.representative import ClusterRepresentative


def _unit(vec: list[float]) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


def _rep(cluster_id: str, model: str | None) -> ClusterRepresentative:
    return ClusterRepresentative(
        id=str(uuid4()),
        cluster_id=cluster_id,
        identity_id=str(uuid4()),
        embedding=_unit([1.0, 0.0]),
        created_at=datetime.now(tz=UTC),
        embedding_model=model,
    )


def _orm_identity(*, tenant_id: str, model: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        media_id="media-1",
        embedding=_unit([1.0, 0.0]),
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
        embedding_model=model,
    )


def _session_with_unclustered(models: list[SimpleNamespace]) -> AsyncMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = models
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


async def _accept(candidate):  # noqa: ANN001
    return AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=["confidence_check"],
        checks_failed=[],
    )


def _harness(*, reps: list[ClusterRepresentative], unclustered: list[SimpleNamespace], tenant_id: str, cluster_id: str):
    persist = AsyncMock()
    evaluate = AsyncMock(side_effect=_accept)
    assignment_writer = SimpleNamespace(
        cluster_repository=SimpleNamespace(get_all_representatives=AsyncMock(return_value=reps)),
        member_repository=SimpleNamespace(get_by_identity_id=AsyncMock(return_value=[])),
        persist_assignment=persist,
    )
    gate = SimpleNamespace(
        settings=SimpleNamespace(similarity_threshold=0.5),
        evaluate=evaluate,
    )
    suggestion_service = SimpleNamespace(
        get_by_cluster=AsyncMock(return_value=[]),
        create=AsyncMock(),
        resolve_for_identity=AsyncMock(),
        update_scores=AsyncMock(),
    )
    return persist, evaluate, assignment_writer, gate, suggestion_service, _session_with_unclustered(unclustered)


@pytest.mark.asyncio
async def test_post_merge_retry_scores_same_space_unclustered() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    persist, evaluate, writer, gate, suggestions, session = _harness(
        reps=[_rep(cluster_id, "space-a")],
        unclustered=[_orm_identity(tenant_id=tenant_id, model="space-a")],
        tenant_id=tenant_id,
        cluster_id=cluster_id,
    )

    await post_merge_retry_matching(
        tenant_id=tenant_id,
        target_cluster_id=cluster_id,
        session=session,
        gate=gate,
        assignment_writer=writer,
        suggestion_service=suggestions,
        max_unclustered=10,
        min_similarity_for_unclustered=0.5,
    )

    evaluate.assert_awaited()
    persist.assert_awaited()


@pytest.mark.asyncio
async def test_post_merge_retry_skips_foreign_space_even_when_cosine_is_high() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    persist, evaluate, writer, gate, suggestions, session = _harness(
        reps=[_rep(cluster_id, "space-a")],
        unclustered=[_orm_identity(tenant_id=tenant_id, model="space-b")],
        tenant_id=tenant_id,
        cluster_id=cluster_id,
    )

    await post_merge_retry_matching(
        tenant_id=tenant_id,
        target_cluster_id=cluster_id,
        session=session,
        gate=gate,
        assignment_writer=writer,
        suggestion_service=suggestions,
        max_unclustered=10,
        min_similarity_for_unclustered=0.5,
    )

    evaluate.assert_not_awaited()
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_merge_retry_unstamped_gallery_matches_unstamped_probe() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    persist, evaluate, writer, gate, suggestions, session = _harness(
        reps=[_rep(cluster_id, None)],
        unclustered=[_orm_identity(tenant_id=tenant_id, model=None)],
        tenant_id=tenant_id,
        cluster_id=cluster_id,
    )

    await post_merge_retry_matching(
        tenant_id=tenant_id,
        target_cluster_id=cluster_id,
        session=session,
        gate=gate,
        assignment_writer=writer,
        suggestion_service=suggestions,
        max_unclustered=10,
        min_similarity_for_unclustered=0.5,
    )

    evaluate.assert_awaited()
    persist.assert_awaited()
