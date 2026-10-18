import uuid

import pytest
from sqlalchemy import select

from db.models import IdentityCluster as ClusterModel
from db.models import IdentityMember
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.scan.service import ScanService
from recognition.domain.cluster import IdentityCluster
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.interface_adapters.http import deps as dependencies


@pytest.mark.asyncio
async def test_cancel_scan_preserves_cluster_labels(db_session, tenant) -> None:
    """Verification: Identity ID Recycling should preserve memberships during re-scans."""
    # 1. Setup
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    # Initialize ScanService (uses StubFaceDetector by default)
    scan_service = ScanService(session=db_session)

    media_id = 12345
    media_url = "http://example.test/12345.jpg"

    # First scan: Create initial identity
    await scan_service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=media_id,
        media_url=media_url,
    )
    await db_session.flush()

    # Find the created identity
    stmt_mi = select(MediaIdentityModel).where(
        MediaIdentityModel.tenant_id == tenant.id, MediaIdentityModel.media_id == media_id
    )
    identity = (await db_session.execute(stmt_mi)).scalar_one()
    initial_identity_id = identity.id

    # Create labeled cluster and add member
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Original Label",
            is_labeled=True,
            identity_count=1,
            user_confirmed=True,
        )
    )
    await member_repo.add_member(cluster.id, identity_id=str(initial_identity_id), similarity=1.0)
    await db_session.commit()

    # Verify setup
    members = await member_repo.get_by_cluster(cluster.id)
    assert len(members) == 1
    assert members[0].identity_id == str(initial_identity_id)

    # 2. Simulate re-scan (e.g. during a new scan job or re-processing)
    # This call should reuse initial_identity_id because the bbox will match exactly (stub is deterministic).
    await scan_service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=media_id,
        media_url=media_url,
    )
    await db_session.flush()

    # 3. Verify Identity ID Recycling
    # Find the identity again
    identity_after = (await db_session.execute(stmt_mi)).scalar_one()
    assert identity_after.id == initial_identity_id, "Identity ID should be preserved (recycled)"

    # 4. Verify Membership Preservation
    # Check if membership row still exists and points to the SAME identity
    stmt_member = select(IdentityMember).where(IdentityMember.cluster_id == _coerce_uuid(cluster.id))
    members_after = (await db_session.execute(stmt_member)).scalars().all()

    assert len(members_after) == 1, "Membership should NOT have been deleted via CASCADE"
    assert members_after[0].identity_id == initial_identity_id

    # 5. Simulate Cancellation (verify it doesn't affect labels)
    queue_repo = SqlAlchemyScanQueueRepository(db_session)
    queue_service = ScanQueueService(queue_repo)

    enqueued = await queue_service.enqueue_scan_job(
        tenant_id=tenant.id,
        media_items=[(media_id, media_url)],
    )
    job_id = enqueued.job_id

    # Cancel job
    await queue_service.cancel_scan_job(job_id=job_id)
    await db_session.commit()

    # Verify cluster and membership still intact
    fetched_cluster = await cluster_repo.get_by_id(cluster.id)
    assert fetched_cluster is not None
    assert fetched_cluster.label == "Original Label"

    members_final = await member_repo.get_by_cluster(cluster.id)
    assert len(members_final) == 1
    assert members_final[0].identity_id == str(initial_identity_id)


@pytest.mark.asyncio
async def test_analyze_media_preserves_cluster_membership(db_session, tenant) -> None:
    """Verification: The synchronous analyze_media path should also recycle IDs."""
    # 1. Setup
    scan_service = ScanService(session=db_session)
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    media_id = 67890
    media_url = "http://example.test/67890.jpg"

    # Initial scan
    await scan_service.analyze_media(tenant_id=str(tenant.id), media_ids=[str(media_id)], media_sources=[media_url])
    await db_session.flush()

    # Get identity
    stmt_mi = select(MediaIdentityModel).where(
        MediaIdentityModel.tenant_id == tenant.id, MediaIdentityModel.media_id == media_id
    )
    identity = (await db_session.execute(stmt_mi)).scalar_one()
    initial_id = identity.id

    # Create cluster + member
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Batch User",
            is_labeled=True,
            identity_count=1,
            user_confirmed=True,
        )
    )
    await member_repo.add_member(cluster.id, identity_id=str(initial_id), similarity=1.0)
    await db_session.commit()

    # 2. Re-scan via analyze_media
    await scan_service.analyze_media(tenant_id=str(tenant.id), media_ids=[str(media_id)], media_sources=[media_url])
    await db_session.flush()

    # 3. Verify
    identity_after = (await db_session.execute(stmt_mi)).scalar_one_or_none()
    assert identity_after is not None
    assert identity_after.id == initial_id, "Sync path failed to recycle ID"

    members = await member_repo.get_by_cluster(cluster.id)
    assert len(members) == 1
    assert members[0].identity_id == str(initial_id)


def _coerce_uuid(value):
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
