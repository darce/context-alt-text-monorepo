"""Portal composition wiring: the origin pin must reach the azp check."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from recognition.interface_adapters.http.deps.portal_composition import (
    _portal_auth_settings,
    _request_tenant_id,
    admit_usage,
)

ISSUER = "https://clerk.example.test"
JWKS_URL = "https://clerk.example.test/.well-known/jwks.json"


@pytest.fixture(autouse=True)
def _clear_portal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ACX_CLERK_ISSUER", "ACX_CLERK_JWKS_URL", "ACX_CLERK_AUTHORIZED_PARTIES"):
        monkeypatch.delenv(name, raising=False)


def _settings(**portal: object) -> SimpleNamespace:
    return SimpleNamespace(portal={"issuer": ISSUER, "jwks_url": JWKS_URL, **portal})


def test_distinct_audience_enforces_the_configured_authorized_parties() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(
        _settings(audience="clerk-instance-aud", authorized_parties="https://app.altcontext.io"),
        missing,
    )

    assert missing == []
    assert resolved is not None
    assert resolved.audience == ("clerk-instance-aud",)
    assert resolved.authorized_parties == ("https://app.altcontext.io",)


def test_authorized_parties_from_the_environment_reach_the_azp_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACX_CLERK_AUTHORIZED_PARTIES", "https://app.altcontext.io, https://admin.altcontext.io")
    missing: list[str] = []
    resolved = _portal_auth_settings(_settings(audience="clerk-instance-aud"), missing)

    assert resolved is not None
    assert resolved.authorized_parties == ("https://app.altcontext.io", "https://admin.altcontext.io")


def test_authorized_parties_alone_serve_as_the_audience_without_pinning_azp() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(_settings(authorized_parties="https://app.altcontext.io"), missing)

    assert missing == []
    assert resolved is not None
    assert resolved.audience == ("https://app.altcontext.io",)
    # Pinning azp to the audience value would reject every legitimate Clerk token.
    assert resolved.authorized_parties is None


def test_audience_is_never_taken_from_the_authorized_parties_setting_name() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(
        _settings(portal_audience="clerk-instance-aud", authorized_parties="https://app.altcontext.io"),
        missing,
    )

    assert resolved is not None
    assert resolved.audience == ("clerk-instance-aud",)
    assert resolved.authorized_parties == ("https://app.altcontext.io",)


def test_missing_configuration_is_reported_rather_than_guessed() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(_settings(), missing)

    assert resolved is None
    assert "ACX_CLERK_AUTHORIZED_PARTIES" in missing


class _RecordingAdmissionService:
    def __init__(self) -> None:
        self.ticket = object()
        self.events: list[str] = []

    async def reserve(self, tenant_id: UUID, **_kwargs: object) -> object:
        self.events.append("reserve")
        return self.ticket

    async def commit(self, ticket: object) -> None:
        assert ticket is self.ticket
        self.events.append("commit")

    async def release(self, ticket: object) -> None:
        assert ticket is self.ticket
        self.events.append("release")


async def _run_admission_dependency(
    service: _RecordingAdmissionService,
    *,
    route_error: BaseException | None = None,
) -> None:
    tenant_id = uuid4()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/recognition/analyze",
        "raw_path": b"/recognition/analyze",
        "query_string": b"",
        "headers": [(b"idempotency-key", b"analysis-1")],
        "client": ("test", 123),
        "server": ("test", 80),
    }
    dependency = admit_usage(Request(scope), service, SimpleNamespace(tenant_claim=str(tenant_id)))
    if hasattr(dependency, "asend"):
        await anext(dependency)
        if route_error is None:
            with pytest.raises(StopAsyncIteration):
                await anext(dependency)
        else:
            with pytest.raises(type(route_error)):
                await dependency.athrow(route_error)
    else:
        await dependency


@pytest.mark.asyncio
async def test_admission_commits_its_reservation_after_successful_route() -> None:
    service = _RecordingAdmissionService()

    await _run_admission_dependency(service)

    assert service.events == ["reserve", "commit"]


@pytest.mark.asyncio
async def test_admission_releases_its_reservation_when_route_raises() -> None:
    service = _RecordingAdmissionService()

    await _run_admission_dependency(service, route_error=RuntimeError("analysis failed"))

    assert service.events == ["reserve", "release"]


@pytest.mark.asyncio
async def test_admission_releases_its_reservation_when_client_disconnects() -> None:
    service = _RecordingAdmissionService()

    await _run_admission_dependency(service, route_error=asyncio.CancelledError())

    assert service.events == ["reserve", "release"]


def _multipart_request(
    body: bytes,
    *,
    receive=None,
    declared_length: int | None = None,
) -> Request:
    headers = [(b"content-type", b"multipart/form-data; boundary=tenant-test")]
    if receive is None:
        length = len(body) if declared_length is None else declared_length
        headers.append((b"content-length", str(length).encode("ascii")))

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/recognition/analyze/multipart",
        "raw_path": b"/recognition/analyze/multipart",
        "query_string": b"",
        "headers": headers,
        "client": ("test", 123),
        "server": ("test", 80),
    }
    return Request(scope, receive)


def _multipart_envelope_and_image(image: bytes) -> bytes:
    tenant_id = "12345678-1234-5678-1234-567812345678"
    return (
        b"--tenant-test\r\n"
        b'Content-Disposition: form-data; name="request"\r\n'
        b"Content-Type: application/json\r\n\r\n"
        + b'{"tenant_id":"' + tenant_id.encode("ascii") + b'"}\r\n'
        b"--tenant-test\r\n"
        b'Content-Disposition: form-data; name="image_1"; filename="image.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
        + image
        + b"\r\n--tenant-test--\r\n"
    )


@pytest.mark.asyncio
async def test_multipart_tenant_lookup_caches_bounded_body_for_route_parser() -> None:
    body = _multipart_envelope_and_image(b"image-bytes")
    request = _multipart_request(body)

    tenant_id = await _request_tenant_id(request)

    assert tenant_id == UUID("12345678-1234-5678-1234-567812345678")
    assert await request.body() == body


@pytest.mark.asyncio
async def test_multipart_tenant_lookup_rejects_body_over_its_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recognition.interface_adapters.http.deps.portal_composition._MAX_TENANT_LOOKUP_BODY_BYTES",
        128,
        raising=False,
    )
    request = _multipart_request(_multipart_envelope_and_image(b"x" * 256), declared_length=1)

    with pytest.raises(HTTPException) as error:
        await _request_tenant_id(request)

    assert error.value.status_code == 413


@pytest.mark.asyncio
async def test_multipart_tenant_lookup_times_out_while_reading_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recognition.interface_adapters.http.deps.portal_composition._TENANT_LOOKUP_READ_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )

    async def slow_receive():
        await asyncio.Event().wait()

    request = _multipart_request(b"", receive=slow_receive)

    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(_request_tenant_id(request), timeout=0.25)

    assert error.value.status_code == 408
