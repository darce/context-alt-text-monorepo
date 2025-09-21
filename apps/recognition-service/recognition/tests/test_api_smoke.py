"""
API Smoke Tests

Basic smoke tests to verify the recognition API endpoints work.
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
    """Create a sample RGB image for testing."""
    # Create a simple 100x100 RGB image
    image = Image.new('RGB', (100, 100), color=(128, 128, 128))
    
    # Convert to bytes
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='JPEG')
    img_byte_arr.seek(0)
    
    return img_byte_arr


def test_health_endpoint(client):
    """Test the health check endpoint."""
    response = client.get("/api/v0/health")
    assert response.status_code == 200
    
    data = response.json()
    assert "status" in data
    assert "model" in data


def test_service_info_endpoint(client):
    """Test the service info endpoint."""
    response = client.get("/api/v0/service/info")
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "success"
    assert "data" in data
    assert "model" in data["data"]
    assert data["data"]["model"] == "deepinsight/insightface-scrfd-arcface-w600k"


def test_analyze_scene_endpoint(client, sample_image):
    """Test the main analyze-scene endpoint."""
    response = client.post(
        "/api/v0/analyze-scene",
        files={"images": ("test.jpg", sample_image, "image/jpeg")},
        data={"use_roster": True}
    )
    
    # Should return 200 even if no faces detected
    assert response.status_code == 200
    
    data = response.json()
    assert "results" in data
    assert "total_images_processed" in data
    assert data["total_images_processed"] == 1
    assert "roster_identification_enabled" in data
    assert data["roster_identification_enabled"] is True


def test_analyze_scene_with_threshold(client, sample_image):
    """Test the analyze-scene endpoint with threshold parameter."""
    response = client.post(
        "/api/v0/analyze-scene/0.5",
        files={"images": ("test.jpg", sample_image, "image/jpeg")},
        data={"use_roster": True}
    )
    
    assert response.status_code == 200
    
    data = response.json()
    assert "results" in data
    assert "configuration_used" in data
    assert data["configuration_used"]["threshold"] == 0.5


def test_reload_embeddings_endpoint(client):
    """Test the reload embeddings endpoint."""
    response = client.post("/api/v0/service/reload-embeddings")
    
    # Should return 200 even if no embeddings file exists
    assert response.status_code == 200
    
    data = response.json()
    assert "status" in data
    assert "message" in data


def test_analyze_scene_multiple_images(client, sample_image):
    """Test analyze-scene with multiple images."""
    # Create second image
    sample_image2 = io.BytesIO()
    image2 = Image.new('RGB', (50, 50), color=(255, 0, 0))
    image2.save(sample_image2, format='JPEG')
    sample_image2.seek(0)
    
    response = client.post(
        "/api/v0/analyze-scene",
        files=[
            ("images", ("test1.jpg", sample_image, "image/jpeg")),
            ("images", ("test2.jpg", sample_image2, "image/jpeg"))
        ],
        data={"use_roster": True}
    )
    
    assert response.status_code == 200
    
    data = response.json()
    assert data["total_images_processed"] == 2
    assert len(data["results"]) == 2


def test_invalid_image_format(client):
    """Test handling of invalid image format."""
    invalid_file = io.BytesIO(b"not an image")
    
    response = client.post(
        "/api/v0/analyze-scene",
        files={"images": ("invalid.txt", invalid_file, "text/plain")},
        data={"use_roster": True}
    )
    
    # Should return 400 for invalid image
    assert response.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
