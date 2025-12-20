from __future__ import annotations

import uuid
from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy import select

from db.models import MediaIdentity as MediaIdentityModel
from db.models import RecognitionEvent
from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemyMemberRepository
from recognition.observability.recognition_runs import create_recognition_run


def _make_identity(
    tenant_id: str,
    *,
    media_id: int,
    bbox_x: int,
    bbox_y: int,
) -> tuple[MediaIdentity, MediaIdentityModel]:
    identity_uuid = uuid.uuid4()
    embedding = np.zeros(512, dtype=np.float32)
    embedding[0] = 1.0
    domain_identity = MediaIdentity(
        id=str(identity_uuid),
        tenant_id=tenant_id,
        media_id=str(media_id),
        embedding=embedding,
        confidence=0.95,
        bbox_width=10,
        bbox_height=10,
        bbox_x=bbox_x,
        bbox_y=bbox_y,
    )
    model_identity = MediaIdentityModel(
        id=identity_uuid,
        tenant_id=uuid.UUID(tenant_id),
        media_id=media_id,
        media_url=f"http://example.test/{media_id}.jpg",
        bbox_x=bbox_x,
        bbox_y=bbox_y,
        bbox_width=10,
        bbox_height=10,
        confidence=0.95,
        embedding=[float(x) for x in embedding.tolist()],
        created_at=datetime.now(tz=UTC),
    )
    return domain_identity, model_identity


@pytest.mark.asyncio
async def test_persist_new_cluster_emits_events(db_session, tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    run_ctx = await create_recognition_run(db_session, tenant_id=tenant.id, source="test")

    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo, run_context=run_ctx)

    identity_1, model_1 = _make_identity(str(tenant.id), media_id=101, bbox_x=1, bbox_y=2)
    identity_2, model_2 = _make_identity(str(tenant.id), media_id=102, bbox_x=3, bbox_y=4)
    db_session.add_all([model_1, model_2])
    await db_session.commit()

    cluster = await writer.persist_new_cluster(
        tenant_id=str(tenant.id),
        identities=[identity_1, identity_2],
        similarities=[0.91, 0.92],
        algorithm="graph",
    )
    await db_session.commit()

    events = (await db_session.execute(select(RecognitionEvent))).scalars().all()
    event_types = {event.event_type for event in events}
    assert "cluster_created" in event_types
    assert "representative_selected" in event_types

    cluster_created = next(event for event in events if event.event_type == "cluster_created")
    assert str(cluster_created.cluster_id) == cluster.id
    assert cluster_created.payload.get("creation_method") == "graph"
    assert cluster_created.payload.get("identity_count") == 2

    members = cluster_created.payload.get("members")
    assert isinstance(members, list)
    assert any(member.get("identity_id") == identity_1.id for member in members)
    assert any(member.get("identity_id") == identity_2.id for member in members)

    rep_events = [event for event in events if event.event_type == "representative_selected"]
    assert len(rep_events) == 2
    assert all(event.payload.get("identity_locator") for event in rep_events)


@pytest.mark.asyncio
async def test_persist_assignment_emits_representative_selected_event(db_session, tenant) -> None:
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    run_ctx = await create_recognition_run(db_session, tenant_id=tenant.id, source="test")
    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo, run_context=run_ctx)

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )

    identity, model = _make_identity(str(tenant.id), media_id=201, bbox_x=5, bbox_y=6)
    db_session.add(model)
    await db_session.commit()

    candidate = AssignmentCandidate(
        identity=identity,
        identity_vector=identity.extract_face_embedding(),
        cluster_id=cluster.id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.93,
    )
    decision = AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=[],
        checks_failed=[],
    )

    await writer.persist_assignment(decision)
    await db_session.commit()

    events = (await db_session.execute(select(RecognitionEvent))).scalars().all()
    rep_events = [event for event in events if event.event_type == "representative_selected"]
    assert len(rep_events) == 1
    assert rep_events[0].cluster_id == uuid.UUID(cluster.id)
    assert rep_events[0].identity_id == uuid.UUID(identity.id)
    assert rep_events[0].payload.get("identity_locator") is not None
