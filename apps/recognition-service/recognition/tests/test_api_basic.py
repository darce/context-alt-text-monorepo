"""
API Smoke Tests - Simplified

Basic tests to verify API endpoints respond correctly.
These tests are designed to work without heavy model dependencies.
"""

import pytest
from fastapi.testclient import TestClient
import io
from PIL import Image

from recognition.ports.api_routes import router


# Create test client
client = TestClient(router)


def create_test_image() -> bytes:
    """Create a simple test image as bytes."""
    img = Image.new('RGB', (100, 100), color=(128, 128, 128))
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    return img_bytes.getvalue()


def test_health_endpoint():
    """Test the health endpoint."""
    response = client.get("/api/v0/health")
    assert response.status_code == 200
    
    data = response.json()
    assert "status" in data
    # Note: status might be "warning" or "unhealthy" if no embeddings loaded


def test_service_info_endpoint():
    """Test the service info endpoint.""" 
    response = client.get("/api/v0/service/info")
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "success"
    assert "data" in data


def test_reload_embeddings_endpoint():
    """Test the reload embeddings endpoint."""
    response = client.post("/api/v0/service/reload-embeddings")
    assert response.status_code == 200
    
    data = response.json()
    assert "status" in data


def test_invalid_image_format():
    """Test handling of invalid image format."""
    invalid_file = b"This is not an image file"
    
    # The test client will propagate HTTPException as an exception
    # rather than converting to HTTP response, so we catch it
    try:
        response = client.post(
            "/api/v0/analyze-scene",
            files={"images": ("invalid.txt", invalid_file, "text/plain")},
            data={"use_roster": True}
        )
        # If we get here, check for 400 status
        assert response.status_code == 400
    except Exception as e:
        # FastAPI test client propagates HTTPException - verify it's the right one
        assert "Invalid image file" in str(e)
        assert "400" in str(e)


def test_analyze_scene_basic():
    """Test basic analyze-scene functionality."""
    test_image_bytes = create_test_image()
    
    response = client.post(
        "/api/v0/analyze-scene",
        files={"images": ("test.jpg", test_image_bytes, "image/jpeg")},
        data={"use_roster": True}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "total_images_processed" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
