"""Integration tests for label inference service using in-memory DB."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityMember, MediaIdentity, Tenant
from recognition.application.suggestions.label_inference import infer_suggested_label
from recognition.domain.suggestion import SuggestedLabelSource


@pytest.mark.asyncio
@pytest.mark.skip(reason="Vector search not supported in SQLite")
async def test_infer_suggested_label_from_similar_cluster(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    # 1. Setup Data
    tenant_id = tenant.id

    # Create target cluster (unlabeled)
    target_cluster_id = uuid.uuid4()
    target_rep_id = uuid.uuid4()

    target_rep = MediaIdentity(
        id=target_rep_id,
        tenant_id=tenant_id,
        media_id=1,
        media_url="http://example.test/1.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=[0.1] * 512,  # Unit vector approx
    )
    db_session.add(target_rep)

    target_cluster = IdentityCluster(
        id=target_cluster_id,
        tenant_id=tenant_id,
        label=None,
        representative_identity_id=target_rep_id,
        identity_count=1,
        user_confirmed=False,
    )
    db_session.add(target_cluster)

    # Create neighbor cluster (labeled "Alice")
    # High similarity: same embedding direction
    neighbor_cluster_id = uuid.uuid4()
    neighbor_rep_id = uuid.uuid4()

    neighbor_rep = MediaIdentity(
        id=neighbor_rep_id,
        tenant_id=tenant_id,
        media_id=2,
        media_url="http://example.test/2.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        # Same direction, slightly different magnitude usually normalized but pgvector handles it
        embedding=[0.1] * 512,
    )
    db_session.add(neighbor_rep)

    neighbor_cluster = IdentityCluster(
        id=neighbor_cluster_id,
        tenant_id=tenant_id,
        label="Alice",  # Labeled
        representative_identity_id=neighbor_rep_id,
        identity_count=5,
        user_confirmed=True,
    )
    db_session.add(neighbor_cluster)

    await db_session.commit()

    # 2. Execute Inference
    result = await infer_suggested_label(
        tenant_id=str(tenant_id), cluster_id=str(target_cluster_id), session=db_session
    )

    # 3. Verify
    assert result is not None
    assert result.label == "Alice"
    assert result.source == SuggestedLabelSource.SIMILAR_CLUSTER
    assert result.confidence >= 0.99  # Identical embeddings -> high similarity


@pytest.mark.asyncio
@pytest.mark.skip(reason="Vector search not supported in SQLite")
async def test_infer_suggested_label_no_match_low_similarity(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    # 1. Setup Data - Orthogonal embeddings
    tenant_id = tenant.id
    target_cluster_id = uuid.uuid4()
    target_rep_id = uuid.uuid4()

    target_rep = MediaIdentity(
        id=target_rep_id,
        tenant_id=tenant_id,
        media_id=3,
        media_url="url",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.9,
        embedding=[1.0] + [0.0] * 511,  # X-axis
    )
    db_session.add(target_rep)

    target_cluster = IdentityCluster(
        id=target_cluster_id,
        tenant_id=tenant_id,
        label=None,
        representative_identity_id=target_rep_id,
    )
    db_session.add(target_cluster)

    neighbor_cluster_id = uuid.uuid4()
    neighbor_rep_id = uuid.uuid4()

    neighbor_rep = MediaIdentity(
        id=neighbor_rep_id,
        tenant_id=tenant_id,
        media_id=4,
        media_url="url",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.9,
        embedding=[0.0, 1.0] + [0.0] * 510,  # Y-axis: Orthogonal, similarity = 0
    )
    db_session.add(neighbor_rep)

    neighbor_cluster = IdentityCluster(
        id=neighbor_cluster_id,
        tenant_id=tenant_id,
        label="Bob",
        representative_identity_id=neighbor_rep_id,
    )
    db_session.add(neighbor_cluster)

    await db_session.commit()

    # 2. Execute
    result = await infer_suggested_label(
        tenant_id=str(tenant_id), cluster_id=str(target_cluster_id), session=db_session
    )

    # 3. Verify
    assert result is None


@pytest.mark.asyncio
async def test_infer_suggested_label_from_identity_match_deprecated(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    # 1. Setup Data - Cluster linked to Identity that has a name (Legacy Match)
    uuid.uuid4()

    # In legacy/mixed state, a cluster might be created for an Identity that already exists
    # but the cluster itself is unlabeled. If the Identity has a name, we suggest it.

    # Create Identity (Legacy concept, but table likely exists or we simulate match)
    # Actually, the spec says: "Matched identity name (if suggestion links to a known identity)"
    # This implies we look at Merge Suggestions or Identity-Cluster links?
    # For MVP, let's assume if cluster.identity_id is set (if that field exists) or if
    # we have a way to link them.
    # Checking `IdentityCluster` model in `db/models.py` would be good.
    # Assuming `identity_id` exists on Cluster based on context, or we use `IdentitySuggestion`.

    # IF `IdentityCluster` has no `identity_id` column, maybe we use `IdentitySuggestion` table?
    # "if suggestion links to a known identity" -> Suggestion table.

    pass  # TODO: Implement after confirming model


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
        # Note: If we swap IDs, the suggestion is still valid but A/B mapping changes.
        # However, merge suggestion just says "these two should merge".
        # If we infer label for 'cluster_a', we check if it is part of the pair.
        # But wait, my test logic expects 'cluster_a' to be the one we are inferring FOR.
        # If I swap them in the suggestion record, I must ensure 'suggestion.cluster_a_id' matches 'cluster_a.id' OR 'cluster_b.id'.
        # Actually, the logic looks for BOTH directions: (A==ID and B==Target) OR (B==ID and A==Target).
        # So swapping is fine for the query logic I implemented!
        pass

    from db.models.constraints import ClusterMergeSuggestion

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
    from db.models.constraints import IdentitySuggestion

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
async def test_infer_suggested_label_from_roster_match(
    db_session: AsyncSession,
    tenant: Tenant,
) -> None:
    # Create temporary roster_entries table for test context
    # SQLite syntax is compatible with raw text execution in SQLAlchemy
    from sqlalchemy import text

    await db_session.execute(text("CREATE TABLE IF NOT EXISTS roster_entries (id UUID PRIMARY KEY, name TEXT)"))

    roster_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO roster_entries (id, name) VALUES (:id, :name)"), {"id": str(roster_id), "name": "Roster Dave"}
    )

    # Setup target cluster pointing to this roster ID
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
    )
    db_session.add(rep)

    target_cluster = IdentityCluster(
        id=target_cluster_id,
        tenant_id=tenant_id,
        label=None,
        identity_count=1,
        representative_identity_id=rep_id,
        roster_id=roster_id,  # Link to the roster entry
    )
    db_session.add(target_cluster)
    await db_session.commit()

    # Execute
    result = await infer_suggested_label(
        tenant_id=str(tenant_id), cluster_id=str(target_cluster_id), session=db_session
    )

    # Verify
    assert result is not None
    assert result.label == "Roster Dave"
    assert result.source == SuggestedLabelSource.ROSTER
    assert result.confidence == 1.0
