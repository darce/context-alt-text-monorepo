from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from db.models import MediaIdentity as MediaIdentityModel
from db.models import RecognitionEvent
from recognition.application.suggestions.service import SuggestionService
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import SuggestionCreateData
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemySuggestionRepository
from recognition.observability.recognition_runs import create_recognition_run


@pytest.mark.asyncio
async def test_accept_emits_suggestion_resolved_event(db_session, tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Target",
            is_labeled=True,
            identity_count=0,
            created_at=None,
            user_confirmed=True,
        )
    )

    identity_uuid = uuid.uuid4()
    db_session.add(
        MediaIdentityModel(
            id=identity_uuid,
            tenant_id=tenant.id,
            media_id=101,
            media_url="http://example.test/101.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=[0.0] * 512,
        )
    )
    await db_session.commit()

    suggestion_repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))
    suggestion = await suggestion_repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(identity_uuid),
            cluster_id=cluster.id,
            representative_similarity=0.91,
            member_similarity=0.91,
            confidence_score=0.91,
        ),
    )

    run_ctx = await create_recognition_run(db_session, tenant_id=tenant.id, source="test")
    service = SuggestionService(
        suggestion_repo,
        tenant_id=str(tenant.id),
        cluster_repository=cluster_repo,
        session=db_session,
        run_context=run_ctx,
    )

    accepted = await service.accept(suggestion.id)
    assert accepted is not None
    await db_session.commit()

    events = (await db_session.execute(select(RecognitionEvent))).scalars().all()
    resolved = [event for event in events if event.event_type == "suggestion_resolved"]
    assert len(resolved) == 1
    event = resolved[0]
    assert event.identity_id == identity_uuid
    assert event.cluster_id == uuid.UUID(cluster.id)
    assert event.payload.get("resolution") == "accepted"
    assert event.payload.get("outcome_cluster_id") == cluster.id
    assert event.payload.get("suggestion_id") == suggestion.id


@pytest.mark.asyncio
async def test_resolve_for_identity_emits_suggestion_resolved_event(db_session, tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Target",
            is_labeled=True,
            identity_count=0,
            created_at=None,
            user_confirmed=True,
        )
    )

    identity_uuid = uuid.uuid4()
    db_session.add(
        MediaIdentityModel(
            id=identity_uuid,
            tenant_id=tenant.id,
            media_id=102,
            media_url="http://example.test/102.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            confidence=0.99,
            embedding=[0.0] * 512,
        )
    )
    await db_session.commit()

    suggestion_repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))
    suggestion = await suggestion_repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(identity_uuid),
            cluster_id=cluster.id,
            representative_similarity=0.91,
            member_similarity=0.91,
            confidence_score=0.91,
        ),
    )

    run_ctx = await create_recognition_run(db_session, tenant_id=tenant.id, source="test")
    service = SuggestionService(
        suggestion_repo,
        tenant_id=str(tenant.id),
        cluster_repository=cluster_repo,
        session=db_session,
        run_context=run_ctx,
    )

    resolved_count = await service.resolve_for_identity(str(identity_uuid), cluster.id, resolution="accepted")
    assert resolved_count == 1
    await db_session.commit()

    events = (await db_session.execute(select(RecognitionEvent))).scalars().all()
    resolved = [event for event in events if event.event_type == "suggestion_resolved"]
    assert len(resolved) == 1
    event = resolved[0]
    assert event.identity_id == identity_uuid
    assert event.cluster_id == uuid.UUID(cluster.id)
    assert event.payload.get("resolution") == "accepted"
    assert event.payload.get("outcome_cluster_id") == cluster.id
    assert event.payload.get("suggestion_id") == suggestion.id
