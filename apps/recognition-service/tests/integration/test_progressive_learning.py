import os
import time
import uuid
import requests
import pytest

RUN_INTEGRATION = bool(os.environ.get("RUN_INTEGRATION"))
BASE_URL = os.environ.get("RECOGNITION_BASE_URL", "http://localhost:8000")


@pytest.mark.skipif(not RUN_INTEGRATION, reason="Integration tests skipped unless RUN_INTEGRATION=1")
def test_progressive_learning_workflow():
    """Smoke test for progressive learning:
    - create a roster entry
    - post a batch of augmented embeddings via /roster/{id}/augment
    - verify aggregate_embedding exists on the roster entry

    This test is a smoke test and will be skipped by default.
    """
    # Create roster entry
    create_url = f"{BASE_URL}/api/v0/roster"
    payload = {
        "label": "integration-test-person",
        "display_name": "Integration Test",
        "model": "test-model",
        "metadata": {"source": "integration-test"}
    }
    r = requests.post(create_url, json=payload)
    assert r.status_code in (200, 201), f"Failed to create roster entry: {r.status_code} {r.text}"
    entry = r.json()
    roster_id = entry.get("id") or entry.get("data", {}).get("id")
    assert roster_id, "roster_id missing from create response"

    # Post augmented embeddings
    augment_url = f"{BASE_URL}/api/v0/roster/{roster_id}/augment"
    embeddings = []
    for i in range(3):
        embeddings.append({
            "observation_id": str(uuid.uuid4()),
            "embedding": [0.01 * (i + 1)] * 512,
            "source": "integration-test",
            "quality_tier": "low"
        })

    for emb in embeddings:
        r = requests.post(augment_url, json=emb)
        assert r.status_code in (200, 201), f"augment failed: {r.status_code} {r.text}"

    # Allow background processing/FAISS refresh a short time (configurable)
    time.sleep(1)

    # Fetch roster entry and check aggregate_embedding presence
    get_url = f"{BASE_URL}/api/v0/roster/{roster_id}"
    r = requests.get(get_url)
    assert r.status_code == 200, f"Failed to fetch roster entry: {r.status_code} {r.text}"
    body = r.json()
    agg = body.get("aggregate_embedding") or body.get("data", {}).get("aggregate_embedding")
    assert agg is not None, "aggregate_embedding not present after augment"
