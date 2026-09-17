"""Wave 3: production multipart envelopes against the shared schema."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft7Validator
from referencing import Registry, Resource

from scene.tests.test_describe_route import TENANT_ID, _client, _gpu_env, _GpuAdapter, _post

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCHEMA_DIR = _REPO_ROOT / "packages/shared-contracts/schemas"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gpuflow-multipart.json"
_UNAVAILABLE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gpuflow2-unavailable.json"
_SCHEMA_FILES = (
    "image-description-response.schema.json",
    "scene-describe-multipart.schema.json",
)


def _load_schema(name: str):
    return json.loads((_SCHEMA_DIR / name).read_text())


def _retrieve_schema(uri: str):
    return Resource.from_contents(_load_schema(Path(uri).name))


def _multipart_validator():
    registry = Registry(retrieve=_retrieve_schema).with_resources(
        (name, Resource.from_contents(_load_schema(name))) for name in _SCHEMA_FILES
    )
    return Draft7Validator(_load_schema("scene-describe-multipart.schema.json"), registry=registry)


TIMING = {
    "queue_ms": None,
    "ramp_up_ms": 1200,
    "processing_ms": 12,
    "startup_ms": None,
    "server_elapsed_ms": 1212,
}


def test_fixture_validates_success_branch():
    payload = json.loads(_FIXTURE.read_text())
    _multipart_validator().validate(payload)
    assert payload["operation_id"]
    assert "startup_id" in payload
    assert payload["timing"]["ramp_up_ms"] == 0


def test_typed_error_envelopes_validate():
    validator = _multipart_validator()
    starting = {
        "detail": {
            "code": "description_service_starting",
            "message": "Description service is starting",
            "operation_id": "opaque operation",
            "startup_id": "ocid1.instance.test",
            "warmup_eta_seconds": 45,
            "startup_budget_seconds": 510,
            "timing": TIMING,
        }
    }
    validator.validate(starting)
    unavailable = {
        "detail": {
            "code": "description_service_unavailable",
            "message": "Description service is unavailable",
            "operation_id": "opaque operation",
            "startup_id": None,
            "reason": "state_missing",
            "timing": TIMING,
        }
    }
    validator.validate(unavailable)
    unavailable_null = {
        "detail": {
            "code": "description_service_unavailable",
            "message": "Description service is unavailable",
            "operation_id": None,
            "startup_id": None,
            "reason": "state_missing",
            "timing": TIMING,
        }
    }
    validator.validate(unavailable_null)
    starting_null = {
        "detail": {
            **starting["detail"],
            "operation_id": None,
        }
    }
    assert not validator.is_valid(starting_null)
    assert not validator.is_valid(
        {
            "detail": {
                **unavailable["detail"],
                "warmup_eta_seconds": 4,
            }
        }
    )
    assert not validator.is_valid(
        {"detail": {k: value for k, value in starting["detail"].items() if k != "startup_budget_seconds"}}
    )
    assert not validator.is_valid({"detail": {k: value for k, value in unavailable["detail"].items() if k != "reason"}})


def _rebuild_test_exception_detail(**overrides):
    detail = {
        "code": "description_service_starting",
        "message": "dependency starting",
        "operation_id": "upstream-operation",
        "startup_id": "upstream-startup",
        "warmup_eta_seconds": 45,
        "startup_budget_seconds": 510,
        "timing": {
            "queue_ms": 1,
            "ramp_up_ms": 2,
            "processing_ms": None,
            "startup_ms": None,
            "server_elapsed_ms": 4,
        },
    }
    detail.update(overrides)
    return detail


@pytest.mark.parametrize("eta", [-1, float("nan"), float("inf"), "30", None])
def test_post_accept_rebuild_drops_invalid_warmup_eta(eta):
    from fastapi import HTTPException, status

    from scene.config.settings import DescriptionSettings
    from scene.interface_adapters.http.routers import describe as describe_module

    rebuilt = describe_module._rebuild_post_accept_typed_error(
        HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_rebuild_test_exception_detail(warmup_eta_seconds=eta),
        ),
        op=SimpleNamespace(operation_id="accepted-operation", startup_id="accepted-startup"),
        settings=DescriptionSettings(gpu_warmup_timeout_seconds=17.5),
        server_start=0,
    )

    _multipart_validator().validate({"detail": rebuilt.detail})
    assert rebuilt.detail["code"] == "description_service_starting"
    assert "warmup_eta_seconds" not in rebuilt.detail
    assert rebuilt.detail["operation_id"] == "accepted-operation"


def test_post_accept_starting_rebuild_falls_back_when_operation_id_unavailable():
    from fastapi import HTTPException, status

    from scene.config.settings import DescriptionSettings
    from scene.interface_adapters.http.routers import describe as describe_module

    detail = _rebuild_test_exception_detail(operation_id=None)
    rebuilt = describe_module._rebuild_post_accept_typed_error(
        HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail),
        op=SimpleNamespace(operation_id=None, startup_id="accepted-startup"),
        settings=DescriptionSettings(gpu_warmup_timeout_seconds=17.5),
        server_start=0,
    )

    _multipart_validator().validate({"detail": rebuilt.detail})
    assert rebuilt.detail["code"] == "description_service_unavailable"
    assert rebuilt.detail["reason"] == "state_missing"
    assert "warmup_eta_seconds" not in rebuilt.detail
    assert "startup_budget_seconds" not in rebuilt.detail


def test_post_accept_starting_rebuild_uses_accepted_operation_id_when_upstream_id_null():
    from fastapi import HTTPException, status

    from scene.config.settings import DescriptionSettings
    from scene.interface_adapters.http.routers import describe as describe_module

    rebuilt = describe_module._rebuild_post_accept_typed_error(
        HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_rebuild_test_exception_detail(operation_id=None),
        ),
        op=SimpleNamespace(operation_id="accepted-operation", startup_id="accepted-startup"),
        settings=DescriptionSettings(gpu_warmup_timeout_seconds=17.5),
        server_start=0,
    )

    _multipart_validator().validate({"detail": rebuilt.detail})
    assert rebuilt.detail["code"] == "description_service_starting"
    assert rebuilt.detail["operation_id"] == "accepted-operation"


def test_post_accept_unavailable_rebuild_uses_contract_reason_for_null_reason():
    from fastapi import HTTPException, status

    from scene.config.settings import DescriptionSettings
    from scene.interface_adapters.http.routers import describe as describe_module

    detail = _rebuild_test_exception_detail(
        code="description_service_unavailable",
        operation_id="upstream-operation",
        startup_id="upstream-startup",
        warmup_eta_seconds=None,
        startup_budget_seconds=None,
        reason=None,
    )
    rebuilt = describe_module._rebuild_post_accept_typed_error(
        HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail),
        op=SimpleNamespace(operation_id="accepted-operation", startup_id="accepted-startup"),
        settings=DescriptionSettings(gpu_warmup_timeout_seconds=17.5),
        server_start=0,
    )

    _multipart_validator().validate({"detail": rebuilt.detail})
    assert rebuilt.detail["code"] == "description_service_unavailable"
    assert rebuilt.detail["reason"] == "state_missing"
    assert "warmup_eta_seconds" not in rebuilt.detail
    assert "startup_budget_seconds" not in rebuilt.detail


def test_gpuflow2_unavailable_fixture_round_trips():
    payload = json.loads(_UNAVAILABLE_FIXTURE.read_text())
    validator = _multipart_validator()
    starting = payload["starting"]["body"]
    validator.validate(starting)
    assert starting["detail"]["startup_budget_seconds"] == 510
    assert "reason" not in starting["detail"]
    degraded = payload["unavailable_degraded"]["body"]
    validator.validate(degraded)
    assert degraded["detail"]["reason"] == "degraded"
    assert degraded["detail"]["lifecycle_reason"] == "readiness_timeout"
    for key, example in payload.items():
        if key == "starting":
            continue
        validator.validate(example["body"])
        assert example["body"]["detail"]["reason"]
        assert "startup_budget_seconds" not in example["body"]["detail"]


def test_success_envelope_allows_absent_operation_id_and_rejects_null():
    payload = json.loads(_FIXTURE.read_text())
    validator = _multipart_validator()
    absent = dict(payload)
    del absent["operation_id"]
    validator.validate(absent)
    payload["operation_id"] = None
    assert not validator.is_valid(payload)
    payload["operation_id"] = ""
    assert not validator.is_valid(payload)


_NAMING_PROVENANCE_SCHEMA_KEYS = {"injected_names", "naming_allowed", "reason", "mode"}


def _schema_body(payload: dict) -> dict:
    """Drop additive naming keys the shared schema has not absorbed yet."""
    body = json.loads(json.dumps(payload))
    provenance = body.get("naming_provenance")
    if isinstance(provenance, dict):
        body["naming_provenance"] = {
            key: provenance[key] for key in _NAMING_PROVENANCE_SCHEMA_KEYS if key in provenance
        }
    return body


def test_production_route_success_validates_against_shared_schema():
    validator = _multipart_validator()
    with _client() as client:
        response = _post(client, TENANT_ID)
        assert response.status_code == 200, response.text
        body = response.json()
        validator.validate(_schema_body(body))
        assert body["operation_id"]
        assert "startup_id" in body
        assert body["startup_id"] is None
        assert body["timing"]["ramp_up_ms"] == 0
        assert body["timing"]["processing_ms"] is not None
        cached = _post(client, TENANT_ID)
        assert cached.status_code == 200, cached.text
        cached_body = cached.json()
        validator.validate(_schema_body(cached_body))
        assert cached_body["cached"] is True
        assert cached_body["startup_id"] is None
        assert cached_body["timing"]["ramp_up_ms"] == 0
        assert cached_body["timing"]["processing_ms"] == 0
        assert cached_body["timing"]["startup_ms"] is None


def test_production_route_starting_error_validates_against_shared_schema(monkeypatch, tmp_path):
    _gpu_env(monkeypatch, tmp_path, state="stopped")
    validator = _multipart_validator()
    with _client(adapter=_GpuAdapter()) as client:
        response = _post(client, TENANT_ID)
        assert response.status_code == 503, response.text
        body = response.json()
        validator.validate(body)
        assert body["detail"]["code"] == "description_service_starting"
        assert body["detail"]["operation_id"]
        assert "startup_id" in body["detail"]
        assert "timing" in body["detail"]
        assert body["detail"]["startup_budget_seconds"] > 0
        assert "reason" not in body["detail"]


@pytest.mark.parametrize("reason", ["__missing__", None, "not-a-contract-reason"])
def test_post_accept_unavailable_reason_is_normalized(monkeypatch, tmp_path, reason):
    from fastapi import HTTPException, status

    from scene.interface_adapters.http.routers import describe as describe_module

    _gpu_env(monkeypatch, tmp_path, state="ready")

    detail = {
        "code": "description_service_unavailable",
        "message": "dependency unavailable",
        "operation_id": "upstream-operation",
        "startup_id": "upstream-startup",
        "timing": {
            "queue_ms": 1,
            "ramp_up_ms": 2,
            "processing_ms": 3,
            "startup_ms": None,
            "server_elapsed_ms": 4,
        },
    }
    if reason != "__missing__":
        detail["reason"] = reason

    async def reject_quota(*args, **kwargs):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)

    monkeypatch.setattr(describe_module, "maybe_consume_demo_quota", reject_quota)
    with _client(adapter=_GpuAdapter()) as client:
        response = _post(client, TENANT_ID)
        assert response.status_code == 503, response.text
        body = response.json()
        _multipart_validator().validate(body)
        normalized = body["detail"]
        assert normalized["code"] == "description_service_unavailable"
        assert normalized["message"] == "dependency unavailable"
        assert normalized["reason"] == "state_missing"
        assert normalized["operation_id"] != "upstream-operation"
        assert normalized["startup_id"] is None
        assert "warmup_eta_seconds" not in normalized
        assert "startup_budget_seconds" not in normalized


@pytest.mark.parametrize("budget", [None, 0])
def test_post_accept_starting_budget_is_normalized(monkeypatch, tmp_path, budget):
    from fastapi import HTTPException, status

    from scene.interface_adapters.http.routers import describe as describe_module

    _gpu_env(monkeypatch, tmp_path, state="ready")
    monkeypatch.setenv("ACX_GPU_WARMUP_TIMEOUT_SECONDS", "17.5")

    detail = {
        "code": "description_service_starting",
        "message": "dependency starting",
        "operation_id": "upstream-operation",
        "startup_id": "upstream-startup",
        "warmup_eta_seconds": 45,
        "timing": {
            "queue_ms": 1,
            "ramp_up_ms": 2,
            "processing_ms": None,
            "startup_ms": None,
            "server_elapsed_ms": 4,
        },
    }
    if budget is not None:
        detail["startup_budget_seconds"] = budget

    async def reject_quota(*args, **kwargs):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "45"},
            detail=detail,
        )

    monkeypatch.setattr(describe_module, "maybe_consume_demo_quota", reject_quota)
    with _client(adapter=_GpuAdapter()) as client:
        response = _post(client, TENANT_ID)
        assert response.status_code == 503, response.text
        body = response.json()
        _multipart_validator().validate(body)
        normalized = body["detail"]
        assert normalized["code"] == "description_service_starting"
        assert normalized["message"] == "dependency starting"
        assert normalized["operation_id"] != "upstream-operation"
        assert normalized["startup_id"] is None
        assert normalized["startup_budget_seconds"] == pytest.approx(17.5)
        assert normalized["warmup_eta_seconds"] == 45
        assert "reason" not in normalized
        assert response.headers.get("Retry-After") == "45"


def test_production_route_unavailable_error_validates_against_shared_schema(monkeypatch, tmp_path):
    _gpu_env(monkeypatch, tmp_path, state="ready")
    validator = _multipart_validator()
    with _client(adapter=_GpuAdapter(), db_absent=True) as client:
        response = _post(client, TENANT_ID)
        assert response.status_code == 503, response.text
        body = response.json()
        validator.validate(body)
        assert body["detail"]["code"] == "description_service_unavailable"
        assert "operation_id" in body["detail"]
        assert body["detail"]["operation_id"] is None
        assert "startup_id" in body["detail"]
        assert body["detail"]["startup_id"] is None
        assert "timing" in body["detail"]
        assert "warmup_eta_seconds" not in body["detail"]
        assert body["detail"]["reason"] == "state_missing"
        assert "startup_budget_seconds" not in body["detail"]


def test_production_cpu_no_session_success_omits_operation_id():
    validator = _multipart_validator()
    with _client(db_absent=True) as client:
        response = _post(client, TENANT_ID)
        assert response.status_code == 200, response.text
        body = response.json()
        validator.validate(_schema_body(body))
        assert "operation_id" not in body
        assert "startup_id" in body
        assert "timing" in body
