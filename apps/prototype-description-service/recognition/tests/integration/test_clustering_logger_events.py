from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from db.models import IdentityCluster, MediaIdentity, RecognitionEvent
from recognition.observability import ClusteringLogger, DecisionType
from recognition.observability.recognition_runs import create_recognition_run


@pytest.mark.asyncio
async def test_log_decision_emits_recognition_event(db_session, tenant) -> None:
    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=101,
        media_url="http://example.test/101.jpg",
        bbox_x=1,
        bbox_y=2,
        bbox_width=10,
        bbox_height=10,
        confidence=0.99,
        embedding=[0.0] * 512,
    )
    cluster = IdentityCluster(tenant_id=tenant.id, label=None, user_confirmed=False, identity_count=0)
    db_session.add_all([identity, cluster])
    await db_session.commit()
    await db_session.refresh(identity)
    await db_session.refresh(cluster)

    run_ctx = await create_recognition_run(db_session, tenant_id=tenant.id, source="test")
    logger = ClusteringLogger()
    logger.bind_run_context(run_ctx)

    ts = datetime(2025, 1, 1, tzinfo=UTC)
    logger.log_decision(
        identity_id=str(identity.id),
        cluster_id=str(cluster.id),
        decision=DecisionType.ACCEPT,
        similarity=0.91,
        reason=None,
        metadata={"method": "representative"},
        timestamp=ts,
        media_id=str(identity.media_id),
    )
    await db_session.commit()

    events = (await db_session.execute(select(RecognitionEvent))).scalars().all()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "assignment_decision"
    assert event.identity_id == identity.id
    assert event.cluster_id == cluster.id
    assert event.timestamp.replace(tzinfo=UTC) == ts
    assert event.payload.get("decision") == "accept"
    assert event.payload.get("method") == "representative"
