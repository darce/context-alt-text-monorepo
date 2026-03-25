"""Contract and persistence tests for MemberRepository (Phase 5, TDD first)."""

from __future__ import annotations

import inspect
import uuid
from typing import Protocol

import pytest

from db.models import Tenant
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import MemberData, MemberRepository
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemyMemberRepository


class DummyMemberRepository(MemberRepository):
    async def get_by_cluster(self, cluster_id: str):
        raise NotImplementedError

    async def add_member(self, cluster_id: str, identity_id: str, similarity: float):
        raise NotImplementedError

    async def bulk_add_members(self, cluster_id: str, members):
        raise NotImplementedError

    async def move_members(self, source_cluster_id: str, target_cluster_id: str):
        raise NotImplementedError

    async def remove_member(self, member_id: str):
        raise NotImplementedError


def test_member_repository_is_protocol() -> None:
    """MemberRepository must be a typing Protocol."""
    assert issubclass(MemberRepository, Protocol)


def test_member_repository_methods_are_async() -> None:
    """All required methods should be async coroutine functions."""
    for method_name in ("get_by_cluster", "add_member", "bulk_add_members", "move_members", "remove_member"):
        method = getattr(DummyMemberRepository, method_name)
        assert inspect.iscoroutinefunction(method)


def test_member_data_has_required_fields() -> None:
    """MemberData should expose identity_id and similarity."""
    data = MemberData(identity_id="id-1", similarity=0.9)
    assert data.identity_id == "id-1"
    assert data.similarity == 0.9


@pytest.mark.asyncio
async def test_add_member_and_fetch(db_session, tenant) -> None:
    """Members should be persisted and retrieved by cluster."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))

    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Member cluster",
            is_labeled=True,
            identity_count=0,
            created_at=None,
        )
    )
    member = await member_repo.add_member(cluster.id, identity_id=str(uuid.uuid4()), similarity=0.88)

    members = await member_repo.get_by_cluster(cluster.id)
    assert len(members) == 1
    assert members[0].id == member.id
    assert members[0].similarity == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_bulk_add_members(db_session, tenant) -> None:
    """Bulk insertion should persist all member rows."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Bulk cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )

    members = [
        MemberData(identity_id=str(uuid.uuid4()), similarity=0.8),
        MemberData(identity_id=str(uuid.uuid4()), similarity=0.81),
        MemberData(identity_id=str(uuid.uuid4()), similarity=0.82),
    ]
    created = await member_repo.bulk_add_members(cluster.id, members)

    assert len(created) == 3
    stored = await member_repo.get_by_cluster(cluster.id)
    assert {m.identity_id for m in stored} == {m.identity_id for m in members}


@pytest.mark.asyncio
async def test_remove_member(db_session, tenant) -> None:
    """Members should be removable by ID."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Deletable cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )
    member = await member_repo.add_member(cluster.id, identity_id=str(uuid.uuid4()), similarity=0.77)

    await member_repo.remove_member(member.id)
    remaining = await member_repo.get_by_cluster(cluster.id)

    assert remaining == []


@pytest.mark.asyncio
async def test_get_by_cluster_is_tenant_scoped(db_session, tenant) -> None:
    """Cross-tenant members should not be returned."""
    # Seed cluster and member for a different tenant
    other_tenant = Tenant(site_url="http://other.example")
    db_session.add(other_tenant)
    await db_session.commit()
    await db_session.refresh(other_tenant)

    other_cluster_repo = SqlAlchemyClusterRepository(db_session)
    other_member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(other_tenant.id))

    other_cluster = await other_cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(other_tenant.id),
            label="Other tenant cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )
    await other_member_repo.add_member(other_cluster.id, identity_id=str(uuid.uuid4()), similarity=0.55)

    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    members = await member_repo.get_by_cluster(other_cluster.id)

    assert members == []


# ---------------------------------------------------------------------------
# Phase 1: Conflict-safe bulk membership scaffolds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_add_members_if_not_exists_inserts_new_rows(db_session, tenant) -> None:
    """bulk_add_members_if_not_exists should insert all rows when none exist."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Conflict-safe cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )

    members = [
        MemberData(identity_id=str(uuid.uuid4()), similarity=0.85),
        MemberData(identity_id=str(uuid.uuid4()), similarity=0.86),
    ]
    created, skipped = await member_repo.bulk_add_members_if_not_exists(cluster.id, members)

    assert len(created) == 2
    assert skipped == 0
    stored = await member_repo.get_by_cluster(cluster.id)
    assert {m.identity_id for m in stored} == {m.identity_id for m in members}


@pytest.mark.asyncio
async def test_bulk_add_members_if_not_exists_skips_duplicates(db_session, tenant) -> None:
    """bulk_add_members_if_not_exists must not raise on duplicate identity inserts.

    This is the regression guard for planner overlap: calling persist_new_cluster()
    twice with the same identity must not produce an integrity error.
    """
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Idempotent cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )

    identity_id = str(uuid.uuid4())
    first_member = MemberData(identity_id=identity_id, similarity=0.9)

    # Insert once
    await member_repo.add_member(cluster.id, identity_id=identity_id, similarity=0.9)

    # Attempt to insert the same identity again via conflict-safe path
    created, skipped = await member_repo.bulk_add_members_if_not_exists(cluster.id, [first_member])

    assert len(created) == 0
    assert skipped == 1

    # Exactly one row in the cluster
    stored = await member_repo.get_by_cluster(cluster.id)
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_bulk_add_members_if_not_exists_returns_empty_for_empty_input(db_session, tenant) -> None:
    """bulk_add_members_if_not_exists on empty list returns empty result without error."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Empty cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )

    created, skipped = await member_repo.bulk_add_members_if_not_exists(cluster.id, [])

    assert created == []
    assert skipped == 0
