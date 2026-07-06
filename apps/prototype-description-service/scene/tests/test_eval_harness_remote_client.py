"""VLM-2A Slice 2: remote client — Nygard discipline over httpx MockTransport (no network)."""

import httpx
import pytest

from scripts.eval_harness.remote_client import (
    CircuitOpenError,
    JobPollTimeoutError,
    RemoteClientError,
    RemoteSceneClient,
)


def _client(handler, **kwargs) -> RemoteSceneClient:
    transport = httpx.MockTransport(handler)
    return RemoteSceneClient(
        base_url="http://testserver",
        api_key="test-key",
        tenant_id="00000000-0000-4000-8000-0000000000e1",
        transport=transport,
        poll_interval=0.0,
        **kwargs,
    )


def test_describe_posts_multipart_with_auth_and_returns_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("X-API-Key")
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.read()
        return httpx.Response(200, json={"alt_text_draft": "A lake.", "media_id": 7})

    client = _client(handler)
    payload = client.describe(image_bytes=b"img", filename="a.jpg", media_id=7, context_pack={})
    assert payload["alt_text_draft"] == "A lake."
    assert seen["path"] == "/scene/describe/multipart"
    assert seen["auth"] == "test-key"
    assert seen["content_type"].startswith("multipart/form-data")
    # describe.py contract: single part named image_<media_id>; envelope has tenant_id
    assert b'name="image_7"' in seen["body"]
    assert b"00000000-0000-4000-8000-0000000000e1" in seen["body"]


def test_analyze_uses_image_media_id_part_names_and_returns_job_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read()
        # live JobStatusResponse contract uses 'id' (the reason for hotfix 2fe574fa)
        return httpx.Response(202, json={"id": "job-1", "status": "queued"})

    client = _client(handler)
    job_id = client.analyze(images=[(42, "a.jpg", b"img-bytes")])
    assert job_id == "job-1"
    assert b'name="image_42"' in seen["body"]
    # analyze_multipart.py contract: envelope needs only tenant_id; media ids are
    # derived server-side from the image_<id> part names, so the client must not
    # invent a media_ids envelope field the route ignores (rg-015, S2-07).
    assert b'"tenant_id": "00000000-0000-4000-8000-0000000000e1"' in seen["body"]
    assert b"media_ids" not in seen["body"]


def test_analyze_accepts_legacy_job_id_field():  # S2-07 back-compat fallback
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"job_id": "job-legacy", "status": "queued"})

    assert _client(handler).analyze(images=[(1, "a.jpg", b"x")]) == "job-legacy"


def test_wait_job_polls_until_done():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        status = "completed" if calls["n"] >= 3 else "running"
        return httpx.Response(200, json={"job_id": "job-1", "status": status})

    client = _client(handler)
    result = client.wait_job("job-1")
    assert result["status"] == "completed"
    assert calls["n"] == 3


def test_wait_job_bounded_poll_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "job-1", "status": "running"})

    client = _client(handler, max_poll_attempts=5)
    with pytest.raises(JobPollTimeoutError):
        client.wait_job("job-1")


def test_wait_job_failed_status_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "job-1", "status": "failed"})

    client = _client(handler)
    with pytest.raises(RemoteClientError, match="failed"):
        client.wait_job("job-1")


def test_wait_job_completed_with_errors_is_terminal_success():  # S2-01
    # Matches the live JobStatus contract: partial success is terminal, returns.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "job-1", "status": "completed_with_errors"})

    result = _client(handler, max_poll_attempts=3).wait_job("job-1")
    assert result["status"] == "completed_with_errors"


def test_wait_job_rejected_status_raises():  # S2-01
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "job-1", "status": "rejected"})

    with pytest.raises(RemoteClientError, match="rejected"):
        _client(handler).wait_job("job-1")


def test_media_identities_query():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["media_ids"] = request.url.params.get_list("media_ids")
        return httpx.Response(200, json={"identities": {"42": ["Alice"]}})

    client = _client(handler)
    payload = client.media_identities([42, 43])
    assert payload["identities"]["42"] == ["Alice"]
    # FastAPI list Query: repeated params, not comma-joined
    assert seen["media_ids"] == ["42", "43"]


def test_three_strike_circuit_breaker_opens():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client(handler)
    for _ in range(3):
        with pytest.raises(RemoteClientError):
            client.media_identities([1])
    with pytest.raises(CircuitOpenError):
        client.media_identities([1])


def test_success_resets_breaker():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"identities": {}})

    client = _client(handler)
    for _ in range(2):
        with pytest.raises(RemoteClientError):
            client.media_identities([1])
    assert client.media_identities([1]) == {"identities": {}}
    # breaker reset: two more failures do not open it
    calls["n"] = -10_000
    with pytest.raises(RemoteClientError):
        client.media_identities([1])


def test_http_error_carries_status_and_does_not_crash():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    client = _client(handler)
    with pytest.raises(RemoteClientError, match="401"):
        client.media_identities([1])


def test_429_backs_off_and_retries_without_breaker_strike():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, text="rate limit exceeded", headers={"Retry-After": "0"})
        return httpx.Response(200, json={"identities": {}})

    client = _client(handler, rate_limit_wait=0.0)
    assert client.media_identities([1]) == {"identities": {}}
    assert calls["n"] == 3
    # 429s did not count toward the 3-strike breaker
    assert client._consecutive_failures == 0


def test_429_exhaustion_raises_and_charges_breaker():  # S2-02
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limit exceeded", headers={"Retry-After": "0"})

    client = _client(handler, rate_limit_wait=0.0, max_rate_limit_retries=2)
    with pytest.raises(RemoteClientError, match="429"):
        client.media_identities([1])
    # terminal exhaustion is a request-level failure -> strikes the breaker so a
    # persistently rate-limited key can eventually open the circuit
    assert client._consecutive_failures == 1


def test_429_exhaustion_eventually_opens_circuit():  # S2-02
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limit exceeded", headers={"Retry-After": "0"})

    client = _client(handler, rate_limit_wait=0.0, max_rate_limit_retries=1)
    for _ in range(3):
        with pytest.raises(RemoteClientError):
            client.media_identities([1])
    with pytest.raises(CircuitOpenError):
        client.media_identities([1])


def test_retry_after_http_date_does_not_crash():  # S2-03
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            # HTTP-date form (RFC 9110), not a bare number -> must not raise ValueError
            return httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        return httpx.Response(200, json={"ok": True})

    client = _client(handler, rate_limit_wait=0.0)
    assert client.media_identities([1]) == {"ok": True}
    assert calls["n"] == 2


def test_clusters_paginates_until_short_page():  # S2-08
    pages = {"seen_offsets": []}
    full = [{"id": f"c{i}", "label": None} for i in range(200)]
    tail = [{"id": "c200", "label": None}]

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        pages["seen_offsets"].append(offset)
        return httpx.Response(200, json=full if offset == 0 else tail)

    client = _client(handler)
    result = client.clusters()
    assert len(result) == 201  # both pages aggregated, not just the first 200
    assert pages["seen_offsets"] == [0, 200]


def test_clusters_pagination_is_bounded():  # S2-08 rg-007 stall bound
    # a route that ignores offset and always returns a full page must not loop forever
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": f"c{i}", "label": None} for i in range(200)])

    with pytest.raises(RemoteClientError, match="pagination exceeded"):
        _client(handler).clusters()
