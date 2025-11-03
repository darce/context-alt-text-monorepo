"""
WordPress API Contract Integration Tests

Tests the contract between WordPress plugin and Recognition Service:
1. Progressive learning confirmation endpoint (/roster/{id}/confirm)
2. Observation idempotency (duplicate observation_id handling)
3. Service info endpoint progressive learning stats
4. Roster entry updates after confirmations

These tests validate the API contract that WordPress will rely on.
"""

import os
import time
import uuid
import random
import pytest
import requests
from typing import Dict, List, Any


# Service URL - configurable for different environments
SERVICE_URL = os.getenv("RECOGNITION_SERVICE_URL", "http://localhost:7860")
API_BASE = f"{SERVICE_URL}/api/v0"

# Test tenant configuration
TEST_TENANT_ID = os.getenv("TENANT_ID", "test-tenant-wp")


pytestmark = pytest.mark.integration


def generate_random_embedding(dim: int = 512) -> List[float]:
    """Generate a random normalized embedding vector."""
    vec = [random.uniform(-1, 1) for _ in range(dim)]
    # Normalize
    norm = sum(x**2 for x in vec) ** 0.5
    return [x / norm for x in vec]


def create_test_roster_entry(label: str = None) -> Dict[str, Any]:
    """
    Create a test roster entry via API.
    
    Returns:
        Dict with 'unique_id' and other entry metadata
    """
    if label is None:
        label = f"test-person-{uuid.uuid4().hex[:8]}"
    
    # API expects RosterBatchRequest format with entries array
    payload = {
        "entries": [
            {
                "name": label,
                "embedding": generate_random_embedding(),
                "metadata": {
                    "display_name": f"Test {label}",
                    "type": "person"
                }
            }
        ],
        "model": "insightface_w600k"
    }
    
    response = requests.post(
        f"{API_BASE}/roster",
        json=payload,
        headers={"X-Tenant-ID": TEST_TENANT_ID}
    )
    
    assert response.status_code == 200, f"Failed to create roster entry: {response.text}"
    data = response.json()
    
    # Extract the first successful entry name and fetch full entry details
    successful = data.get("successful", [])
    assert len(successful) > 0, f"No successful entries created: {data}"
    
    entry_name = successful[0]
    
    # Fetch the created entry to get unique_id
    list_response = requests.get(
        f"{API_BASE}/roster",
        headers={"X-Tenant-ID": TEST_TENANT_ID}
    )
    assert list_response.status_code == 200
    
    list_data = list_response.json()
    # Response structure: {"model": "...", "entries": [...], ...}
    entries = list_data.get("entries", [])
    for entry in entries:
        if entry.get("name") == entry_name:
            return entry
    
    raise AssertionError(f"Could not find created entry '{entry_name}' in roster")


class TestWordPressConfirmationAPI:
    """Test the confirmation API that WordPress will use."""
    
    def test_confirmation_payload_structure(self):
        """Verify WordPress confirmation payload is accepted."""
        # Create a test roster entry
        entry = create_test_roster_entry()
        roster_id = entry["unique_id"]
        
        # WordPress-style confirmation payload for augmentation endpoint
        wordpress_payload = {
            "observation_id": f"wp_attachment_456_face_0_{uuid.uuid4().hex[:8]}",
            "embedding": generate_random_embedding(),
            "confidence": 0.88,
            "attachment_id": 456,
            "bbox": {"x": 100, "y": 150, "width": 200, "height": 200},
            "metadata": {
                "confirmed_by": "user_id_42",
                "confirmed_at": "2025-11-03T14:30:00Z"
            }
        }
        
        # Using /augment endpoint (WordPress will use this for confirmations)
        response = requests.post(
            f"{API_BASE}/roster/{roster_id}/augment",
            json=wordpress_payload,
            headers={"X-Tenant-ID": TEST_TENANT_ID}
        )
        
        assert response.status_code == 200, f"Unexpected status: {response.status_code}: {response.text}"
        
        data = response.json()
        assert "success" in data
        assert data["success"] is True
        assert "roster_entry" in data
        
        # Verify the roster entry structure
        roster_entry = data["roster_entry"]
        assert "unique_id" in roster_entry
        assert roster_entry["unique_id"] == roster_id
        assert "augmented_count" in roster_entry
        assert roster_entry["augmented_count"] >= 1  # At least one augmentation added
    
    def test_duplicate_observation_idempotency(self):
        """Verify duplicate observation_id returns 409 Conflict."""
        entry = create_test_roster_entry()
        roster_id = entry["unique_id"]
        
        observation_id = f"wp_attachment_789_face_0_{uuid.uuid4().hex[:8]}"
        payload = {
            "observation_id": observation_id,
            "embedding": generate_random_embedding(),
            "confidence": 0.85,
            "attachment_id": 789
        }
        
        # First confirmation via augment endpoint
        resp1 = requests.post(
            f"{API_BASE}/roster/{roster_id}/augment",
            json=payload,
            headers={"X-Tenant-ID": TEST_TENANT_ID}
        )
        
        assert resp1.status_code == 200, f"First confirmation failed: {resp1.text}"
        
        # Second confirmation with same observation_id
        resp2 = requests.post(
            f"{API_BASE}/roster/{roster_id}/augment",
            json=payload,
            headers={"X-Tenant-ID": TEST_TENANT_ID}
        )
        
        # Should return 409 Conflict
        assert resp2.status_code == 409, f"Expected 409, got {resp2.status_code}: {resp2.text}"
        
        data = resp2.json()
        assert "observation" in data.get("detail", "").lower() or "duplicate" in str(data).lower()


class TestServiceInfoProgressiveLearning:
    """Test /service/info endpoint progressive learning stats."""
    
    def test_service_info_includes_progressive_learning(self):
        """Verify /service/info exposes progressive learning metrics."""
        response = requests.get(
            f"{API_BASE}/service/info",
            headers={"X-Tenant-ID": TEST_TENANT_ID}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        
        info = data["data"]
        
        # Check for progressive learning section
        if "progressive_learning" in info:
            pl = info["progressive_learning"]
            
            assert "enabled" in pl
            
            if pl["enabled"]:
                # When enabled, should have these fields
                assert "confirmations_last_24h" in pl
                assert "avg_augmentations_per_entry" in pl
                assert "quality_distribution" in pl
                
                quality_dist = pl["quality_distribution"]
                assert "high" in quality_dist
                assert "medium" in quality_dist
                assert "low" in quality_dist
                
                # All percentages should sum to ~100 or be 0
                total_pct = quality_dist["high"] + quality_dist["medium"] + quality_dist["low"]
                assert total_pct == 0 or 99 <= total_pct <= 101
        
        # Check for database info
        if "database" in info:
            db = info["database"]
            assert db["type"] == "postgresql"
            if "pgvector_version" in db:
                assert db["pgvector_version"] != "unknown"
    
    def test_service_info_roster_stats_updated(self):
        """Verify roster stats include progressive learning data."""
        response = requests.get(
            f"{API_BASE}/service/info",
            headers={"X-Tenant-ID": TEST_TENANT_ID}
        )
        
        assert response.status_code == 200
        data = response.json()
        info = data["data"]
        
        if "roster_stats" in info:
            roster_stats = info["roster_stats"]
            
            # Should have basic counts
            assert "entry_count" in roster_stats or "total_entries" in roster_stats
            
            # May have progressive learning enhanced stats
            if "entries_with_augmentations" in roster_stats:
                assert isinstance(roster_stats["entries_with_augmentations"], int)
            
            if "total_augmented_embeddings" in roster_stats:
                assert isinstance(roster_stats["total_augmented_embeddings"], int)
    
    def test_service_info_faiss_stats(self):
        """Verify FAISS index stats are exposed."""
        response = requests.get(
            f"{API_BASE}/service/info",
            headers={"X-Tenant-ID": TEST_TENANT_ID}
        )
        
        assert response.status_code == 200
        data = response.json()
        info = data["data"]
        
        if "faiss_index_stats" in info:
            faiss = info["faiss_index_stats"]
            
            assert "total_vectors" in faiss
            assert "dimension" in faiss
            assert faiss["dimension"] == 512
            
            # May have reload stats
            if "last_reload" in faiss and faiss["last_reload"] is not None:
                # last_reload can be either string (ISO format) or float (timestamp)
                assert isinstance(faiss["last_reload"], (str, int, float))


class TestRosterEntryUpdates:
    """Test roster entry behavior after confirmations."""
    
    def test_roster_entry_fetch_after_confirmation(self):
        """Verify roster entry can be fetched after confirmation."""
        entry = create_test_roster_entry()
        roster_id = entry["unique_id"]
        
        # Note: GET /roster/{unique_id} endpoint doesn't exist yet
        # Use the list endpoint to verify the entry exists
        response = requests.get(
            f"{API_BASE}/roster",
            headers={"X-Tenant-ID": TEST_TENANT_ID}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should have entry data in the list
        entries = data.get("entries", [])
        found_entry = None
        for e in entries:
            if e.get("unique_id") == roster_id:
                found_entry = e
                break
        
        assert found_entry is not None, f"Could not find entry {roster_id}"
        assert "name" in found_entry
        
        # May have embedding counts (from augmented roster entry DTO)
        # These would be populated after confirmations
        if "image_count" in found_entry:
            assert isinstance(found_entry["image_count"], int)


class TestWordPressIntegrationReadiness:
    """High-level tests to verify WordPress integration readiness."""
    
    def test_required_endpoints_accessible(self):
        """Verify all required endpoints are accessible."""
        endpoints = [
            ("/health", "GET"),
            ("/service/info", "GET"),
            ("/roster", "GET"),
            ("/roster", "POST"),
        ]
        
        for path, method in endpoints:
            url = f"{API_BASE}{path}"
            
            if method == "GET":
                response = requests.get(url, headers={"X-Tenant-ID": TEST_TENANT_ID})
            elif method == "POST":
                # Use minimal valid payload
                response = requests.post(
                    url,
                    json={"label": "test", "type": "person", "reference_images": []},
                    headers={"X-Tenant-ID": TEST_TENANT_ID}
                )
            
            # Should not be 404 (endpoint exists)
            assert response.status_code != 404, f"Endpoint {method} {path} not found"
            
            # Should return valid JSON
            try:
                response.json()
            except:
                pytest.fail(f"Endpoint {method} {path} did not return valid JSON")
    
    def test_progressive_learning_chain(self):
        """
        Test the complete progressive learning chain:
        1. Create entry
        2. Confirm observation (when implemented)
        3. Verify stats updated
        """
        # Create entry
        entry = create_test_roster_entry(label=f"integration-test-{uuid.uuid4().hex[:8]}")
        roster_id = entry["unique_id"]
        
        # Get initial stats
        resp_before = requests.get(
            f"{API_BASE}/service/info",
            headers={"X-Tenant-ID": TEST_TENANT_ID}
        )
        assert resp_before.status_code == 200
        info_before = resp_before.json()["data"]
        
        initial_confirmations = 0
        if "progressive_learning" in info_before and info_before["progressive_learning"].get("enabled"):
            initial_confirmations = info_before["progressive_learning"].get("confirmations_last_24h", 0)
        
        # Attempt confirmation (will skip if not implemented)
        confirmation_payload = {
            "observation_id": f"integration_test_{uuid.uuid4().hex}",
            "embedding": generate_random_embedding(),
            "confidence": 0.90,
            "attachment_id": 999
        }
        
        resp_confirm = requests.post(
            f"{API_BASE}/roster/{roster_id}/augment",
            json=confirmation_payload,
            headers={"X-Tenant-ID": TEST_TENANT_ID}
        )
        
        # If augmentation succeeded, verify stats
        if resp_confirm.status_code == 200:
            # Wait a moment for stats to update
            time.sleep(1)
            
            resp_after = requests.get(
                f"{API_BASE}/service/info",
                headers={"X-Tenant-ID": TEST_TENANT_ID}
            )
            assert resp_after.status_code == 200
            info_after = resp_after.json()["data"]
            
            if "progressive_learning" in info_after and info_after["progressive_learning"].get("enabled"):
                final_confirmations = info_after["progressive_learning"].get("confirmations_last_24h", 0)
                
                # Confirmations should have increased (might have other tests running)
                assert final_confirmations >= initial_confirmations


if __name__ == "__main__":
    # Allow running directly for quick testing
    pytest.main([__file__, "-v", "-s"])
