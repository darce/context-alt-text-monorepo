"""GPUFLOW timing stays typed and preserves unknown observations."""

import pytest
from pydantic import ValidationError

from scene.interface_adapters.http.schemas.responses import (
    DescribeRunItemsResponse,
    DescribeRunResponse,
    VisualFactsResponse,
)


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
        }
        timing = {"queue_ms": None, "ramp_up_ms": 0, "processing_ms": 12.5, "startup_ms": None, "server_elapsed_ms": 15}
    else:
        payload = {
            "tenant_id": "tenant",
            "run_id": "run",
            "status": "cancelled",
            "phase": "cancelled",
            "completed": 1,
            "failed": 1,
            "skipped": 1,
            "total": 3,
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


def test_timing_and_opaque_correlation_round_trip(response_case):
    model, payload, timing = response_case
    response = model(**payload, operation_id="opaque-operation", startup_id=None, timing=timing)
    wire = response.model_dump(mode="json")
    assert wire["timing"] == timing
    assert wire["operation_id"] == "opaque-operation"
    assert wire["startup_id"] is None


def test_older_response_can_omit_timing(response_case):
    model, payload, _ = response_case
    assert "timing" not in model(**payload).model_dump(exclude_unset=True)


def test_timing_rejects_unknown_missing_and_invalid_measurements(response_case):
    model, payload, timing = response_case
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
    for operation_id in ("", "x" * 129):
        with pytest.raises(ValidationError):
            model(**payload, operation_id=operation_id)


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
