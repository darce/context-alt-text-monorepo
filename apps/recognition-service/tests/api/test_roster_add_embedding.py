"""
Tests for POST /roster/add-embedding endpoint.

Validates progressive learning functionality:
- Adding embeddings to existing roster entries with observationId tracking
- Duplicate prevention (same observationId)
- FAISS index updates after embedding addition
"""

import pytest
import numpy as np
import time
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


# Fixtures
@pytest.fixture(autouse=True)
def clear_synced_observations():
    """Clear the module-level _SYNCED_OBSERVATIONS dict before each test."""
    from api.routes import roster
    roster._SYNCED_OBSERVATIONS.clear()
    yield
    roster._SYNCED_OBSERVATIONS.clear()


@pytest.fixture
def empty_roster():
    """Mock roster service with no entries initially.
    
    Mocks will be updated dynamically as entries are created during tests.
    """
    mock_service = mock.Mock()
    roster_entries = {}  # Dictionary to track created entries
    
    def mock_add_entry(name, embedding, model, metadata=None, image_path=None):
        """Mock add_entry to track created entries."""
        entry = mock.Mock()
        entry.unique_id = name  # Use name as unique_id for simplicity
        entry.name = name
        entry.display_name = metadata.get("display_name", name) if metadata else name
        entry.aggregate_embedding = np.array(embedding, dtype=np.float32)
        entry.metadata = metadata or {}
        entry.created_timestamp = time.time()
        entry.updated_timestamp = time.time()
        entry.image_count = 1
        entry.reference_images = []
        roster_entries[name] = entry
        return entry
    
    def mock_get_entry(unique_id, model):
        """Mock get_entry to return tracked entries."""
        return roster_entries.get(unique_id)
    
    def mock_update_entry(unique_id, model, embedding=None, metadata=None, image_path=None):
        """Mock update_entry to succeed if entry exists."""
        if unique_id in roster_entries:
            # Update the entry
            entry = roster_entries[unique_id]
            entry.image_count += 1
            entry.updated_timestamp = time.time()
            if embedding:
                # Simulate adding reference embedding
                ref_mock = mock.Mock()
                ref_mock.embedding = embedding
                entry.reference_images.append(ref_mock)
            return True
        return False
    
    def mock_get_entries(model):
        """Mock get_entries to return all tracked entries."""
        return list(roster_entries.values())
    
    mock_service.list_all.return_value = []
    mock_service.get_entries.side_effect = mock_get_entries
    mock_service.get_entry_count.return_value = 0
    mock_service.add_entry.side_effect = mock_add_entry
    mock_service.get_entry.side_effect = mock_get_entry
    mock_service.update_entry.side_effect = mock_update_entry
    
    return mock_service


class TestAddEmbeddingEndpoint:
    """Test suite for POST /api/v0/roster/add-embedding"""
    
    def test_add_embedding_success(self, empty_roster):
        """Should successfully add embedding to roster entry."""
        client = create_test_client(empty_roster)
        
        # First create a roster entry
        embedding1 = np.random.rand(512).tolist()
        create_response = client.post(
            "/api/v0/roster",
            json={
                "entries": [{
                    "name": "ana-rodriguez",
                    "embedding": embedding1,
                    "metadata": {"display_name": "Ana Rodriguez"}
                }],
                "model": "insightface_w600k"
            }
        )
        assert create_response.status_code == 200
        
        # Now add another embedding to the same person
        embedding2 = np.random.rand(512).tolist()
        response = client.post(
            "/api/v0/roster/add-embedding",
            json={
                "rosterId": "ana-rodriguez",
                "observationId": "obs-123",
                "embedding": embedding2,
                "model": "insightface_w600k"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "message" in data
        assert "rosterId" in data
        assert data["rosterId"] == "ana-rodriguez"
    
    def test_add_embedding_duplicate_observation_id(self, empty_roster):
        """Should reject duplicate observationId for same rosterId."""
        client = create_test_client(empty_roster)
        
        # Create roster entry
        embedding1 = np.random.rand(512).tolist()
        create_response = client.post(
            "/api/v0/roster",
            json={
                "entries": [{
                    "name": "ana-rodriguez",
                    "embedding": embedding1,
                }]
            }
        )
        assert create_response.status_code == 200
        
        # Add embedding with observationId
        embedding2 = np.random.rand(512).tolist()
        response1 = client.post(
            "/api/v0/roster/add-embedding",
            json={
                "rosterId": "ana-rodriguez",
                "observationId": "obs-123",
                "embedding": embedding2,
            }
        )
        assert response1.status_code == 200
        
        # Try to add same observationId again
        embedding3 = np.random.rand(512).tolist()
        response2 = client.post(
            "/api/v0/roster/add-embedding",
            json={
                "rosterId": "ana-rodriguez",
                "observationId": "obs-123",  # Same ID
                "embedding": embedding3,
            }
        )
        
        assert response2.status_code == 409  # Conflict
        data = response2.json()
        assert "detail" in data
        assert "already synced" in data["detail"].lower()
    
    def test_add_embedding_roster_not_found(self, empty_roster):
        """Should return 404 when roster entry doesn't exist."""
        client = create_test_client(empty_roster)
        
        embedding = np.random.rand(512).tolist()
        response = client.post(
            "/api/v0/roster/add-embedding",
            json={
                "rosterId": "nonexistent-person",
                "observationId": "obs-456",
                "embedding": embedding,
            }
        )
        
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()
    
    def test_add_embedding_invalid_embedding(self, empty_roster):
        """Should return 422 for invalid embedding data."""
        client = create_test_client(empty_roster)
        
        # Create roster entry first
        embedding1 = np.random.rand(512).tolist()
        create_response = client.post(
            "/api/v0/roster",
            json={
                "entries": [{
                    "name": "ana-rodriguez",
                    "embedding": embedding1,
                }]
            }
        )
        assert create_response.status_code == 200
        
        # Try with empty embedding
        response = client.post(
            "/api/v0/roster/add-embedding",
            json={
                "rosterId": "ana-rodriguez",
                "observationId": "obs-789",
                "embedding": [],  # Empty
            }
        )
        
        assert response.status_code == 422
    
    def test_add_embedding_missing_required_fields(self, empty_roster):
        """Should return 422 when required fields are missing."""
        client = create_test_client(empty_roster)
        
        embedding = np.random.rand(512).tolist()
        
        # Missing rosterId
        response1 = client.post(
            "/api/v0/roster/add-embedding",
            json={
                "observationId": "obs-999",
                "embedding": embedding,
            }
        )
        assert response1.status_code == 422
        
        # Missing observationId
        response2 = client.post(
            "/api/v0/roster/add-embedding",
            json={
                "rosterId": "ana-rodriguez",
                "embedding": embedding,
            }
        )
        assert response2.status_code == 422
        
        # Missing embedding
        response3 = client.post(
            "/api/v0/roster/add-embedding",
            json={
                "rosterId": "ana-rodriguez",
                "observationId": "obs-999",
            }
        )
        assert response3.status_code == 422
    
    def test_add_embedding_updates_faiss_index(self, empty_roster):
        """Should successfully call update_entry which triggers FAISS index update.
        
        Note: Full FAISS integration is tested in integration tests.
        This unit test verifies the endpoint correctly calls roster_service.update_entry()
        which is responsible for updating the FAISS index.
        """
        client = create_test_client(empty_roster)
        
        # Create roster entry
        embedding1 = np.random.rand(512).tolist()
        create_response = client.post(
            "/api/v0/roster",
            json={
                "entries": [{
                    "name": "ana-rodriguez",
                    "embedding": embedding1,
                }]
            }
        )
        assert create_response.status_code == 200
        
        # Add second embedding
        embedding2 = np.random.rand(512).tolist()
        add_response = client.post(
            "/api/v0/roster/add-embedding",
            json={
                "rosterId": "ana-rodriguez",
                "observationId": "obs-111",
                "embedding": embedding2,
            }
        )
        assert add_response.status_code == 200
        
        # Verify the response indicates success
        data = add_response.json()
        assert data["success"] is True
        assert data["rosterId"] == "ana-rodriguez"
        assert data["observationId"] == "obs-111"
        
        # Verify update_entry was called (this method updates FAISS index)
        empty_roster.update_entry.assert_called()
        call_args = empty_roster.update_entry.call_args
        assert call_args.kwargs["unique_id"] == "ana-rodriguez"
        assert call_args.kwargs["embedding"] == embedding2
    
    def test_add_embedding_with_metadata(self, empty_roster):
        """Should accept optional metadata field."""
        client = create_test_client(empty_roster)
        
        # Create roster entry
        embedding1 = np.random.rand(512).tolist()
        create_response = client.post(
            "/api/v0/roster",
            json={
                "entries": [{
                    "name": "ana-rodriguez",
                    "embedding": embedding1,
                }]
            }
        )
        assert create_response.status_code == 200
        
        # Add embedding with metadata
        embedding2 = np.random.rand(512).tolist()
        response = client.post(
            "/api/v0/roster/add-embedding",
            json={
                "rosterId": "ana-rodriguez",
                "observationId": "obs-222",
                "embedding": embedding2,
                "metadata": {
                    "attachmentId": 42,
                    "bbox": [0.1, 0.2, 0.3, 0.4],
                    "source": "wordpress-plugin"
                }
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
