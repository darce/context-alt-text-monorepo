"""
Tests for /cluster-unknowns endpoint.

Validates DBSCAN and Agglomerative clustering for grouping unknown faces.
"""

import pytest
import numpy as np
from unittest import mock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.main import router as api_router


def create_test_client():
    """Factory function to create test client."""
    app = FastAPI()
    app.state.is_initializing = False
    app.state.initialization_complete = True
    app.include_router(api_router, prefix="/api/v0")
    return TestClient(app)


class TestClusterUnknownsEndpoint:
    """Test suite for POST /api/v0/cluster-unknowns"""
    
    def test_cluster_similar_embeddings(self):
        """Should cluster similar embeddings together."""
        client = create_test_client()
        
        # Create 3 groups of similar embeddings
        base1 = np.random.rand(512)
        base2 = np.random.rand(512)
        base3 = np.random.rand(512)
        
        # Add small noise to create similar embeddings
        group1 = [base1 + np.random.rand(512) * 0.01 for _ in range(4)]
        group2 = [base2 + np.random.rand(512) * 0.01 for _ in range(3)]
        group3 = [base3 + np.random.rand(512) * 0.01 for _ in range(2)]
        
        all_embeddings = group1 + group2 + group3
        embeddings_list = [emb.tolist() for emb in all_embeddings]
        
        response = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": embeddings_list,
                "algorithm": "dbscan",
                "distanceThreshold": 0.3,
                "minSamples": 2,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "clusterIds" in data
        assert "summary" in data
        assert len(data["clusterIds"]) == 9  # Total embeddings
        
        # Should have 3 distinct clusters
        unique_clusters = len(set(data["clusterIds"]))
        assert unique_clusters >= 3
        
        # Summary should reflect clustering
        assert data["summary"]["total_embeddings"] == 9
        assert data["summary"]["num_clusters"] >= 3
    
    def test_cluster_agglomerative_algorithm(self):
        """Should use agglomerative clustering when specified."""
        client = create_test_client()
        
        # Create similar embeddings
        base = np.random.rand(512)
        embeddings = [base + np.random.rand(512) * 0.02 for _ in range(5)]
        embeddings_list = [emb.tolist() for emb in embeddings]
        
        response = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": embeddings_list,
                "algorithm": "agglomerative",
                "distanceThreshold": 0.4,
                "linkage": "average",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["clusterIds"]) == 5
        # Agglomerative should not have noise points
        assert all("-noise-" not in cid for cid in data["clusterIds"])
    
    def test_cluster_single_embedding(self):
        """Should handle single embedding gracefully."""
        client = create_test_client()
        
        embedding = np.random.rand(512).tolist()
        
        response = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": [embedding],
                "algorithm": "dbscan",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["clusterIds"]) == 1
        assert "-single-" in data["clusterIds"][0]
        assert data["summary"]["total_embeddings"] == 1
        assert data["summary"]["num_clusters"] == 1
    
    def test_cluster_dissimilar_embeddings(self):
        """Should create separate clusters for dissimilar embeddings."""
        client = create_test_client()
        
        # Create very different embeddings (orthogonal vectors)
        # Make them explicitly different by spacing them far apart
        embeddings = []
        for i in range(10):
            emb = np.zeros(512)
            # Set different dimensions to 1.0 for each embedding
            start_idx = i * 50
            emb[start_idx:start_idx + 50] = 1.0
            embeddings.append(emb)
        
        embeddings_list = [emb.tolist() for emb in embeddings]
        
        response = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": embeddings_list,
                "algorithm": "dbscan",
                "distanceThreshold": 0.3,  # Strict threshold
                "minSamples": 2,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Orthogonal vectors should not cluster together
        # Should have mostly noise or many small clusters
        assert data["summary"]["num_clusters"] >= 5 or data["summary"]["num_noise_points"] >= 5
    
    def test_cluster_threshold_affects_results(self):
        """Should create different clusters with different thresholds."""
        client = create_test_client()
        
        # Create embeddings with moderate similarity
        base = np.random.rand(512)
        embeddings = [base + np.random.rand(512) * 0.1 for _ in range(8)]
        embeddings_list = [emb.tolist() for emb in embeddings]
        
        # Strict threshold
        response_strict = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": embeddings_list,
                "algorithm": "agglomerative",
                "distanceThreshold": 0.3,
            },
        )
        
        # Permissive threshold
        response_permissive = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": embeddings_list,
                "algorithm": "agglomerative",
                "distanceThreshold": 0.8,
            },
        )
        
        assert response_strict.status_code == 200
        assert response_permissive.status_code == 200
        
        strict_clusters = len(set(response_strict.json()["clusterIds"]))
        permissive_clusters = len(set(response_permissive.json()["clusterIds"]))
        
        # Strict threshold should create more clusters
        assert strict_clusters >= permissive_clusters
    
    def test_cluster_invalid_embedding_dimensions(self):
        """Should reject embeddings with wrong dimensions."""
        client = create_test_client()
        
        # 256-dim instead of 512-dim
        embedding = np.random.rand(256).tolist()
        
        response = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": [embedding],
                "algorithm": "dbscan",
            },
        )
        
        assert response.status_code == 422  # Pydantic validation error
        assert "512" in response.json()["detail"][0]["msg"]
    
    def test_cluster_empty_embeddings(self):
        """Should reject empty embeddings array."""
        client = create_test_client()
        
        response = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": [],
                "algorithm": "dbscan",
            },
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_cluster_invalid_threshold(self):
        """Should reject threshold outside 0-2 range."""
        client = create_test_client()
        
        embedding = np.random.rand(512).tolist()
        
        response = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": [embedding],
                "algorithm": "dbscan",
                "distanceThreshold": 3.0,  # Invalid (max is 2.0)
            },
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_cluster_invalid_linkage(self):
        """Should reject invalid linkage method."""
        client = create_test_client()
        
        embedding = np.random.rand(512).tolist()
        
        response = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": [embedding],
                "algorithm": "agglomerative",
                "linkage": "invalid_method",
            },
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_cluster_response_format(self):
        """Should return correctly formatted response."""
        client = create_test_client()
        
        embeddings = [np.random.rand(512).tolist() for _ in range(5)]
        
        response = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": embeddings,
                "algorithm": "dbscan",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check structure
        assert "clusterIds" in data
        assert "summary" in data
        assert isinstance(data["clusterIds"], list)
        assert isinstance(data["summary"], dict)
        assert len(data["clusterIds"]) == 5
        
        # Check summary format
        summary = data["summary"]
        assert "total_embeddings" in summary
        assert "num_clusters" in summary
        assert "num_noise_points" in summary
        assert "largest_cluster_size" in summary
        assert "smallest_cluster_size" in summary
        assert "avg_cluster_size" in summary
        
        # Check cluster ID format
        for cluster_id in data["clusterIds"]:
            assert isinstance(cluster_id, str)
            assert cluster_id.startswith("cluster-")
    
    def test_cluster_deterministic_ids(self):
        """Should generate same cluster IDs for same input."""
        client = create_test_client()
        
        # Use fixed seed for reproducibility
        np.random.seed(42)
        embeddings = [np.random.rand(512).tolist() for _ in range(5)]
        
        response1 = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": embeddings,
                "algorithm": "agglomerative",
                "distanceThreshold": 0.6,
            },
        )
        
        response2 = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": embeddings,
                "algorithm": "agglomerative",
                "distanceThreshold": 0.6,
            },
        )
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Cluster IDs should be consistent
        ids1 = response1.json()["clusterIds"]
        ids2 = response2.json()["clusterIds"]
        
        # The exact IDs should match for same input
        assert ids1 == ids2
    
    def test_cluster_min_samples_parameter(self):
        """Should respect minSamples parameter for DBSCAN."""
        client = create_test_client()
        
        # Create embeddings with moderate similarity
        base = np.random.rand(512)
        embeddings = [base + np.random.rand(512) * 0.05 for _ in range(6)]
        embeddings_list = [emb.tolist() for emb in embeddings]
        
        # High minSamples - should create noise
        response_high = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": embeddings_list,
                "algorithm": "dbscan",
                "distanceThreshold": 0.5,
                "minSamples": 5,  # High threshold
            },
        )
        
        # Low minSamples - should cluster
        response_low = client.post(
            "/api/v0/cluster-unknowns",
            json={
                "embeddings": embeddings_list,
                "algorithm": "dbscan",
                "distanceThreshold": 0.5,
                "minSamples": 2,  # Low threshold
            },
        )
        
        assert response_high.status_code == 200
        assert response_low.status_code == 200
        
        high_noise = response_high.json()["summary"]["num_noise_points"]
        low_noise = response_low.json()["summary"]["num_noise_points"]
        
        # High minSamples should produce more noise
        assert high_noise >= low_noise
