"""Integration tests for label inference service using in-memory DB."""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityClusterRepresentative, IdentityMember, MediaIdentity, Tenant
from db.models.constraints import ClusterMergeSuggestion, IdentitySuggestion
from recognition.application.suggestions.label_inference import infer_suggested_label
from recognition.domain.suggestion import SuggestedLabelSource
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository


@pytest.mark.asyncio
async def test_infer_suggested_label_from_merge_suggestion_above_threshold(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    """Pending merge suggestions above threshold should infer a label."""
    tenant_id = tenant.id

    target_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label=None,
        identity_count=4,
        user_confirmed=False,
    )
    labeled_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label="Alice",
        identity_count=10,
        user_confirmed=True,
    )
    db_session.add_all([target_cluster, labeled_cluster])

    id_a, id_b = target_cluster.id, labeled_cluster.id
    if id_a > id_b:
        id_a, id_b = id_b, id_a

    db_session.add(
        ClusterMergeSuggestion(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            cluster_a_id=id_a,
            cluster_b_id=id_b,
            similarity=0.92,
            resolution="pending",
        )
    )
    await db_session.commit()

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_cluster.id),
        session=db_session,
    )

    assert result is not None
    assert result.label == "Alice"
    assert result.source == SuggestedLabelSource.SIMILAR_CLUSTER
    assert result.confidence == 0.92
    assert result.target_cluster_id == str(labeled_cluster.id)


@pytest.mark.asyncio
async def test_infer_suggested_label_merge_suggestion_below_threshold_returns_none(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    """Merge suggestions below threshold should not infer a label."""
    tenant_id = tenant.id

    target_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label=None,
        identity_count=2,
        representative_identity_id=None,
        user_confirmed=False,
    )
    labeled_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label="Bob",
        identity_count=8,
        user_confirmed=True,
    )
    db_session.add_all([target_cluster, labeled_cluster])

    id_a, id_b = target_cluster.id, labeled_cluster.id
    if id_a > id_b:
        id_a, id_b = id_b, id_a

    db_session.add(
        ClusterMergeSuggestion(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            cluster_a_id=id_a,
            cluster_b_id=id_b,
            similarity=0.2,
            resolution="pending",
        )
    )
    await db_session.commit()

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_cluster.id),
        session=db_session,
    )

    assert result is None


@pytest.mark.asyncio
async def test_infer_suggested_label_returns_none_for_invalid_identifiers(
    db_session: AsyncSession,
) -> None:
    """Invalid UUIDs should short-circuit inference and return None."""
    result = await infer_suggested_label(
        tenant_id="not-a-uuid",
        cluster_id="also-not-a-uuid",
        session=db_session,
    )
    assert result is None


@pytest.mark.asyncio
async def test_infer_suggested_label_from_merge_suggestion(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    # 1. Setup Data - Cluster A (unlabeled) and Cluster B (labeled) with a Merge Suggestion
    tenant_id = tenant.id

    # Cluster A (Unlabeled target)
    rep_a_id = uuid.uuid4()
    rep_a = MediaIdentity(
        id=rep_a_id,
        tenant_id=tenant_id,
        media_id=1,
        media_url="url",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.9,
        embedding=[0.1] * 512,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(rep_a)

    cluster_a = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label=None,
        identity_count=5,
        representative_identity_id=rep_a_id,
    )
    db_session.add(cluster_a)

    # Cluster B (Labeled "Charlie")
    cluster_b = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label="Charlie",
        identity_count=10,
    )
    db_session.add(cluster_b)

    # Merge Suggestion A -> B (ensure canonical order)
    id_a = cluster_a.id
    id_b = cluster_b.id
    if id_a > id_b:
        id_a, id_b = id_b, id_a

    suggestion = ClusterMergeSuggestion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        cluster_a_id=id_a,
        cluster_b_id=id_b,
        similarity=0.88,
        resolution="pending",
    )
    db_session.add(suggestion)
    await db_session.commit()

    # 2. Execute
    result = await infer_suggested_label(tenant_id=str(tenant_id), cluster_id=str(cluster_a.id), session=db_session)

    # 3. Verify
    assert result is not None
    assert result.label == "Charlie"
    assert result.source == SuggestedLabelSource.SIMILAR_CLUSTER
    assert result.confidence == 0.88


@pytest.mark.asyncio
async def test_infer_suggested_label_from_identity_match(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    """Test inference from pending IdentitySuggestion linking member -> labeled cluster."""
    tenant_id = tenant.id

    # 1. Setup Target Cluster (Unlabeled)
    # It has a member "MemberIdentity" which also serves as representative for simplicity
    member_identity_id = uuid.uuid4()
    member_identity = MediaIdentity(
        id=member_identity_id,
        tenant_id=tenant_id,
        media_id=10,
        media_url="url",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=[0.0] * 512,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(member_identity)

    target_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label=None,
        identity_count=1,
        representative_identity_id=member_identity_id,
    )
    db_session.add(target_cluster)

    # Link member to target cluster
    member_rel = IdentityMember(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        cluster_id=target_cluster.id,
        identity_id=member_identity_id,
        similarity=0.9,
    )
    db_session.add(member_rel)

    # 2. Setup "Known Identity" / Labeled Cluster
    # Imagine there's another cluster labeled "Dave"
    labeled_cluster = IdentityCluster(id=uuid.uuid4(), tenant_id=tenant_id, label="Dave", identity_count=5)
    db_session.add(labeled_cluster)

    # 3. Create Suggestion: Member -> Labeled Cluster
    # This implies "MemberIdentity" might be "Dave"
    suggestion = IdentitySuggestion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        identity_id=member_identity_id,
        suggested_cluster_id=labeled_cluster.id,
        representative_similarity=0.92,
        avg_member_similarity=0.90,
        confidence_score=0.91,
        resolution="pending",
    )
    db_session.add(suggestion)
    await db_session.commit()

    # 4. Execute Inference
    result = await infer_suggested_label(
        tenant_id=str(tenant_id), cluster_id=str(target_cluster.id), session=db_session
    )

    # 5. Verify
    # Should suggest "Dave" because one of its members is suggested to be Dave
    assert result is not None, "Should infer label from identity suggestion"
    assert result.label == "Dave"
    assert result.source == SuggestedLabelSource.IDENTITY
    assert result.confidence == 0.91


@pytest.mark.asyncio
async def test_infer_suggested_label_from_accepted_member_suggestion_without_representative(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    """Accepted member suggestions should infer label even when representative linkage is missing."""
    tenant_id = tenant.id

    # Unlabeled source cluster intentionally has no representative_identity_id.
    source_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label=None,
        identity_count=1,
        representative_identity_id=None,
    )
    db_session.add(source_cluster)

    member_identity = MediaIdentity(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        media_id=11,
        media_url="url",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=[0.0] * 512,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(member_identity)
    db_session.add(
        IdentityMember(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            cluster_id=source_cluster.id,
            identity_id=member_identity.id,
            similarity=0.75,
        )
    )

    # Confirmed labeled target cluster.
    labeled_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label="Slate Willow",
        identity_count=10,
        user_confirmed=True,
    )
    db_session.add(labeled_cluster)

    # Low confidence is intentional: accepted suggestions should still be surfaced.
    db_session.add(
        IdentitySuggestion(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            identity_id=member_identity.id,
            suggested_cluster_id=labeled_cluster.id,
            representative_similarity=0.41,
            avg_member_similarity=0.41,
            confidence_score=0.41,
            resolution="accepted",
        )
    )
    await db_session.commit()

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(source_cluster.id),
        session=db_session,
    )

    assert result is not None
    assert result.label == "Slate Willow"
    assert result.source == SuggestedLabelSource.IDENTITY
    assert result.target_cluster_id == str(labeled_cluster.id)


@pytest.mark.asyncio
async def test_infer_suggested_label_prefers_accepted_member_signal_over_conflicting_merge_suggestion(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    """Accepted member evidence should win over a stronger conflicting merge suggestion."""
    tenant_id = tenant.id

    source_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label=None,
        identity_count=1,
        representative_identity_id=None,
    )
    accepted_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label="Accepted Label",
        identity_count=8,
        user_confirmed=True,
    )
    conflicting_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label="Conflicting Label",
        identity_count=9,
        user_confirmed=True,
    )
    db_session.add_all([source_cluster, accepted_cluster, conflicting_cluster])

    member_identity = MediaIdentity(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        media_id=12,
        media_url="url",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=[0.0] * 512,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(member_identity)
    db_session.add(
        IdentityMember(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            cluster_id=source_cluster.id,
            identity_id=member_identity.id,
            similarity=0.72,
        )
    )

    db_session.add(
        IdentitySuggestion(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            identity_id=member_identity.id,
            suggested_cluster_id=accepted_cluster.id,
            representative_similarity=0.42,
            avg_member_similarity=0.42,
            confidence_score=0.42,
            resolution="accepted",
        )
    )

    merge_a = source_cluster.id
    merge_b = conflicting_cluster.id
    if merge_a > merge_b:
        merge_a, merge_b = merge_b, merge_a

    db_session.add(
        ClusterMergeSuggestion(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            cluster_a_id=merge_a,
            cluster_b_id=merge_b,
            similarity=0.97,
            resolution="pending",
        )
    )
    await db_session.commit()

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(source_cluster.id),
        session=db_session,
    )

    assert result is not None
    assert result.label == "Accepted Label"
    assert result.source == SuggestedLabelSource.IDENTITY
    assert result.confidence == 0.42
    assert result.target_cluster_id == str(accepted_cluster.id)


@pytest.mark.asyncio
async def test_infer_suggested_label_from_roster_match(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    roster_id = uuid.uuid4()
    tenant_id = tenant.id
    target_cluster_id = uuid.uuid4()

    # Minimal valid rep (unused but required for integrity if constraints existed)
    rep_id = uuid.uuid4()
    rep = MediaIdentity(
        id=rep_id,
        tenant_id=tenant_id,
        media_id=999,
        media_url="url",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=[0.0] * 512,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(rep)

    target_cluster = IdentityCluster(
        id=target_cluster_id,
        tenant_id=tenant_id,
        label=None,
        identity_count=1,
        representative_identity_id=rep_id,
        roster_id=roster_id,
    )
    labeled_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label="Roster Dave",
        identity_count=2,
        representative_identity_id=rep_id,
        roster_id=roster_id,
        user_confirmed=True,
    )
    db_session.add_all([target_cluster, labeled_cluster])
    await db_session.commit()

    # Execute
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_cluster_id),
        session=db_session,
        cluster_repository=cluster_repo,
    )

    # Verify
    assert result is not None
    assert result.label == "Roster Dave"
    assert result.source == SuggestedLabelSource.ROSTER
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_infer_suggested_label_uses_representative_table_when_missing_rep_identity(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    """Inference should use representative table embeddings when representative_identity_id is null."""
    tenant_id = tenant.id

    labeled_rep = MediaIdentity(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        media_id=301,
        media_url="http://example.test/301.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=[1.0] + [0.0] * 511,
        embedding_model="buffalo_l@insightface",
    )
    labeled_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label="Casey",
        representative_identity_id=labeled_rep.id,
        identity_count=2,
        user_confirmed=True,
    )

    unlabeled_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label=None,
        representative_identity_id=None,
        identity_count=1,
        user_confirmed=False,
    )
    db_session.add_all([labeled_rep, labeled_cluster, unlabeled_cluster])
    await db_session.flush()

    db_session.add(
        IdentityClusterRepresentative(
            tenant_id=tenant_id,
            cluster_id=labeled_cluster.id,
            identity_id=labeled_rep.id,
            embedding=[1.0] + [0.0] * 511,
            quality_score=1.0,
        )
    )
    db_session.add(
        IdentityClusterRepresentative(
            tenant_id=tenant_id,
            cluster_id=unlabeled_cluster.id,
            identity_id=labeled_rep.id,
            embedding=[1.0] + [0.0] * 511,
            quality_score=1.0,
        )
    )
    await db_session.commit()

    repo = SqlAlchemyClusterRepository(db_session)
    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(unlabeled_cluster.id),
        session=db_session,
        cluster_repository=repo,
    )

    assert result is not None
    assert result.label == "Casey"
    assert result.source == SuggestedLabelSource.SIMILAR_CLUSTER


@pytest.mark.asyncio
async def test_infer_suggested_label_does_not_raise_on_numpy_embedding(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    """Embedding stored as a NumPy array must not raise ValueError on truthiness check.

    Regression test for the bug where ``if embedding:`` on a multi-element
    NumPy array raised ``ValueError: The truth value of an array with more
    than one element is ambiguous``.
    """
    tenant_id = tenant.id

    embedding_array = np.random.default_rng(42).standard_normal(512).astype(np.float32)

    rep_identity = MediaIdentity(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        media_id=9001,
        media_url="http://example.test/9001.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=embedding_array.tolist(),
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(rep_identity)

    target_cluster = IdentityCluster(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        label=None,
        identity_count=3,
        representative_identity_id=rep_identity.id,
        user_confirmed=False,
    )
    db_session.add(target_cluster)
    await db_session.commit()

    repo = SqlAlchemyClusterRepository(db_session)

    # Should not raise ValueError; returns None because no labeled clusters exist.
    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_cluster.id),
        session=db_session,
        cluster_repository=repo,
    )

    assert result is None
