"""Integration test for POST /recognition/analyze/multipart (E15-11 Slice 1.4d).

Wires the new route into a minimal FastAPI app with overrides for auth,
session, scan_queue, settings, and ObjectStore. Verifies the route accepts
a multipart submission, persists each image part through ObjectStore.put,
calls scan_queue.create_scan_job_record with the pre-generated job_id,
and returns 202 with the matching id. Negative paths assert the 422 / 400
/ 403 boundary checks at the route level.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from starlette.datastructures import FormData, Headers, UploadFile
from starlette.requests import ClientDisconnect, Request
from starlette.testclient import TestClient

from recognition.application.storage import FilesystemObjectStore, ObjectStoreError
from recognition.config.settings import RecognitionSettings
from recognition.interface_adapters.http.deps import (
    get_optional_session,
    get_scan_queue_service_optional,
    require_write_access,
)
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.deps.object_store import (
    _settings_default,
    get_object_store_factory_for_request,
)
from recognition.interface_adapters.http.exception_handlers import register_exception_handlers
from recognition.interface_adapters.http.middleware.correlation import (
    CORRELATION_ID_HEADER,
    CorrelationIdMiddleware,
)
from recognition.interface_adapters.http.routers.analyze_multipart import router

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes-for-tests"


class _FakeScanQueue:
    """Captures route -> scan_queue calls so tests can assert on them."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.populate_calls: list[dict] = []

    async def create_scan_job_record(
        self,
        *,
        tenant_id: uuid.UUID,
        total: int,
        created_by_user_id: int | None = None,
        job_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        # The multipart route must pass the pre-generated job_id.
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "total": total,
                "job_id": job_id,
                "created_by_user_id": created_by_user_id,
            }
        )
        assert job_id is not None, "multipart route must pre-generate job_id"
        return job_id

    async def populate_scan_job_items(self, **kwargs) -> int:
        # Reached via chain_populate_and_process scheduled by the route
        # (BR-05). Recorded so tests can introspect dispatch shape; returns
        # the number of items "enqueued" to satisfy the caller's contract.
        self.populate_calls.append(kwargs)
        media_items = kwargs.get("media_items") or []
        return len(list(media_items))


class _CommitOnlySession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()

    async def execute(self, *args, **kwargs):
        return None

    async def commit(self) -> None:
        self.commit_calls += 1


def _patch_scan_dispatch_ready(monkeypatch: pytest.MonkeyPatch, *, mod=None) -> None:
    """Bypass worker/capability intake gate — multipart route tests own other boundaries."""
    from recognition.application.scan import capability as capability_module
    from recognition.interface_adapters.http.routers import analyze_multipart as multipart_mod

    async def _ready(_session, *, inline_processing: bool) -> None:
        return None

    target = mod if mod is not None else multipart_mod
    monkeypatch.setattr(target, "require_scan_dispatch_ready", _ready)
    monkeypatch.setattr(capability_module, "require_scan_dispatch_ready", _ready)


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def app_with_overrides(tmp_path: Path, tenant_id: str, monkeypatch: pytest.MonkeyPatch):
    # The repo-wide conftest enables RECOGNITION_ASYNC_ANALYZE_INLINE so the
    # JSON analyze flow exercises the inline-processor in tests; the multipart
    # route's BackgroundTask would then try to hit a real DB through
    # process_scan_job_inline. Force it off here so the route's dispatch can
    # be exercised against the fake scan queue alone.
    monkeypatch.setenv("RECOGNITION_ASYNC_ANALYZE_INLINE", "0")

    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "blobs"

    fake_queue = _FakeScanQueue()

    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/recognition")

    fastapi_app.dependency_overrides[require_write_access] = lambda: AuthContext(token="t", tenant_claim=tenant_id)
    fastapi_app.dependency_overrides[get_optional_session] = lambda: None
    fastapi_app.dependency_overrides[get_scan_queue_service_optional] = lambda: fake_queue
    fastapi_app.dependency_overrides[_settings_default] = lambda: settings

    return fastapi_app, fake_queue, settings


def _multipart_submission(tenant_id: str) -> dict:
    """Build a multipart submission with one image part and a JSON request part."""
    return {
        "files": [
            (
                "request",
                ("request.json", json.dumps({"tenant_id": tenant_id}), "application/json"),
            ),
            ("image_42", ("a.png", PNG_BYTES, "image/png")),
        ],
    }


def test_multipart_happy_path_returns_202_and_stores_blob(
    app_with_overrides, tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies the route's synchronous behaviour: blob written, scan job
    record created with pre-generated id, 202 returned. The BackgroundTask
    is monkeypatched out so the cleanup phase wired in S1.6 does not race
    the assertions about on-disk state."""
    app, queue, settings = app_with_overrides

    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    async def _noop_chain(**_kwargs):
        return None

    monkeypatch.setattr(mod, "chain_populate_and_process", _noop_chain)

    client = TestClient(app)
    response = client.post("/recognition/analyze/multipart", **_multipart_submission(tenant_id))
    assert response.status_code == 202, response.text
    body = response.json()
    job_id = body["id"]
    assert uuid.UUID(job_id), "response id must be a UUID"

    # scan_queue was called exactly once with the pre-generated job_id
    assert len(queue.calls) == 1
    call = queue.calls[0]
    assert str(call["tenant_id"]) == tenant_id
    assert call["total"] == 1
    assert str(call["job_id"]) == job_id

    # Blob landed under <blob_root>/<tenant>/<job_id>/42.bin
    expected = settings.blob_root / tenant_id / job_id / "42.bin"
    assert expected.is_file()
    assert expected.read_bytes() == PNG_BYTES


def test_multipart_ensures_tenant_exists_before_blob_writes(
    tmp_path: Path, tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RECOGNITION_ASYNC_ANALYZE_INLINE", "0")

    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "blobs"

    fake_queue = _FakeScanQueue()
    fake_session = _CommitOnlySession()

    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/recognition")
    fastapi_app.dependency_overrides[require_write_access] = lambda: AuthContext(token="t", tenant_claim=tenant_id)
    fastapi_app.dependency_overrides[get_optional_session] = lambda: fake_session
    fastapi_app.dependency_overrides[get_scan_queue_service_optional] = lambda: fake_queue
    fastapi_app.dependency_overrides[_settings_default] = lambda: settings

    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    require_calls: list[str] = []

    async def _require_tenant_record(session, tenant_uuid):
        assert session is fake_session
        require_calls.append(str(tenant_uuid))

    async def _noop_chain(**_kwargs):
        return None

    monkeypatch.setattr(mod, "require_tenant_record", _require_tenant_record)
    monkeypatch.setattr(mod, "is_postgres", lambda _session: True)
    monkeypatch.setattr(mod, "chain_populate_and_process", _noop_chain)
    _patch_scan_dispatch_ready(monkeypatch, mod=mod)

    client = TestClient(fastapi_app)
    response = client.post("/recognition/analyze/multipart", **_multipart_submission(tenant_id))

    assert response.status_code == 202, response.text
    assert require_calls == [tenant_id]
    assert fake_session.commit_calls == 1


def test_multipart_gate_failure_writes_no_blobs(
    tmp_path: Path, tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the provisioning gate rejects the tenant, the route must fail BEFORE writing any blob."""
    monkeypatch.setenv("RECOGNITION_ASYNC_ANALYZE_INLINE", "0")

    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "blobs"

    fake_queue = _FakeScanQueue()
    fake_session = _CommitOnlySession()

    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/recognition")
    fastapi_app.dependency_overrides[require_write_access] = lambda: AuthContext(token="t", tenant_claim=tenant_id)
    fastapi_app.dependency_overrides[get_optional_session] = lambda: fake_session
    fastapi_app.dependency_overrides[get_scan_queue_service_optional] = lambda: fake_queue
    fastapi_app.dependency_overrides[_settings_default] = lambda: settings

    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    async def _reject_tenant(session, tenant_uuid):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "tenant_not_provisioned"})

    async def _noop_chain(**_kwargs):
        return None

    monkeypatch.setattr(mod, "require_tenant_record", _reject_tenant)
    monkeypatch.setattr(mod, "is_postgres", lambda _session: True)
    monkeypatch.setattr(mod, "chain_populate_and_process", _noop_chain)

    client = TestClient(fastapi_app)
    response = client.post("/recognition/analyze/multipart", **_multipart_submission(tenant_id))

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "tenant_not_provisioned"
    # No blob may have been persisted before the gate rejected the request.
    written = list(settings.blob_root.rglob("*")) if settings.blob_root.exists() else []
    assert [p for p in written if p.is_file()] == []
    assert fake_session.commit_calls == 0


def test_multipart_admin_key_with_envelope_tenant_succeeds(
    tmp_path: Path, tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Admin keys (auth.tenant_claim is None) must reach the multipart route
    and have their ObjectStore built from the envelope's tenant_id.

    Regression for MAINT-multipart-admin-tenant-20260426: the route used to
    depend on get_object_store_for_request, which 401'd whenever
    auth.tenant_claim was empty — making the route unreachable from any
    deployment whose API key was an admin/dev key (the LocalWP -> remote
    OCI VM scenario). Tenant binding is still enforced because the
    factory pins the FilesystemObjectStore to the envelope tenant_id.
    """
    monkeypatch.setenv("RECOGNITION_ASYNC_ANALYZE_INLINE", "0")

    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "blobs"

    fake_queue = _FakeScanQueue()

    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/recognition")

    fastapi_app.dependency_overrides[require_write_access] = lambda: AuthContext(
        token="admin-key", tenant_claim=None, is_admin=True, enabled=True
    )
    fastapi_app.dependency_overrides[get_optional_session] = lambda: None
    fastapi_app.dependency_overrides[get_scan_queue_service_optional] = lambda: fake_queue
    fastapi_app.dependency_overrides[_settings_default] = lambda: settings

    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    async def _noop_chain(**_kwargs):
        return None

    monkeypatch.setattr(mod, "chain_populate_and_process", _noop_chain)

    client = TestClient(fastapi_app)
    response = client.post("/recognition/analyze/multipart", **_multipart_submission(tenant_id))
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]

    # Blob landed under the ENVELOPE tenant_id, not auth.tenant_claim.
    expected = settings.blob_root / tenant_id / job_id / "42.bin"
    assert expected.is_file()
    assert expected.read_bytes() == PNG_BYTES


def test_multipart_canonicalizes_uppercase_envelope_tenant_uuid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An envelope tenant_id submitted in uppercase must be canonicalized to
    the lowercase UUID form before binding the ObjectStore.

    Regression for MAINT-multipart-admin-tenant-20260426-BR-01: uuid.UUID()
    accepts uppercase but str() always returns lowercase canonical, which
    is the form auth.tenant_claim carries (from the api_keys row) and the
    form the BackgroundTask rebuilds the store with via str(tenant_uuid).
    Binding the request-scoped store to the raw uppercase string would
    write blobs under <root>/ABC.../<job>/<media>.bin while the lowercase-
    bound store rebuilt in the BackgroundTask (Linux deployment, case-
    sensitive FS) could neither open the blob_uri nor clean up the orphan.

    The assertion targets the factory call argument directly rather than the
    on-disk path because macOS APFS is case-insensitive and would mask the
    bug — the production runtime (OCI VM, ext4) is case-sensitive.
    """
    from recognition.interface_adapters.http.deps.object_store import (
        get_object_store_factory_for_request,
    )

    monkeypatch.setenv("RECOGNITION_ASYNC_ANALYZE_INLINE", "0")

    canonical_tenant = str(uuid.uuid4())
    upper_tenant = canonical_tenant.upper()
    assert upper_tenant != canonical_tenant, "test premise: upper differs from lower"

    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "blobs"

    factory_calls: list[str] = []

    def _spy_factory_provider():
        def _factory(tenant_id: str):
            factory_calls.append(tenant_id)
            return FilesystemObjectStore(root=settings.blob_root, tenant_id=tenant_id)

        return _factory

    fake_queue = _FakeScanQueue()
    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/recognition")
    fastapi_app.dependency_overrides[require_write_access] = lambda: AuthContext(
        token="admin-key", tenant_claim=None, is_admin=True, enabled=True
    )
    fastapi_app.dependency_overrides[get_optional_session] = lambda: None
    fastapi_app.dependency_overrides[get_scan_queue_service_optional] = lambda: fake_queue
    fastapi_app.dependency_overrides[_settings_default] = lambda: settings
    fastapi_app.dependency_overrides[get_object_store_factory_for_request] = _spy_factory_provider

    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    async def _noop_chain(**_kwargs):
        return None

    monkeypatch.setattr(mod, "chain_populate_and_process", _noop_chain)

    client = TestClient(fastapi_app)
    response = client.post("/recognition/analyze/multipart", **_multipart_submission(upper_tenant))
    assert response.status_code == 202, response.text

    # The factory must have been called with the canonical (lowercase) form,
    # never the raw uppercase envelope. Multiple calls are fine; none may
    # carry the raw casing.
    assert factory_calls, "object_store_factory must be invoked at least once"
    assert all(call == canonical_tenant for call in factory_calls), (
        f"factory must receive canonical tenant id only; got: {factory_calls}"
    )
    assert upper_tenant not in factory_calls

    # The scan_queue records the canonical tenant_id too (as a UUID object).
    assert len(fake_queue.calls) == 1
    assert str(fake_queue.calls[0]["tenant_id"]) == canonical_tenant


def test_multipart_canonicalizes_uppercase_envelope_tenant_for_auth_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tenant-scoped key whose tenant_claim equals the envelope tenant_id
    in canonical form must NOT be 403'd just because the envelope was
    submitted in uppercase. Locks in canonical comparison at the auth /
    envelope mismatch guard alongside the storage canonicalization above.
    """
    monkeypatch.setenv("RECOGNITION_ASYNC_ANALYZE_INLINE", "0")

    canonical_tenant = str(uuid.uuid4())
    upper_tenant = canonical_tenant.upper()

    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "blobs"
    fake_queue = _FakeScanQueue()

    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/recognition")
    # auth.tenant_claim carries the canonical (lowercase) form from the DB row.
    fastapi_app.dependency_overrides[require_write_access] = lambda: AuthContext(
        token="t", tenant_claim=canonical_tenant
    )
    fastapi_app.dependency_overrides[get_optional_session] = lambda: None
    fastapi_app.dependency_overrides[get_scan_queue_service_optional] = lambda: fake_queue
    fastapi_app.dependency_overrides[_settings_default] = lambda: settings

    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    async def _noop_chain(**_kwargs):
        return None

    monkeypatch.setattr(mod, "chain_populate_and_process", _noop_chain)

    client = TestClient(fastapi_app)
    response = client.post("/recognition/analyze/multipart", **_multipart_submission(upper_tenant))
    assert response.status_code == 202, response.text


def test_multipart_rejects_when_request_part_missing(app_with_overrides, tenant_id: str) -> None:
    app, _queue, _settings = app_with_overrides
    client = TestClient(app)

    response = client.post(
        "/recognition/analyze/multipart",
        files=[("image_1", ("a.png", PNG_BYTES, "image/png"))],
    )
    assert response.status_code == 400


def test_multipart_rejects_when_no_image_parts(app_with_overrides, tenant_id: str) -> None:
    app, _queue, _settings = app_with_overrides
    client = TestClient(app)

    response = client.post(
        "/recognition/analyze/multipart",
        files=[
            (
                "request",
                ("request.json", json.dumps({"tenant_id": tenant_id}), "application/json"),
            ),
        ],
    )
    assert response.status_code == 422


def test_multipart_rejects_tenant_mismatch(app_with_overrides, tenant_id: str) -> None:
    """auth.tenant_claim from the override must match the tenant_id in the
    request envelope. A mismatch is 403 — defends against a token issued
    for tenant A submitting work that claims to be tenant B's."""
    app, _queue, _settings = app_with_overrides
    client = TestClient(app)
    other_tenant = str(uuid.uuid4())

    response = client.post(
        "/recognition/analyze/multipart",
        files=[
            (
                "request",
                ("request.json", json.dumps({"tenant_id": other_tenant}), "application/json"),
            ),
            ("image_1", ("a.png", PNG_BYTES, "image/png")),
        ],
    )
    assert response.status_code == 403


def test_multipart_rejects_unsupported_mime(app_with_overrides, tenant_id: str) -> None:
    """The route delegates to multipart_to_media_items which raises 415 for
    a disallowed MIME type. Verify the error surfaces via the route."""
    app, _queue, _settings = app_with_overrides
    client = TestClient(app)
    response = client.post(
        "/recognition/analyze/multipart",
        files=[
            (
                "request",
                ("request.json", json.dumps({"tenant_id": tenant_id}), "application/json"),
            ),
            ("image_1", ("a.gif", b"GIF89a-fake", "image/gif")),
        ],
    )
    assert response.status_code == 415


@pytest.mark.asyncio
async def test_multipart_accepts_five_images_and_rejects_six(
    app_with_overrides, tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, queue, settings = app_with_overrides
    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    async def _noop_chain(**_kwargs):
        return None

    async def _auth_provider():
        return AuthContext(token="t", tenant_claim=tenant_id)

    async def _no_session_provider():
        return None

    async def _queue_provider():
        return queue

    async def _factory_provider():
        return lambda scoped_tenant: FilesystemObjectStore(root=settings.blob_root, tenant_id=scoped_tenant)

    monkeypatch.setattr(mod, "chain_populate_and_process", _noop_chain)
    app.dependency_overrides[require_write_access] = _auth_provider
    app.dependency_overrides[get_optional_session] = _no_session_provider
    app.dependency_overrides[get_scan_queue_service_optional] = _queue_provider
    app.dependency_overrides[get_object_store_factory_for_request] = _factory_provider

    def submission(image_count: int) -> dict:
        files = [
            (
                "request",
                ("request.json", json.dumps({"tenant_id": tenant_id}), "application/json"),
            )
        ]
        files.extend(
            (f"image_{media_id}", (f"{media_id}.png", PNG_BYTES, "image/png")) for media_id in range(1, image_count + 1)
        )
        return {"files": files}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        accepted = await client.post("/recognition/analyze/multipart", **submission(5))
        rejected = await client.post("/recognition/analyze/multipart", **submission(6))

    assert accepted.status_code == 202, accepted.text
    assert queue.calls[0]["total"] == 5
    assert rejected.status_code == 400, rejected.text
    assert len(queue.calls) == 1


@pytest.mark.asyncio
async def test_multipart_storage_failure_uses_opaque_production_error_envelope(
    tmp_path: Path,
    tenant_id: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_path = tmp_path / "private" / "tenant-secret" / "image.png"
    driver_error = f"permission denied writing {secret_path} with password=secret"

    class _FailingStore:
        def put(self, *, job_id: str, media_id: str, data: bytes) -> str:
            raise ObjectStoreError(driver_error)

        def cleanup(self, *, job_id: str) -> None:
            return None

        def open(self, uri: str):
            raise ObjectStoreError("not reached")

    async def _factory_provider():
        return lambda _tenant_id: _FailingStore()

    async def _auth_provider():
        return AuthContext(token="t", tenant_claim=tenant_id)

    async def _no_session_provider():
        return None

    async def _queue_provider():
        return fake_queue

    fake_queue = _FakeScanQueue()
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(router, prefix="/recognition")
    register_exception_handlers(app)
    app.dependency_overrides[require_write_access] = _auth_provider
    app.dependency_overrides[get_optional_session] = _no_session_provider
    app.dependency_overrides[get_scan_queue_service_optional] = _queue_provider
    app.dependency_overrides[get_object_store_factory_for_request] = _factory_provider

    import logging

    from recognition.interface_adapters.http import exception_handlers

    caplog.set_level(logging.ERROR, logger=exception_handlers.logger.name)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/recognition/analyze/multipart",
            headers={CORRELATION_ID_HEADER: "req-storage-failure"},
            **_multipart_submission(tenant_id),
        )

    body = response.json()
    assert response.status_code == 500
    assert body == {
        "error": "internal_server_error",
        "path": "http://testserver/recognition/analyze/multipart",
        "correlation_id": "req-storage-failure",
    }
    assert driver_error not in response.text
    assert str(secret_path) not in response.text
    records = [record for record in caplog.records if record.name == exception_handlers.logger.name]
    assert len(records) == 1
    assert records[0].correlation_id == "req-storage-failure"
    assert records[0].exc_info is not None
    assert driver_error in str(records[0].exc_info[1])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        None,
        HTTPException(status_code=400, detail="invalid multipart"),
        ObjectStoreError("storage failed"),
        RuntimeError("persistence failed"),
    ],
    ids=["success", "validation-error", "storage-error", "persistence-error"],
)
async def test_multipart_closes_parsed_form_on_every_exit(
    tenant_id: str, monkeypatch: pytest.MonkeyPatch, failure: Exception | None
) -> None:
    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    upload = UploadFile(
        filename="a.png",
        file=tempfile.SpooledTemporaryFile(),  # noqa: SIM115 - route closure is the behavior under test
    )
    upload.headers = Headers({"content-type": "image/png"})
    upload.file.write(PNG_BYTES)
    upload.file.seek(0)

    class _CloseSpyForm(FormData):
        closed = False

        async def close(self) -> None:
            self.closed = True
            await super().close()

    form = _CloseSpyForm([("image_1", upload)])
    expected_result = object()

    async def _fake_parse(_request: Request) -> FormData:
        return form

    async def _fake_process(**_kwargs):
        if failure is not None:
            raise failure
        return expected_result

    monkeypatch.setattr(mod, "_parse_multipart_form", _fake_parse)
    monkeypatch.setattr(mod, "_analyze_media_multipart_form", _fake_process)
    request = Request({"type": "http", "method": "POST", "path": "/recognition/analyze/multipart", "headers": []})

    async def _call_route():
        return await mod.analyze_media_multipart(
            request=request,
            background_tasks=BackgroundTasks(),
            auth=AuthContext(token="t", tenant_claim=tenant_id),
            session=None,
            scan_queue=_FakeScanQueue(),
            object_store_factory=lambda _tenant: None,
            _demo_quota=None,
        )

    if failure is None:
        assert await _call_route() is expected_result
    else:
        with pytest.raises(type(failure)):
            await _call_route()
    assert form.closed is True
    assert upload.file.closed is True


@pytest.mark.asyncio
async def test_multipart_parser_closes_partial_spool_on_client_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette import formparsers

    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    opened_spools: list = []
    real_spooled_temporary_file = tempfile.SpooledTemporaryFile

    def _tracking_spool(*args, **kwargs):
        spool = real_spooled_temporary_file(*args, **kwargs)
        opened_spools.append(spool)
        return spool

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", _tracking_spool)
    boundary = "disconnect-boundary"
    partial_body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="image_1"; filename="a.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + PNG_BYTES
    messages = iter(
        [
            {"type": "http.request", "body": partial_body, "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    async def receive():
        return next(messages)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/recognition/analyze/multipart",
            "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
        },
        receive,
    )

    with pytest.raises(ClientDisconnect):
        await mod._parse_multipart_form(request)

    assert opened_spools, "test must reach file-spool allocation before disconnecting"
    assert all(spool.closed for spool in opened_spools)


# ---------------------------------------------------------------------------
# BR-05 + BR-06 regression tests
# ---------------------------------------------------------------------------


def test_multipart_schedules_chain_populate_and_process(
    app_with_overrides, tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E15-11-BR-05: a successful multipart submission must enqueue
    chain_populate_and_process via BackgroundTasks so the scan worker has
    work to claim. Without this wiring the route would return 202 but no
    queue items would ever exist for the worker to pick up."""
    app, _queue, _settings = app_with_overrides
    calls: list[dict] = []

    async def _fake_chain(**kwargs):
        calls.append(kwargs)

    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    monkeypatch.setattr(mod, "chain_populate_and_process", _fake_chain)

    client = TestClient(app)
    response = client.post("/recognition/analyze/multipart", **_multipart_submission(tenant_id))
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]

    assert len(calls) == 1, "chain_populate_and_process must be scheduled exactly once"
    kwargs = calls[0]
    assert kwargs["job_id"] == job_id
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["media_items"] == [(42, kwargs["media_sources"][0])]
    assert len(kwargs["media_sources"]) == 1
    assert kwargs["media_sources"][0].startswith("file://")


def test_multipart_cleans_up_blobs_when_create_scan_job_record_fails(tmp_path: Path, tenant_id: str) -> None:
    """E15-11-BR-06: if create_scan_job_record raises after blobs have been
    written, the route must call object_store.cleanup so the per-job
    directory does not become an orphaned blob the worker can never find
    (no DB row exists for it to discover)."""
    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "blobs"

    class _RaisingQueue:
        async def create_scan_job_record(self, **kwargs):
            raise RuntimeError("simulated DB outage during job creation")

    app = FastAPI()
    app.include_router(router, prefix="/recognition")
    app.dependency_overrides[require_write_access] = lambda: AuthContext(token="t", tenant_claim=tenant_id)
    app.dependency_overrides[get_optional_session] = lambda: None
    app.dependency_overrides[get_scan_queue_service_optional] = lambda: _RaisingQueue()
    app.dependency_overrides[_settings_default] = lambda: settings

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/recognition/analyze/multipart", **_multipart_submission(tenant_id))
    assert response.status_code >= 500, response.text

    # The per-tenant directory may or may not exist (cleanup removes the per-job
    # subdir under it); but no per-job subdirectory must remain — the failed
    # job's blobs were rolled back.
    tenant_root = settings.blob_root / tenant_id
    if tenant_root.exists():
        assert list(tenant_root.iterdir()) == [], f"per-job subdirectory leaked: {list(tenant_root.iterdir())}"


# ---------------------------------------------------------------------------
# E15-11-BR-14: route must not reach through FilesystemObjectStore.root
# ---------------------------------------------------------------------------


def test_multipart_route_does_not_reach_through_filesystem_protocol(
    tmp_path: Path, tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The multipart route must construct background-task cleanup through
    the ObjectStore protocol, not by reading FilesystemObjectStore.root.
    Stub store implements only put/open/cleanup; route must still
    complete 202 — proving any non-filesystem implementation can swap in
    unchanged (e.g. Slice B's OCI store)."""
    from recognition.application.storage import ObjectStore as _ObjectStore
    from recognition.interface_adapters.http.deps.object_store import (
        get_object_store_factory_for_request,
    )

    monkeypatch.setenv("RECOGNITION_ASYNC_ANALYZE_INLINE", "0")

    class _ProtocolOnlyStore:
        """Implements only put/open/cleanup; deliberately has NO .root attr."""

        _shared: dict[str, bytes] = {}

        def __init__(self, tenant_id: str) -> None:
            self._tenant_id = tenant_id

        def put(self, *, job_id: str, media_id: str, data: bytes) -> str:
            uri = f"stub://{self._tenant_id}/{job_id}/{media_id}"
            type(self)._shared[uri] = bytes(data)
            return uri

        def open(self, uri: str):
            import io

            return io.BytesIO(type(self)._shared[uri])

        def cleanup(self, *, job_id: str) -> None:
            type(self)._shared = {k: v for k, v in type(self)._shared.items() if f"/{job_id}/" not in k}

    def _stub_factory_provider():
        def _factory(tenant: str) -> _ObjectStore:
            return _ProtocolOnlyStore(tenant_id=tenant)

        return _factory

    fake_queue = _FakeScanQueue()
    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/recognition")
    fastapi_app.dependency_overrides[require_write_access] = lambda: AuthContext(token="t", tenant_claim=tenant_id)
    fastapi_app.dependency_overrides[get_optional_session] = lambda: None
    fastapi_app.dependency_overrides[get_scan_queue_service_optional] = lambda: fake_queue
    fastapi_app.dependency_overrides[get_object_store_factory_for_request] = _stub_factory_provider

    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    async def _noop_chain(**_kwargs):
        return None

    monkeypatch.setattr(mod, "chain_populate_and_process", _noop_chain)

    client = TestClient(fastapi_app)
    response = client.post("/recognition/analyze/multipart", **_multipart_submission(tenant_id))
    assert response.status_code == 202, response.text


# ---------------------------------------------------------------------------
# S3.1 — structured log fields on the multipart route
# ---------------------------------------------------------------------------


def test_multipart_route_emits_structured_telemetry_log_line(
    app_with_overrides, tenant_id: str, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """E15-11 S3.1: the multipart route must emit a single structured log
    line with the diagnostic fields needed to triage transport failures
    (transport, parts_count, total_bytes, tenant_id, job_id) — no PII."""
    app, _queue, _settings = app_with_overrides

    from recognition.interface_adapters.http.routers import analyze_multipart as mod

    async def _noop_chain(**_kwargs):
        return None

    monkeypatch.setattr(mod, "chain_populate_and_process", _noop_chain)

    import logging

    caplog.set_level(logging.INFO, logger=mod.logger.name)

    client = TestClient(app)
    response = client.post("/recognition/analyze/multipart", **_multipart_submission(tenant_id))
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]

    matching = [
        rec
        for rec in caplog.records
        if rec.name == mod.logger.name and "analyze_media_multipart_dispatch" in rec.getMessage()
    ]
    assert len(matching) == 1, f"expected exactly one telemetry log line, got {len(matching)}: " + str(
        [r.getMessage() for r in caplog.records]
    )
    msg = matching[0].getMessage()
    assert "transport=multipart" in msg
    assert "parts_count=1" in msg
    assert f"total_bytes={len(PNG_BYTES)}" in msg
    assert f"tenant_id={tenant_id}" in msg
    assert f"job_id={job_id}" in msg
