from __future__ import annotations

import uuid

import numpy as np
import pytest

from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.regression_harness.report_builder import generate_canonical_report
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.locator import IdentityLocator
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
        embedding_model="buffalo_l@insightface",
    )
    return domain_identity, model_identity


@pytest.mark.asyncio
async def test_generate_canonical_report_includes_pre_curation_state(db_session, tenant) -> None:
    identity_1, model_1 = _make_identity(str(tenant.id), media_id=101, bbox_x=1, bbox_y=2)
    identity_2, model_2 = _make_identity(str(tenant.id), media_id=102, bbox_x=3, bbox_y=4)
    db_session.add_all([model_1, model_2])
    await db_session.commit()

    run_ctx = await create_recognition_run(
        db_session,
        tenant_id=tenant.id,
        source="test",
        dataset_selector={"media_ids": [101, 102]},
    )

    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo, run_context=run_ctx)

    cluster = await writer.persist_new_cluster(
        tenant_id=str(tenant.id),
        identities=[identity_1, identity_2],
        similarities=[0.91, 0.92],
        algorithm="graph",
    )
    assert cluster.id is not None

    cluster_domain = await cluster_repo.get_by_id(cluster.id)
    assert cluster_domain is not None
    cluster_domain.label = "Alice"
    cluster_domain.is_labeled = True
    cluster_domain.user_confirmed = True
    await cluster_repo.update(cluster_domain)
    await db_session.commit()

    report = await generate_canonical_report(db_session, tenant_id=str(tenant.id), run_id=str(run_ctx.run_id))
    pre_state = report.get("pre_curation_state")
    assert isinstance(pre_state, dict)

    predicted_clusters = pre_state.get("predicted_clusters")
    assert isinstance(predicted_clusters, list)
    assert any(pc.get("predicted_cluster_id") == cluster.id for pc in predicted_clusters)

    expected_locators = {
        IdentityLocator(media_id=101, bbox_x=1, bbox_y=2, bbox_width=10, bbox_height=10, crop_hash=None),
        IdentityLocator(media_id=102, bbox_x=3, bbox_y=4, bbox_width=10, bbox_height=10, crop_hash=None),
    }
    cluster_payload = next(pc for pc in predicted_clusters if pc.get("predicted_cluster_id") == cluster.id)
    members = cluster_payload.get("member_identity_locators")
    assert isinstance(members, list)
    parsed = {IdentityLocator.from_dict(locator) for locator in members}
    assert expected_locators.issubset(parsed)
