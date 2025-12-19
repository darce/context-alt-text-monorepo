"""Integration tests for ClusterRepository.get_maturity_info."""

from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MediaIdentity, Tenant
from recognition.domain.cluster import IdentityCluster
from recognition.domain.maturity import ClusterMaturityLevel
from recognition.domain.representative import ClusterRepresentative
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.shared.ids import generate_id


@pytest.mark.asyncio
async def test_get_maturity_info_cold_cluster(
    cluster_repository: SqlAlchemyClusterRepository,
    db_session: AsyncSession,
    tenant: "Tenant",  # Use fixture
) -> None:
    # 1. Create identity
    identity = MediaIdentity(
        id=generate_id(),
        tenant_id=tenant.id,
        media_id=1,
        media_url="http://x",
        bbox_x=0,
        bbox_y=0,
        bbox_width=100,
        bbox_height=100,
        confidence=0.9,
        embedding=np.zeros(512, dtype=np.float32).tolist(),
    )
    db_session.add(identity)
    await db_session.flush()

    # 2. Create a cold cluster
    cluster_id = str(generate_id())
    cluster = IdentityCluster(
        id=cluster_id, tenant_id=tenant.id, is_labeled=False, member_count=1, user_confirmed=False
    )
    await cluster_repository.save(cluster)

    # Add representative
    rep = ClusterRepresentative(
        id=str(generate_id()),
        cluster_id=cluster_id,
        identity_id=str(identity.id),
        embedding=np.zeros(512, dtype=np.float32),
        created_at=datetime.now(tz=UTC),
        quality_score=0.9,
        tenant_id=str(tenant.id),
    )
    await cluster_repository.add_representative(rep)

    # 3. Fetch maturity info
    info = await cluster_repository.get_maturity_info(cluster_id)

    # 4. Verify
    assert info is not None
    assert info.identity_count == 1
    assert info.representative_count == 1
    assert info.user_confirmed is False
    assert info.level == ClusterMaturityLevel.COLD
    assert info.threshold_adjustment > 0


@pytest.mark.asyncio
async def test_get_maturity_info_confirmed_cluster(
    cluster_repository: SqlAlchemyClusterRepository,
    db_session: AsyncSession,
    tenant: "Tenant",
) -> None:
    identity = MediaIdentity(
        id=generate_id(),
        tenant_id=tenant.id,
        media_id=2,
        media_url="http://x",
        bbox_x=0,
        bbox_y=0,
        bbox_width=100,
        bbox_height=100,
        confidence=0.9,
        embedding=np.zeros(512, dtype=np.float32).tolist(),
    )
    db_session.add(identity)
    await db_session.flush()

    cluster_id = str(generate_id())
    cluster = IdentityCluster(id=cluster_id, tenant_id=tenant.id, is_labeled=True, member_count=2, user_confirmed=True)
    await cluster_repository.save(cluster)

    rep = ClusterRepresentative(
        id=str(generate_id()),
        cluster_id=cluster_id,
        identity_id=str(identity.id),
        embedding=np.zeros(512, dtype=np.float32),
        created_at=datetime.now(tz=UTC),
        quality_score=0.9,
        tenant_id=str(tenant.id),
    )
    await cluster_repository.add_representative(rep)

    info = await cluster_repository.get_maturity_info(cluster_id)

    assert info is not None
    assert info.user_confirmed is True
    assert info.level == ClusterMaturityLevel.CONFIRMED
    assert info.threshold_adjustment < 0


@pytest.mark.asyncio
async def test_get_maturity_info_mature_cluster(
    cluster_repository: SqlAlchemyClusterRepository,
    db_session: AsyncSession,
    tenant: "Tenant",
) -> None:
    cluster_id = str(generate_id())
    cluster = IdentityCluster(
        id=cluster_id, tenant_id=tenant.id, is_labeled=False, member_count=15, user_confirmed=False
    )
    await cluster_repository.save(cluster)

    # Create identities and reps
    identities = []
    for i in range(3):
        ident = MediaIdentity(
            id=generate_id(),
            tenant_id=tenant.id,
            media_id=10 + i,
            media_url="http://x",
            bbox_x=0,
            bbox_y=0,
            bbox_width=100,
            bbox_height=100,
            confidence=0.9,
            embedding=np.zeros(512, dtype=np.float32).tolist(),
        )
        identities.append(ident)
        db_session.add(ident)
    await db_session.flush()

    for ident in identities:
        rep = ClusterRepresentative(
            id=str(generate_id()),
            cluster_id=cluster_id,
            identity_id=str(ident.id),
            embedding=np.zeros(512, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            quality_score=0.9,
            tenant_id=str(tenant.id),
        )
        await cluster_repository.add_representative(rep)

    info = await cluster_repository.get_maturity_info(cluster_id)

    assert info is not None
    assert info.identity_count == 15
    assert info.representative_count == 3
    assert info.level == ClusterMaturityLevel.MATURE
    assert info.threshold_adjustment < 0
