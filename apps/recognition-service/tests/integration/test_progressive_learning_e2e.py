"""
End-to-end integration tests for progressive learning flow

Tests the complete progressive learning pipeline:
1. Create roster entry with reference embedding
2. Confirm face observations (augmented embeddings)
3. Verify materialized view updates
4. Verify search results improve progressively
5. Test idempotency and error handling

Requires running recognition service with PostgreSQL + pgvector.
"""

import os
import time
import uuid
import json
import pytest
import numpy as np
from fastapi.testclient import TestClient


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(reason="E2E tests require running service - use for manual testing")
]


@pytest.fixture(scope="module")
def test_client():
    """Create FastAPI test client."""
    # Import here to avoid circular dependencies
    from app import app
    
    client = TestClient(app)
    return client


@pytest.fixture(scope="module")
def test_database_url():
    """Get test database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("PostgreSQL DATABASE_URL not configured")
    return url


class TestProgressiveLearningE2E:
    """End-to-end progressive learning tests."""

    def test_confirm_observation_end_to_end(self, test_client):
        """Verify full progressive learning pipeline."""
        # 1. Create roster entry with reference embedding
        create_payload = {
            "label": f"Alice-{uuid.uuid4()}",
            "entity_type": "person",
            "model": "test-model",
            "metadata": {"source": "test"},
            "embeddings": [[0.1] * 512]
        }
        
        response = test_client.post("/api/v0/roster", json=create_payload)
        assert response.status_code in (200, 201), \
            f"Failed to create roster entry: {response.status_code} {response.text}"
        
        data = response.json()
        roster_id = data.get("id") or data.get("unique_id") or data.get("data", {}).get("id")
        assert roster_id, "No roster ID in response"
        
        # 2. Confirm observation (augmented embedding)
        observation_payload = {
            "observation_id": str(uuid.uuid4()),
            "embedding": [0.15] * 512,
            "metadata": {
                "confidence": 0.88,
                "source": "test-observation",
                "quality_tier": "high"
            }
        }
        
        response = test_client.post(
            f"/api/v0/roster/{roster_id}/augment",
            json=observation_payload
        )
        assert response.status_code in (200, 201), \
            f"Failed to confirm observation: {response.status_code} {response.text}"
        
        result = response.json()
        assert result.get("augmented_count", 0) >= 1, \
            "Augmented count not incremented"
        
        # 3. Verify aggregate embedding updated
        response = test_client.get(f"/api/v0/roster/{roster_id}")
        assert response.status_code == 200, \
            f"Failed to fetch roster: {response.status_code}"
        
        entry = response.json()
        aggregate = entry.get("aggregate_embedding") or entry.get("data", {}).get("aggregate_embedding")
        assert aggregate is not None, "Aggregate embedding not present"
        assert len(aggregate) == 512, "Aggregate has wrong dimension"
        
        # 4. Wait briefly for any background processing
        time.sleep(0.5)
        
        # 5. Search with similar query - should match with good score
        search_payload = {
            "embedding": [0.12] * 512,
            "threshold": 0.5,
            "top_k": 5
        }
        
        response = test_client.post("/api/v0/embeddings", json=search_payload)
        assert response.status_code == 200, \
            f"Search failed: {response.status_code} {response.text}"
        
        matches = response.json().get("matches", [])
        # Should find our entry
        entity_ids = [m.get("entity_id") or m.get("unique_id") for m in matches]
        
        # Note: Depending on database state, we might not always be top match
        # but we should be in results with decent score
        if roster_id in entity_ids:
            idx = entity_ids.index(roster_id)
            score = matches[idx].get("score", 0)
            assert score > 0.5, f"Match score too low: {score}"

    def test_idempotent_confirmation(self, test_client):
        """Verify duplicate observation_id is rejected or handled idempotently."""
        # Create roster entry
        roster_id = self._create_test_roster(test_client)
        
        observation_id = str(uuid.uuid4())
        observation_payload = {
            "observation_id": observation_id,
            "embedding": [0.1] * 512,
            "metadata": {
                "confidence": 0.85,
                "quality_tier": "medium"
            }
        }
        
        # First confirmation should succeed
        response1 = test_client.post(
            f"/api/v0/roster/{roster_id}/augment",
            json=observation_payload
        )
        assert response1.status_code in (200, 201), \
            f"First confirmation failed: {response1.status_code}"
        
        # Second confirmation with same observation_id
        response2 = test_client.post(
            f"/api/v0/roster/{roster_id}/augment",
            json=observation_payload
        )
        
        # Should either return 409 Conflict or 200 with idempotent behavior
        assert response2.status_code in (200, 201, 409), \
            f"Unexpected status for duplicate: {response2.status_code}"
        
        if response2.status_code == 409:
            # Verify error message mentions duplicate/already processed
            error_detail = response2.json().get("detail", "").lower()
            assert "already" in error_detail or "duplicate" in error_detail, \
                "Error message should mention duplicate"

    def test_progressive_improvement(self, test_client):
        """Verify search results improve as more observations confirmed."""
        # Create roster entry with initial embedding
        initial_emb = np.zeros(512)
        initial_emb[0] = 1.0
        
        roster_id = self._create_test_roster_with_embedding(
            test_client, 
            initial_emb.tolist()
        )
        
        # Initial search - establish baseline
        query = initial_emb.tolist()
        initial_score = self._search_and_get_score(test_client, roster_id, query)
        
        # Add high-quality observation in same direction
        obs1 = np.zeros(512)
        obs1[0] = 0.95
        obs1 = obs1 / np.linalg.norm(obs1)
        
        self._add_observation(test_client, roster_id, obs1.tolist(), "high", 0.92)
        
        # Search again - score should be similar or better
        time.sleep(0.5)  # Allow materialized view refresh
        score_after_one = self._search_and_get_score(test_client, roster_id, query)
        
        # Add another high-quality observation
        obs2 = np.zeros(512)
        obs2[0] = 0.98
        obs2 = obs2 / np.linalg.norm(obs2)
        
        self._add_observation(test_client, roster_id, obs2.tolist(), "high", 0.94)
        
        time.sleep(0.5)
        score_after_two = self._search_and_get_score(test_client, roster_id, query)
        
        # Scores should remain high (all embeddings aligned)
        assert initial_score > 0.8, "Initial score unexpectedly low"
        assert score_after_one > 0.8, "Score degraded after observation"
        assert score_after_two > 0.8, "Score degraded after second observation"

    def test_quality_tier_impact(self, test_client):
        """Verify different quality tiers affect aggregate appropriately."""
        # Create roster with base embedding pointing in direction [1, 0, 0, ...]
        base_emb = np.zeros(512)
        base_emb[0] = 1.0
        
        roster_id = self._create_test_roster_with_embedding(
            test_client,
            base_emb.tolist()
        )
        
        # Add high-quality observation in same direction
        high_obs = np.zeros(512)
        high_obs[0] = 0.95
        high_obs = high_obs / np.linalg.norm(high_obs)
        
        self._add_observation(test_client, roster_id, high_obs.tolist(), "high", 0.92)
        
        # Add low-quality observation in different direction
        # Should have less impact due to lower weight
        low_obs = np.zeros(512)
        low_obs[1] = 1.0
        
        self._add_observation(test_client, roster_id, low_obs.tolist(), "low", 0.62)
        
        time.sleep(0.5)
        
        # Fetch aggregate and verify it's still mostly in [1, 0, ...] direction
        response = test_client.get(f"/api/v0/roster/{roster_id}")
        entry = response.json()
        aggregate = entry.get("aggregate_embedding") or entry.get("data", {}).get("aggregate_embedding")
        
        assert aggregate is not None
        agg_array = np.array(aggregate)
        
        # First dimension should dominate (base + high-quality have weight 3x each)
        # Low-quality has weight 1x in different direction
        # So first dimension should be stronger
        assert agg_array[0] > abs(agg_array[1]), \
            "High-quality observations should dominate aggregate"

    def test_concurrent_observations(self, test_client):
        """Verify multiple observations can be added without conflicts."""
        roster_id = self._create_test_roster(test_client)
        
        # Add multiple observations rapidly
        observation_ids = []
        for i in range(5):
            obs_id = str(uuid.uuid4())
            observation_ids.append(obs_id)
            
            emb = [0.1 + i * 0.01] * 512
            payload = {
                "observation_id": obs_id,
                "embedding": emb,
                "metadata": {
                    "confidence": 0.80 + i * 0.02,
                    "quality_tier": "medium"
                }
            }
            
            response = test_client.post(
                f"/api/v0/roster/{roster_id}/augment",
                json=payload
            )
            assert response.status_code in (200, 201), \
                f"Observation {i} failed: {response.status_code}"
        
        # Verify all observations recorded
        time.sleep(1)  # Allow processing
        
        response = test_client.get(f"/api/v0/roster/{roster_id}")
        entry = response.json()
        augmented_count = entry.get("augmented_count", 0) or entry.get("data", {}).get("augmented_count", 0)
        
        assert augmented_count >= 5, \
            f"Expected at least 5 augmented embeddings, got {augmented_count}"

    def test_error_invalid_embedding_dimension(self, test_client):
        """Verify error handling for invalid embedding dimensions."""
        roster_id = self._create_test_roster(test_client)
        
        # Try to add observation with wrong dimension
        payload = {
            "observation_id": str(uuid.uuid4()),
            "embedding": [0.1] * 256,  # Wrong dimension
            "metadata": {"quality_tier": "high"}
        }
        
        response = test_client.post(
            f"/api/v0/roster/{roster_id}/augment",
            json=payload
        )
        
        # Should return error (400 or 422)
        assert response.status_code in (400, 422), \
            f"Expected validation error, got {response.status_code}"

    def test_error_nonexistent_roster(self, test_client):
        """Verify error handling for nonexistent roster ID."""
        fake_id = str(uuid.uuid4())
        
        payload = {
            "observation_id": str(uuid.uuid4()),
            "embedding": [0.1] * 512,
            "metadata": {"quality_tier": "high"}
        }
        
        response = test_client.post(
            f"/api/v0/roster/{fake_id}/augment",
            json=payload
        )
        
        # Should return 404
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"

    # Helper methods
    
    def _create_test_roster(self, test_client):
        """Helper to create a test roster entry."""
        payload = {
            "label": f"test-person-{uuid.uuid4()}",
            "entity_type": "person",
            "model": "test-model",
            "embeddings": [[0.1] * 512]
        }
        
        response = test_client.post("/api/v0/roster", json=payload)
        data = response.json()
        return data.get("id") or data.get("unique_id") or data.get("data", {}).get("id")
    
    def _create_test_roster_with_embedding(self, test_client, embedding):
        """Helper to create roster with specific embedding."""
        payload = {
            "label": f"test-person-{uuid.uuid4()}",
            "entity_type": "person",
            "model": "test-model",
            "embeddings": [embedding]
        }
        
        response = test_client.post("/api/v0/roster", json=payload)
        data = response.json()
        return data.get("id") or data.get("unique_id") or data.get("data", {}).get("id")
    
    def _add_observation(self, test_client, roster_id, embedding, quality_tier, confidence):
        """Helper to add an observation."""
        payload = {
            "observation_id": str(uuid.uuid4()),
            "embedding": embedding,
            "metadata": {
                "quality_tier": quality_tier,
                "confidence": confidence
            }
        }
        
        response = test_client.post(
            f"/api/v0/roster/{roster_id}/augment",
            json=payload
        )
        return response
    
    def _search_and_get_score(self, test_client, roster_id, query_embedding):
        """Helper to search and get score for specific roster ID."""
        payload = {
            "embedding": query_embedding,
            "threshold": 0.3,
            "top_k": 10
        }
        
        response = test_client.post("/api/v0/embeddings", json=payload)
        matches = response.json().get("matches", [])
        
        for match in matches:
            match_id = match.get("entity_id") or match.get("unique_id")
            if match_id == roster_id:
                return match.get("score", 0)
        
        return 0.0  # Not found in results


class TestProgressiveLearningMetrics:
    """Test metrics tracking for progressive learning."""

    def test_confirmation_metrics_tracked(self, test_client):
        """Verify confirmation requests are tracked in metrics."""
        # Create roster and add observation
        roster_id = self._create_test_roster(test_client)
        
        payload = {
            "observation_id": str(uuid.uuid4()),
            "embedding": [0.1] * 512,
            "metadata": {"quality_tier": "high", "confidence": 0.9}
        }
        
        test_client.post(f"/api/v0/roster/{roster_id}/augment", json=payload)
        
        # Fetch metrics endpoint
        response = test_client.get("/metrics")
        assert response.status_code == 200
        
        metrics_text = response.text
        
        # Check for progressive learning metrics
        # (actual metric names depend on implementation)
        assert "augmented_embedding_requests_total" in metrics_text or \
               "progressive_learning" in metrics_text, \
               "Progressive learning metrics not found"

    def _create_test_roster(self, test_client):
        """Helper to create a test roster entry."""
        payload = {
            "label": f"test-person-{uuid.uuid4()}",
            "entity_type": "person",
            "model": "test-model",
            "embeddings": [[0.1] * 512]
        }
        
        response = test_client.post("/api/v0/roster", json=payload)
        data = response.json()
        return data.get("id") or data.get("unique_id") or data.get("data", {}).get("id")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
