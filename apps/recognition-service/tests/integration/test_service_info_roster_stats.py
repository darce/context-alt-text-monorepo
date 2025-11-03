"""Integration test for /service/info roster_stats.

This test verifies that the /service/info endpoint returns roster_stats
that reflect actual database state after augment operations.

Run with: RUN_INTEGRATION=1 pytest tests/integration/test_service_info_roster_stats.py -v
"""

import os
import uuid
import requests
import pytest

RUN_INTEGRATION = bool(os.environ.get("RUN_INTEGRATION"))
BASE_URL = os.environ.get("RECOGNITION_BASE_URL", "http://localhost:8000")


@pytest.mark.skipif(not RUN_INTEGRATION, reason="Integration tests skipped unless RUN_INTEGRATION=1")
def test_service_info_roster_stats_reflect_augmented_embeddings():
    """
    Integration test: verify /service/info roster_stats update after augment operations.
    
    Steps:
    1. GET /api/v0/service/info -> capture initial roster_stats
    2. POST /api/v0/roster -> create a roster entry
    3. POST /api/v0/roster/{id}/augment -> add augmented embeddings
    4. GET /api/v0/service/info -> verify roster_stats.augmented_embeddings increased
    """
    service_info_url = f"{BASE_URL}/api/v0/service/info"
    roster_url = f"{BASE_URL}/api/v0/roster"
    
    # Step 1: Get initial stats
    r = requests.get(service_info_url)
    assert r.status_code == 200, f"Failed to get service info: {r.status_code} {r.text}"
    
    initial_data = r.json().get("data", {})
    initial_roster_stats = initial_data.get("roster_stats", {})
    initial_augmented = initial_roster_stats.get("augmented_embeddings", 0)
    initial_total = initial_roster_stats.get("total_embeddings", 0)
    
    print(f"Initial roster_stats: {initial_roster_stats}")
    
    # Verify roster_stats structure
    assert "entry_count" in initial_roster_stats
    assert "reference_embeddings" in initial_roster_stats
    assert "augmented_embeddings" in initial_roster_stats
    assert "total_embeddings" in initial_roster_stats
    
    # Verify faiss_index_stats structure
    faiss_stats = initial_data.get("faiss_index_stats", {})
    assert "total_vectors" in faiss_stats
    assert "dimension" in faiss_stats
    assert faiss_stats["dimension"] == 512
    
    print(f"Initial FAISS stats: {faiss_stats}")
    
    # Step 2: Create roster entry
    roster_payload = {
        "label": f"integration-test-{uuid.uuid4().hex[:8]}",
        "display_name": "Integration Test Person",
        "model": "insightface_w600k",
        "metadata": {"source": "integration-test"}
    }
    
    r = requests.post(roster_url, json=roster_payload)
    assert r.status_code in (200, 201), f"Failed to create roster entry: {r.status_code} {r.text}"
    
    entry = r.json()
    roster_id = entry.get("id") or entry.get("data", {}).get("id")
    assert roster_id, "roster_id missing from create response"
    
    print(f"Created roster entry: {roster_id}")
    
    # Step 3: Add augmented embeddings
    augment_url = f"{BASE_URL}/api/v0/roster/{roster_id}/augment"
    embeddings_to_add = 3
    
    for i in range(embeddings_to_add):
        augment_payload = {
            "observation_id": str(uuid.uuid4()),
            "embedding": [0.01 * (i + 1)] * 512,
            "source": "integration-test",
            "quality_tier": "medium"
        }
        
        r = requests.post(augment_url, json=augment_payload)
        assert r.status_code in (200, 201), f"Augment failed: {r.status_code} {r.text}"
        print(f"Added augmented embedding {i+1}/{embeddings_to_add}")
    
    # Step 4: Verify updated stats
    r = requests.get(service_info_url)
    assert r.status_code == 200
    
    updated_data = r.json().get("data", {})
    updated_roster_stats = updated_data.get("roster_stats", {})
    updated_augmented = updated_roster_stats.get("augmented_embeddings", 0)
    updated_total = updated_roster_stats.get("total_embeddings", 0)
    
    print(f"Updated roster_stats: {updated_roster_stats}")
    
    # Verify augmented_embeddings increased
    assert updated_augmented >= initial_augmented + embeddings_to_add, (
        f"Expected augmented_embeddings to increase by at least {embeddings_to_add}, "
        f"but got {updated_augmented} (was {initial_augmented})"
    )
    
    # Verify total_embeddings increased
    assert updated_total >= initial_total + embeddings_to_add, (
        f"Expected total_embeddings to increase by at least {embeddings_to_add}, "
        f"but got {updated_total} (was {initial_total})"
    )
    
    # Verify FAISS stats also updated (if FAISS reload is fast enough)
    updated_faiss_stats = updated_data.get("faiss_index_stats", {})
    print(f"Updated FAISS stats: {updated_faiss_stats}")
    
    # Note: FAISS may not reload instantly, so we don't assert on vector count
    # but we verify the structure is still present
    assert "total_vectors" in updated_faiss_stats
    assert "dimension" in updated_faiss_stats
    
    print("✅ Integration test passed: roster_stats correctly reflect augmented embeddings")


@pytest.mark.skipif(not RUN_INTEGRATION, reason="Integration tests skipped unless RUN_INTEGRATION=1")
def test_service_info_faiss_stats_structure():
    """
    Verify that faiss_index_stats includes all expected fields.
    """
    service_info_url = f"{BASE_URL}/api/v0/service/info"
    
    r = requests.get(service_info_url)
    assert r.status_code == 200
    
    data = r.json().get("data", {})
    faiss_stats = data.get("faiss_index_stats", {})
    
    # Required fields
    assert "total_vectors" in faiss_stats
    assert "dimension" in faiss_stats
    assert "index_type" in faiss_stats
    
    # Verify dimension value
    assert faiss_stats["dimension"] == 512
    
    # Verify index_type is a non-empty string
    assert isinstance(faiss_stats["index_type"], str)
    assert len(faiss_stats["index_type"]) > 0
    
    # Optional fields (may be present if reload has occurred)
    # last_reload, last_reload_duration_ms
    
    print(f"FAISS index stats: {faiss_stats}")
    print("✅ FAISS stats structure verified")
