"""Wave 1 document-only contracts: no application or builder imports."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[4] / "packages/shared-contracts/schemas"
NAMES = ("image-description-response", "scene-describe-multipart", "scene-describe-run")


def validator(name, definition=None):
    documents = [json.loads((ROOT / f"{n}.schema.json").read_text()) for n in NAMES]
    registry = Registry().with_resources((d["$id"], Resource.from_contents(d)) for d in documents)
    schema = documents[NAMES.index(name)]
    if definition:
        schema = {"$ref": schema["$id"] + "#/definitions/" + definition}
    return Draft7Validator(schema, registry=registry)


TIMING = dict(queue_ms=None, ramp_up_ms=1200, processing_ms=12, startup_ms=None, server_elapsed_ms=1212)
SUCCESS = dict(
    tenant_id="00000000-0000-0000-0000-000000000001",
    media_id=42,
    image_hash="a" * 64,
    context_hash="b" * 64,
    adapter="seeded",
    model_id="seeded-fixtures",
    model_version="1",
    prompt_or_task_version="1",
    visual_facts={"caption": "A cat"},
    alt_text_draft="A cat.",
    context_used={"sources": [], "applied": False},
    provider_disclosure={"provider": "none", "left_service_boundary": False},
    cached=False,
    duration_ms=12,
    retention_class="retain_all",
    tier="provisional_cpu",
    result_generation=1,
    operation_id="opaque operation",
    startup_id=None,
    timing=TIMING,
)
RUN = dict(
    tenant_id=SUCCESS["tenant_id"],
    run_id=SUCCESS["tenant_id"],
    status="running",
    phase="describing",
    completed=0,
    failed=0,
    skipped=0,
    total=2,
    cancel_requested=False,
    eta_seconds=None,
    gpu_state="ready",
    recognition_enabled=True,
    operation_id="run operation",
    startup_id=None,
    timing=dict(
        queue_ms=10,
        ramp_up_ms=0,
        processing_ms_p50=None,
        processing_ms_max=None,
        items_timed=0,
        startup_ms=None,
        server_elapsed_ms=10,
    ),
)


@pytest.mark.parametrize("name", NAMES)
def test_schema_is_well_formed(name):
    Draft7Validator.check_schema(json.loads((ROOT / f"{name}.schema.json").read_text()))


@pytest.mark.parametrize("name", NAMES[:2])
def test_success(name):
    validator(name).validate(SUCCESS)
    older = {k: v for k, v in SUCCESS.items() if k != "timing"}
    assert validator(name).is_valid(older) == (name == "image-description-response")
    bad = copy.deepcopy(SUCCESS)
    bad["timing"]["processing_ms"] = -1
    assert not validator(name).is_valid(bad)


@pytest.mark.parametrize(
    "code",
    [
        "description_service_starting",
        "description_service_unavailable",
        "description_service_error",
        "operation_mismatch",
        "operation_expired",
    ],
)
def test_typed_errors(code):
    detail = dict(
        code=code, message="Description service status", operation_id="opaque operation", startup_id=None, timing=TIMING
    )
    v = validator("scene-describe-multipart")
    v.validate({"detail": detail})
    assert not v.is_valid({"detail": {k: value for k, value in detail.items() if k != "timing"}})
    detail["warmup_eta_seconds"] = None
    assert v.is_valid({"detail": detail}) == (code == "description_service_starting")
    detail["warmup_eta_seconds"] = 4
    assert v.is_valid({"detail": detail}) == (code == "description_service_starting")
    assert not v.is_valid(detail)


def test_run_and_items():
    validator("scene-describe-run").validate(RUN)
    item = dict(
        media_id=42,
        status="failed",
        alt_text_draft=None,
        caption=None,
        provenance=None,
        error="adapter failure",
        tier=None,
        result_generation=0,
        processing_ms=None,
    )
    validator("scene-describe-run", "item").validate(item)
    validator("scene-describe-run", "items").validate(
        dict(tenant_id=SUCCESS["tenant_id"], run_id=RUN["run_id"], items=[item])
    )
    item["processing_ms"] = -1
    assert not validator("scene-describe-run", "item").is_valid(item)


def test_request_and_lease_vocabulary():
    v = validator("scene-describe-multipart", "retryFields")
    v.validate({})
    v.validate({"operation_id": "x" * 128})
    assert not v.is_valid({"operation_id": "x" * 129})
    lease = validator("scene-describe-multipart", "leaseState")
    for state in ("active", "completed", "expired", "rejected"):
        lease.validate(state)
    assert not lease.is_valid("warming")


def test_strict_errors_and_correlation():
    v = validator("scene-describe-multipart")
    for key, value in (("operation_id", None), ("operation_id", "x" * 129), ("startup_id", 42), ("Retry-After", 10)):
        bad = copy.deepcopy(SUCCESS)
        bad[key] = value
        assert not v.is_valid(bad)
    detail = dict(code="unrecognized", message="error", operation_id="op", startup_id=None, timing=TIMING)
    assert not v.is_valid({"detail": detail})
    detail["code"] = "description_service_starting"
    detail["warmup_eta_seconds"] = -1
    assert not v.is_valid({"detail": detail})


@pytest.mark.parametrize("status", ["failed", "cancelled", "completed_with_errors"])
def test_terminal_run_keeps_nullable_timing(status):
    payload = copy.deepcopy(RUN)
    payload["status"] = status
    payload["timing"] = {key: None for key in RUN["timing"]}
    validator("scene-describe-run").validate(payload)
    payload["timing"]["items_timed"] = -1
    assert not validator("scene-describe-run").is_valid(payload)


def test_item_status_vocabulary():
    item_validator = validator("scene-describe-run", "item")
    for status in ("queued", "running", "completed", "failed", "skipped"):
        item_validator.validate(dict(media_id=42, status=status, processing_ms=0))
    assert not item_validator.is_valid(dict(media_id=42, status="cancelled", processing_ms=None))


@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed", "skipped"])
def test_item_requires_explicit_processing_timing(status):
    v = validator("scene-describe-run", "item")
    item = dict(media_id=42, status=status, processing_ms=None)
    v.validate(item)
    del item["processing_ms"]
    assert not v.is_valid(item)


@pytest.mark.parametrize("name", NAMES[:2])
def test_cache_timing_consistency(name):
    payload = copy.deepcopy(SUCCESS)
    payload["cached"] = True
    payload["timing"].update(ramp_up_ms=0, processing_ms=0)
    v = validator(name)
    v.validate(payload)
    for field, value in (("startup_id", "startup"), ("ramp_up_ms", 1),
                         ("processing_ms", 1), ("ramp_up_ms", None), ("processing_ms", None)):
        bad = copy.deepcopy(payload)
        target = bad if field == "startup_id" else bad["timing"]
        target[field] = value
        assert not v.is_valid(bad)
    if name == "image-description-response":
        del payload["timing"]
        del payload["startup_id"]
        v.validate(payload)


@pytest.mark.parametrize(
    "document, requirements",
    [
        ("gpu-lifecycle", (
            "Each active, unexpired, policy-eligible lease contributes one to `in_flight`",
            "`lease_demand` field is a nonnegative nullable integer",
            "STOP-held and max-lease-blocked",
            "has_work := (queue_depth + in_flight) > 0",
        )),
        ("gpu-lifecycle", (
            "sequence inside the same transaction as the demand read",
            "write-if-newer under the existing cross-process writer lock",
            "candidate `revision` is greater than the currently published one",
            "A must be dropped, leaving revision 11",
        )),
        ("image-description-api", (
            "REQUIRED on every `description_service_starting` 503",
            "integer delta-seconds in [1, 120]",
            "MUST be absent on all other typed errors",
        )),
    ],
)
def test_documented_publisher_and_retry_requirements(document, requirements):
    """Guard the normative clauses; runtime scenarios belong to producer lanes."""
    path = ROOT.parents[2] / "docs/workbay/contracts" / f"{document}.md"
    text = " ".join(path.read_text().split())
    for requirement in requirements:
        assert requirement in text
