"""Validate an already-redacted FIR development-runtime snapshot.

The validator is deliberately offline and stdlib-only.  It consumes the
observations collected by the runtime, applies the supplied freshness and
isolation policies, and returns a machine-readable readiness result with one
of the stable ``ready``, ``incomplete``, or ``invalid`` statuses.

The checks have a fixed precedence.  Structural validation runs before the
contract rungs, followed by secret-shape and model-id parsing, freshness,
tenant isolation, runtime contract, database dimensions, model assets,
provenance, and persisted-store evidence.  A report is built before refusal
and replaces secret-shaped strings; role model IDs and the tenant ID are
represented by coarse SHA-256 tokens.  Keep this order stable:
``schema -> secret shape -> model-id parse -> freshness -> tenant ->
forbidden resources -> auth -> adapter -> image -> dimension -> model
contract -> database dimension -> weight hashes -> provenance -> database
identity -> vector inventory -> store state``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
DATABASE_BASE_FIELDS = (
    "identity",
    "server_version",
    "extension_versions",
    "vector_column_inventory",
)
DATABASE_EVIDENCE_FIELDS = ("store_state", "embedding_provenance")

EXPECTED_VECTOR_COLUMNS = frozenset(
    {
        "public.media_identities.embedding",
        "public.identity_cluster_representatives.embedding",
        "public.mv_identity_cluster_centroids.centroid",
    }
)
_VECTOR_SAMPLE_NAMES = ("representative_vector", "centroid")

EXPECTED_MODEL_CONTRACT: dict[str, Any] = {
    "effective_profile": "face_pipeline",
    "embedding_dimension": 128,
    "model_name_prefix": "opencv-sface+",
    "model_suffix": ("128d", "l2", "cosine"),
    "preprocessing_id": "sface-align-v1",
}

# Source of truth: recognition/infrastructure/face_pipeline/provenance.py:71.
EXPECTED_MODEL_ASSET_HASHES = {
    "yunet": "sha256:ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
    "sface": "sha256:0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
}

_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "captured_at",
        "tenant_id",
        "observations",
        "database",
        "storage",
        "description_adapter",
    }
)
_ROLE_WRAPPER_KEYS = frozenset({"value", "provenance"})
_INVENTORY_WRAPPER_KEYS = frozenset({"value", "provenance", "discovery_complete"})
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNRESOLVED_MODEL_MARKERS = ("${", "PENDING_OPERATOR_FETCH")

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
    "database.store_state": frozenset({"database_catalog"}),
    "database.embedding_provenance": frozenset({"database_catalog"}),
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
_CREDENTIAL_KEY = re.compile(
    r"^(?:password|passwd|pwd|secret|token|api[-_]?key|access[-_]?key)$",
    re.IGNORECASE,
)
_CREDENTIAL_KEY_VALUE = re.compile(
    r"(?:^|\s)(?:password|passwd|pwd|secret|token|api[-_]?key|access[-_]?key)"
    r"\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|(?!(?:[A-Za-z_][A-Za-z0-9_-]*)\s*=)[^\s]+)",
    re.IGNORECASE,
)
_BEARER_TOKEN_PREFIX = re.compile(
    r"^\s*(?:authorization\s*:\s*)?(?:bearer|basic|token)\s+\S",
    re.IGNORECASE,
)
_MAX_CLOCK_SKEW = timedelta(seconds=60)
_ISOLATION_RESOURCE_CATEGORIES = frozenset(
    {
        "volumes",
        "networks",
        "compose_projects",
        "database_names",
        "database_roles",
        "blob_namespaces",
    }
)

_INCOMPLETE_REASON_CODES = frozenset(
    {
        "missing_loaded_weight_hashes",
        "observation_provenance_declared",
        "database_identity_version_unobserved",
        "vector_inventory_incomplete",
        "incomplete_loaded_weight_hashes",
        "vector_inventory_discovery_incomplete",
        "vector_column_coverage_incomplete",
        "vector_column_identity_invalid",
        "fir_store_state_unobserved",
        "embedding_provenance_unobserved",
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


def _credential_value_is_nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip().strip("\"'").strip())
    if isinstance(value, Mapping):
        if "value" in value:
            return _credential_value_is_nonempty(value["value"])
        return bool(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_credential_value_is_nonempty(item) for item in value)
    return value is not None and bool(value)


def _keyword_value_has_credential(value: str) -> bool:
    return any(_credential_value_is_nonempty(match.group("value")) for match in _CREDENTIAL_KEY_VALUE.finditer(value))


def _is_secret_shaped_string(value: str) -> bool:
    return (
        bool(_SECRET_MARKER.search(value))
        or _uri_has_password(value)
        or _keyword_value_has_credential(value)
        or bool(_BEARER_TOKEN_PREFIX.search(value))
    )


def _contains_secret_shaped(value: Any) -> bool:
    """Inspect input values for credential-bearing shapes before any validation rung."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and _CREDENTIAL_KEY.fullmatch(key.strip()) and _credential_value_is_nonempty(item):
                return True
            if _contains_secret_shaped(key) or _contains_secret_shaped(item):
                return True
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_secret_shaped(item) for item in value)
    return isinstance(value, str) and _is_secret_shaped_string(value)


def _redact_credential_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if key == "value" and _credential_value_is_nonempty(item):
                redacted[key] = "[redacted-secret]"
            else:
                redacted[key] = _redact_value(item)
        return redacted
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redact_credential_value(item) for item in value]
    return "[redacted-secret]"


def _redact_value(value: Any) -> Any:
    """Copy JSON-like values while removing secret-shaped strings."""

    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            redacted_key = "[redacted-key]" if isinstance(key, str) and _is_secret_shaped_string(key) else key
            if isinstance(key, str) and _CREDENTIAL_KEY.fullmatch(key.strip()) and _credential_value_is_nonempty(item):
                redacted[redacted_key] = _redact_credential_value(item)
            else:
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
    snapshot: Any,
    freshness_policy: Any,
    isolation_policy: Any,
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

    if not isinstance(snapshot, Mapping):
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
    observations = snapshot.get("observations")
    if not isinstance(observations, list):
        raise TypeError("snapshot observations must be a list")
    by_name: dict[str, Mapping[str, Any]] = {}
    for record in observations:
        if not isinstance(record, Mapping) or not isinstance(record.get("role"), str):
            raise TypeError("snapshot role observation must be a mapping with a string role")
        role = record["role"]
        if role in by_name:
            raise ValueError(f"duplicate role observation: {role}")
        by_name[role] = record
    if set(by_name) != set(ROLE_NAMES):
        raise ValueError("snapshot role observations do not match the required role set")
    return tuple(by_name[name] for name in ROLE_NAMES)


def _field(record: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    value = record[field_name]
    if not isinstance(value, Mapping):
        raise TypeError(f"observation field {field_name!r} is not a mapping wrapper")
    return value


def _model_id_is_parseable(value: Any) -> bool:
    return _parse_model_id(value) is not None


def _parse_model_id(value: Any) -> tuple[str, tuple[str, str, str]] | None:
    if not isinstance(value, str):
        return None
    pieces = value.rsplit("@", 1)
    if len(pieces) != 2 or not pieces[0]:
        return None
    suffix_parts = pieces[1].split("/")
    if len(suffix_parts) != 3 or not all(suffix_parts):
        return None
    return pieces[0], (suffix_parts[0], suffix_parts[1], suffix_parts[2])


def _flatten_policy_values(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _flatten_policy_values(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _flatten_policy_values(item)
    else:
        yield value


def _observed_resource_values(snapshot: Mapping[str, Any]) -> Iterable[tuple[str, Any]]:
    storage = snapshot["storage"]
    storage_categories = {
        "volume_ids": "volumes",
        "network_ids": "networks",
        "compose_project": "compose_projects",
        "blob_namespace": "blob_namespaces",
    }
    for field_name in STORAGE_FIELDS:
        value = storage[field_name]["value"]
        category = storage_categories[field_name]
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                yield category, item
        else:
            yield category, value
    identity = snapshot["database"]["identity"]
    yield "database_names", identity["database_name"]["value"]
    yield "database_roles", identity["role"]["value"]


def _resource_is_forbidden(
    value: Any,
    forbidden_values: Iterable[Any],
    *,
    allow_compose_prefix: bool = True,
) -> bool:
    """Match strip/casefold-normalized IDs, including Compose volume suffixes when enabled."""

    for forbidden in forbidden_values:
        if isinstance(value, str) and isinstance(forbidden, str):
            normalized_value = value.strip().casefold()
            normalized_forbidden = forbidden.strip().casefold()
            if normalized_value == normalized_forbidden:
                return True
            if allow_compose_prefix and normalized_forbidden and normalized_value.endswith(
                f"_{normalized_forbidden}"
            ):
                return True
        elif value == forbidden:
            return True
    return False


def _non_database_provenance_is_declared(snapshot: Mapping[str, Any], roles: tuple[Mapping[str, Any], ...]) -> bool:
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


def _is_wrapper(value: Any, expected_keys: frozenset[str] = _ROLE_WRAPPER_KEYS) -> bool:
    return isinstance(value, Mapping) and set(value) == expected_keys


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and value > 0


def _is_nonempty_identity(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return bool(value) and all(isinstance(item, str) and bool(item.strip()) for item in value)
    return False


def _validate_isolation_policy_shape(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return "malformed_isolation_policy"
    for category in _ISOLATION_RESOURCE_CATEGORIES:
        category_values = value.get(category)
        if not isinstance(category_values, (list, tuple)) or not category_values:
            return "malformed_isolation_policy"
    return None


def _validate_required_identity_values(snapshot: Mapping[str, Any]) -> str | None:
    database = snapshot["database"]
    identity = database["identity"]
    if any(not _is_nonempty_identity(identity[field_name]["value"]) for field_name in ("database_name", "role")):
        return "database_identity_version_unobserved"
    if not _is_nonempty_identity(database["server_version"]["value"]):
        return "database_identity_version_unobserved"

    extension_versions = database["extension_versions"]["value"]
    if (
        not isinstance(extension_versions, Mapping)
        or not extension_versions
        or any(not _is_nonempty_identity(value) for value in extension_versions.values())
    ):
        return "database_identity_version_unobserved"

    storage = snapshot["storage"]
    if any(not _is_nonempty_identity(storage[field_name]["value"]) for field_name in STORAGE_FIELDS):
        return "observation_provenance_declared"

    roles = _roles(snapshot)
    if any(not _is_nonempty_identity(_field(record, "source_git_sha")["value"]) for record in roles):
        return "observation_provenance_declared"
    return None


def _validate_schema(
    snapshot: Any,
    *,
    freshness_policy: Any,
    isolation_policy: Any,
    now: Any,
) -> str | None:
    """Validate the JSON boundary before any contract rung reads a field."""

    if not isinstance(snapshot, Mapping):
        return "snapshot_schema_invalid"

    schema_version = snapshot.get("schema_version")
    if schema_version is None or isinstance(schema_version, bool) or not isinstance(schema_version, int):
        return "snapshot_schema_invalid"
    if schema_version != 1:
        return "unsupported_schema_version"
    if set(snapshot) != _SNAPSHOT_FIELDS:
        return "snapshot_schema_invalid"

    observations = snapshot.get("observations")
    if not isinstance(observations, list) or len(observations) != len(ROLE_NAMES):
        return "snapshot_schema_invalid"
    observed_roles: list[str] = []
    expected_role_keys = {"role", *ROLE_FIELDS}
    for record in observations:
        if not isinstance(record, Mapping):
            return "snapshot_schema_invalid"
        role = record.get("role")
        if not isinstance(role, str) or role not in ROLE_NAMES:
            return "unknown_role_observation"
        if role in observed_roles:
            return "duplicate_role_observation"
        observed_roles.append(role)
        if set(record) != expected_role_keys:
            return "snapshot_schema_invalid"
        if any(not _is_wrapper(record[field_name]) for field_name in ROLE_FIELDS):
            return "malformed_observation_wrapper"
    if set(observed_roles) != set(ROLE_NAMES):
        return "unknown_role_observation"

    for field_name in ("captured_at", "tenant_id"):
        if not _is_wrapper(snapshot.get(field_name)):
            return "malformed_observation_wrapper"

    database = snapshot.get("database")
    if not isinstance(database, Mapping):
        return "snapshot_schema_invalid"
    database_keys = set(database)
    allowed_database_keys = set(DATABASE_BASE_FIELDS) | set(DATABASE_EVIDENCE_FIELDS)
    if not set(DATABASE_BASE_FIELDS).issubset(database_keys) or not database_keys <= allowed_database_keys:
        return "snapshot_schema_invalid"
    identity = database.get("identity")
    if not isinstance(identity, Mapping) or set(identity) != {"database_name", "role"}:
        return "snapshot_schema_invalid"
    if any(not _is_wrapper(identity[field_name]) for field_name in ("database_name", "role")):
        return "malformed_observation_wrapper"
    for field_name in ("server_version", "extension_versions"):
        if not _is_wrapper(database.get(field_name)):
            return "malformed_observation_wrapper"
    inventory = database.get("vector_column_inventory")
    if not (_is_wrapper(inventory) or _is_wrapper(inventory, _INVENTORY_WRAPPER_KEYS)):
        return "malformed_observation_wrapper"
    for field_name in DATABASE_EVIDENCE_FIELDS:
        if field_name in database and not _is_wrapper(database[field_name]):
            return "malformed_observation_wrapper"

    storage = snapshot.get("storage")
    if not isinstance(storage, Mapping) or set(storage) != set(STORAGE_FIELDS):
        return "snapshot_schema_invalid"
    if any(not _is_wrapper(storage[field_name]) for field_name in STORAGE_FIELDS):
        return "malformed_observation_wrapper"

    description_adapter = snapshot.get("description_adapter")
    description_fields = ("model_id", "model_revision", "serving_profile", "is_stub")
    if not isinstance(description_adapter, Mapping) or set(description_adapter) != set(description_fields):
        return "snapshot_schema_invalid"
    if any(not _is_wrapper(description_adapter[field_name]) for field_name in description_fields):
        return "malformed_observation_wrapper"

    if not isinstance(freshness_policy, Mapping) or not _is_positive_number(freshness_policy.get("max_age_seconds")):
        return "malformed_policy_input"
    if (
        not isinstance(isolation_policy, Mapping)
        or "required_tenant_id" not in isolation_policy
    ):
        return "malformed_policy_input"
    isolation_reason = _validate_isolation_policy_shape(isolation_policy.get("forbidden_resource_ids"))
    if isolation_reason is not None:
        return isolation_reason

    try:
        _parse_timestamp(snapshot["captured_at"]["value"])
        _parse_timestamp(now)
    except (TypeError, ValueError, OverflowError):
        return "malformed_timestamp"
    return None


def _validate_secret_and_model_ids(snapshot: Mapping[str, Any]) -> str | None:
    if _contains_secret_shaped(snapshot):
        return "secret_shaped_input"
    roles = _roles(snapshot)
    if any(not _model_id_is_parseable(_field(record, "model_id")["value"]) for record in roles):
        return "unparseable_model_id"
    return None


def _validate_freshness_and_isolation(
    snapshot: Mapping[str, Any],
    *,
    freshness_policy: Mapping[str, Any],
    isolation_policy: Mapping[str, Any],
    now: Any,
) -> str | None:
    try:
        captured_at = _parse_timestamp(snapshot["captured_at"]["value"])
        current_time = _parse_timestamp(now)
    except (TypeError, ValueError, OverflowError):
        return "malformed_timestamp"
    age = current_time - captured_at
    if age < -_MAX_CLOCK_SKEW:
        return "future_snapshot"
    if age > timedelta(seconds=freshness_policy["max_age_seconds"]):
        return "stale_snapshot"
    if snapshot["tenant_id"]["value"] != isolation_policy["required_tenant_id"]:
        return "shared_default_tenant"
    # Policy contract: string IDs are compared after strip/casefold normalization. Collectors may emit
    # Docker Compose volume IDs as ``<project>_<declared-name>``; volume policy IDs match that suffix.
    forbidden_resources = isolation_policy["forbidden_resource_ids"]
    for category, value in _observed_resource_values(snapshot):
        forbidden_values = tuple(_flatten_policy_values(forbidden_resources[category]))
        if _resource_is_forbidden(value, forbidden_values, allow_compose_prefix=category == "volumes"):
            return "forbidden_resource_id"
    return None


def _model_id_has_unresolved_space_marker(value: str) -> bool:
    if any(marker in value for marker in _UNRESOLVED_MODEL_MARKERS):
        return True
    parsed = _parse_model_id(value)
    return parsed is not None and parsed[0] == EXPECTED_MODEL_CONTRACT["model_name_prefix"]


def _validate_runtime_contract(snapshot: Mapping[str, Any]) -> str | None:
    roles = _roles(snapshot)

    if any(_field(record, "auth_enabled")["value"] is not True for record in roles):
        return "auth_disabled"

    description_adapter = snapshot["description_adapter"]
    if description_adapter["is_stub"]["value"] is not False:
        return "description_adapter_stub_or_seeded"
    for field_name in ("model_id", "model_revision", "serving_profile"):
        value = description_adapter[field_name]["value"]
        if not isinstance(value, str) or not value.strip():
            return "description_adapter_unverified_model"
    if description_adapter["serving_profile"]["value"] != "remote_self_hosted":
        return "description_adapter_unverified_model"

    image_digests = [_field(record, "image_digest")["value"] for record in roles]
    if any(value != image_digests[0] for value in image_digests[1:]):
        return "role_image_digest_mismatch"
    if any(not isinstance(value, str) or _SHA256_DIGEST.fullmatch(value) is None for value in image_digests):
        return "unpinned_image_digest"

    dimensions = [_field(record, "embedding_dimension")["value"] for record in roles]
    if any(value != dimensions[0] for value in dimensions[1:]):
        return "role_embedding_dimension_mismatch"
    agreed_dimension = dimensions[0]

    expected_profile = EXPECTED_MODEL_CONTRACT["effective_profile"]
    if any(_field(record, "effective_profile")["value"] != expected_profile for record in roles):
        return "unexpected_face_pipeline_profile"

    model_ids = [_field(record, "model_id")["value"] for record in roles]
    preprocessing_ids = [_field(record, "preprocessing_id")["value"] for record in roles]
    if any(_model_id_has_unresolved_space_marker(value) for value in model_ids):
        return "unresolved_model_space_marker"
    if any(value != model_ids[0] for value in model_ids[1:]) or any(
        value != preprocessing_ids[0] for value in preprocessing_ids[1:]
    ):
        return "model_contract_mismatch"

    if agreed_dimension != EXPECTED_MODEL_CONTRACT["embedding_dimension"]:
        return "model_space_contract_mismatch"

    expected_suffix = EXPECTED_MODEL_CONTRACT["model_suffix"]
    expected_prefix = EXPECTED_MODEL_CONTRACT["model_name_prefix"]
    for model_id in model_ids:
        parsed = _parse_model_id(model_id)
        if parsed is None:
            return "unparseable_model_id"
        name, suffix = parsed
        if not name.startswith(expected_prefix) or suffix != expected_suffix:
            return "model_space_contract_mismatch"
    if preprocessing_ids[0] != EXPECTED_MODEL_CONTRACT["preprocessing_id"]:
        return "model_space_contract_mismatch"
    return None


def _validate_database_inventory(snapshot: Mapping[str, Any]) -> str | None:
    roles = _roles(snapshot)
    dimensions = [_field(record, "embedding_dimension")["value"] for record in roles]
    agreed_dimension = dimensions[0]
    inventory = snapshot["database"]["vector_column_inventory"]["value"]
    if isinstance(inventory, (list, tuple)):
        for item in inventory:
            if not isinstance(item, Mapping):
                continue
            dimension = item.get("dimension")
            if isinstance(dimension, int) and not isinstance(dimension, bool) and dimension != agreed_dimension:
                return "database_dimension_mismatch"
    return None


def _validate_model_assets(snapshot: Mapping[str, Any]) -> str | None:
    roles = _roles(snapshot)
    hash_values = [_field(record, "loaded_weight_hashes")["value"] for record in roles]
    if any(isinstance(value, Mapping) and not value for value in hash_values):
        return "missing_loaded_weight_hashes"
    for value in hash_values:
        if not isinstance(value, Mapping) or set(value) != set(EXPECTED_MODEL_ASSET_HASHES):
            return "incomplete_loaded_weight_hashes"
        if any(not isinstance(digest, str) or _SHA256_DIGEST.fullmatch(digest) is None for digest in value.values()):
            return "malformed_loaded_weight_hash"
    first_mapping = hash_values[0]
    if any(value != first_mapping for value in hash_values[1:]):
        return "role_loaded_weight_hash_mismatch"
    if first_mapping != EXPECTED_MODEL_ASSET_HASHES:
        return "model_asset_hash_unexpected"
    return None


def _vector_inventory_is_incomplete(snapshot: Mapping[str, Any]) -> str | None:
    inventory_field = snapshot["database"]["vector_column_inventory"]
    if inventory_field.get("provenance") != "database_catalog":
        return "vector_inventory_incomplete"
    inventory = inventory_field.get("value")
    if not isinstance(inventory, (list, tuple)):
        return "vector_inventory_incomplete"
    for item in inventory:
        if not isinstance(item, Mapping):
            return "vector_inventory_incomplete"
        if item.get("provenance") != "database_catalog" or item.get("dimension") is None:
            return "vector_inventory_incomplete"

    if inventory_field.get("discovery_complete") is not True:
        return "vector_inventory_discovery_incomplete"

    identities: set[str] = set()
    for item in inventory:
        schema = item.get("schema")
        table = item.get("table")
        column = item.get("column")
        dimension = item.get("dimension")
        if (
            not isinstance(schema, str)
            or not schema.strip()
            or not isinstance(table, str)
            or not table.strip()
            or not isinstance(column, str)
            or not column.strip()
            or not isinstance(dimension, int)
            or isinstance(dimension, bool)
        ):
            return "vector_column_identity_invalid"
        identities.add(f"{schema}.{table}.{column}")
    if not EXPECTED_VECTOR_COLUMNS.issubset(identities):
        return "vector_column_coverage_incomplete"
    return None


def _validate_provenance(snapshot: Mapping[str, Any]) -> str | None:
    roles = _roles(snapshot)
    if _non_database_provenance_is_declared(snapshot, roles):
        return "observation_provenance_declared"
    identity_reason = _validate_required_identity_values(snapshot)
    if identity_reason is not None:
        return identity_reason
    if _database_identity_or_version_is_unobserved(snapshot):
        return "database_identity_version_unobserved"
    return _vector_inventory_is_incomplete(snapshot)


def _is_finite_vector(value: Any, expected_dimension: int) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != expected_dimension:
        return False
    return all(
        isinstance(component, (int, float)) and not isinstance(component, bool) and math.isfinite(float(component))
        for component in value
    )


def _validate_store_state(snapshot: Mapping[str, Any]) -> str | None:
    database = snapshot["database"]
    store_state = database.get("store_state")
    if not isinstance(store_state, Mapping) or store_state.get("provenance") != "database_catalog":
        return "fir_store_state_unobserved"
    state = store_state.get("value")
    if state not in {"empty", "enrolled"}:
        return "fir_store_state_unobserved"

    embedding_provenance = database.get("embedding_provenance")
    if (
        not isinstance(embedding_provenance, Mapping)
        or embedding_provenance.get("provenance") != "database_catalog"
        or not isinstance(embedding_provenance.get("value"), Mapping)
    ):
        return "embedding_provenance_unobserved"
    summary = embedding_provenance["value"]
    required_summary_fields = {"row_counts", "model_id", "preprocessing_id", *_VECTOR_SAMPLE_NAMES}
    if not required_summary_fields.issubset(summary):
        return "embedding_provenance_unobserved"

    inventory = database["vector_column_inventory"]["value"]
    if not isinstance(inventory, (list, tuple)):
        return "embedding_provenance_unobserved"
    inventory_identities = {
        f"{item['schema']}.{item['table']}.{item['column']}"
        for item in inventory
        if isinstance(item, Mapping)
        and isinstance(item.get("schema"), str)
        and isinstance(item.get("table"), str)
        and isinstance(item.get("column"), str)
    }
    row_counts = summary["row_counts"]
    if not isinstance(row_counts, Mapping) or set(row_counts) != inventory_identities:
        return "embedding_provenance_unobserved"
    if any(not isinstance(count, int) or isinstance(count, bool) or count < 0 for count in row_counts.values()):
        return "embedding_provenance_unobserved"

    if state == "empty":
        if any(count != 0 for count in row_counts.values()):
            return "fir_store_state_unobserved"
        return None

    if not any(count > 0 for count in row_counts.values()):
        return "fir_store_state_unobserved"

    roles = _roles(snapshot)
    runtime_model_id = _field(roles[0], "model_id")["value"]
    runtime_preprocessing_id = _field(roles[0], "preprocessing_id")["value"]
    if summary["model_id"] != runtime_model_id or summary["preprocessing_id"] != runtime_preprocessing_id:
        return "persisted_model_stamp_mismatch"

    expected_dimension = EXPECTED_MODEL_CONTRACT["embedding_dimension"]
    for sample_name in _VECTOR_SAMPLE_NAMES:
        if not _is_finite_vector(summary[sample_name], expected_dimension):
            return "non_finite_persisted_vector"
    return None


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError("timestamp must be an ISO-8601 string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def validate_snapshot(
    snapshot: Mapping[str, Any],
    *,
    freshness_policy: Mapping[str, Any],
    isolation_policy: Mapping[str, Any],
    now: Any,
) -> Mapping[str, Any]:
    """Validate a snapshot and return status, reason, and a redacted report."""

    report = _build_report(snapshot, freshness_policy, isolation_policy, now)

    reason = _validate_schema(
        snapshot,
        freshness_policy=freshness_policy,
        isolation_policy=isolation_policy,
        now=now,
    )
    if reason is not None:
        return _outcome(reason, report)

    ordered_checks = (
        lambda: _validate_secret_and_model_ids(snapshot),
        lambda: _validate_freshness_and_isolation(
            snapshot,
            freshness_policy=freshness_policy,
            isolation_policy=isolation_policy,
            now=now,
        ),
        lambda: _validate_runtime_contract(snapshot),
        lambda: _validate_database_inventory(snapshot),
        lambda: _validate_model_assets(snapshot),
        lambda: _validate_provenance(snapshot),
        lambda: _validate_store_state(snapshot),
    )
    for check in ordered_checks:
        reason = check()
        if reason is not None:
            return _outcome(reason, report)
    return _outcome("ready", report)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _error_outcome(reason_code: str, reason: str) -> dict[str, Any]:
    return {
        "status": "invalid",
        "exit_code": 2,
        "reason_code": reason_code,
        "reason": f"{reason_code}: {reason}",
        "report": {},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--freshness-policy", type=Path, required=True)
    parser.add_argument("--isolation-policy", type=Path, required=True)
    parser.add_argument("--now", required=True)
    args = parser.parse_args(argv)

    try:
        snapshot = _load_json(args.snapshot)
        freshness_policy = _load_json(args.freshness_policy)
        isolation_policy = _load_json(args.isolation_policy)
        result = validate_snapshot(
            snapshot,
            freshness_policy=freshness_policy,
            isolation_policy=isolation_policy,
            now=args.now,
        )
    except (json.JSONDecodeError, OSError):
        result = _error_outcome("snapshot_unreadable", "unable to read or parse JSON input")
    except Exception:
        result = _error_outcome("validator_internal_error", "validator failed unexpectedly")
    print(json.dumps(result, sort_keys=True))
    print(result["reason"], file=sys.stderr)
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
