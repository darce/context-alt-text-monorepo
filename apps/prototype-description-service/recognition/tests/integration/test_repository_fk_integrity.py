"""INFRA-3: repository write paths must let the FK enforce identity integrity.

Previously ``ensure_media_identity`` fabricated a placeholder ``MediaIdentity``
row inside every write path, silently masking foreign-key violations. These
tests pin the post-cleanup contract: writing a member / representative whose
``identity_id`` has no backing ``media_identities`` row raises an
``IntegrityError``. Tests that legitimately need an identity seed it explicitly
via the ``seed_media_identity`` fixture.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from recognition.domain.cluster import IdentityCluster
from recognition.domain.representative import ClusterRepresentative
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemyMemberRepository


async def _make_cluster(cluster_repo: SqlAlchemyClusterRepository, tenant_id: str) -> IdentityCluster:
    return await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label="FK cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )


@pytest.mark.asyncio
async def test_add_member_with_unknown_identity_raises_fk_error(db_session, tenant) -> None:
    """add_member must not fabricate the identity; the FK rejects the orphan write."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    cluster = await _make_cluster(cluster_repo, str(tenant.id))

    with pytest.raises(IntegrityError):
        await member_repo.add_member(cluster.id, identity_id=str(uuid.uuid4()), similarity=0.9)


@pytest.mark.asyncio
async def test_add_member_with_seeded_identity_succeeds(db_session, tenant, seed_media_identity) -> None:
    """When the identity is seeded explicitly, the same write path succeeds."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    cluster = await _make_cluster(cluster_repo, str(tenant.id))

    identity_id = str(uuid.uuid4())
    await seed_media_identity(identity_id)

    member = await member_repo.add_member(cluster.id, identity_id=identity_id, similarity=0.9)
    stored = await member_repo.get_by_cluster(cluster.id)
    assert [m.id for m in stored] == [member.id]


@pytest.mark.asyncio
async def test_save_cluster_with_unknown_representative_raises_fk_error(db_session, tenant) -> None:
    """Cluster.save must not fabricate the representative identity row."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)

    with pytest.raises(IntegrityError):
        await cluster_repo.save(
            IdentityCluster(
                id=None,
                tenant_id=str(tenant.id),
                label="Rep cluster",
                is_labeled=False,
                identity_count=0,
                created_at=None,
                representative_identity_id=str(uuid.uuid4()),
            )
        )


@pytest.mark.asyncio
async def test_add_representative_with_seeded_identity_succeeds(db_session, tenant, seed_media_identity) -> None:
    """A representative write succeeds once its identity is seeded explicitly."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await _make_cluster(cluster_repo, str(tenant.id))

    identity_id = str(uuid.uuid4())
    await seed_media_identity(identity_id)

    await cluster_repo.add_representative(
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=cluster.id,
            identity_id=identity_id,
            tenant_id=str(tenant.id),
            embedding=[0.0] * 512,
            created_at=datetime.now(UTC),
            quality_score=0.9,
        )
    )
    assert await cluster_repo.get_representative_count(cluster.id) == 1
