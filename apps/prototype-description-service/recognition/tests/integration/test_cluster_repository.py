"""Contract and persistence tests for ClusterRepository (Phase 5, TDD first)."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

import numpy as np
import pytest

from db.models import Tenant
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import ClusterRepository
from recognition.domain.representative import ClusterRepresentative
from recognition.infrastructure.repositories import (
    SqlAlchemyClusterRepository,
    SqlAlchemyMemberRepository,
)


class DummyClusterRepository(ClusterRepository):
    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None:
        raise NotImplementedError

    async def get_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        labeled_only: bool = False,
        search: str | None = None,
    ) -> list[IdentityCluster]:
        raise NotImplementedError

    async def save(self, cluster: IdentityCluster) -> IdentityCluster:
        raise NotImplementedError

    async def update(self, cluster: IdentityCluster) -> IdentityCluster:
        raise NotImplementedError

    async def delete(self, cluster_id: str) -> None:
        raise NotImplementedError


def test_cluster_repository_is_protocol() -> None:
    """ClusterRepository must be a typing Protocol."""
    assert issubclass(ClusterRepository, Protocol)


def test_cluster_repository_methods_are_async() -> None:
    """All required methods should be async coroutine functions."""
    for method_name in ("get_by_id", "get_by_tenant", "save", "update", "delete"):
        method = getattr(DummyClusterRepository, method_name)
        assert inspect.iscoroutinefunction(method)


@pytest.mark.asyncio
async def test_save_and_retrieve_cluster(db_session, tenant) -> None:
    """Clusters should round-trip through the repository."""
    repo = SqlAlchemyClusterRepository(db_session)
    cluster = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label="Person A",
        is_labeled=True,
        identity_count=0,
        created_at=datetime.now(tz=UTC),
    )

    saved = await repo.save(cluster)
    assert saved.id is not None

    fetched = await repo.get_by_id(saved.id)
    assert fetched is not None
    assert fetched.label == "Person A"
    assert fetched.tenant_id == str(tenant.id)
    assert fetched.identity_count == 0


@pytest.mark.asyncio
async def test_get_by_tenant_respects_pagination(db_session, tenant) -> None:
    """get_by_tenant should apply limit/offset ordering by newest first."""
    repo = SqlAlchemyClusterRepository(db_session)
    older = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label="Older",
        is_labeled=True,
        identity_count=2,
        created_at=datetime.now(tz=UTC) - timedelta(days=1),
    )
    newer = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label="Newer",
        is_labeled=False,
        identity_count=1,
        created_at=datetime.now(tz=UTC),
    )

    await repo.save(older)
    await repo.save(newer)

    first_page = await repo.get_by_tenant(str(tenant.id), limit=1, offset=0)
    second_page = await repo.get_by_tenant(str(tenant.id), limit=1, offset=1)

    assert [c.label for c in first_page] == ["Newer"]
    assert [c.label for c in second_page] == ["Older"]


@pytest.mark.asyncio
async def test_update_cluster_label(db_session, tenant) -> None:
    """Updates should persist label and labeled status."""
    repo = SqlAlchemyClusterRepository(db_session)
    cluster = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label=None,
        is_labeled=False,
        identity_count=0,
        created_at=datetime.now(tz=UTC),
    )
    saved = await repo.save(cluster)

    saved.label = "Updated"
    saved.is_labeled = True
    updated = await repo.update(saved)

    assert updated.label == "Updated"
    assert updated.is_labeled is True

    fetched = await repo.get_by_id(updated.id)
    assert fetched is not None
    assert fetched.label == "Updated"
    assert fetched.is_labeled is True


@pytest.mark.asyncio
async def test_delete_cascades_members(db_session, tenant) -> None:
    """Deleting a cluster should remove associated members."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    cluster = IdentityCluster(
        id=None,
        tenant_id=str(tenant.id),
        label="With members",
        is_labeled=True,
        identity_count=1,
        created_at=datetime.now(tz=UTC),
    )
    saved_cluster = await cluster_repo.save(cluster)
    await member_repo.add_member(saved_cluster.id, identity_id=str(uuid.uuid4()), similarity=0.92)

    await cluster_repo.delete(saved_cluster.id)
    members = await member_repo.get_by_cluster(saved_cluster.id)

    assert members == []


@pytest.mark.asyncio
async def test_get_by_tenant_filters_other_tenants(db_session, tenant) -> None:
    """Clusters from other tenants should not be returned."""
    repo = SqlAlchemyClusterRepository(db_session)

    other_tenant = Tenant(site_url="http://other.test")
    db_session.add(other_tenant)
    await db_session.commit()
    await db_session.refresh(other_tenant)

    # Cluster for current tenant
    await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Mine",
            is_labeled=False,
            identity_count=0,
            created_at=datetime.now(tz=UTC),
        )
    )
    # Cluster for other tenant
    await repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(other_tenant.id),
            label="Theirs",
            is_labeled=False,
            identity_count=0,
            created_at=datetime.now(tz=UTC),
        )
    )

    clusters = await repo.get_by_tenant(str(tenant.id), limit=10, offset=0)

    assert [c.label for c in clusters] == ["Mine"]


@pytest.mark.asyncio
async def test_clear_representatives_removes_all(db_session, tenant) -> None:
    """clear_representatives should remove all representative rows for the cluster."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="With reps",
            is_labeled=False,
            identity_count=1,
            created_at=datetime.now(tz=UTC),
        )
    )
    identity_id = str(uuid.uuid4())
    await member_repo.add_member(cluster.id, identity_id=identity_id, similarity=0.92)

    rep = ClusterRepresentative(
        id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        identity_id=identity_id,
        embedding=np.ones(512, dtype=np.float32),
        created_at=datetime.now(tz=UTC),
        tenant_id=str(tenant.id),
    )
    await cluster_repo.add_representative(rep)
    assert await cluster_repo.get_representative_count(cluster.id) == 1

    await cluster_repo.clear_representatives(cluster.id)
    assert await cluster_repo.get_representative_count(cluster.id) == 0
