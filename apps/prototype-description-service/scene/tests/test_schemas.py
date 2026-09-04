"""S1: typed visual-facts request/response contract (15 fields, extra-forbid)."""

import uuid

import pytest
from pydantic import ValidationError

from scene.domain.description import DescriptionAdapterKind, DescriptionResultTier, ProviderMode, RetentionClass
from scene.interface_adapters.http.schemas.requests import DescribeImageEnvelope
from scene.interface_adapters.http.schemas.responses import DescribeRunItemResponse, VisualFactsResponse

# 15 contract-locked core fields + additive optional preview/fusion fields.
PREVIEW_FIELDS = {
    "generic_draft",
    "named_draft",
    "naming_provenance",
    "attachment_provenance",
    # ALTQ-1: optional long-form surface (dual-length prompting); null when
    # the adapter produces only the short draft.
    "alt_text_long",
}
EXPECTED_FIELDS = {
    "tenant_id",
    "media_id",
    "image_hash",
    "context_hash",
    "adapter",
    "model_id",
    "model_version",
    "prompt_or_task_version",
    "visual_facts",
    "alt_text_draft",
    "context_used",
    "provider_disclosure",
    "cached",
    "duration_ms",
    "retention_class",
    "tier",
    "result_generation",
}


def _sample_response() -> dict:
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
        "tier": "final_gpu",
        "result_generation": 1,
    }


def test_response_has_exactly_15_contract_fields():
    assert set(VisualFactsResponse.model_fields) == EXPECTED_FIELDS | PREVIEW_FIELDS
    assert len(EXPECTED_FIELDS) == 17


def test_response_round_trip_typed_provenance():
    r = VisualFactsResponse.model_validate(_sample_response())
    assert r.adapter is DescriptionAdapterKind.SEEDED
    assert r.retention_class is RetentionClass.RETAIN_ALL
    assert r.provider_disclosure.provider is ProviderMode.NONE
    assert set(r.model_dump().keys()) == EXPECTED_FIELDS | PREVIEW_FIELDS
    # Preview fields default to None when the merge layer is not run.
    assert r.generic_draft is None and r.named_draft is None and r.naming_provenance is None
    # ALTQ-1: absent long surface defaults to None — old payloads stay valid.
    assert r.alt_text_long is None


def test_response_forbids_extra_provenance_field():
    bad = _sample_response()
    bad["sneaky_provider"] = "openai"
    with pytest.raises(ValidationError):
        VisualFactsResponse.model_validate(bad)


def test_describe_run_item_serializes_tier_and_generation_and_forbids_extra_fields():
    item = DescribeRunItemResponse.model_validate(
        {
            "media_id": 42,
            "status": "completed",
            "tier": "final_gpu",
            "result_generation": 2,
        }
    )

    assert item.tier is DescriptionResultTier.FINAL_GPU
    assert item.model_dump(mode="json")["tier"] == "final_gpu"
    assert item.model_dump()["result_generation"] == 2

    with pytest.raises(ValidationError):
        DescribeRunItemResponse.model_validate(
            {"media_id": 42, "status": "completed", "tier": None, "result_generation": -1}
        )

    with pytest.raises(ValidationError):
        DescribeRunItemResponse.model_validate(
            {
                "media_id": 42,
                "status": "completed",
                "tier": "final_gpu",
                "result_generation": 2,
                "unexpected": True,
            }
        )


def test_request_canonicalizes_tenant_uuid_lowercase():
    tid = str(uuid.uuid4()).upper()
    env = DescribeImageEnvelope.model_validate({"tenant_id": tid, "media_id": 7})
    assert env.tenant_id == tid.lower()
    assert env.media_id == 7


def test_request_rejects_bad_uuid():
    with pytest.raises(ValidationError):
        DescribeImageEnvelope.model_validate({"tenant_id": "not-a-uuid", "media_id": 1})


def test_request_rejects_extra_field_and_nonpositive_media_id():
    good_tid = str(uuid.uuid4())
    with pytest.raises(ValidationError):
        DescribeImageEnvelope.model_validate({"tenant_id": good_tid, "media_id": 1, "nope": 1})
    with pytest.raises(ValidationError):
        DescribeImageEnvelope.model_validate({"tenant_id": good_tid, "media_id": 0})


def test_describe_envelope_accepts_gpu_tier_hint():
    envelope = DescribeImageEnvelope.model_validate(
        {
            "tenant_id": str(uuid.uuid4()),
            "media_id": 123,
            "tier": "gpu",
        }
    )
    assert envelope.tier == "gpu"


def test_enums_have_canonical_values():
    assert [e.value for e in DescriptionAdapterKind] == ["seeded", "local_cpu", "gpu", "hosted_provider"]
    assert [e.value for e in RetentionClass] == ["retain_all", "dispose_after_ack", "purge_on_demand"]
    assert ProviderMode.NONE.value == "none"
