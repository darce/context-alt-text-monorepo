from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from db.models import IdentityCluster as IdentityClusterModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import ClusterRepository
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository


def test_cluster_repository_protocol_exposes_get_delta() -> None:
    method = ClusterRepository.get_delta

    assert inspect.iscoroutinefunction(method)

    signature = inspect.signature(method)
    assert str(signature) == (
        "(self, tenant_id: 'str', *, since_version: 'int') -> "
        "'tuple[list[IdentityCluster], list[tuple[IdentityMember, MediaIdentity]], int]'"
    )
    assert signature.parameters["since_version"].kind is inspect.Parameter.KEYWORD_ONLY
    assert hasattr(AsyncMock(spec=ClusterRepository), "get_delta")


@pytest.mark.asyncio
async def test_sqlalchemy_cluster_repository_get_delta_returns_changed_clusters_and_members(db_session, tenant) -> None:
    repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    base_time = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)

    older_cluster = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Older",
            is_labeled=True,
            identity_count=1,
            created_at=base_time,
        )
    )
    newer_cluster = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Newer",
            is_labeled=True,
            identity_count=1,
            created_at=base_time + timedelta(seconds=1),
        )
    )

    older_identity_id = uuid.uuid4()
    newer_identity_id = uuid.uuid4()
    db_session.add_all(
        [
            MediaIdentityModel(
                id=older_identity_id,
                tenant_id=tenant.id,
                media_id=101,
                media_url="http://example.test/older.jpg",
                bbox_x=0,
                bbox_y=0,
                bbox_width=40,
                bbox_height=40,
                confidence=0.9,
                embedding=[0.1] * 512,
            ),
            MediaIdentityModel(
                id=newer_identity_id,
                tenant_id=tenant.id,
                media_id=202,
                media_url="http://example.test/newer.jpg",
                bbox_x=1,
                bbox_y=2,
                bbox_width=41,
                bbox_height=42,
                confidence=0.95,
                embedding=[0.2] * 512,
            ),
        ]
    )
    await db_session.flush()

    await member_repo.add_member(older_cluster.id, identity_id=str(older_identity_id), similarity=0.91)
    await member_repo.add_member(newer_cluster.id, identity_id=str(newer_identity_id), similarity=0.97)

    older_cluster_model = await db_session.get(IdentityClusterModel, uuid.UUID(older_cluster.id))
    newer_cluster_model = await db_session.get(IdentityClusterModel, uuid.UUID(newer_cluster.id))
    assert older_cluster_model is not None
    assert newer_cluster_model is not None

    older_cluster_model.updated_at = base_time + timedelta(seconds=2)
    newer_cluster_model.updated_at = base_time + timedelta(seconds=5)
    await db_session.commit()

    since_version = int(older_cluster_model.updated_at.timestamp() * 1_000_000) + 1
    clusters, members, snapshot_version = await repo.get_delta(str(tenant.id), since_version=since_version)
    expected_snapshot_version = await repo.get_snapshot_version(str(tenant.id))

    assert [cluster.id for cluster in clusters] == [newer_cluster.id]
    assert [member.cluster_id for member, _identity in members] == [newer_cluster.id]
    assert [member.identity_id for member, _identity in members] == [str(newer_identity_id)]
    assert snapshot_version == expected_snapshot_version


@pytest.mark.asyncio
async def test_sqlalchemy_cluster_repository_get_delta_returns_empty_payload_when_current_version_is_already_synced(
    db_session,
    tenant,
) -> None:
    repo = SqlAlchemyClusterRepository(db_session)
    base_time = datetime(2026, 3, 19, 13, 0, tzinfo=UTC)

    cluster = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Stable",
            is_labeled=True,
            identity_count=0,
            created_at=base_time,
        )
    )
    cluster_model = await db_session.get(IdentityClusterModel, uuid.UUID(cluster.id))
    assert cluster_model is not None
    cluster_model.updated_at = base_time + timedelta(seconds=4)
    await db_session.commit()

    current_version = await repo.get_snapshot_version(str(tenant.id))
    clusters, members, snapshot_version = await repo.get_delta(str(tenant.id), since_version=current_version)

    assert clusters == []
    assert members == []
    assert snapshot_version == current_version


@pytest.mark.asyncio
async def test_sqlalchemy_cluster_repository_get_delta_returns_full_current_membership_for_changed_cluster(
    db_session,
    tenant,
) -> None:
    repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    base_time = datetime(2026, 3, 19, 13, 30, tzinfo=UTC)

    cluster = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Replacement set",
            is_labeled=True,
            identity_count=2,
            created_at=base_time,
        )
    )

    first_identity_id = uuid.uuid4()
    second_identity_id = uuid.uuid4()
    db_session.add_all(
        [
            MediaIdentityModel(
                id=first_identity_id,
                tenant_id=tenant.id,
                media_id=301,
                media_url="http://example.test/first.jpg",
                bbox_x=10,
                bbox_y=11,
                bbox_width=45,
                bbox_height=46,
                confidence=0.93,
                embedding=[0.3] * 512,
            ),
            MediaIdentityModel(
                id=second_identity_id,
                tenant_id=tenant.id,
                media_id=302,
                media_url="http://example.test/second.jpg",
                bbox_x=12,
                bbox_y=13,
                bbox_width=47,
                bbox_height=48,
                confidence=0.94,
                embedding=[0.4] * 512,
            ),
        ]
    )
    await db_session.flush()

    await member_repo.add_member(cluster.id, identity_id=str(first_identity_id), similarity=0.88)
    await member_repo.add_member(cluster.id, identity_id=str(second_identity_id), similarity=0.92)

    cluster_model = await db_session.get(IdentityClusterModel, uuid.UUID(cluster.id))
    assert cluster_model is not None
    cluster_model.updated_at = base_time + timedelta(seconds=10)
    await db_session.commit()

    since_version = int((base_time + timedelta(seconds=9)).timestamp() * 1_000_000)
    clusters, members, _snapshot_version = await repo.get_delta(str(tenant.id), since_version=since_version)

    assert [returned_cluster.id for returned_cluster in clusters] == [cluster.id]
    assert [member.cluster_id for member, _identity in members] == [cluster.id, cluster.id]
    assert {member.identity_id for member, _identity in members} == {str(first_identity_id), str(second_identity_id)}


@pytest.mark.asyncio
async def test_sqlalchemy_cluster_repository_get_delta_honors_microsecond_snapshot_boundaries(
    db_session,
    tenant,
) -> None:
    repo = SqlAlchemyClusterRepository(db_session)
    base_time = datetime(2026, 3, 19, 13, 45, tzinfo=UTC)

    cluster = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Microsecond boundary",
            is_labeled=True,
            identity_count=0,
            created_at=base_time,
        )
    )
    cluster_model = await db_session.get(IdentityClusterModel, uuid.UUID(cluster.id))
    assert cluster_model is not None

    exact_updated_at = base_time + timedelta(microseconds=37)
    cluster_model.updated_at = exact_updated_at
    await db_session.commit()

    exact_version = int(exact_updated_at.timestamp() * 1_000_000)

    clusters_at_boundary, members_at_boundary, snapshot_version_at_boundary = await repo.get_delta(
        str(tenant.id),
        since_version=exact_version,
    )
    clusters_before_boundary, members_before_boundary, snapshot_version_before_boundary = await repo.get_delta(
        str(tenant.id),
        since_version=exact_version - 1,
    )

    assert clusters_at_boundary == []
    assert members_at_boundary == []
    assert snapshot_version_at_boundary == exact_version
    assert [returned_cluster.id for returned_cluster in clusters_before_boundary] == [cluster.id]
    assert members_before_boundary == []
    assert snapshot_version_before_boundary == exact_version


@pytest.mark.asyncio
async def test_sqlalchemy_cluster_repository_get_delta_returns_empty_payload_for_disposed_cluster_changes(
    db_session,
    tenant,
) -> None:
    repo = SqlAlchemyClusterRepository(db_session)
    base_time = datetime(2026, 3, 19, 14, 0, tzinfo=UTC)

    cluster = await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Soon disposed",
            is_labeled=True,
            identity_count=0,
            created_at=base_time,
        )
    )
    cluster_model = await db_session.get(IdentityClusterModel, uuid.UUID(cluster.id))
    assert cluster_model is not None
    cluster_model.updated_at = base_time + timedelta(seconds=2)
    await db_session.commit()

    baseline_version = await repo.get_snapshot_version(str(tenant.id))

    cluster_model.disposed_at = base_time + timedelta(seconds=5)
    cluster_model.updated_at = base_time + timedelta(seconds=5)
    await db_session.commit()

    clusters, members, snapshot_version = await repo.get_delta(str(tenant.id), since_version=baseline_version)

    assert clusters == []
    assert members == []
    assert snapshot_version > baseline_version
