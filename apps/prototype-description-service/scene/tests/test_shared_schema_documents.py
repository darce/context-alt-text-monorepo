"""Wave 1 document-only contracts: no application or builder imports."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[4] / "packages/shared-contracts/schemas"
NAMES = ("image-description-response", "scene-describe-multipart", "scene-describe-run", "scene-health-detailed")


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
HEALTH = {
    "status": "ok",
    "timestamp": "2026-09-17T00:00:00Z",
    "description_adapter": {
        "profile": "gpu_qwen30b",
        "kind": "gpu",
        "endpoint_configured": True,
        "endpoint_allowlisted": True,
        "endpoint_private": True,
        "checked_at": 1789603200.0,
        "fresh": True,
        "usable": True,
        "reason": None,
    },
}


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
    if code == "description_service_starting":
        detail["startup_budget_seconds"] = 510
    elif code == "description_service_unavailable":
        detail["reason"] = "state_stale"
    v = validator("scene-describe-multipart")
    v.validate({"detail": detail})
    assert not v.is_valid({"detail": {k: value for k, value in detail.items() if k != "timing"}})
    detail["warmup_eta_seconds"] = None
    assert v.is_valid({"detail": detail}) == (code == "description_service_starting")
    detail["warmup_eta_seconds"] = 4
    assert v.is_valid({"detail": detail}) == (code == "description_service_starting")
    assert not v.is_valid(detail)


def test_health_detailed_adapter_readiness_document():
    validator("scene-health-detailed").validate(HEALTH)
    adapter = HEALTH["description_adapter"]
    assert set(adapter) == {
        "profile",
        "kind",
        "endpoint_configured",
        "endpoint_allowlisted",
        "endpoint_private",
        "checked_at",
        "fresh",
        "usable",
        "reason",
    }


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


ROSTER_SCHEMAS = (
    "recognition-cluster-snapshot",
    "roster-entry",
    "recognition-cluster-merge-candidates-response",
    "roster-merge-candidates-response",
)


def _schema(name):
    return json.loads((ROOT / f"{name}.schema.json").read_text())


def _draft7_without_dependent_required(schema):
    """Draft-07 metaschema rejects dependentRequired; instance validation still uses dependencies."""
    cloned = copy.deepcopy(schema)
    stack = [cloned]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            node.pop("dependentRequired", None)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return cloned


SNAPSHOT_CLUSTER = {
    "cluster_uuid": "6c1a2e32-31b2-4d54-a4de-98b1a73d77a1",
    "label": "Alice Example",
    "curation_state": "confirmed",
    "is_user_confirmed": True,
    "identity_count": 2,
    "representative_quality": 0.82,
    "quality_components": {
        "confidence": 0.94,
        "bbox_area": 7680,
        "sharpness": 42.5,
        "occlusion_severity": 0.12,
    },
}

ROSTER_IDENTITY = {
    "identity_id": "id-1",
    "media_id": 1,
    "media_url": None,
    "bbox": {"x": 0, "y": 0, "width": 10, "height": 10},
    "similarity": 0.9,
    "representative_quality": 0.82,
    "quality_components": {
        "confidence": 0.94,
        "bbox_area": 7680,
        "sharpness": 77.0,
        "occlusion_severity": 0.12,
    },
}


@pytest.mark.parametrize("name", ROSTER_SCHEMAS)
def test_gpuflow_roster_schema_is_well_formed(name):
    Draft7Validator.check_schema(_draft7_without_dependent_required(_schema(name)))


def test_snapshot_sharpness_is_unbounded_variance_of_laplacian():
    cluster_schema = _schema("recognition-cluster-snapshot")["properties"]["clusters"]["items"]
    validator = Draft7Validator(cluster_schema)
    payload = copy.deepcopy(SNAPSHOT_CLUSTER)
    validator.validate(payload)
    payload["quality_components"]["sharpness"] = 77.0
    validator.validate(payload)
    payload["quality_components"]["sharpness"] = -0.1
    assert not validator.is_valid(payload)
    payload["quality_components"]["sharpness"] = 42.5
    payload["quality_components"]["confidence"] = 1.1
    assert not validator.is_valid(payload)
    sharpness = cluster_schema["properties"]["quality_components"]["properties"]["sharpness"]
    assert sharpness.get("minimum") == 0
    assert "maximum" not in sharpness


def test_snapshot_quality_fields_are_co_required():
    cluster_schema = _schema("recognition-cluster-snapshot")["properties"]["clusters"]["items"]
    validator = Draft7Validator(cluster_schema)
    missing_components = copy.deepcopy(SNAPSHOT_CLUSTER)
    del missing_components["quality_components"]
    assert not validator.is_valid(missing_components)
    missing_quality = copy.deepcopy(SNAPSHOT_CLUSTER)
    del missing_quality["representative_quality"]
    assert not validator.is_valid(missing_quality)
    omitted = copy.deepcopy(SNAPSHOT_CLUSTER)
    del omitted["representative_quality"]
    del omitted["quality_components"]
    validator.validate(omitted)
    assert cluster_schema["dependencies"] == {
        "representative_quality": ["quality_components"],
        "quality_components": ["representative_quality"],
    }
    assert cluster_schema["dependentRequired"] == cluster_schema["dependencies"]
    assert cluster_schema["properties"]["quality_components"]["required"] == [
        "confidence",
        "bbox_area",
        "sharpness",
        "occlusion_severity",
    ]


def test_roster_entry_quality_fields_are_co_required_and_sharpness_unbounded():
    identity_schema = _schema("roster-entry")["properties"]["clusters"]["items"]["properties"][
        "representative_identity"
    ]
    validator = Draft7Validator(identity_schema)
    validator.validate(ROSTER_IDENTITY)
    missing_components = copy.deepcopy(ROSTER_IDENTITY)
    del missing_components["quality_components"]
    assert not validator.is_valid(missing_components)
    missing_quality = copy.deepcopy(ROSTER_IDENTITY)
    del missing_quality["representative_quality"]
    assert not validator.is_valid(missing_quality)
    sharpness = identity_schema["properties"]["quality_components"]["properties"]["sharpness"]
    assert sharpness.get("minimum") == 0
    assert "maximum" not in sharpness
    assert identity_schema["dependencies"] == {
        "representative_quality": ["quality_components"],
        "quality_components": ["representative_quality"],
    }
    assert identity_schema["dependentRequired"] == identity_schema["dependencies"]


def test_merge_candidate_schemas_document_similarity_and_self_exclusion():
    cluster_text = json.dumps(_schema("recognition-cluster-merge-candidates-response"))
    roster_text = json.dumps(_schema("roster-merge-candidates-response"))
    assert "max(centroid cosine, latest pending ClusterMergeSuggestion similarity)" in cluster_text
    assert "canonical unordered pair (min uuid, max uuid)" in cluster_text
    assert "Person aggregation excludes candidates whose person_id equals the probe person_id" in roster_text
    assert "the service drops them" in roster_text


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
                         ("processing_ms", 1), ("startup_ms", 7),
                         ("ramp_up_ms", None), ("processing_ms", None)):
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
            "has_work := ((queue_depth + in_flight) > 0) OR batch_in_progress",
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
        ("identity-merge", (
            "`representative_quality` normalizes sharpness before weighting",
            "Receipts carry `tenant_id` (`NOT NULL`, RLS like sibling identity tables).",
            "`revert_merge(tenant_id, receipt_id, path cluster id)`",
            "merge_receipt_stale",
            "The receipt revert is the only recognition undo surface",
            "POST /recognition/clusters/revert-merge",
            "revert_merge_cluster",
            "## Retired surfaces",
            "Restore the source cluster under its stored `source_cluster_id`",
            "Return the restored `source_cluster_id`",
            "max(centroid cosine, latest pending ClusterMergeSuggestion similarity)",
            "canonical unordered pair",
            "Person aggregation excludes candidates whose person_id equals the probe person_id",
            "`operator_initial_choice` is required on commit",
            "invalid_initial_choice",
        )),
    ],
)
def test_documented_publisher_and_retry_requirements(document, requirements):
    """Guard the normative clauses; runtime scenarios belong to producer lanes."""
    path = ROOT.parents[2] / "docs/workbay/contracts" / f"{document}.md"
    text = " ".join(path.read_text().split())
    for requirement in requirements:
        assert requirement in text


def test_publication_has_work_includes_batch_gaps():
    path = ROOT.parents[2] / "docs/workbay/contracts/gpu-lifecycle.md"
    section = path.read_text().split("### Publication and deployment bounds", 1)[1]
    text = " ".join(section.split())
    assert "has_work := ((queue_depth + in_flight) > 0) OR batch_in_progress" in text
    assert "START and STOP, including batch gaps with both counts zero" in text
