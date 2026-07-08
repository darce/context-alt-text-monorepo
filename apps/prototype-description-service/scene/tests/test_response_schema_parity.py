"""S1: the checked-in JSON schema and the Pydantic response model stay in lockstep."""

import json
from pathlib import Path

import jsonschema
import pytest

from scene.interface_adapters.http.schemas.responses import VisualFactsResponse

SCHEMA_PATH = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "shared-contracts"
    / "schemas"
    / "image-description-response.schema.json"
)


def _schema() -> dict:
    data: dict = json.loads(SCHEMA_PATH.read_text())
    return data


def _sample() -> dict:
    return {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "media_id": 42,
        "image_hash": "a" * 64,
        "context_hash": "b" * 64,
        "adapter": "seeded",
        "model_id": "seeded-fixtures",
        "model_version": "1",
        "prompt_or_task_version": "1",
        "visual_facts": {"caption": "A cat on a mat", "objects": ["cat", "mat"], "ocr_text": None},
        "alt_text_draft": "A cat sitting on a mat.",
        "context_used": {"sources": [], "applied": False},
        "provider_disclosure": {"provider": "none", "left_service_boundary": False},
        "cached": False,
        "duration_ms": 12,
        "retention_class": "retain_all",
        "tier": "provisional_cpu",
        "result_generation": 1,
    }


# E19-4a additive optional preview fields: never in `required`, always in
# `properties` — the 17 core-contract fields stay locked.
PREVIEW_FIELDS = {"generic_draft", "named_draft", "naming_provenance"}


def test_schema_required_matches_model_fields():
    schema = _schema()
    assert set(schema["required"]) == set(VisualFactsResponse.model_fields) - PREVIEW_FIELDS
    assert len(schema["required"]) == 17
    assert set(schema["properties"]) == set(VisualFactsResponse.model_fields)


def test_sample_validates_against_schema():
    jsonschema.validate(_sample(), _schema())


def test_sample_with_preview_fields_validates():
    sample = _sample()
    sample["generic_draft"] = "A cat sitting on a mat."
    sample["named_draft"] = "A cat sitting on a mat. Pictured from left: Daniel."
    sample["naming_provenance"] = {
        "injected_names": [
            {
                "name": "Daniel",
                "cluster_id": "00000000-0000-0000-0000-000000000002",
                "roster_id": "00000000-0000-0000-0000-000000000003",
                "detection_confidence": 0.97,
            }
        ],
        "naming_allowed": True,
        "reason": None,
        "mode": "grounded",
    }
    jsonschema.validate(sample, _schema())


def test_schema_reason_enum_matches_naming_skip_reason():
    from scene.application.identity_merge import NamingMode, NamingSkipReason

    schema = _schema()
    provenance = schema["properties"]["naming_provenance"]
    reasons = set(provenance["properties"]["reason"]["enum"]) - {None}
    assert reasons == {r.value for r in NamingSkipReason}
    modes = set(provenance["properties"]["mode"]["enum"]) - {None}
    assert modes == {m.value for m in NamingMode}


def test_missing_provenance_field_fails_schema():
    bad = _sample()
    del bad["provider_disclosure"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, _schema())
