from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from db.models import IdentityCluster, MediaIdentity, RecognitionEvent, RecognitionRun
from recognition.observability.recognition_runs import complete_recognition_run, create_recognition_run


@pytest.mark.asyncio
async def test_create_run_and_add_event(db_session, tenant) -> None:
    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=101,
        media_url="http://example.test/101.jpg",
        bbox_x=0,
        bbox_y=0,
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

    ctx = await create_recognition_run(
        db_session,
        tenant_id=tenant.id,
        source="test",
        settings_snapshot={"similarity_threshold": 0.85},
        dataset_selector={"media_ids": [101]},
        started_at=datetime.now(tz=UTC),
    )
    ctx.add_event(
        event_type="assignment_decision",
        identity_id=identity.id,
        cluster_id=cluster.id,
        payload={"decision": "accept"},
    )
    await db_session.commit()

    runs = (await db_session.execute(select(RecognitionRun))).scalars().all()
    assert len(runs) == 1
    assert runs[0].id == ctx.run_id

    events = (await db_session.execute(select(RecognitionEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].run_id == ctx.run_id
    assert events[0].tenant_id == tenant.id
    assert events[0].event_type == "assignment_decision"
    assert events[0].identity_id == identity.id
    assert events[0].cluster_id == cluster.id
    assert events[0].payload.get("decision") == "accept"


@pytest.mark.asyncio
async def test_complete_run_updates_status(db_session, tenant) -> None:
    ctx = await create_recognition_run(db_session, tenant_id=tenant.id, source="test")
    await complete_recognition_run(db_session, run_id=ctx.run_id, status="completed", completed_at=datetime.now(tz=UTC))
    await db_session.commit()

    run = (await db_session.execute(select(RecognitionRun))).scalars().one()
    assert run.status == "completed"
    assert run.completed_at is not None
