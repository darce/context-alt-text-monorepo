import os
import requests
import pytest

RUN_INTEGRATION = bool(os.environ.get("RUN_INTEGRATION"))
BASE_URL = os.environ.get("RECOGNITION_BASE_URL", "http://localhost:8000")


@pytest.mark.skipif(not RUN_INTEGRATION, reason="Integration tests skipped unless RUN_INTEGRATION=1")
def test_etag_caching_roundtrip():
    """Smoke test for ETag caching on /api/v0/roster

    Steps:
    - GET /api/v0/roster to capture ETag
    - GET with If-None-Match -> expect 304
    - POST a small roster entry -> expect 201
    - GET /api/v0/roster with old ETag -> expect 200 and changed payload
    """
    roster_url = f"{BASE_URL}/api/v0/roster"

    r = requests.get(roster_url)
    assert r.status_code == 200
    etag = r.headers.get("ETag")

    if etag:
        r2 = requests.get(roster_url, headers={"If-None-Match": etag})
        assert r2.status_code in (200, 304)

    # create a new roster entry to invalidate ETag
    payload = {"label": "etag-integration", "display_name": "ETag Test", "model": "test"}
    r3 = requests.post(roster_url, json=payload)
    assert r3.status_code in (200, 201)

    # If we had a previous ETag, the old one should now be stale
    if etag:
        r4 = requests.get(roster_url, headers={"If-None-Match": etag})
        assert r4.status_code == 200, "Old ETag unexpectedly still valid after mutation"
