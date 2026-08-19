from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "packages" / "shared-contracts" / "recognition"
SCHEMA_ROOT = REPO_ROOT / "packages" / "shared-contracts" / "schemas"


@dataclass(frozen=True)
class FixtureContract:
	fixture_path: Path
	schema_path: Path
	label: str


LIST_RESPONSE_CONTRACTS: tuple[FixtureContract, ...] = (
	FixtureContract(
		fixture_path=FIXTURE_ROOT / "cluster-list-response.golden.json",
		schema_path=SCHEMA_ROOT / "recognition-cluster-list-response.schema.json",
		label="GET /recognition/clusters fixture",
	),
	FixtureContract(
		fixture_path=FIXTURE_ROOT / "cluster-labels-response.golden.json",
		schema_path=SCHEMA_ROOT / "recognition-cluster-labels-response.schema.json",
		label="GET /recognition/clusters/labels fixture",
	),
	FixtureContract(
		fixture_path=FIXTURE_ROOT / "cluster-members-response.golden.json",
		schema_path=SCHEMA_ROOT / "recognition-cluster-members-response.schema.json",
		label="GET /recognition/clusters/{cluster_id}/members fixture",
	),
	FixtureContract(
		fixture_path=FIXTURE_ROOT / "cluster-top-unlabeled-response.golden.json",
		schema_path=SCHEMA_ROOT / "recognition-cluster-top-unlabeled-response.schema.json",
		label="GET /recognition/clusters/top-unlabeled fixture",
	),
)


class SchemaValidationError(ValueError):
	pass


def _load_json(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def _python_type_matches(expected_type: str, value: Any) -> bool:
	if "null" == expected_type:
		return value is None
	if "boolean" == expected_type:
		return isinstance(value, bool)
	if "integer" == expected_type:
		return isinstance(value, int) and not isinstance(value, bool)
	if "number" == expected_type:
		return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
	if "string" == expected_type:
		return isinstance(value, str)
	if "object" == expected_type:
		return isinstance(value, dict)
	if "array" == expected_type:
		return isinstance(value, list)
	return False


def _normalize_expected_types(schema: dict[str, Any]) -> tuple[str, ...]:
	type_value = schema.get("type")
	if isinstance(type_value, str):
		return (type_value,)
	if isinstance(type_value, list):
		return tuple(type_name for type_name in type_value if isinstance(type_name, str))
	return tuple()


def _validate_format(value: str, fmt: str, path: str) -> None:
	if "uri" == fmt:
		parsed = urlparse(value)
		if not parsed.scheme or not parsed.netloc:
			raise SchemaValidationError(f"{path}: expected URI-formatted string, got {value!r}")
		return

	if "date-time" == fmt:
		normalized = value.replace("Z", "+00:00")
		try:
			datetime.fromisoformat(normalized)
		except ValueError as exc:
			raise SchemaValidationError(f"{path}: expected RFC3339 date-time string, got {value!r}") from exc


def validate_against_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
	expected_types = _normalize_expected_types(schema)
	if expected_types and not any(_python_type_matches(expected_type, value) for expected_type in expected_types):
		raise SchemaValidationError(
			f"{path}: expected type {expected_types}, got {type(value).__name__}"
		)

	if value is None:
		return

	if isinstance(value, dict):
		required = schema.get("required", [])
		for key in required:
			if key not in value:
				raise SchemaValidationError(f"{path}: missing required key {key!r}")

		properties = schema.get("properties", {})
		for key, property_schema in properties.items():
			if key in value and isinstance(property_schema, dict):
				validate_against_schema(value[key], property_schema, f"{path}.{key}")

		return

	if isinstance(value, list):
		min_items = schema.get("minItems")
		if isinstance(min_items, int) and len(value) < min_items:
			raise SchemaValidationError(f"{path}: expected minItems {min_items}, got {len(value)}")
		item_schema = schema.get("items")
		if isinstance(item_schema, dict):
			for index, item in enumerate(value):
				validate_against_schema(item, item_schema, f"{path}[{index}]")
		return

	if isinstance(value, (int, float)) and not isinstance(value, bool):
		minimum = schema.get("minimum")
		maximum = schema.get("maximum")
		if isinstance(minimum, (int, float)) and value < minimum:
			raise SchemaValidationError(f"{path}: expected >= {minimum}, got {value}")
		if isinstance(maximum, (int, float)) and value > maximum:
			raise SchemaValidationError(f"{path}: expected <= {maximum}, got {value}")

	if isinstance(value, str):
		string_format = schema.get("format")
		if isinstance(string_format, str):
			_validate_format(value, string_format, path)


def validate_fixture_contract(contract: FixtureContract) -> None:
	if not contract.fixture_path.is_file():
		raise SchemaValidationError(f"Missing fixture file: {contract.fixture_path}")
	if not contract.schema_path.is_file():
		raise SchemaValidationError(f"Missing schema file: {contract.schema_path}")

	fixture_payload = _load_json(contract.fixture_path)
	schema_payload = _load_json(contract.schema_path)
	validate_against_schema(fixture_payload, schema_payload, path=contract.label)


def validate_all_fixture_contracts() -> None:
	for contract in LIST_RESPONSE_CONTRACTS:
		validate_fixture_contract(contract)


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Validate shared list-response golden fixtures against their declared schemas."
	)
	parser.parse_args()

	try:
		validate_all_fixture_contracts()
	except SchemaValidationError as exc:
		print(str(exc))
		return 1

	print(f"Validated {len(LIST_RESPONSE_CONTRACTS)} shared contract fixture(s).")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())