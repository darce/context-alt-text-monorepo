import os
import time
import uuid
import requests
import pytest

RUN_E2E = bool(os.environ.get("RUN_E2E"))
BASE_URL = os.environ.get("RECOGNITION_BASE_URL", "http://localhost:7860")


@pytest.mark.skipif(not RUN_E2E, reason="E2E tests skipped unless RUN_E2E=1")
def test_progressive_learning_workflow():
    """Smoke test for progressive learning:
    - create a roster entry
    - post a batch of augmented embeddings via /roster/{id}/augment
    - verify aggregate_embedding exists on the roster entry

    This test is a smoke test and will be skipped by default.
    """
    # Create roster entry with current API format (entries array)
    create_url = f"{BASE_URL}/api/v0/roster"
    name = f"integration-test-{uuid.uuid4()}"
    test_model = "test-model"
    payload = {
        "entries": [
            {
                "name": name,
                "embedding": [0.1] * 512,
                "metadata": {
                    "entity_type": "person",
                    "display_name": "Integration Test",
                    "source": "integration-test"
                }
            }
        ],
        "model": test_model
    }
    r = requests.post(create_url, json=payload)
    assert r.status_code in (200, 201), f"Failed to create roster entry: {r.status_code} {r.text}"
    data = r.json()
    successful = data.get("successful", [])
    assert len(successful) > 0, "No successful entries created"
    
    # The successful list contains the entry name we just created
    created_name = successful[0]
    
    # Allow brief time for entry to be committed
    time.sleep(0.2)
    
    # Get unique_id by fetching from list - use model filter to narrow results
    list_response = requests.get(f"{BASE_URL}/api/v0/roster?model={test_model}")
    assert list_response.status_code == 200, \
        f"Failed to list roster: {list_response.status_code} {list_response.text}"
    
    list_data = list_response.json()
    entries = list_data.get("entries", [])
    
    # Find our entry by name
    roster_id = None
    for entry in entries:
        if entry.get("name") == created_name:
            roster_id = entry.get("unique_id")
            break
    
    # More helpful error message if not found
    if not roster_id:
        entry_names = [e.get("name") for e in entries[:10]]  # Show first 10
        assert False, (
            f"Could not find entry '{created_name}' in roster. "
            f"Total entries: {len(entries)}, First 10 names: {entry_names}"
        )

    # Post augmented embeddings
    augment_url = f"{BASE_URL}/api/v0/roster/{roster_id}/augment"
    last_response = None
    for i in range(3):
        payload = {
            "observation_id": str(uuid.uuid4()),
            "embedding": [0.01 * (i + 1)] * 512,
            "model": test_model,  # Include model parameter
            "metadata": {
                "source": "integration-test",
                "quality_tier": "low",
                "confidence": 0.75
            }
        }
        r = requests.post(augment_url, json=payload)
        assert r.status_code in (200, 201), f"augment failed: {r.status_code} {r.text}"
        last_response = r

    # Check aggregate_embedding from last augment response
    assert last_response is not None
    body = last_response.json()
    roster_entry = body.get("roster_entry", {})
    agg = roster_entry.get("aggregate_embedding")
    assert agg is not None, "aggregate_embedding not present after augment"
    assert len(agg) == 512, f"aggregate_embedding has wrong dimension: {len(agg)}"
