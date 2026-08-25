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


# Additive optional fields: never in `required`, always in `properties` —
# the 17 core-contract fields stay locked.
# E19-4a preview trio + E20-FUSION attachment provenance + ALTQ-1 long surface.
PREVIEW_FIELDS = {
    "generic_draft",
    "named_draft",
    "naming_provenance",
    "attachment_provenance",
    "alt_text_long",
}


def test_schema_model_id_documents_gpu_hub_pin_format():
    """W3-E-03: GPU wire model_id is <hub-repo>@<40-hex hub revision>."""
    description = _schema()["properties"]["model_id"].get("description") or ""
    assert "<hub-repo>@" in description
    assert "40-hex" in description
    assert "idempotence" in description.lower() or "cache" in description.lower()


def test_schema_required_matches_model_fields():
    schema = _schema()
    assert set(schema["required"]) == set(VisualFactsResponse.model_fields) - PREVIEW_FIELDS
    assert len(schema["required"]) == 17
    assert set(schema["properties"]) == set(VisualFactsResponse.model_fields)


def test_sample_validates_against_schema():
    jsonschema.validate(_sample(), _schema())


def test_sample_with_alt_text_long_validates():
    # ALTQ-1: the optional long surface is accepted as string, null, or absent.
    with_long = _sample()
    with_long["alt_text_long"] = "A tabby cat lounging on a woven mat in warm afternoon light."
    jsonschema.validate(with_long, _schema())

    with_null = _sample()
    with_null["alt_text_long"] = None
    jsonschema.validate(with_null, _schema())


def test_alt_text_long_never_required():
    # Absent field = old behavior: alt_text_long must never join the core set.
    assert "alt_text_long" not in _schema()["required"]
    assert "alt_text_long" in _schema()["properties"]


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
    sample["attachment_provenance"] = {
        "facts": [
            {
                "fact_id": "identity:cluster:00000000-0000-0000-0000-000000000002",
                "fact_source": "identity",
                "fact_label": "Daniel",
                "decision": "object",
                "altitude": "object",
                "target_evidence": "person",
                "review_reason": None,
                "visible": True,
            }
        ]
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


def test_schema_attachment_enums_match_reconcile_enums():
    """EH-03: reconcile's decision/altitude StrEnums must equal the frozen
    contract enums, else a new member would emit on the wire uncaught."""
    from scene.application.fusion import AttachmentAltitude, AttachmentDecision

    facts_item = _schema()["properties"]["attachment_provenance"]["properties"]["facts"]["items"]
    assert set(facts_item["properties"]["decision"]["enum"]) == {d.value for d in AttachmentDecision}
    assert set(facts_item["properties"]["altitude"]["enum"]) == {a.value for a in AttachmentAltitude}


def test_populated_attachment_provenance_model_roundtrips():
    """EH-04: the model's own serialization of a populated attachment_provenance
    must validate against the contract (structural round-trip, not a hand-built dict)."""
    from scene.interface_adapters.http.schemas.responses import (
        AttachmentFactProvenance,
        AttachmentProvenance,
    )

    provenance = AttachmentProvenance(
        facts=[
            AttachmentFactProvenance(
                fact_id="identity:cluster:00000000-0000-0000-0000-000000000002",
                fact_source="identity",
                fact_label="Daniel",
                decision="object",
                altitude="object",
                target_evidence="person",
                review_reason=None,
                visible=True,
            )
        ]
    )
    sample = _sample()
    sample["attachment_provenance"] = provenance.model_dump(mode="json")
    jsonschema.validate(sample, _schema())


def test_missing_provenance_field_fails_schema():
    bad = _sample()
    del bad["provider_disclosure"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, _schema())
