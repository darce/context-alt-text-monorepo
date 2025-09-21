"""
Production Health Check Tests

Lightweight tests for production health monitoring.
These tests should run quickly and verify basic service functionality
without requiring heavy model downloads or extensive computation.
"""

import pytest
import io
from PIL import Image
from fastapi.testclient import TestClient
from fastapi import FastAPI

from recognition.ports.api_routes import router


@pytest.fixture
def client():
    """Create test client with recognition routes."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def sample_image():
    """Create a minimal test image."""
    image = Image.new('RGB', (32, 32), color=(128, 128, 128))
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='JPEG')
    img_byte_arr.seek(0)
    return img_byte_arr


def test_health_endpoint(client):
    """Test the health check endpoint - critical for load balancers."""
    response = client.get("/api/v0/health")
    assert response.status_code == 200
    
    data = response.json()
    assert "status" in data
    assert "model" in data


def test_service_info_endpoint(client):
    """Test the service info endpoint - verifies configuration."""
    response = client.get("/api/v0/service/info")
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "success"
    assert "data" in data
    assert "model" in data["data"]


def test_service_responds_to_invalid_requests(client):
    """Test that service handles invalid requests gracefully."""
    # Test missing file
    response = client.post("/api/v0/analyze-scene")
    assert response.status_code == 422  # Validation error
    
    # Test invalid content type
    response = client.post(
        "/api/v0/analyze-scene",
        data={"not_a_file": "test"}
    )
    assert response.status_code == 422


def test_reload_embeddings_endpoint(client):
    """Test embeddings reload endpoint - should not crash even if no file exists."""
    response = client.post("/api/v0/service/reload-embeddings")
    assert response.status_code == 200
    
    data = response.json()
    assert "status" in data
    assert "message" in data


def test_service_accepts_valid_image_format(client, sample_image):
    """Test that service accepts valid image uploads without crashing."""
    response = client.post(
        "/api/v0/analyze-scene",
        files={"images": ("test.jpg", sample_image, "image/jpeg")},
        data={"use_roster": False}  # Don't require roster for health check
    )
    
    # Should return 200 and valid JSON structure
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "total_images_processed" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
