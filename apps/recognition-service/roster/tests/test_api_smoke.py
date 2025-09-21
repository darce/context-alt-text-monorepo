"""
API Smoke Tests for Roster Service

Basic functional tests to ensure the API endpoints work correctly.
"""

import pytest
import json
import tempfile
import os
from fastapi.testclient import TestClient
from fastapi import FastAPI

from roster.ports.api_router import router
from roster.ports.dependencies import reset_roster_service
from roster.config import reload_config

# Create test app
app = FastAPI()
app.include_router(router)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test():
    """Setup for each test."""
    # Create a temporary directory for each test
    temp_dir = tempfile.mkdtemp()
    os.environ['ROSTER_DATA_DIR'] = temp_dir
    
    # Reset service instance to ensure clean state
    reset_roster_service()
    # Reload config for test environment
    reload_config()
    yield
    # Cleanup after test
    reset_roster_service()
    # Clean up temp directory
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_health_check():
    """Test health check endpoint."""
    response = client.get("/api/v0/roster/health")
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "models" in data


def test_add_roster_entry():
    """Test adding a roster entry."""
    model = "adaface_ir101"
    request_data = {
        "name": "test_person",
        "embedding": [0.1] * 512,  # Valid 512-dim embedding
        "metadata": {"test": "data"}
    }
    
    response = client.post(f"/api/v0/roster/{model}/upsert", json=request_data)
    assert response.status_code == 200
    
    data = response.json()
    assert data["success"] is True
    assert data["entry"]["name"] == "test_person"
    assert data["entry"]["unique_id"] is not None


def test_get_roster_entries():
    """Test getting roster entries."""
    model = "adaface_ir101"
    
    # First add an entry
    request_data = {
        "name": "test_person",
        "embedding": [0.1] * 512
    }
    client.post(f"/api/v0/roster/{model}/upsert", json=request_data)
    
    # Then get entries
    response = client.get(f"/api/v0/roster/{model}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["success"] is True
    assert data["count"] == 1
    assert len(data["entries"]) == 1
    assert data["entries"][0]["name"] == "test_person"


def test_get_roster_entry_by_id():
    """Test getting a specific roster entry."""
    model = "adaface_ir101"
    
    # Add an entry
    request_data = {
        "name": "test_person",
        "embedding": [0.1] * 512
    }
    add_response = client.post(f"/api/v0/roster/{model}/upsert", json=request_data)
    unique_id = add_response.json()["entry"]["unique_id"]
    
    # Get the entry by ID
    response = client.get(f"/api/v0/roster/{model}/{unique_id}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["success"] is True
    assert data["entry"]["unique_id"] == unique_id
    assert data["entry"]["name"] == "test_person"


def test_delete_roster_entry():
    """Test deleting a roster entry."""
    model = "adaface_ir101"
    
    # Add an entry
    request_data = {
        "name": "test_person",
        "embedding": [0.1] * 512
    }
    add_response = client.post(f"/api/v0/roster/{model}/upsert", json=request_data)
    unique_id = add_response.json()["entry"]["unique_id"]
    
    # Delete the entry
    response = client.delete(f"/api/v0/roster/{model}/{unique_id}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["success"] is True
    assert data["deleted_id"] == unique_id


def test_bulk_add_entries():
    """Test bulk adding entries."""
    model = "adaface_ir101"
    request_data = {
        "entries": [
            {
                "name": "person1",
                "embedding": [0.1] * 512
            },
            {
                "name": "person2", 
                "embedding": [0.2] * 512
            }
        ]
    }
    
    response = client.post(f"/api/v0/roster/{model}/bulk", json=request_data)
    assert response.status_code == 200
    
    data = response.json()
    assert data["success"] is True
    assert data["stats"]["successful"] == 2
    assert len(data["successful_entries"]) == 2


def test_roster_stats():
    """Test getting roster statistics."""
    model = "adaface_ir101"
    
    response = client.get(f"/api/v0/roster/{model}/stats")
    assert response.status_code == 200
    
    data = response.json()
    assert data["success"] is True
    assert data["model"] == model
    assert "entry_count" in data
    assert "storage_info" in data


def test_invalid_model():
    """Test using an invalid model."""
    invalid_model = "invalid_model"
    request_data = {
        "name": "test_person",
        "embedding": [0.1] * 512
    }
    
    response = client.post(f"/api/v0/roster/{invalid_model}/upsert", json=request_data)
    assert response.status_code == 400


def test_invalid_embedding():
    """Test using an invalid embedding."""
    model = "adaface_ir101"
    request_data = {
        "name": "test_person",
        "embedding": []  # Empty embedding
    }
    
    response = client.post(f"/api/v0/roster/{model}/upsert", json=request_data)
    assert response.status_code == 422  # Validation error


def test_missing_required_fields():
    """Test missing required fields."""
    model = "adaface_ir101"
    request_data = {
        "embedding": [0.1] * 512
        # Missing 'name' field
    }
    
    response = client.post(f"/api/v0/roster/{model}/upsert", json=request_data)
    assert response.status_code == 422  # Validation error
