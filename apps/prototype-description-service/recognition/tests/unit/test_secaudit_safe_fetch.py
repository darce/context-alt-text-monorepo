"""Local SSRF regression checks; no live hosts are contacted."""

import asyncio
import socket

import httpx
import pytest

from recognition.shared.safe_fetch import SafeFetchError, fetch_public_image


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://127.0.0.1/a", "http://10.1.2.3/a", "http://169.254.169.254/a",
    "http://[::1]/a", "http://[::ffff:127.0.0.1]/a", "file:///tmp/image",
    "gopher://8.8.8.8/a", "http:///missing", "http://private.test/a",
])
async def test_rejects_internal_or_invalid_destinations_without_request(url):
    calls = []

    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 80))]

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r))) as client:
        with pytest.raises(SafeFetchError):
            await fetch_public_image(url, client=client, timeout=1, resolver=resolve)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [[], ["8.8.8.8", "127.0.0.1"], ["::ffff:10.0.0.1"]])
async def test_requires_every_dns_address_to_be_public(addresses):
    calls = []

    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80)) for ip in addresses]

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r))) as client:
        with pytest.raises(SafeFetchError):
            await fetch_public_image("https://mixed.test/a", client=client, timeout=1, resolver=resolve)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,limit,accepted", [
    (200, b"image", 5, True), (302, b"", 5, False), (200, b"large!", 5, False),
])
async def test_public_response_policy(status, body, limit, accepted):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, content=body, headers={"location": "http://127.0.0.1/"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        if accepted:
            assert await fetch_public_image("https://8.8.8.8/a", client=client, timeout=1, max_bytes=limit) == body
        else:
            with pytest.raises(SafeFetchError):
                await fetch_public_image("https://8.8.8.8/a", client=client, timeout=1, max_bytes=limit)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_dns_resolution_is_within_deadline():
    calls = []

    async def resolve(*args, **kwargs):
        await asyncio.sleep(1)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r))) as client:
        with pytest.raises(SafeFetchError):
            await fetch_public_image("http://slow.test/", client=client, timeout=0.01, resolver=resolve)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("detector_type", ["insightface", "pipeline"])
async def test_injected_detector_client_is_guarded(detector_type):
    from recognition.application.embedding.detector import InsightFaceFaceDetector
    from recognition.infrastructure.embeddings.face_pipeline_adapter import FacePipelineFaceDetector

    cls = InsightFaceFaceDetector if detector_type == "insightface" else FacePipelineFaceDetector
    detector = object.__new__(cls)
    detector._timeout = 1
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r))) as client:
        detector._client = client
        assert await detector._fetch_image("http://169.254.169.254/") is None
    assert calls == []


@pytest.mark.asyncio
async def test_default_resolver_path_is_checked(monkeypatch):
    from recognition.shared import safe_fetch

    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]

    monkeypatch.setattr(safe_fetch, "_getaddrinfo", resolve)
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r))) as client:
        with pytest.raises(SafeFetchError):
            await fetch_public_image("http://metadata.test/", client=client, timeout=1)
    assert calls == []
