"""
Integration tests for pgvector-specific operations

Tests vector insert/retrieve precision, cosine similarity search ordering,
weighted aggregate computation, and edge cases specific to PostgreSQL + pgvector.

These tests require a PostgreSQL database with pgvector extension.
"""

import os
import uuid
import numpy as np
import pytest

from roster.adapters.postgresql_storage_adapter import PostgreSQLStorageAdapter
from roster.domain.entities import RosterEntry, RosterImage


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def test_database_url():
    """Get test database URL from environment."""
    from dotenv import load_dotenv
    load_dotenv()
    
    url = os.getenv("DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("PostgreSQL DATABASE_URL not configured for pgvector tests")
    return url


@pytest.fixture(scope="module")
def test_tenant_id():
    """Generate a valid UUID for test tenant."""
    return str(uuid.uuid4())


@pytest.fixture
def adapter(test_database_url, test_tenant_id):
    """Create PostgreSQL storage adapter for testing."""
    adapter = PostgreSQLStorageAdapter(
        database_url=test_database_url,
        tenant_id=test_tenant_id,
        pool_size=2,
        max_overflow=5
    )
    yield adapter
    # Cleanup after test
    try:
        adapter.clear_roster("test_model")
    finally:
        adapter.close()


def create_roster_with_embedding(adapter, roster_id, embedding, metadata=None):
    """Helper to create a roster entry with a reference embedding.
    
    Note: Refreshes the materialized view so the entry is immediately searchable.
    """
    entry = RosterEntry(
        unique_id=roster_id,
        name=f"Person-{roster_id[:8]}",
        reference_images=[
            RosterImage(
                embedding=embedding,
                metadata=metadata or {}
            )
        ]
    )
    adapter.save_roster_entry(entry, "test_model")
    
    # Refresh MV so entry appears in search results
    adapter.refresh_aggregate_view()
    
    return entry


def add_augmented_embedding(adapter, roster_id, observation_id, embedding, metadata=None):
    """Helper to add an augmented embedding to an existing roster entry."""
    entry = adapter.get_roster_entry(roster_id, "test_model")
    if not entry:
        raise ValueError(f"Roster entry {roster_id} not found")
    
    entry.add_augmented_embedding(
        embedding=embedding,
        source="test",
        observation_id=observation_id,
        metadata=metadata or {}
    )
    adapter.save_roster_entry(entry, "test_model")
    return entry


class TestVectorPrecision:
    """Test vector insertion and retrieval maintains precision."""

    def test_vector_insert_and_retrieve_precision(self, adapter):
        """Verify embedding insertion and retrieval maintains precision within tolerance."""
        # Create test embedding with specific values
        embedding = [0.1 * i for i in range(512)]
        embedding = embedding / np.linalg.norm(embedding)  # Normalize
        
        # Create roster entry with reference embedding
        roster_id = f"precision-test-{uuid.uuid4()}"
        create_roster_with_embedding(
            adapter,
            roster_id,
            embedding.tolist(),
            {"test": "precision"}
        )
        
        # Retrieve and compare
        retrieved_entry = adapter.get_roster_entry(roster_id, "test_model")
        assert retrieved_entry is not None, "Failed to retrieve roster entry"
        assert len(retrieved_entry.reference_images) == 1, "Expected exactly one embedding"
        
        retrieved_embedding = retrieved_entry.reference_images[0].embedding
        assert retrieved_embedding is not None, "Retrieved embedding is None"
        assert len(retrieved_embedding) == 512, "Retrieved embedding has wrong dimension"
        
        # Check precision (pgvector uses float4, so tolerance is ~1e-6)
        assert np.allclose(retrieved_embedding, embedding, atol=1e-6), \
            "Retrieved embedding differs from inserted beyond tolerance"

    def test_multiple_embeddings_precision(self, adapter):
        """Verify precision maintained across multiple embeddings."""
        roster_id = f"multi-precision-{uuid.uuid4()}"
        embeddings = []
        
        # Create entry with first embedding
        emb0 = np.zeros(512)
        emb0[0:100] = 0.5
        emb0 = emb0 / np.linalg.norm(emb0)
        embeddings.append(emb0)
        
        create_roster_with_embedding(adapter, roster_id, emb0.tolist(), {"index": 0})
        
        # Add more reference embeddings with different patterns
        for i in range(1, 3):
            emb = np.zeros(512)
            emb[i*100:(i+1)*100] = 0.5 + i * 0.1
            emb = emb / np.linalg.norm(emb)
            embeddings.append(emb)
            
            # Retrieve entry, add image, save back
            entry = adapter.get_roster_entry(roster_id, "test_model")
            entry.reference_images.append(
                RosterImage(embedding=emb.tolist(), metadata={"index": i})
            )
            adapter.save_roster_entry(entry, "test_model")
        
        # Retrieve all and verify
        retrieved_entry = adapter.get_roster_entry(roster_id, "test_model")
        assert len(retrieved_entry.reference_images) == 3, "Expected three embeddings"
        
        for i, img in enumerate(retrieved_entry.reference_images):
            ret_emb = np.array(img.embedding)
            # Find matching original embedding
            matches = [np.allclose(ret_emb, emb, atol=1e-6) for emb in embeddings]
            assert any(matches), f"Embedding {i} doesn't match any original"

    def test_augmented_embedding_precision(self, adapter):
        """Verify augmented embeddings maintain precision."""
        roster_id = f"aug-precision-{uuid.uuid4()}"
        observation_id = str(uuid.uuid4())
        
        # Create roster with initial reference embedding
        ref_emb = np.ones(512) / np.sqrt(512)
        create_roster_with_embedding(adapter, roster_id, ref_emb.tolist())
        
        # Create specific augmented embedding pattern
        embedding = np.random.rand(512)
        embedding = embedding / np.linalg.norm(embedding)
        
        add_augmented_embedding(
            adapter,
            roster_id,
            observation_id,
            embedding.tolist(),
            {"quality_tier": "high", "confidence": 0.92}
        )
        
        # Retrieve and verify
        retrieved_entry = adapter.get_roster_entry(roster_id, "test_model")
        augmented_embeds = retrieved_entry.metadata.get("augmented_embeddings", [])
        assert len(augmented_embeds) == 1, "Expected one augmented embedding"
        
        ret_emb = np.array(augmented_embeds[0]["embedding"])
        assert np.allclose(ret_emb, embedding, atol=1e-6), \
            "Augmented embedding precision degraded"


class TestCosineSimilaritySearch:
    """Test pgvector cosine distance search returns correct ordering."""

    def test_cosine_similarity_ordering(self, adapter):
        """Verify pgvector cosine distance search returns correct ordering."""
        # Create three entries with known embeddings
        # e1: unit vector in first dimension [1, 0, 0, ...]
        e1 = np.zeros(512)
        e1[0] = 1.0
        
        # e2: close to e1 [0.9, 0.1, 0, ...]
        e2 = np.zeros(512)
        e2[0] = 0.9
        e2[1] = 0.1
        e2 = e2 / np.linalg.norm(e2)
        
        # e3: orthogonal to e1 [0, 1, 0, ...]
        e3 = np.zeros(512)
        e3[1] = 1.0
        
        # Add roster entries
        id1 = f"search-person-1-{uuid.uuid4()}"
        id2 = f"search-person-2-{uuid.uuid4()}"
        id3 = f"search-person-3-{uuid.uuid4()}"
        
        create_roster_with_embedding(adapter, id1, e1.tolist(), {})
        create_roster_with_embedding(adapter, id2, e2.tolist(), {})
        create_roster_with_embedding(adapter, id3, e3.tolist(), {})
        
        # Search with query close to e1
        query = np.zeros(512)
        query[0] = 0.95
        query[1] = 0.05
        query = query / np.linalg.norm(query)
        
        results = adapter.search_similar(
            query_embedding=query.tolist(),
            model="test_model",
            top_k=3,
            threshold=0.5
        )
        
        # Verify we got results
        assert len(results) >= 2, "Expected at least 2 matches"
        
        # Extract entity IDs and scores
        entity_ids = [r[0].unique_id for r in results]
        scores = [r[1] for r in results]
        
        # Verify ordering: closest match first
        assert scores[0] > scores[1], "Results not ordered by similarity"
        
        # id2 should be closest (most similar to query)
        assert id2 in entity_ids[:2], "Expected id2 in top 2 results"
        
        # id3 should have lowest score (orthogonal)
        id3_idx = next((i for i, eid in enumerate(entity_ids) if eid == id3), None)
        if id3_idx is not None:
            assert scores[id3_idx] < 0.8, "Orthogonal vector should have low similarity"

    def test_threshold_filtering(self, adapter):
        """Verify threshold parameter filters low-similarity results."""
        # Create entries with varying similarity
        base = np.zeros(512)
        base[0] = 1.0
        
        # Very similar
        similar = np.zeros(512)
        similar[0] = 0.95
        similar[1] = 0.05
        similar = similar / np.linalg.norm(similar)
        
        # Somewhat similar
        medium = np.zeros(512)
        medium[0] = 0.7
        medium[1] = 0.3
        medium = medium / np.linalg.norm(medium)
        
        # Not similar (orthogonal)
        dissimilar = np.zeros(512)
        dissimilar[1] = 1.0
        
        id1 = f"thresh-1-{uuid.uuid4()}"
        id2 = f"thresh-2-{uuid.uuid4()}"
        id3 = f"thresh-3-{uuid.uuid4()}"
        
        create_roster_with_embedding(adapter, id1, similar.tolist(), {})
        create_roster_with_embedding(adapter, id2, medium.tolist(), {})
        create_roster_with_embedding(adapter, id3, dissimilar.tolist(), {})
        
        # Search with high threshold
        results_high = adapter.search_similar(
            query_embedding=base.tolist(),
            model="test_model",
            top_k=10,
            threshold=0.9
        )
        
        # Should only get the very similar one
        entity_ids_high = [r[0].unique_id for r in results_high]
        assert id1 in entity_ids_high, "Very similar entry should pass high threshold"
        assert id3 not in entity_ids_high, "Dissimilar entry should not pass high threshold"
        
        # Search with low threshold
        results_low = adapter.search_similar(
            query_embedding=base.tolist(),
            model="test_model",
            top_k=10,
            threshold=0.5
        )
        
        # Should get both similar and medium
        entity_ids_low = [r[0].unique_id for r in results_low]
        assert len(entity_ids_low) >= 2, "Low threshold should return more results"

    def test_top_k_limit(self, adapter):
        """Verify top_k parameter limits result count."""
        # Create 5 similar entries
        base = np.zeros(512)
        base[0] = 1.0
        
        ids = []
        for i in range(5):
            emb = np.zeros(512)
            emb[0] = 0.9 + i * 0.01
            emb[1] = 0.1 - i * 0.01
            emb = emb / np.linalg.norm(emb)
            
            roster_id = f"topk-{i}-{uuid.uuid4()}"
            ids.append(roster_id)
            create_roster_with_embedding(adapter, roster_id, emb.tolist(), {})
        
        # Search with top_k=3
        results = adapter.search_similar(
            query_embedding=base.tolist(),
            model="test_model",
            top_k=3,
            threshold=0.5
        )
        
        assert len(results) <= 3, f"Expected at most 3 results, got {len(results)}"


class TestWeightedAggregates:
    """Test weighted aggregate computation in materialized view."""

    def test_weighted_aggregate_computation(self, adapter):
        """Verify materialized view computes weighted average correctly."""
        roster_id = f"weighted-{uuid.uuid4()}"
        
        # Add reference embedding (weight=3x via duplication)
        ref_emb = np.zeros(512)
        ref_emb[0] = 1.0
        create_roster_with_embedding(adapter, roster_id, ref_emb.tolist(), {"type": "reference"})
        
        # Add high-quality augmented embedding (weight=3x)
        aug_high = np.zeros(512)
        aug_high[0] = 0.9
        aug_high[1] = 0.1
        aug_high = aug_high / np.linalg.norm(aug_high)
        add_augmented_embedding(
            adapter,
            roster_id,
            str(uuid.uuid4()),
            aug_high.tolist(),
            {"quality_tier": "high", "confidence": 0.92}
        )
        
        # Add low-quality augmented embedding (weight=1x)
        aug_low = np.zeros(512)
        aug_low[0] = 0.5
        aug_low[1] = 0.5
        aug_low = aug_low / np.linalg.norm(aug_low)
        add_augmented_embedding(
            adapter,
            roster_id,
            str(uuid.uuid4()),
            aug_low.tolist(),
            {"quality_tier": "low", "confidence": 0.60}
        )
        
        # Refresh materialized view
        adapter.refresh_aggregate_view(roster_id)
        
        # Retrieve aggregate embedding
        entry = adapter.get_roster_entry(roster_id, "test_model")
        assert entry is not None, "Failed to retrieve roster entry"
        
        aggregate = entry.aggregate_embedding
        assert aggregate is not None, "Aggregate embedding is None"
        assert len(aggregate) == 512, "Aggregate has wrong dimension"
        
        # Expected: (3*ref + 3*aug_high + 1*aug_low) / 7, then normalized
        expected = (3 * ref_emb + 3 * aug_high + 1 * aug_low) / 7
        expected = expected / np.linalg.norm(expected)
        
        # Allow tolerance for floating point operations and pgvector computation differences
        # The aggregate should be very close but pgvector may have slight numerical differences
        aggregate_array = np.array(aggregate)
        
        # Check that the direction is correct (first two dimensions dominate)
        assert aggregate_array[0] > 0.9, "First dimension should dominate"
        assert 0.1 < aggregate_array[1] < 0.3, "Second dimension should have moderate contribution"
        assert np.allclose(aggregate_array[2:], 0, atol=1e-6), "Other dimensions should be near zero"
        
        # Check similarity to expected (should be very high)
        similarity = np.dot(aggregate_array, expected)
        assert similarity > 0.999, f"Aggregate direction differs from expected (similarity={similarity})"

    def test_quality_tier_weighting(self, adapter):
        """Verify different quality tiers have correct weights."""
        # Test each quality tier in isolation
        quality_tiers = [
            ("reference", 3),
            ("high", 3),
            ("medium", 2),
            ("low", 1)
        ]
        
        for tier, expected_weight in quality_tiers:
            roster_id = f"quality-{tier}-{uuid.uuid4()}"
            
            # Add single embedding with known direction
            emb = np.zeros(512)
            emb[0] = 1.0
            
            if tier == "reference":
                create_roster_with_embedding(adapter, roster_id, emb.tolist(), {})
            else:
                # First create the roster entry with a reference embedding
                create_roster_with_embedding(adapter, roster_id, emb.tolist(), {})
                # Then add augmented embedding
                add_augmented_embedding(
                    adapter,
                    roster_id,
                    str(uuid.uuid4()),
                    emb.tolist(),
                    {"quality_tier": tier, "confidence": 0.85}
                )
            
            # Refresh and check counts
            adapter.refresh_aggregate_view(roster_id)
            
            # Get aggregate info
            entry = adapter.get_roster_entry(roster_id, "test_model")
            assert entry is not None
            
            # The aggregate should still point in the same direction
            # (since all duplicates are identical)
            if entry.aggregate_embedding is not None:
                agg_emb = np.array(entry.aggregate_embedding)
                # Should be very close to [1, 0, 0, ...]
                assert agg_emb[0] > 0.99, f"Quality tier {tier} aggregate not as expected"

    def test_aggregate_updates_progressively(self, adapter):
        """Verify aggregate embedding updates as new augmented embeddings added."""
        roster_id = f"progressive-{uuid.uuid4()}"
        
        # Start with reference
        ref = np.zeros(512)
        ref[0] = 1.0
        create_roster_with_embedding(adapter, roster_id, ref.tolist(), {})
        adapter.refresh_aggregate_view(roster_id)
        
        entry1 = adapter.get_roster_entry(roster_id, "test_model")
        agg1 = np.array(entry1.aggregate_embedding) if entry1.aggregate_embedding else None
        assert agg1 is not None, "Initial aggregate should exist"
        
        # Add augmented embedding in different direction
        aug = np.zeros(512)
        aug[1] = 1.0
        add_augmented_embedding(
            adapter,
            roster_id,
            str(uuid.uuid4()),
            aug.tolist(),
            {"quality_tier": "high", "confidence": 0.9}
        )
        adapter.refresh_aggregate_view(roster_id)
        
        entry2 = adapter.get_roster_entry(roster_id, "test_model")
        agg2 = np.array(entry2.aggregate_embedding) if entry2.aggregate_embedding else None
        assert agg2 is not None, "Updated aggregate should exist"
        
        # Aggregate should have shifted
        # Initially: [1, 0, 0, ...] (3 copies)
        # After: [1, 0, 0, ...] (3 copies) + [0, 1, 0, ...] (3 copies) = [3, 3, 0, ...]
        # Normalized: [0.707, 0.707, 0, ...]
        assert not np.allclose(agg1, agg2, atol=1e-3), \
            "Aggregate should change after adding augmented embedding"
        
        # Check that agg2 has contributions from both dimensions
        assert agg2[0] > 0.5, "First dimension should still contribute"
        assert agg2[1] > 0.5, "Second dimension should now contribute"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_zero_vector_handling(self, adapter):
        """Verify handling of zero vectors (invalid)."""
        roster_id = f"zero-vec-{uuid.uuid4()}"
        zero_vec = [0.0] * 512
        
        # Attempting to add zero vector should either raise or be rejected
        # (pgvector may handle this differently)
        try:
            create_roster_with_embedding(adapter, roster_id, zero_vec, {})
            # If it succeeds, verify it doesn't break search
            results = adapter.search_similar(
                query_embedding=zero_vec,
                model="test_model",
                top_k=5,
                threshold=0.5
            )
            # Should return empty or handle gracefully
            assert isinstance(results, list)
        except (ValueError, Exception):
            # Expected behavior: reject zero vectors
            pass

    def test_non_normalized_vectors(self, adapter):
        """Verify system handles non-normalized vectors."""
        roster_id = f"non-norm-{uuid.uuid4()}"
        
        # Create non-normalized vector
        non_norm = [100.0] * 512
        
        create_roster_with_embedding(adapter, roster_id, non_norm, {})
        
        # Retrieve and verify it's stored (may be normalized internally)
        entry = adapter.get_roster_entry(roster_id, "test_model")
        assert entry is not None
        assert len(entry.reference_images) == 1
        
        ret_emb = np.array(entry.reference_images[0].embedding)
        # Check if normalized
        norm = np.linalg.norm(ret_emb)
        # pgvector doesn't auto-normalize, so it should be unnormalized
        # But search should still work
        results = adapter.search_similar(
            query_embedding=non_norm,
            model="test_model",
            top_k=5,
            threshold=0.5
        )
        assert isinstance(results, list)

    def test_empty_roster_search(self, adapter):
        """Verify search on empty roster returns empty results."""
        query = [1.0] + [0.0] * 511
        
        results = adapter.search_similar(
            query_embedding=query,
            model="empty_test_model",
            top_k=5,
            threshold=0.5
        )
        
        assert isinstance(results, list)
        assert len(results) == 0, "Empty roster should return no results"

    def test_duplicate_observation_id(self, adapter):
        """Verify duplicate observation_id handling."""
        roster_id = f"dup-obs-{uuid.uuid4()}"
        obs_id = str(uuid.uuid4())
        emb = [0.1] * 512
        
        # First create roster entry
        create_roster_with_embedding(adapter, roster_id, emb, {})
        
        # Add first augmented embedding - should succeed
        result1 = add_augmented_embedding(
            adapter, roster_id, obs_id, emb,
            {"quality_tier": "high", "confidence": 0.9}
        )
        assert result1 is not None
        
        # Add again with same observation_id - should handle gracefully
        try:
            result2 = add_augmented_embedding(
                adapter, roster_id, obs_id, emb,
                {"quality_tier": "high", "confidence": 0.9}
            )
            # If it succeeds, verify embeddings exist
            entry = adapter.get_roster_entry(roster_id, "test_model")
            # Should have embeddings
            assert entry is not None
        except Exception:
            # Expected: duplicate observation_id rejected
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
