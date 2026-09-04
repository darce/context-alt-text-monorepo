from __future__ import annotations

import json
from pathlib import Path

from check_shared_contract_fixtures import (
    LIST_RESPONSE_CONTRACTS,
    SchemaValidationError,
    validate_against_schema,
    validate_all_fixture_contracts,
)


def test_validate_all_fixture_contracts_passes_for_current_shared_payloads() -> None:
    validate_all_fixture_contracts()


def test_validator_rejects_missing_envelope_field() -> None:
    contract = LIST_RESPONSE_CONTRACTS[0]
    fixture = json.loads(contract.fixture_path.read_text(encoding="utf-8"))
    schema = json.loads(contract.schema_path.read_text(encoding="utf-8"))
    fixture.pop("truncated")

    try:
        validate_against_schema(fixture, schema, path="cluster list fixture")
        raise AssertionError("expected SchemaValidationError when `truncated` is missing")
    except SchemaValidationError as exc:
        assert "missing required key 'truncated'" in str(exc)


def test_validator_rejects_numeric_value_outside_schema_bounds() -> None:
    contract = LIST_RESPONSE_CONTRACTS[2]
    fixture = json.loads(contract.fixture_path.read_text(encoding="utf-8"))
    schema = json.loads(contract.schema_path.read_text(encoding="utf-8"))
    fixture["limit"] = 0

    try:
        validate_against_schema(fixture, schema, path="cluster members fixture")
        raise AssertionError("expected SchemaValidationError when `limit` is below minimum")
    except SchemaValidationError as exc:
        assert "expected >= 1" in str(exc)
