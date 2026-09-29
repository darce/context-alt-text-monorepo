"""Regression tests for independently composed usage admission."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from fastapi.routing import APIRoute


def _route(app, path: str, method: str) -> APIRoute:
    matches = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == path and method in (route.methods or set())
    ]
    assert len(matches) == 1, f"expected one {method} {path}, got {len(matches)}"
    return matches[0]


def _dependency_calls(route: APIRoute) -> set[object]:
    pending = list(route.dependant.dependencies)
    calls: set[object] = set()
    while pending:
        dependency = pending.pop()
        if dependency.call is not None:
            calls.add(dependency.call)
        pending.extend(dependency.dependencies)
    return calls


def test_usage_admission_mounts_without_the_portal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    monkeypatch.delenv("RECOGNITION_PORTAL_ENABLED", raising=False)
    monkeypatch.setenv("RECOGNITION_BETA_ADMISSION_ENABLED", "1")
    monkeypatch.delenv("RECOGNITION_ADMIN_ENABLED", raising=False)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN", raising=False)

    from api.main import create_app
    from recognition.interface_adapters.http.deps import portal_composition

    admit_usage = getattr(portal_composition, "admit_usage", None)
    assert callable(admit_usage), "composition must expose the usage admission dependency"

    app = create_app()

    assert getattr(app.state, "usage_admission_service_factory", None) is not None
    for path in ("/recognition/analyze", "/recognition/analyze/multipart"):
        assert admit_usage in _dependency_calls(_route(app, path, "POST"))
    assert admit_usage not in _dependency_calls(_route(app, "/recognition/jobs/{job_id}", "GET"))


class _UsageAdmissionStub:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, str | None, int]] = []
        self.ticket = object()
        self.commits: list[object] = []
        self.releases: list[object] = []

    async def reserve(
        self,
        tenant_id: UUID,
        *,
        idempotency_key: str,
        job_id: str | None,
        cost_units: int,
    ) -> object:
        self.calls.append((tenant_id, idempotency_key, job_id, cost_units))
        return self.ticket

    async def commit(self, ticket: object) -> None:
        self.commits.append(ticket)

    async def release(self, ticket: object) -> None:
        self.releases.append(ticket)


def _request(*, path: str, body: bytes, content_type: str) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", content_type.encode()),
            (b"idempotency-key", b"request-123"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
@pytest.mark.parametrize("multipart", (False, True))
async def test_admit_usage_reserves_analysis_request(multipart: bool) -> None:
    from recognition.interface_adapters.http.deps import portal_composition

    admit_usage = getattr(portal_composition, "admit_usage", None)
    assert callable(admit_usage), "composition must expose the usage admission dependency"

    tenant_id = uuid4()
    if multipart:
        boundary = "usage-test-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="request"\r\n'
            "Content-Type: application/json\r\n\r\n"
            f'{json.dumps({"tenant_id": str(tenant_id)})}\r\n'
            f"--{boundary}--\r\n"
        ).encode()
        content_type = f"multipart/form-data; boundary={boundary}"
        path = "/recognition/analyze/multipart"
    else:
        body = json.dumps({"tenant_id": str(tenant_id), "media_ids": []}).encode()
        content_type = "application/json"
        path = "/recognition/analyze"

    service = _UsageAdmissionStub()
    request = _request(path=path, body=body, content_type=content_type)
    dependency = admit_usage(
        request,
        usage_admission_service=service,
        auth=SimpleNamespace(tenant_claim=None if multipart else str(tenant_id)),
    )
    await anext(dependency)

    assert service.calls == [(tenant_id, "request-123", None, 1)]
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)
    assert service.commits == [service.ticket]
    assert service.releases == []
    if multipart:
        from recognition.interface_adapters.http.routers.analyze_multipart import _parse_multipart_form

        parsed_form = await _parse_multipart_form(request)
        assert parsed_form.get("request") == json.dumps({"tenant_id": str(tenant_id)})
        await parsed_form.close()


class _FailingCommitAdmissionService:
    def __init__(self) -> None:
        self.ticket = object()
        self.commit_error = RuntimeError("commit failed")
        self.events: list[str] = []

    async def reserve(self, tenant_id: UUID, **_kwargs: object) -> object:
        self.events.append("reserve")
        return self.ticket

    async def commit(self, ticket: object) -> None:
        assert ticket is self.ticket
        self.events.append("commit")
        raise self.commit_error

    async def release(self, ticket: object) -> None:
        assert ticket is self.ticket
        self.events.append("release")


@pytest.mark.asyncio
async def test_admission_releases_ticket_when_commit_fails_and_propagates_error() -> None:
    from recognition.interface_adapters.http.deps.portal_composition import admit_usage

    service = _FailingCommitAdmissionService()
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
    dependency = admit_usage(Request(scope), service, SimpleNamespace(tenant_claim=str(uuid4())))

    await anext(dependency)
    with pytest.raises(RuntimeError, match="commit failed") as raised:
        await anext(dependency)

    assert raised.value is service.commit_error
    assert service.events == ["reserve", "commit", "release"]


@pytest.mark.asyncio
async def test_admit_usage_yields_once_when_admission_is_disabled() -> None:
    from recognition.interface_adapters.http.deps.portal_composition import admit_usage

    dependency = admit_usage(
        _request(path="/recognition/analyze", body=b"", content_type="application/json"),
        usage_admission_service=None,
        auth=SimpleNamespace(tenant_claim=None),
    )

    assert await anext(dependency) is None
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)
    await dependency.aclose()
