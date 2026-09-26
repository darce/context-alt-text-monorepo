"""Regression tests for the detailed health readiness schema contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft7Validator

SCHEMA_PATH = (
    Path(__file__).resolve().parents[4] / "packages/shared-contracts/schemas/scene-health-detailed.schema.json"
)
READINESS_REASONS = (
    "profile_unavailable",
    "vlm_dependencies_missing",
    "endpoint_unconfigured",
    "endpoint_invalid_url",
    "endpoint_not_allowlisted",
    "endpoint_not_private",
    "endpoint_resolution_pending",
)


def _adapter_validator_and_example() -> tuple[Draft7Validator, dict[str, Any]]:
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft7Validator(document["definitions"]["descriptionAdapterReadiness"])
    return validator, document["examples"][0]["description_adapter"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("endpoint_private", None), ("checked_at", None)],
)
def test_fresh_readiness_requires_endpoint_evidence(field: str, value: Any) -> None:
    validator, adapter = _adapter_validator_and_example()
    adapter[field] = value

    assert not validator.is_valid(adapter), f"fresh readiness must require {field} evidence"


def test_usable_readiness_requires_fresh_evidence() -> None:
    validator, adapter = _adapter_validator_and_example()
    adapter["fresh"] = False

    assert not validator.is_valid(adapter), "usable readiness must not be stale"


def test_unusable_readiness_requires_a_reason() -> None:
    validator, adapter = _adapter_validator_and_example()
    adapter["usable"] = False

    assert not validator.is_valid(adapter), "unusable readiness must explain why"


@pytest.mark.parametrize("reason", READINESS_REASONS)
def test_readiness_schema_accepts_documented_reasons(reason: str) -> None:
    validator, adapter = _adapter_validator_and_example()
    adapter["reason"] = reason
    adapter["usable"] = False

    assert validator.is_valid(adapter)


def test_readiness_schema_rejects_unknown_reason() -> None:
    validator, adapter = _adapter_validator_and_example()
    adapter["reason"] = "endpoint_not_allowlisted_typo"

    assert not validator.is_valid(adapter), "unsupported readiness reasons must be rejected"
