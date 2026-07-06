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
        return httpx.Response(200, json={"alt_text_draft": "A lake.", "media_id": 7})

    client = _client(handler)
    payload = client.describe(image_bytes=b"img", filename="a.jpg", media_id=7, context_pack={})
    assert payload["alt_text_draft"] == "A lake."
    assert seen["path"] == "/scene/describe/multipart"
    assert seen["auth"] == "test-key"
    assert seen["content_type"].startswith("multipart/form-data")


def test_analyze_uses_image_media_id_part_names_and_returns_job_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read()
        return httpx.Response(202, json={"job_id": "job-1", "status": "queued"})

    client = _client(handler)
    job_id = client.analyze(images=[(42, "a.jpg", b"img-bytes")])
    assert job_id == "job-1"
    assert b'name="image_42"' in seen["body"]


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
