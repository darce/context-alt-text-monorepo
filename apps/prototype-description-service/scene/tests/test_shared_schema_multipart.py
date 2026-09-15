"""Wave 3: production multipart envelopes against the shared schema."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource

from scene.tests.test_describe_route import TENANT_ID, _client, _gpu_env, _GpuAdapter, _post

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCHEMA_DIR = _REPO_ROOT / "packages/shared-contracts/schemas"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gpuflow-multipart.json"
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
