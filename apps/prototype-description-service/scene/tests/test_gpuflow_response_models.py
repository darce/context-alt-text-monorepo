"""GPUFLOW timing stays typed and preserves unknown observations."""

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from scene.interface_adapters.http.schemas.responses import (
    DescribeRunItemsResponse,
    DescribeRunResponse,
    VisualFactsResponse,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCHEMAS = {
    VisualFactsResponse: json.loads(
        (_REPO_ROOT / "packages/shared-contracts/schemas/image-description-response.schema.json").read_text()
    ),
    DescribeRunResponse: json.loads(
        (_REPO_ROOT / "packages/shared-contracts/schemas/scene-describe-run.schema.json").read_text()
    ),
}
_ABSENT_OPERATION_KEYS = ("operation_id", "startup_id", "timing")


@pytest.fixture(params=[VisualFactsResponse, DescribeRunResponse])
def response_case(request):
    if request.param is VisualFactsResponse:
        payload = {
            "tenant_id": "tenant",
            "media_id": 1,
            "image_hash": "hash",
            "context_hash": "context",
            "adapter": "seeded",
            "model_id": "model",
            "model_version": "1",
            "prompt_or_task_version": "1",
            "visual_facts": {"caption": "A tree"},
            "alt_text_draft": "A tree",
            "context_used": {},
            "provider_disclosure": {},
            "cached": False,
            "duration_ms": 12,
            "retention_class": "retain_all",
            "tier": "provisional_cpu",
            "result_generation": 1,
        }
        timing = {"queue_ms": None, "ramp_up_ms": 0, "processing_ms": 12.5, "startup_ms": None, "server_elapsed_ms": 15}
    else:
        payload = {
            "tenant_id": "11111111-1111-4111-8111-111111111111",
            "run_id": "22222222-2222-4222-8222-222222222222",
            "status": "cancelled",
            "phase": "cancelled",
            "completed": 1,
            "failed": 1,
            "skipped": 1,
            "total": 3,
            "cancel_requested": False,
            "eta_seconds": None,
            "gpu_state": "unknown",
            "recognition_enabled": True,
        }
        timing = {
            "queue_ms": None,
            "ramp_up_ms": 0,
            "processing_ms_p50": 12.5,
            "processing_ms_max": 20,
            "startup_ms": None,
            "server_elapsed_ms": 25,
            "items_timed": 2,
        }
    return request.param, payload, timing


def _dumped_payloads(response):
    return response.model_dump(mode="json"), json.loads(response.model_dump_json())


def _assert_omits_operation_metadata(payload):
    for key in _ABSENT_OPERATION_KEYS:
        assert key not in payload
        assert payload.get(key) is None


def _validate_shared_schema(model, payload):
    jsonschema.validate(payload, _SCHEMAS[model])


def test_timing_and_opaque_correlation_round_trip(response_case):
    model, payload, timing = response_case
    response = model(**payload, operation_id="opaque-operation", startup_id=None, timing=timing)
    wire = response.model_dump(mode="json")
    assert wire["timing"] == timing
    assert wire["operation_id"] == "opaque-operation"
    assert wire["startup_id"] is None


def test_builder_shaped_response_omits_absent_operation_metadata(response_case):
    model, payload, _timing = response_case
    response = model(**payload)
    dumped, encoded = _dumped_payloads(response)
    _assert_omits_operation_metadata(dumped)
    _assert_omits_operation_metadata(encoded)
    _validate_shared_schema(model, dumped)
    _validate_shared_schema(model, encoded)


def test_explicit_none_operation_metadata_is_omitted(response_case):
    model, payload, _timing = response_case
    response = model(**payload, operation_id=None, startup_id=None, timing=None)
    dumped, encoded = _dumped_payloads(response)
    _assert_omits_operation_metadata(dumped)
    _assert_omits_operation_metadata(encoded)
    _validate_shared_schema(model, dumped)
    _validate_shared_schema(model, encoded)


def test_populated_operation_metadata_validates_against_shared_schema(response_case):
    model, payload, timing = response_case
    response = model(
        **payload,
        operation_id="opaque-operation",
        startup_id="opaque-startup",
        timing=timing,
    )
    dumped, encoded = _dumped_payloads(response)
    for wire in (dumped, encoded):
        assert wire["operation_id"] == "opaque-operation"
        assert wire["startup_id"] == "opaque-startup"
        assert wire["timing"] == timing
        _validate_shared_schema(model, wire)


def test_timing_rejects_unknown_missing_and_invalid_measurements(response_case):
    model, payload, timing = response_case
    payload = {**payload, "operation_id": "opaque-operation", "startup_id": None}
    for field in timing:
        for invalid in (-1, float("inf"), float("nan"), "12", True):
            with pytest.raises(ValidationError):
                model(**payload, timing={**timing, field: invalid})
        incomplete = timing.copy()
        del incomplete[field]
        with pytest.raises(ValidationError):
            model(**payload, timing=incomplete)
    with pytest.raises(ValidationError):
        model(**payload, timing={**timing, "extra": 1})
    del payload["operation_id"]
    for operation_id in ("", "x" * 129):
        with pytest.raises(ValidationError):
            model(**payload, operation_id=operation_id, timing=timing)


@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed", "skipped"])
@pytest.mark.parametrize("processing_ms", [None, 0, 12.5])
def test_item_timing_survives_container_serialization(status, processing_ms):
    response = DescribeRunItemsResponse(
        tenant_id="tenant",
        run_id="run",
        items=[
            {"media_id": 1, "status": status, "processing_ms": processing_ms},
        ],
    )
    assert response.model_dump(mode="json")["items"][0]["processing_ms"] == processing_ms


@pytest.mark.parametrize("processing_ms", [-1, float("inf"), float("nan"), "12", True])
def test_invalid_item_timing_rejected(processing_ms):
    with pytest.raises(ValidationError):
        DescribeRunItemsResponse(
            tenant_id="tenant",
            run_id="run",
            items=[
                {"media_id": 1, "status": "failed", "processing_ms": processing_ms},
            ],
        )
