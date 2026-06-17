"""Integration tests for auto-labeling during cluster creation."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import AutoLabelSettings, ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemyMemberRepository


def make_identity(tenant_id: str) -> MediaIdentity:
    """Create a synthetic identity with a deterministic 512D embedding."""
    embedding = np.zeros(512, dtype=np.float32)
    embedding[0] = 1.0
    return MediaIdentity(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        media_id=str(uuid.uuid4()),
        embedding=embedding,
        confidence=0.95,
        bbox_width=10,
        bbox_height=10,
    )


@pytest.mark.asyncio
async def test_persist_new_cluster_applies_auto_label_when_criteria_met(db_session, tenant, seed_media_identity) -> None:
    settings = ClusteringSettings(auto_label=AutoLabelSettings(min_members=3, similarity_floor=0.85))
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    writer = AssignmentWriter(settings, cluster_repo, member_repo, session=db_session)

    identities = [make_identity(str(tenant.id)) for _ in range(5)]
    for identity in identities:
        await seed_media_identity(identity.id)
    similarities = [0.90, 0.88, 0.92, 0.89, 0.91]

    cluster = await writer.persist_new_cluster(
        tenant_id=str(tenant.id),
        identities=identities,
        similarities=similarities,
        algorithm="hdbscan",
    )

    assert cluster.label == "Person 1"
    assert cluster.user_confirmed is False
    assert cluster.is_labeled is True


@pytest.mark.asyncio
async def test_persist_new_cluster_skips_auto_label_for_manual_clusters(db_session, tenant, seed_media_identity) -> None:
    settings = ClusteringSettings(auto_label=AutoLabelSettings(min_members=3, similarity_floor=0.85))
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    writer = AssignmentWriter(settings, cluster_repo, member_repo, session=db_session)

    identities = [make_identity(str(tenant.id)) for _ in range(4)]
    for identity in identities:
        await seed_media_identity(identity.id)
    similarities = [0.95, 0.95, 0.95, 0.95]

    cluster = await writer.persist_new_cluster(
        tenant_id=str(tenant.id),
        identities=identities,
        similarities=similarities,
        algorithm="manual",
    )

    assert cluster.label is None
    assert cluster.is_labeled is False


@pytest.mark.asyncio
async def test_persist_new_cluster_skips_auto_label_below_threshold(db_session, tenant, seed_media_identity) -> None:
    settings = ClusteringSettings(auto_label=AutoLabelSettings(min_members=3, similarity_floor=0.85))
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    member_repo = SqlAlchemyMemberRepository(db_session, tenant_id=str(tenant.id))
    writer = AssignmentWriter(settings, cluster_repo, member_repo, session=db_session)

    identities = [make_identity(str(tenant.id)) for _ in range(5)]
    for identity in identities:
        await seed_media_identity(identity.id)
    similarities = [0.70, 0.72, 0.68, 0.74, 0.71]

    cluster = await writer.persist_new_cluster(
        tenant_id=str(tenant.id),
        identities=identities,
        similarities=similarities,
        algorithm="hdbscan",
    )

    assert cluster.label is None
    assert cluster.is_labeled is False
