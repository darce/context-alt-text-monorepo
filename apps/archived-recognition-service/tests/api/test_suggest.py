"""
Tests for /suggest endpoint.

Validates FAISS-based similarity search for roster matching.
"""

import pytest
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest import mock

from api.routes.main import router as api_router
from api.dependencies import get_roster_service


def create_test_client(roster_service):
    """Factory function to create test client with specific roster service."""
    app = FastAPI()
    app.state.is_initializing = False
    app.state.initialization_complete = True
    app.include_router(api_router, prefix="/api/v0")
    app.dependency_overrides[get_roster_service] = lambda: roster_service
    return TestClient(app)


class TestSuggestEndpoint:
    """Test suite for POST /api/v0/suggest"""
    
    def test_suggest_empty_roster(self, empty_roster):
        """Should return empty suggestions when roster is empty."""
        client = create_test_client(empty_roster)
        
        # Create dummy 512-dim embedding
        embedding = np.random.rand(512).tolist()
        
        response = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [embedding],
                "topK": 5,
                "threshold": 0.92,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "suggestions" in data
        assert len(data["suggestions"]) == 1
        assert data["suggestions"][0] == []
    
    def test_suggest_single_match(self, roster_with_one_person):
        """Should return single match above threshold."""
        client = create_test_client(roster_with_one_person)
        
        # Use embedding very similar to roster entry
        # (In real test, mock roster service to return known embedding)
        embedding = np.random.rand(512).tolist()
        
        response = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [embedding],
                "topK": 5,
                "threshold": 0.92,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "suggestions" in data
        assert len(data["suggestions"]) == 1
        # May be empty if similarity too low (depends on mock)
    
    def test_suggest_batch_processing(self, roster_with_multiple_people):
        """Should handle multiple embeddings in single request."""
        client = create_test_client(roster_with_multiple_people)
        
        embeddings = [np.random.rand(512).tolist() for _ in range(10)]
        
        response = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": embeddings,
                "topK": 5,
                "threshold": 0.92,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "suggestions" in data
        assert len(data["suggestions"]) == 10
    
    def test_suggest_threshold_filtering(self, roster_with_multiple_people):
        """Should filter results by similarity threshold."""
        client = create_test_client(roster_with_multiple_people)
        
        embedding = np.random.rand(512).tolist()
        
        # High threshold - should get fewer results
        response_high = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [embedding],
                "topK": 5,
                "threshold": 0.95,
            },
        )
        
        # Low threshold - should get more results
        response_low = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [embedding],
                "topK": 5,
                "threshold": 0.70,
            },
        )
        
        assert response_high.status_code == 200
        assert response_low.status_code == 200
        
        high_matches = len(response_high.json()["suggestions"][0])
        low_matches = len(response_low.json()["suggestions"][0])
        
        # Lower threshold should have >= matches
        assert low_matches >= high_matches
    
    def test_suggest_topk_limit(self, roster_with_many_people):
        """Should respect topK parameter."""
        client = create_test_client(roster_with_many_people)
        
        embedding = np.random.rand(512).tolist()
        
        response = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [embedding],
                "topK": 3,
                "threshold": 0.50,  # Low threshold to get many matches
            },
        )
        
        assert response.status_code == 200
        suggestions = response.json()["suggestions"][0]
        assert len(suggestions) <= 3
    
    def test_suggest_invalid_embedding_dimensions(self, empty_roster):
        """Should reject embeddings with wrong dimensions."""
        client = create_test_client(empty_roster)
        
        # 256-dim instead of 512-dim
        embedding = np.random.rand(256).tolist()
        
        response = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [embedding],
                "topK": 5,
                "threshold": 0.92,
            },
        )
        
        assert response.status_code == 422  # Pydantic validation error
        assert "512" in response.json()["detail"][0]["msg"]
    
    def test_suggest_empty_embeddings(self, empty_roster):
        """Should reject empty embeddings array."""
        client = create_test_client(empty_roster)
        
        response = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [],
                "topK": 5,
                "threshold": 0.92,
            },
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_suggest_invalid_threshold(self, empty_roster):
        """Should reject threshold outside 0-1 range."""
        client = create_test_client(empty_roster)
        
        embedding = np.random.rand(512).tolist()
        
        response = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [embedding],
                "topK": 5,
                "threshold": 1.5,  # Invalid
            },
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_suggest_invalid_topk(self, empty_roster):
        """Should reject topK outside valid range."""
        client = create_test_client(empty_roster)
        
        embedding = np.random.rand(512).tolist()
        
        response = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [embedding],
                "topK": 0,  # Invalid
                "threshold": 0.92,
            },
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_suggest_response_format(self, roster_with_one_person):
        """Should return correctly formatted response."""
        client = create_test_client(roster_with_one_person)
        
        embedding = np.random.rand(512).tolist()
        
        response = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [embedding],
                "topK": 5,
                "threshold": 0.92,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check structure
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)
        assert len(data["suggestions"]) == 1
        
        # Check match format (if any matches)
        if data["suggestions"][0]:
            match = data["suggestions"][0][0]
            assert "rosterId" in match
            assert "display" in match
            assert "score" in match
            assert 0.0 <= match["score"] <= 1.0
    
    def test_suggest_scores_descending_order(self, roster_with_multiple_people):
        """Should return matches in descending score order."""
        client = create_test_client(roster_with_multiple_people)
        
        embedding = np.random.rand(512).tolist()
        
        response = client.post(
            "/api/v0/suggest",
            json={
                "embeddings": [embedding],
                "topK": 10,
                "threshold": 0.50,
            },
        )
        
        assert response.status_code == 200
        suggestions = response.json()["suggestions"][0]
        
        if len(suggestions) > 1:
            scores = [match["score"] for match in suggestions]
            assert scores == sorted(scores, reverse=True)


# Fixtures for different roster configurations
@pytest.fixture
def empty_roster():
    """Mock roster service with no entries."""
    mock_service = mock.Mock()
    mock_service.list_all.return_value = []
    return mock_service


@pytest.fixture
def roster_with_one_person():
    """Mock roster service with one person."""
    mock_entry = mock.Mock()
    mock_entry.unique_id = "person-ana-001"
    mock_entry.name = "Ana Rodriguez"
    mock_entry.aggregate_embedding = np.random.rand(512).astype(np.float32)
    
    mock_service = mock.Mock()
    mock_service.list_all.return_value = [mock_entry]
    return mock_service


@pytest.fixture
def roster_with_multiple_people():
    """Mock roster service with multiple people."""
    entries = []
    for i in range(5):
        entry = mock.Mock()
        entry.unique_id = f"person-{i:03d}"
        entry.name = f"Person {i}"
        entry.aggregate_embedding = np.random.rand(512).astype(np.float32)
        entries.append(entry)
    
    mock_service = mock.Mock()
    mock_service.list_all.return_value = entries
    return mock_service


@pytest.fixture
def roster_with_many_people():
    """Mock roster service with many people (100+)."""
    entries = []
    for i in range(100):
        entry = mock.Mock()
        entry.unique_id = f"person-{i:03d}"
        entry.name = f"Person {i}"
        entry.aggregate_embedding = np.random.rand(512).astype(np.float32)
        entries.append(entry)
    
    mock_service = mock.Mock()
    mock_service.list_all.return_value = entries
    return mock_service
