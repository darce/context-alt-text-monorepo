import uuid
from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy import select

from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.orchestration.cluster_curation import CurationActionType


@pytest.mark.asyncio
async def test_reassign_identity_between_clusters(
    cluster_service,
    db_session,
    tenant,
):
    """Verify that assigning an identity that is already in a cluster moves it correctly."""

    # 1. Seed MediaIdentities
    id1 = str(uuid.uuid4())
    id2 = str(uuid.uuid4())

    embedding_a = np.zeros(512, dtype=np.float32)
    embedding_a[0] = 1.0
    embedding_b = np.zeros(512, dtype=np.float32)
    embedding_b[1] = 1.0

    media1 = MediaIdentityModel(
        id=uuid.UUID(id1),
        tenant_id=tenant.id,
        media_id=1,
        media_url="http://example.com/1.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=100,
        bbox_height=100,
        confidence=0.9,
        embedding=embedding_a,
        quality_score=0.8,
        pose_pitch=10.0,
        pose_yaw=10.0,
        pose_roll=0.0,  # Add pose for completeness
    )
    media2 = MediaIdentityModel(
        id=uuid.UUID(id2),
        tenant_id=tenant.id,
        media_id=2,
        media_url="http://example.com/2.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=100,
        bbox_height=100,
        confidence=0.9,
        embedding=embedding_b,
        quality_score=0.8,
        pose_pitch=10.0,
        pose_yaw=10.0,
        pose_roll=0.0,
    )
    db_session.add_all([media1, media2])
    await db_session.flush()

    # 2. Create Initial Clusters
    cluster_a = await cluster_service.create_cluster_for_identity(
        identity_id=id1, label="Cluster A", tenant_id=str(tenant.id)
    )
    cluster_b = await cluster_service.create_cluster_for_identity(
        identity_id=id2, label="Cluster B", tenant_id=str(tenant.id)
    )

    # Verify initial state
    assert cluster_a.identity_count == 1
    assert cluster_b.identity_count == 1

    # Check membership A
    members_a = await cluster_service.assignment_writer._members.get_by_cluster(cluster_a.id)
    assert len(members_a) == 1
    assert members_a[0].identity_id == id1

    # 3. Perform Reassignment (Move id1 from A to B)
    # The fix we implemented should detect id1 is in A, remove it from A, and add to B.
    # It should also log FALSE_POSITIVE action.

    updated_b = await cluster_service.assign_outlier_to_cluster(
        identity_id=id1, target_cluster_id=cluster_b.id, tenant_id=str(tenant.id), similarity=0.95
    )

    # 4. Assertions
    assert updated_b is not None
    assert updated_b.id == cluster_b.id
    assert updated_b.identity_count == 2  # id2 + id1

    # Verify id1 is in B
    members_b = await cluster_service.assignment_writer._members.get_by_cluster(cluster_b.id)
    member_ids_b = {m.identity_id for m in members_b}
    assert id1 in member_ids_b
    assert id2 in member_ids_b

    # Verify id1 is NOT in A
    members_a_after = await cluster_service.assignment_writer._members.get_by_cluster(cluster_a.id)
    assert len(members_a_after) == 0

    # Verify Cluster A count updated (re-fetch)
    cluster_a_updated = await cluster_service.assignment_writer._clusters.get_by_id(cluster_a.id)
    assert cluster_a_updated.identity_count == 0

    # (Optional) Verify DB constraint didn't raise UniqueViolationError
    # (implied by test passing, but specific check: check identity_members table directly)
    stmt = select(MemberModel).where(MemberModel.identity_id == uuid.UUID(id1))
    result = await db_session.execute(stmt)
    rows = result.scalars().all()
    assert len(rows) == 1
    assert str(rows[0].cluster_id) == cluster_b.id
