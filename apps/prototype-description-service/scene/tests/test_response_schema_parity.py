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
    return json.loads(SCHEMA_PATH.read_text())


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
    }


def test_schema_required_matches_model_fields():
    schema = _schema()
    assert set(schema["required"]) == set(VisualFactsResponse.model_fields)
    assert len(schema["required"]) == 15


def test_sample_validates_against_schema():
    jsonschema.validate(_sample(), _schema())


def test_missing_provenance_field_fails_schema():
    bad = _sample()
    del bad["provider_disclosure"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, _schema())
