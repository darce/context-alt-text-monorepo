"""Unit tests for /service/info endpoint enhancements.

Tests verify that the endpoint returns roster_stats and faiss_index_stats
as required by the WordPress dashboard integration.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mock_scene_analysis_service():
    """Mock SceneAnalysisService with recognition service."""
    service = MagicMock()
    recognition_service = AsyncMock()
    
    # Mock get_service_info response
    recognition_service.get_service_info = AsyncMock(return_value={
        "model": {
            "name": "insightface_w600k",
            "device": "cpu",
            "providers": ["CPUExecutionProvider"]
        },
        "recognition": {
            "default_threshold": 0.45,
            "max_faces_per_image": 20,
            "embedding_dimension": 512
        },
        "embedding_router": {
            "auto_reload": True,
            "reload_interval_seconds": 30,
            "embeddings_source": "database",
            "loaded_embeddings": 150,
            "loaded_entities": ["alice", "bob", "charlie"],
            "reload_stats": {
                "reloaded_at": "2025-11-01T12:00:00Z",
                "duration_ms": 245.5,
                "entry_count": 150,
                "embedding_count": 150
            }
        },
        "performance": {
            "batch_size": 16,
            "max_concurrent_requests": 4
        },
        "cache": {
            "hf_home": "/tmp/.cache/huggingface",
            "hf_datasets_cache": "/tmp/.cache/datasets",
            "torch_home": "/tmp/.cache/torch"
        }
    })
    
    service.recognition_service = recognition_service
    return service


@pytest.fixture
def mock_roster_service():
    """Mock RosterService with storage info."""
    service = MagicMock()
    
    # Mock get_storage_info response
    service.get_storage_info = MagicMock(return_value={
        "backend": "database",
        "database_url": "postgresql://localhost/test",
        "tenant_id": "test-tenant",
        "model": "insightface_w600k",
        "roster_stats": {
            "entry_count": 150,
            "reference_embeddings": 150,
            "augmented_embeddings": 337,
            "total_embeddings": 487
        }
    })
    
    # Mock etag cache
    service._etag_cache = {
        "etag": "sha256:abc123def456",
        "timestamp": "2025-11-01T12:00:00Z"
    }
    
    return service


@pytest.fixture
def app_with_mocks(mock_scene_analysis_service, mock_roster_service):
    """Create FastAPI app with mocked dependencies."""
    from api.routes.main import router
    from api.routes.main import get_scene_analysis_service, get_roster_service
    
    app = FastAPI()
    app.include_router(router, prefix="/api/v0")
    
    # Mark app as initialized
    app.state.initialization_complete = True
    app.state.is_initializing = False
    
    # Override dependencies using FastAPI's dependency_overrides
    app.dependency_overrides[get_scene_analysis_service] = lambda: mock_scene_analysis_service
    app.dependency_overrides[get_roster_service] = lambda: mock_roster_service
    
    return app


def test_service_info_includes_roster_stats(app_with_mocks, mock_roster_service):
    """Test that /service/info includes roster_stats from RosterService."""
    client = TestClient(app_with_mocks)
    
    response = client.get("/api/v0/service/info")
    
    assert response.status_code == 200
    body = response.json()
    
    assert body["status"] == "ok"
    assert "data" in body
    data = body["data"]
    
    # Verify roster_stats is present
    assert "roster_stats" in data
    roster_stats = data["roster_stats"]
    
    # Verify all expected fields
    assert roster_stats["entry_count"] == 150
    assert roster_stats["reference_embeddings"] == 150
    assert roster_stats["augmented_embeddings"] == 337
    assert roster_stats["total_embeddings"] == 487
    
    # Verify etag metadata is included
    assert roster_stats["etag"] == "sha256:abc123def456"
    assert roster_stats["last_updated"] == "2025-11-01T12:00:00Z"
    
    # Verify get_storage_info was called with correct model
    mock_roster_service.get_storage_info.assert_called_once_with(model="insightface_w600k")


def test_service_info_includes_faiss_index_stats(app_with_mocks):
    """Test that /service/info includes faiss_index_stats from embedding_router."""
    client = TestClient(app_with_mocks)
    
    response = client.get("/api/v0/service/info")
    
    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    
    # Verify faiss_index_stats is present
    assert "faiss_index_stats" in data
    faiss_stats = data["faiss_index_stats"]
    
    # Verify all expected fields
    assert faiss_stats["total_vectors"] == 150
    assert faiss_stats["dimension"] == 512
    assert faiss_stats["index_type"] == "Flat"
    assert faiss_stats["last_reload"] == "2025-11-01T12:00:00Z"
    assert faiss_stats["last_reload_duration_ms"] == 245.5


def test_service_info_handles_roster_service_failure(app_with_mocks, mock_roster_service):
    """Test that /service/info gracefully handles roster service errors."""
    client = TestClient(app_with_mocks)
    
    # Make get_storage_info raise an exception
    mock_roster_service.get_storage_info.side_effect = Exception("Database connection failed")
    
    response = client.get("/api/v0/service/info")
    
    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    
    # Verify roster_stats is present but with error info
    assert "roster_stats" in data
    roster_stats = data["roster_stats"]
    
    # Should return fallback values
    assert roster_stats["entry_count"] == 0
    assert roster_stats["reference_embeddings"] == 0
    assert roster_stats["augmented_embeddings"] == 0
    assert roster_stats["total_embeddings"] == 0
    assert "error" in roster_stats
    assert "Database connection failed" in roster_stats["error"]


def test_service_info_handles_missing_etag_cache(app_with_mocks, mock_roster_service):
    """Test that /service/info works when etag cache is not present."""
    client = TestClient(app_with_mocks)
    
    # Remove etag cache
    del mock_roster_service._etag_cache
    
    response = client.get("/api/v0/service/info")
    
    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    
    # Verify roster_stats is present without etag metadata
    assert "roster_stats" in data
    roster_stats = data["roster_stats"]
    
    assert roster_stats["entry_count"] == 150
    assert roster_stats["total_embeddings"] == 487
    # etag and last_updated should not be present
    assert "etag" not in roster_stats or roster_stats["etag"] is None
    assert "last_updated" not in roster_stats or roster_stats["last_updated"] is None


def test_service_info_handles_missing_reload_stats(app_with_mocks, mock_scene_analysis_service):
    """Test that /service/info works when reload_stats are missing."""
    client = TestClient(app_with_mocks)
    
    # Directly modify the mock's return value to not have reload_stats
    info_without_reload_stats = {
        "model": {
            "name": "insightface_w600k",
            "device": "cpu",
            "providers": ["CPUExecutionProvider"]
        },
        "recognition": {
            "default_threshold": 0.45,
            "max_faces_per_image": 20,
            "embedding_dimension": 512
        },
        "embedding_router": {
            "auto_reload": True,
            "reload_interval_seconds": 30,
            "embeddings_source": "database",
            "loaded_embeddings": 150,
            "loaded_entities": ["alice", "bob", "charlie"]
            # Note: reload_stats is intentionally omitted
        },
        "performance": {
            "batch_size": 16,
            "max_concurrent_requests": 4
        },
        "cache": {
            "hf_home": "/tmp/.cache/huggingface",
            "hf_datasets_cache": "/tmp/.cache/datasets",
            "torch_home": "/tmp/.cache/torch"
        }
    }
    
    mock_scene_analysis_service.recognition_service.get_service_info = AsyncMock(
        return_value=info_without_reload_stats
    )
    
    response = client.get("/api/v0/service/info")
    
    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    
    # Verify faiss_index_stats is present without reload info
    assert "faiss_index_stats" in data
    faiss_stats = data["faiss_index_stats"]
    
    assert faiss_stats["total_vectors"] == 150
    assert faiss_stats["dimension"] == 512
    assert faiss_stats["index_type"] == "Flat"
    # last_reload should not be present when reload_stats is missing
    assert "last_reload" not in faiss_stats
    assert "last_reload_duration_ms" not in faiss_stats


def test_service_info_preserves_existing_fields(app_with_mocks):
    """Test that /service/info preserves all existing recognition service fields."""
    client = TestClient(app_with_mocks)
    
    response = client.get("/api/v0/service/info")
    
    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    
    # Verify all original fields are still present
    assert "model" in data
    assert "recognition" in data
    assert "embedding_router" in data
    assert "performance" in data
    assert "cache" in data
    
    # Verify model details
    assert data["model"]["name"] == "insightface_w600k"
    assert data["model"]["device"] == "cpu"
    
    # Verify recognition details
    assert data["recognition"]["default_threshold"] == 0.45
    assert data["recognition"]["embedding_dimension"] == 512
