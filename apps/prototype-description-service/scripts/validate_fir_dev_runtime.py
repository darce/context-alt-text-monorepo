"""Validate an already-redacted FIR development-runtime snapshot.

The validator is deliberately offline and stdlib-only.  It consumes the
observations collected by the runtime, applies the supplied freshness and
isolation policies, and returns a machine-readable readiness result with one
of the stable ``ready``, ``incomplete``, or ``invalid`` statuses.

The checks have a fixed precedence.  Secret-shaped values are refused before
any other check, model identifiers are parsed only to validate their opaque
name and suffix, and provenance is checked only at the explicit contract
paths.  A report is built before refusal and replaces secret-shaped strings;
role model IDs and the tenant ID are represented by coarse SHA-256 tokens.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROLE_NAMES = ("api", "worker", "fix-blob-ownership")
ROLE_FIELDS = (
    "effective_profile",
    "embedding_dimension",
    "model_id",
    "preprocessing_id",
    "image_digest",
    "loaded_weight_hashes",
    "auth_enabled",
    "source_git_sha",
)
STORAGE_FIELDS = ("volume_ids", "network_ids", "compose_project", "blob_namespace")

# These are the accepted observation methods from the snapshot contract.  The
# database paths remain here for documentation, but are intentionally excluded
# from the general provenance rung below and checked by their own rungs.
OBSERVATION_METHODS: dict[str, frozenset[str]] = {
    "observations[*].effective_profile": frozenset({"runtime_probe"}),
    "observations[*].embedding_dimension": frozenset({"runtime_probe"}),
    "observations[*].model_id": frozenset({"runtime_probe"}),
    "observations[*].preprocessing_id": frozenset({"runtime_probe"}),
    "observations[*].image_digest": frozenset({"runtime_resolved_digest"}),
    "observations[*].loaded_weight_hashes": frozenset({"runtime_loaded_artifact"}),
    "observations[*].auth_enabled": frozenset({"runtime_auth_probe"}),
    "observations[*].source_git_sha": frozenset({"binary_identity"}),
    "database.identity": frozenset({"database_catalog"}),
    "database.server_version": frozenset({"database_catalog"}),
    "database.extension_versions": frozenset({"database_catalog"}),
    "database.vector_column_inventory": frozenset({"database_catalog"}),
    "storage.volume_ids": frozenset({"storage_inspection"}),
    "storage.network_ids": frozenset({"storage_inspection"}),
    "storage.compose_project": frozenset({"storage_inspection"}),
    "storage.blob_namespace": frozenset({"storage_inspection"}),
    "description_adapter.model_id": frozenset({"description_probe"}),
    "description_adapter.model_revision": frozenset({"description_probe"}),
    "description_adapter.serving_profile": frozenset({"description_probe"}),
    "description_adapter.is_stub": frozenset({"description_probe"}),
    "captured_at": frozenset({"collector_clock"}),
    "tenant_id": frozenset({"request_context"}),
}

_SECRET_MARKER = re.compile(r"REPLACE_ME[_A-Z0-9]*")

_INCOMPLETE_REASON_CODES = frozenset(
    {
        "missing_loaded_weight_hashes",
        "observation_provenance_declared",
        "database_identity_version_unobserved",
        "vector_inventory_incomplete",
    }
)


def _coarse_space_token(value: str) -> str:
    # WHY: keep the canonical first-eight SHA-256 redaction from health.py:383
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _uri_has_password(value: str) -> bool:
    """Return whether a URI string has non-empty userinfo password data."""

    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return False
    if not parsed.scheme or not parsed.netloc or "@" not in parsed.netloc:
        return False
    userinfo = parsed.netloc.rsplit("@", 1)[0]
    if ":" not in userinfo:
        return False
    return bool(userinfo.rsplit(":", 1)[1])


def _is_secret_shaped_string(value: str) -> bool:
    return bool(_SECRET_MARKER.search(value)) or _uri_has_password(value)


def _contains_secret_shaped(value: Any) -> bool:
    """Inspect input values using only the documented secret-shape rules."""

    if isinstance(value, Mapping):
        return any(_contains_secret_shaped(key) or _contains_secret_shaped(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_secret_shaped(item) for item in value)
    return isinstance(value, str) and _is_secret_shaped_string(value)


def _redact_value(value: Any) -> Any:
    """Copy JSON-like values while removing secret-shaped strings."""

    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            redacted_key = "[redacted-key]" if isinstance(key, str) and _is_secret_shaped_string(key) else key
            redacted[redacted_key] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_redact_value(item) for item in value]
    if isinstance(value, str) and _is_secret_shaped_string(value):
        return "[redacted-secret]"
    return value


def _redacted_field(field: Any, raw_value: Any) -> dict[str, Any]:
    result = _redact_value(field)
    if not isinstance(result, dict):
        result = {}
    result["value"] = _coarse_space_token(str(raw_value))
    return result


def _build_report(
    snapshot: Mapping[str, Any],
    freshness_policy: Mapping[str, Any],
    isolation_policy: Mapping[str, Any],
    now: Any,
) -> dict[str, Any]:
    """Build the report before any validation rung can refuse the input."""

    report = {
        "snapshot": _redact_value(snapshot),
        "freshness_policy": _redact_value(freshness_policy),
        "isolation_policy": _redact_value(isolation_policy),
        "now": _redact_value(now),
    }
    redacted_snapshot = report["snapshot"]
    if not isinstance(redacted_snapshot, dict):
        return report

    tenant_field = snapshot.get("tenant_id")
    if isinstance(tenant_field, Mapping) and "value" in tenant_field:
        redacted_snapshot["tenant_id"] = _redacted_field(tenant_field, tenant_field["value"])

    raw_observations = snapshot.get("observations")
    redacted_observations = redacted_snapshot.get("observations")
    if isinstance(raw_observations, list) and isinstance(redacted_observations, list):
        for index, raw_record in enumerate(raw_observations):
            if not isinstance(raw_record, Mapping) or index >= len(redacted_observations):
                continue
            redacted_record = redacted_observations[index]
            model_field = raw_record.get("model_id")
            if isinstance(redacted_record, dict) and isinstance(model_field, Mapping) and "value" in model_field:
                redacted_record["model_id"] = _redacted_field(model_field, model_field["value"])
    return report


def _outcome(reason_code: str, report: Mapping[str, Any]) -> dict[str, Any]:
    if reason_code == "ready":
        status, exit_code = "ready", 0
        reason = "ready: snapshot satisfies the FIR development-runtime contract"
    elif reason_code in _INCOMPLETE_REASON_CODES:
        status, exit_code = "incomplete", 1
        reason = f"{reason_code}: required runtime evidence is incomplete"
    else:
        status, exit_code = "invalid", 2
        reason = f"{reason_code}: snapshot violates the FIR development-runtime contract"
    return {
        "status": status,
        "exit_code": exit_code,
        "reason_code": reason_code,
        "reason": reason,
        "report": report,
    }


def _roles(snapshot: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    by_name = {record["role"]: record for record in snapshot["observations"]}
    return tuple(by_name[name] for name in ROLE_NAMES)


def _field(record: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    return record[field_name]


def _model_id_is_parseable(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    pieces = value.rsplit("@", 1)
    if len(pieces) != 2 or not pieces[0]:
        return False
    suffix_parts = pieces[1].split("/")
    return len(suffix_parts) == 3 and all(suffix_parts)


def _flatten_policy_values(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _flatten_policy_values(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _flatten_policy_values(item)
    else:
        yield value


def _observed_resource_values(snapshot: Mapping[str, Any]) -> Iterable[Any]:
    storage = snapshot["storage"]
    for field_name in STORAGE_FIELDS:
        value = storage[field_name]["value"]
        if isinstance(value, (list, tuple, set, frozenset)):
            yield from value
        else:
            yield value
    identity = snapshot["database"]["identity"]
    yield identity["database_name"]["value"]
    yield identity["role"]["value"]


def _resource_is_forbidden(value: Any, forbidden_values: Iterable[Any]) -> bool:
    return any(value == forbidden for forbidden in forbidden_values)


def _non_database_provenance_is_declared(
    snapshot: Mapping[str, Any], roles: tuple[Mapping[str, Any], ...]
) -> bool:
    for record in roles:
        for field_name in ROLE_FIELDS:
            path = f"observations[*].{field_name}"
            if _field(record, field_name).get("provenance") not in OBSERVATION_METHODS[path]:
                return True

    for field_name in ("captured_at", "tenant_id"):
        if snapshot[field_name].get("provenance") not in OBSERVATION_METHODS[field_name]:
            return True

    for field_name in STORAGE_FIELDS:
        path = f"storage.{field_name}"
        if snapshot["storage"][field_name].get("provenance") not in OBSERVATION_METHODS[path]:
            return True

    for field_name in ("model_id", "model_revision", "serving_profile", "is_stub"):
        path = f"description_adapter.{field_name}"
        if snapshot["description_adapter"][field_name].get("provenance") not in OBSERVATION_METHODS[path]:
            return True
    return False


def _database_identity_or_version_is_unobserved(snapshot: Mapping[str, Any]) -> bool:
    identity = snapshot["database"]["identity"]
    for field_name in ("database_name", "role"):
        if identity[field_name].get("provenance") != "database_catalog":
            return True
    for field_name in ("server_version", "extension_versions"):
        if snapshot["database"][field_name].get("provenance") != "database_catalog":
            return True
    return False


def _vector_inventory_is_incomplete(snapshot: Mapping[str, Any]) -> bool:
    inventory_field = snapshot["database"]["vector_column_inventory"]
    if inventory_field.get("provenance") != "database_catalog":
        return True
    inventory = inventory_field["value"]
    if not isinstance(inventory, (list, tuple)):
        return True
    for item in inventory:
        if not isinstance(item, Mapping):
            return True
        if item.get("provenance") != "database_catalog" or item.get("dimension") is None:
            return True
    return False


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def validate_snapshot(
    snapshot: Mapping[str, Any],
    *,
    freshness_policy: Mapping[str, Any],
    isolation_policy: Mapping[str, Any],
    now: Any,
) -> Mapping[str, Any]:
    """Validate a snapshot and return status, reason, and a redacted report."""

    report = _build_report(snapshot, freshness_policy, isolation_policy, now)

    # Rung 1: only the documented marker family and URI userinfo passwords
    # are secret-shaped; ordinary hashes, image digests, and URLs are allowed.
    if _contains_secret_shaped(snapshot):
        return _outcome("secret_shaped_input", report)

    roles = _roles(snapshot)

    # Rung 2: parse each observed model ID before comparing any cross-role data.
    if any(not _model_id_is_parseable(_field(record, "model_id")["value"]) for record in roles):
        return _outcome("unparseable_model_id", report)

    # Rung 3: strict freshness boundary; exactly max_age_seconds is fresh.
    captured_at = _parse_timestamp(snapshot["captured_at"]["value"])
    current_time = _parse_timestamp(now)
    if current_time - captured_at > timedelta(seconds=freshness_policy["max_age_seconds"]):
        return _outcome("stale_snapshot", report)

    # Rung 4: tenant isolation is exact and policy-driven.
    if snapshot["tenant_id"]["value"] != isolation_policy["required_tenant_id"]:
        return _outcome("shared_default_tenant", report)

    # Rung 5: flatten every policy category, including categories added later.
    forbidden_values = tuple(_flatten_policy_values(isolation_policy["forbidden_resource_ids"]))
    if any(_resource_is_forbidden(value, forbidden_values) for value in _observed_resource_values(snapshot)):
        return _outcome("forbidden_resource_id", report)

    # Rungs 6-9: invalid-tier checks intentionally read values only.
    if any(_field(record, "auth_enabled")["value"] is False for record in roles):
        return _outcome("auth_disabled", report)
    if snapshot["description_adapter"]["is_stub"]["value"] is True:
        return _outcome("description_adapter_stub_or_seeded", report)

    image_digests = {_field(record, "image_digest")["value"] for record in roles}
    if len(image_digests) != 1:
        return _outcome("role_image_digest_mismatch", report)

    dimensions = {_field(record, "embedding_dimension")["value"] for record in roles}
    if len(dimensions) != 1:
        return _outcome("role_embedding_dimension_mismatch", report)
    agreed_dimension = next(iter(dimensions))

    # Rung 10: compare opaque full model IDs and preprocessing IDs.
    model_ids = {_field(record, "model_id")["value"] for record in roles}
    preprocessing_ids = {_field(record, "preprocessing_id")["value"] for record in roles}
    if len(model_ids) != 1 or len(preprocessing_ids) != 1:
        return _outcome("model_contract_mismatch", report)

    # Rung 11: NULL dimensions are not mismatches; discovered non-NULL values
    # must agree with the runtime role dimension.
    inventory = snapshot["database"]["vector_column_inventory"]["value"]
    if any(item.get("dimension") is not None and item["dimension"] != agreed_dimension for item in inventory):
        return _outcome("database_dimension_mismatch", report)

    # Rung 12: an empty mapping means the runtime did not expose loaded hashes.
    if any(
        isinstance(_field(record, "loaded_weight_hashes")["value"], Mapping)
        and not _field(record, "loaded_weight_hashes")["value"]
        for record in roles
    ):
        return _outcome("missing_loaded_weight_hashes", report)

    # Rung 13 intentionally excludes every database.* wrapper.  A declared
    # database observation is classified by the next two database-specific
    # rungs, not by this general check.
    if _non_database_provenance_is_declared(snapshot, roles):
        return _outcome("observation_provenance_declared", report)

    # Rung 14: database identity and version facts require catalog evidence.
    if _database_identity_or_version_is_unobserved(snapshot):
        return _outcome("database_identity_version_unobserved", report)

    # Rung 15: vector discovery is an open superset, including element-level
    # provenance and NULL dimensions.
    if _vector_inventory_is_incomplete(snapshot):
        return _outcome("vector_inventory_incomplete", report)

    return _outcome("ready", report)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--freshness-policy", type=Path, required=True)
    parser.add_argument("--isolation-policy", type=Path, required=True)
    parser.add_argument("--now", required=True)
    args = parser.parse_args(argv)

    snapshot = _load_json(args.snapshot)
    freshness_policy = _load_json(args.freshness_policy)
    isolation_policy = _load_json(args.isolation_policy)
    result = validate_snapshot(
        snapshot,
        freshness_policy=freshness_policy,
        isolation_policy=isolation_policy,
        now=args.now,
    )
    print(json.dumps(result, sort_keys=True))
    print(result["reason"], file=sys.stderr)
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
