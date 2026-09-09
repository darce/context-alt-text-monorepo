"""CVUP1-R3-17: post_merge_retry_matching must stay inside one embedding space."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.assignment import AssignmentDecision, AssignmentOutcome
from recognition.application.identity_mapping import media_identity_from_model
from recognition.application.orchestration.cluster_merge import post_merge_retry_matching
from recognition.domain.representative import ClusterRepresentative
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus


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
        cluster_repository=SimpleNamespace(
            get_all_representatives=AsyncMock(return_value=reps),
            get_unclustered_in_embedding_space=AsyncMock(
                return_value=[media_identity_from_model(model) for model in unclustered]
            ),
        ),
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
async def test_post_merge_retry_rejects_pending_foreign_space_suggestion() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    identity_id = str(uuid4())
    suggestion = AssignmentSuggestion(
        id=str(uuid4()),
        identity_id=identity_id,
        cluster_id=cluster_id,
        representative_similarity=0.99,
        member_similarity=0.99,
        status=SuggestionStatus.PENDING,
    )
    model = _orm_identity(tenant_id=tenant_id, model="space-b")
    model.id = uuid4()
    model.id = identity_id
    persist, evaluate, writer, gate, suggestions, session = _harness(
        reps=[_rep(cluster_id, "space-a")],
        unclustered=[],
        tenant_id=tenant_id,
        cluster_id=cluster_id,
    )
    suggestions.get_by_cluster = AsyncMock(return_value=[suggestion])
    session.get = AsyncMock(return_value=model)

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

    suggestions.resolve_for_identity.assert_awaited_once_with(
        identity_id,
        cluster_id,
        resolution="rejected",
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


def _compiled_sql(stmt: object) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()


@pytest.mark.asyncio
async def test_post_merge_retry_unstamped_gallery_does_not_starve_on_mixed_batch() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    unstamped = _orm_identity(tenant_id=tenant_id, model=None)
    persist, evaluate, writer, gate, suggestions, session = _harness(
        reps=[_rep(cluster_id, None)],
        unclustered=[],
        tenant_id=tenant_id,
        cluster_id=cluster_id,
    )
    writer.cluster_repository.get_unclustered_in_embedding_space = AsyncMock(
        return_value=[media_identity_from_model(unstamped)]
    )

    await post_merge_retry_matching(
        tenant_id=tenant_id,
        target_cluster_id=cluster_id,
        session=session,
        gate=gate,
        assignment_writer=writer,
        suggestion_service=suggestions,
        max_unclustered=2,
        min_similarity_for_unclustered=0.5,
    )

    writer.cluster_repository.get_unclustered_in_embedding_space.assert_awaited_once_with(
        tenant_id,
        None,
        limit=2,
    )
    evaluate.assert_awaited()
    persist.assert_awaited()


@pytest.mark.asyncio
async def test_get_unclustered_in_embedding_space_sql_is_null_for_legacy_gallery() -> None:
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    repo = SqlAlchemyClusterRepository(session)

    await repo.get_unclustered_in_embedding_space(str(uuid4()), None, limit=2)

    stmt = session.execute.await_args.args[0]
    sql = _compiled_sql(stmt)
    assert "embedding_model is null" in sql
    assert "identity_member" in sql


@pytest.mark.asyncio
async def test_get_unclustered_in_embedding_space_sql_equals_gallery_model() -> None:
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    repo = SqlAlchemyClusterRepository(session)

    await repo.get_unclustered_in_embedding_space(str(uuid4()), "space-a", limit=10)

    stmt = session.execute.await_args.args[0]
    sql = _compiled_sql(stmt)
    assert "embedding_model" in sql
    assert "is null" not in sql
    assert "space-a" in sql
