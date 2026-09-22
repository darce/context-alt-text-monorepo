"""Usage admission factory is independent of the portal UI flag."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps import portal_composition as composition
from recognition.interface_adapters.http.deps.portal_composition import UsageAdmissionServiceFactory
from recognition.interface_adapters.http.deps.usage_admission import get_usage_admission_service
from scene.application.description_adapter import AdapterResult
from scene.domain.description import DescriptionAdapterKind
from scene.interface_adapters.http.deps import get_description_adapter
from scene.interface_adapters.http.router import router as scene_router

TENANT_ID = "00000000-0000-0000-0000-0000000000cd"


class _SpyAdapter:
    kind = DescriptionAdapterKind.SEEDED
    model_id = "spy-seeded"
    model_version = "1"
    prompt_or_task_version = "1"
    calls = 0

    def describe(self, *, image_bytes, context):
        del image_bytes, context
        type(self).calls += 1
        return AdapterResult(
            caption="spy",
            objects=(),
            ocr_text=None,
            alt_text_draft="spy",
            context_sources=(),
            context_applied=False,
        )


class _Auth:
    tenant_claim = TENANT_ID
    user_id = 1


def test_install_usage_admission_factory_does_not_require_clerk_or_polar(
    monkeypatch,
) -> None:
    for name in (
        "ACX_CLERK_ISSUER",
        "ACX_CLERK_JWKS_URL",
        "ACX_CLERK_AUDIENCE",
        "ACX_CLERK_AUTHORIZED_PARTIES",
        "POLAR_WEBHOOK_SECRET",
        "POLAR_PRODUCT_IDS",
        "RECOGNITION_PORTAL_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RECOGNITION_USAGE_ADMISSION_TIMEOUT_S", "4.5")

    app = FastAPI()
    composition.install_usage_admission_factory(app)

    assert isinstance(app.state.usage_admission_service, UsageAdmissionServiceFactory)
    assert app.state.usage_admission_service.timeout_s == 4.5
    assert not hasattr(app.state, "portal_token_verifier")
    assert not hasattr(app.state, "billing_provider")


def test_install_portal_composition_reuses_independent_usage_factory(monkeypatch) -> None:
    config = composition.PortalCompositionConfig(
        portal_auth=SimpleNamespace(),
        billing_webhook_secret="secret",
        billing_product_ids={"starter": "product"},
    )
    monkeypatch.setattr(composition, "_composition_config", lambda _settings: config)
    monkeypatch.setattr(composition, "build_portal_token_verifier", lambda *_args: object())
    monkeypatch.setattr(composition, "PolarBillingProvider", lambda *_args, **_kwargs: object())

    app = FastAPI()
    composition.install_portal_composition(app, settings=SimpleNamespace())

    assert isinstance(app.state.usage_admission_service, UsageAdmissionServiceFactory)


def test_create_app_installs_usage_factory_when_portal_flag_off(monkeypatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    monkeypatch.delenv("RECOGNITION_ADMIN_ENABLED", raising=False)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("RECOGNITION_PORTAL_ENABLED", raising=False)
    for name in (
        "ACX_CLERK_ISSUER",
        "ACX_CLERK_JWKS_URL",
        "ACX_CLERK_AUDIENCE",
        "ACX_CLERK_AUTHORIZED_PARTIES",
        "POLAR_WEBHOOK_SECRET",
        "POLAR_PRODUCT_IDS",
    ):
        monkeypatch.delenv(name, raising=False)

    from api.main import create_app

    app = create_app()
    assert isinstance(app.state.usage_admission_service, UsageAdmissionServiceFactory)
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/portal/me" not in paths


def test_metered_scene_ingress_is_503_when_factory_missing(monkeypatch) -> None:
    from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
    from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota

    _SpyAdapter.calls = 0
    app = FastAPI()
    app.include_router(scene_router, prefix="/scene")
    app.dependency_overrides[require_write_access] = lambda: _Auth()
    app.dependency_overrides[enforce_demo_quota] = lambda: None
    app.dependency_overrides[get_optional_session] = lambda: None
    app.dependency_overrides[get_description_adapter] = lambda: _SpyAdapter()

    data = {"request": json.dumps({"tenant_id": TENANT_ID, "media_id": 42})}
    files = {"image_42": ("x.jpg", b"image-bytes", "image/jpeg")}
    with TestClient(app) as client:
        response = client.post("/scene/describe/multipart", data=data, files=files)

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == {"error": "usage_admission_unavailable"}
    assert _SpyAdapter.calls == 0


def test_usage_ticket_shape_remains_compatible_with_factory() -> None:
    ticket = UsageTicket(
        uuid4(),
        UUID(TENANT_ID),
        "idem-key-aaaaaaaa",
        1,
        operation_id="idem-key-aaaaaaaa",
        request_fingerprint="a" * 64,
        job_id=str(uuid4()),
        fence_token="1:" + str(uuid4()),
    )
    assert ticket.cost_units == 1
    assert callable(get_usage_admission_service)
