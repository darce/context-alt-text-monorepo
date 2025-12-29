import uuid
from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy import select

from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.orchestration.cluster_curation import CurationEventType


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
    result = await db_session.execute(stmt)
    rows = result.scalars().all()
    assert len(rows) == 1
    assert str(rows[0].cluster_id) == cluster_b.id


@pytest.mark.asyncio
async def test_assign_outlier_computes_real_similarity(
    cluster_service,
    db_session,
    tenant,
):
    """Verify that assign_outlier logic computes and logs real cosine similarity."""
    from unittest.mock import Mock

    from recognition.observability import ClusteringLogger

    # 1. Setup Identity and Cluster with representatives
    id1 = str(uuid.uuid4())
    id2 = str(uuid.uuid4())

    # Embedding 1: [1, 0, ...]
    embedding_a = np.zeros(512, dtype=np.float32)
    embedding_a[0] = 1.0

    # Embedding 2: [0.99, 0.14, ...] -> Cosine sim ~0.99
    # normalized: 0.99^2 + 0.14^2 = 0.9801 + 0.0196 = 0.9997 ~= 1.0
    val_0 = 0.99
    val_1 = 0.14
    norm = np.sqrt(val_0**2 + val_1**2)
    embedding_b = np.zeros(512, dtype=np.float32)
    embedding_b[0] = val_0 / norm
    embedding_b[1] = val_1 / norm

    media1 = MediaIdentityModel(
        id=uuid.UUID(id1),
        tenant_id=tenant.id,
        media_id=1,
        media_url="http://example.com/1.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=100,
        bbox_height=100,
        embedding=[float(x) for x in embedding_a],  # Ensure list format for JSON/Array types
        confidence=0.9,
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
        embedding=[float(x) for x in embedding_b],
        confidence=0.9,
    )
    db_session.add_all([media1, media2])
    await db_session.flush()

    # Create target cluster with id2 as representative
    cluster = await cluster_service.create_cluster_for_identity(
        identity_id=id2, label="Cluster Target", tenant_id=str(tenant.id)
    )

    # Ensure representative exists
    # create_cluster_for_identity calls assign_to_new_cluster -> persist_new_cluster -> creates reps
    # So we assume rep exists.

    # 2. Mock logger on service
    mock_logger = Mock(spec=ClusteringLogger)
    cluster_service.logger = mock_logger

    # 3. Assign id1 (embedding_a) to cluster (has embedding_b)
    # This should compute similarity between A and B (~0.99)
    # The default impl uses 0.0000. Ww expect > 0.9.
    await cluster_service.assign_outlier_to_cluster(
        identity_id=id1,
        target_cluster_id=cluster.id,
        tenant_id=str(tenant.id),
        # Do NOT pass similarity manually, ensure it's calculated.
        # But wait, the previous test passed similarity explicitly.
        # Let's check the signature of assign_outlier_to_cluster.
        # It has similarity: float = 0.0.
        # We want the *internal logic* to compute it if it's 0.0?
        # OR we want the caller (API) to not pass it, and the service to compute it.
        # If we pass 0.0 (default), does it compute?
        # The plan says: "Implement compute_curation_similarity" and "Update assign_outlier_to_cluster to use it".
        # So we expect the service to ignore the default 0.0 and compute it if possible, or only if 0.0?
        # Ideally, we calculate it if not provided or if provided as default placeholder.
        # Let's assume we pass nothing for similarity.
    )

    # 4. Verify log call
    # log_decision is called inside assign_outlier_to_cluster (or via gate/writer logic?)
    # Actually, assign_outlier_to_cluster calls writer.persist_assignment or similar?
    # Wait, cluster_curation.py logic:
    # It logs "CURATION_ASSIGNED" via logger.info (standard logger) OR clustering_logger?
    # The existing code uses `self._logger.info` in `ClusteringLogger.log_decision`?
    # No, `cluster_curation.py` uses module level `logger = logging.getLogger(__name__)`.
    # And it calls `clustering_logger.log_curation_action`.

    assert mock_logger.log_curation_action.called
    call_args = mock_logger.log_curation_action.call_args
    kwargs = call_args.kwargs

    similarity_logged = kwargs.get("similarity", 0.0)
    assert similarity_logged > 0.9, f"Expected similarity > 0.9, got {similarity_logged}"


@pytest.mark.asyncio
async def test_remove_representative_triggers_refresh(
    cluster_service,
    db_session,
    tenant,
    caplog,
):
    """Verify that removing a representative triggers recomputation."""
    import logging

    caplog.set_level(logging.INFO)
    from db.models import IdentityClusterRepresentative as RepModel

    # 1. Setup Cluster with 2 members, one is representative
    id1 = str(uuid.uuid4())
    id2 = str(uuid.uuid4())
    embedding = np.zeros(512, dtype=np.float32)
    embedding[0] = 1.0

    # Ensure valid media models
    media1 = MediaIdentityModel(
        id=uuid.UUID(id1),
        tenant_id=tenant.id,
        media_id=1,
        media_url="http://example.com/1.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=100,
        bbox_height=100,
        embedding=[float(x) for x in embedding],
        confidence=0.9,
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
        embedding=[float(x) for x in embedding],
        confidence=0.9,
    )
    db_session.add_all([media1, media2])
    await db_session.flush()

    # Create cluster for id1
    cluster = await cluster_service.create_cluster_for_identity(
        identity_id=id1, label="Rep Test", tenant_id=str(tenant.id)
    )
    # Add id2
    await cluster_service.assign_outlier_to_cluster(
        identity_id=id2, target_cluster_id=cluster.id, tenant_id=str(tenant.id)
    )

    # Force id1 to be the representative
    # create_cluster_for_identity probably made id1 the rep.
    # Let's verify.
    result = await db_session.execute(select(RepModel).where(RepModel.cluster_id == uuid.UUID(cluster.id)))
    reps = result.scalars().all()
    assert id1 in [str(r.identity_id) for r in reps], "id1 should be a rep"

    # 2. Remove id1 (the representative)
    # This should trigger `check_and_refresh_representatives`
    await cluster_service.remove_identity_from_cluster(
        identity_id=id1,
    )

    # 3. Verify Refresh
    # - id1 should no longer be in the cluster
    # - id1 should no longer be a rep
    # - id2 might be promoted to rep (depending on recompute logic, usually recompute picks best)

    # Check members
    members = await cluster_service.assignment_writer._members.get_by_cluster(cluster.id)
    member_ids = {m.identity_id for m in members}
    assert id1 not in member_ids
    assert id2 in member_ids

    # Check representatives
    result = await db_session.execute(select(RepModel).where(RepModel.cluster_id == uuid.UUID(cluster.id)))
    new_reps = result.scalars().all()
    new_rep_ids = {str(r.identity_id) for r in new_reps}

    assert id1 not in new_rep_ids, "Removed identity should not be a rep"
    # Ideally id2 should be the new rep
    assert id2 in new_rep_ids, "Remaining member id2 should be promoted to rep"

    # Verify log
    assert "REPRESENTATIVE_REMOVED" in caplog.text
    assert "triggered_refresh=true" in caplog.text


@pytest.mark.asyncio
async def test_remove_representative_deferred_recompute(
    cluster_service,
    db_session,
    tenant,
    caplog,
):
    """Verify that removing a representative logs event even if recompute is deferred."""
    import logging

    caplog.set_level(logging.INFO)
    from db.models import IdentityClusterRepresentative as RepModel

    # 1. Setup Cluster with representative
    id1 = str(uuid.uuid4())
    embedding = np.zeros(512, dtype=np.float32)
    embedding[0] = 1.0

    media1 = MediaIdentityModel(
        id=uuid.UUID(id1),
        tenant_id=tenant.id,
        media_id=1,
        media_url="http://example.com/1.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=100,
        bbox_height=100,
        embedding=[float(x) for x in embedding],
        confidence=0.9,
    )
    db_session.add(media1)
    await db_session.flush()

    cluster = await cluster_service.create_cluster_for_identity(
        identity_id=id1, label="Rep Test Deferred", tenant_id=str(tenant.id)
    )

    # Verify id1 is rep
    result = await db_session.execute(select(RepModel).where(RepModel.cluster_id == uuid.UUID(cluster.id)))
    reps = result.scalars().all()
    assert id1 in [str(r.identity_id) for r in reps], "id1 should be a rep"

    # 2. Remove id1 with recompute=False
    # This simulates reassign_identity behavior causing check_and_refresh_representatives(refresh=False)
    await cluster_service.remove_identity_from_cluster(
        identity_id=id1,
        recompute=False,
    )

    # 3. Verify Log
    # Should see REPRESENTATIVE_REMOVED with triggered_refresh=false
    assert "REPRESENTATIVE_REMOVED" in caplog.text
    assert "triggered_refresh=false" in caplog.text

    # 4. Verify Rep Removed
    # The helper should have deleted the stale rep
    db_session.expire_all()
    result = await db_session.execute(select(RepModel).where(RepModel.cluster_id == uuid.UUID(cluster.id)))
    reps = result.scalars().all()
    assert len(reps) == 0, "Representative should be removed even if refresh wasn't triggered"
