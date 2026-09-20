"""RED contract for the offline FIR development-runtime snapshot validator.

This module deliberately describes the validator seam before the validator
exists.  The implementation lane must expose a pure-JSON function with this
shape::

    validate_snapshot(
        snapshot,
        *,
        freshness_policy,
        isolation_policy,
        now,
    ) -> mapping

The returned mapping has ``status``, ``exit_code``, ``reason_code``,
``reason``, and a JSON-serializable ``report``.  The command-line interface
must accept ``--snapshot``, ``--freshness-policy``, ``--isolation-policy``,
and the injectable ``--now`` value, emit the JSON report on stdout, and emit
the exit-reason string on stderr.  Missing implementation is converted into a
targeted pytest failure with the case's pinned ``reason_code``; it must not
surface as an ImportError or as zero collected tests during this RED slice.

Snapshot v1 is a role-keyed, already-redacted JSON document.  The only role
set is ``api``, ``worker``, and ``fix-blob-ownership``.  The validator joins
observations across those roles and the database, storage, and description
adapter boundaries.  It does not re-derive the runtime-owned active model
space, three-way dimensions, or model-asset/hash checks: those remain
authoritative in the runtime and arrive here as observations.

The model-id parser must ``rsplit('@', 1)`` and split only the suffix.  The
name segment is opaque and may contain ``+``, ``/``, and ``.``.  A real SFace
fixture therefore has the shape
``opencv-sface+cv<full-opencv-version>/ort<major.minor>@128d/l2/cosine``;
the version is materialized from installed package metadata so this test does
not fossilize a particular OpenCV or onnxruntime release.  ``stub-detector@test``
is not a parseable model id and must be rejected.

The refuse-vs-redact contract is intentional.  A snapshot carrying the
``REPLACE_ME_DEV_FIR_PG`` secret-shaped sentinel is refused, while the
validator's own report is still redacted.  Redaction assertions cover stdout,
the parsed JSON report, and the exit-reason string.  They are anti-vacuous:
each surface check also requires the positive coarse token for the model id
and tenant id, using the runtime's first-eight-hex-SHA256 convention.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.metadata
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "fir_dev_runtime"
APP_ROOT = Path(__file__).resolve().parents[3]
MODULE_NAME = "scripts.validate_fir_dev_runtime"
NOW = "2026-09-20T12:01:00Z"
DEFAULT_TENANT_SENTINEL = "00000000-0000-7000-8000-000000000000"
SENTINEL = "REPLACE_ME_DEV_FIR_PG"
DSN_PASSWORD = "dsn-password-must-not-appear"

ROLE_SET = ("api", "worker", "fix-blob-ownership")
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
DATABASE_FIELDS = (
    "identity",
    "server_version",
    "extension_versions",
    "vector_column_inventory",
    "store_state",
    "embedding_provenance",
)
STORAGE_FIELDS = ("volume_ids", "network_ids", "compose_project", "blob_namespace")
DESCRIPTION_FIELDS = ("model_id", "model_revision", "serving_profile", "is_stub")
VECTOR_COLUMN_IDENTITIES = {
    "public.media_identities.embedding",
    "public.identity_cluster_representatives.embedding",
    "public.mv_identity_cluster_centroids.centroid",
}


# Pinned RED contract: every case in the dispatch brief has one status, exit
# code, and reason code.  The implementation must not invent a second mapping.
CASE_OUTCOMES: dict[str, tuple[str, int, str]] = {
    "valid_empty_fir_store": ("ready", 0, "ready"),
    "valid_enrolled_fir_store": ("ready", 0, "ready"),
    "freshness_boundary_minus_one": ("ready", 0, "ready"),
    "naive_captured_at_timestamp": ("invalid", 2, "malformed_timestamp"),
    "future_dated_snapshot": ("invalid", 2, "future_snapshot"),
    "api_worker_dimension_mismatch": ("invalid", 2, "role_embedding_dimension_mismatch"),
    "database_dimension_mismatch": ("invalid", 2, "database_dimension_mismatch"),
    "model_id_mismatch": ("invalid", 2, "model_contract_mismatch"),
    "preprocessing_id_mismatch": ("invalid", 2, "model_contract_mismatch"),
    "missing_model_weight_hashes": ("incomplete", 1, "missing_loaded_weight_hashes"),
    "database_identity_version_declared": ("incomplete", 1, "database_identity_version_unobserved"),
    "blank_database_identity": ("incomplete", 1, "database_identity_version_unobserved"),
    "empty_storage_id_list": ("incomplete", 1, "observation_provenance_declared"),
    "stale_snapshot": ("invalid", 2, "stale_snapshot"),
    "auth_disabled": ("invalid", 2, "auth_disabled"),
    "seeded_description_adapter": ("invalid", 2, "description_adapter_stub_or_seeded"),
    "image_digest_mismatch": ("invalid", 2, "role_image_digest_mismatch"),
    "forbidden_storage": ("invalid", 2, "forbidden_resource_id"),
    "compose_prefixed_forbidden_storage": ("invalid", 2, "forbidden_resource_id"),
    "casefolded_forbidden_database": ("invalid", 2, "forbidden_resource_id"),
    "default_tenant": ("invalid", 2, "shared_default_tenant"),
    "all_declared_provenance": ("incomplete", 1, "observation_provenance_declared"),
    "unparseable_model_id": ("invalid", 2, "unparseable_model_id"),
    "fourth_vector_column_undiscovered": ("incomplete", 1, "vector_inventory_incomplete"),
    "all_roles_512d_consistent": ("invalid", 2, "model_space_contract_mismatch"),
    "wrong_face_pipeline_profile": ("invalid", 2, "unexpected_face_pipeline_profile"),
    "foreign_model_space": ("invalid", 2, "model_space_contract_mismatch"),
    "unresolved_space_token": ("invalid", 2, "unresolved_model_space_marker"),
    "partial_model_weight_hashes": ("incomplete", 1, "incomplete_loaded_weight_hashes"),
    "non_hash_weight_value": ("invalid", 2, "malformed_loaded_weight_hash"),
    "divergent_role_weight_hashes": ("invalid", 2, "role_loaded_weight_hash_mismatch"),
    "foreign_model_asset_hash": ("invalid", 2, "model_asset_hash_unexpected"),
    "auth_enabled_null": ("invalid", 2, "auth_disabled"),
    "auth_enabled_string": ("invalid", 2, "auth_disabled"),
    "malformed_observation_wrapper": ("invalid", 2, "malformed_observation_wrapper"),
    "is_stub_null": ("invalid", 2, "description_adapter_stub_or_seeded"),
    "hosted_description_adapter": ("invalid", 2, "description_adapter_unverified_model"),
    "mutable_image_tag": ("invalid", 2, "unpinned_image_digest"),
    "empty_image_digest": ("invalid", 2, "unpinned_image_digest"),
    "empty_vector_inventory": ("incomplete", 1, "vector_column_coverage_incomplete"),
    "omitted_centroid_column": ("incomplete", 1, "vector_column_coverage_incomplete"),
    "invalid_vector_column_identity": ("incomplete", 1, "vector_column_identity_invalid"),
    "incomplete_schema_discovery": ("incomplete", 1, "vector_inventory_discovery_incomplete"),
    "enrolled_store_foreign_model_stamp": ("invalid", 2, "persisted_model_stamp_mismatch"),
    "enrolled_store_non_finite_centroid": ("invalid", 2, "non_finite_persisted_vector"),
    "enrolled_store_missing_centroid_sample": ("incomplete", 1, "embedding_provenance_unobserved"),
    "enrolled_store_missing_provenance_summary": ("incomplete", 1, "embedding_provenance_unobserved"),
    "empty_store_with_rows": ("incomplete", 1, "fir_store_state_unobserved"),
    "fourth_vector_column_nonzero": ("incomplete", 1, "fir_store_state_unobserved"),
    "fourth_vector_column_zero": ("ready", 0, "ready"),
    "duplicate_worker_role": ("invalid", 2, "duplicate_role_observation"),
    "unknown_role_present": ("invalid", 2, "unknown_role_observation"),
    "schema_version_two": ("invalid", 2, "unsupported_schema_version"),
    "missing_storage_section": ("invalid", 2, "snapshot_schema_invalid"),
    "empty_forbidden_resource_policy": ("invalid", 2, "malformed_isolation_policy"),
    "malformed_policy_input": ("invalid", 2, "malformed_policy_input"),
    "malformed_timestamp": ("invalid", 2, "malformed_timestamp"),
    "keyword_value_dsn_secret": ("invalid", 2, "secret_shaped_input"),
    "redaction_secret_input": ("invalid", 2, "secret_shaped_input"),
    "import_purity": ("ready", 0, "import_pure"),
}


# Observation-method contract.  A service/env/compose echo is a declaration,
# even when its spelling matches the intended value.  In particular, the
# effective profile is re-read from RECOGNITION_FACE_PIPELINE_PROFILE on every
# probe and ACX_IMAGE_TAG is mutable, so neither is an observation by itself.
OBSERVATION_METHODS: dict[str, dict[str, object]] = {
    "observations[*].effective_profile": {
        "accepted": {"runtime_probe"},
        "declared_when": "service-reported profile or RECOGNITION_FACE_PIPELINE_PROFILE echo",
    },
    "observations[*].embedding_dimension": {
        "accepted": {"runtime_probe"},
        "declared_when": "settings/env/compose value without a loaded runtime probe",
    },
    "observations[*].model_id": {
        "accepted": {"runtime_probe"},
        "declared_when": "manifest/config value without runtime evidence",
    },
    "observations[*].preprocessing_id": {
        "accepted": {"runtime_probe"},
        "declared_when": "adapter/config label without runtime evidence",
    },
    "observations[*].image_digest": {
        "accepted": {"runtime_resolved_digest"},
        "declared_when": "compose image tag, env, or image label only",
    },
    "observations[*].loaded_weight_hashes": {
        "accepted": {"runtime_loaded_artifact"},
        "declared_when": "manifest/file-name hash or expected hash without loaded bytes",
    },
    "observations[*].auth_enabled": {
        "accepted": {"runtime_auth_probe"},
        "declared_when": "auth setting/env value without an authenticated probe",
    },
    "observations[*].source_git_sha": {
        "accepted": {"binary_identity"},
        "declared_when": "compose metadata or mutable tag only",
    },
    "database.identity": {
        "accepted": {"database_catalog"},
        "declared_when": "DSN, env, or role/database config",
    },
    "database.server_version": {
        "accepted": {"database_catalog"},
        "declared_when": "image/compose/server expectation without a connection query",
    },
    "database.extension_versions": {
        "accepted": {"database_catalog"},
        "declared_when": "migration or image expectation without a catalog query",
    },
    "database.vector_column_inventory": {
        "accepted": {"database_catalog"},
        "declared_when": "hardcoded three-column list rather than schema discovery",
    },
    "database.store_state": {
        "accepted": {"database_catalog"},
        "declared_when": "fixture or migration state without a catalog query",
    },
    "database.embedding_provenance": {
        "accepted": {"database_catalog"},
        "declared_when": "expected row counts or model stamps without persisted-row evidence",
    },
    "storage.volume_ids": {
        "accepted": {"storage_inspection"},
        "declared_when": "compose volume declaration only",
    },
    "storage.network_ids": {
        "accepted": {"storage_inspection"},
        "declared_when": "compose network declaration only",
    },
    "storage.compose_project": {
        "accepted": {"storage_inspection"},
        "declared_when": "COMPOSE_PROJECT_NAME/ACX_ENV only",
    },
    "storage.blob_namespace": {
        "accepted": {"storage_inspection"},
        "declared_when": "volume or env name without runtime namespace inspection",
    },
    "description_adapter.model_id": {
        "accepted": {"description_probe"},
        "declared_when": "configured/seeded model name only",
    },
    "description_adapter.model_revision": {
        "accepted": {"description_probe"},
        "declared_when": "configured revision without serving response evidence",
    },
    "description_adapter.serving_profile": {
        "accepted": {"description_probe"},
        "declared_when": "configured profile without serving probe",
    },
    "description_adapter.is_stub": {
        "accepted": {"description_probe"},
        "declared_when": "adapter class/config claim without a serving probe",
    },
    "captured_at": {
        "accepted": {"collector_clock"},
        "declared_when": "operator-entered timestamp",
    },
    "tenant_id": {
        "accepted": {"request_context"},
        "declared_when": "TENANT_ID/default bootstrap value without request or DB context",
    },
}


def _runtime_space_token() -> str:
    """Build the pinned SFace space token without hardcoding package versions."""

    try:
        opencv_version = importlib.metadata.version("opencv-python")
    except importlib.metadata.PackageNotFoundError:
        opencv_version = importlib.metadata.version("opencv-python-headless")
    ort_version = importlib.metadata.version("onnxruntime")
    ort_parts = ort_version.split(".")
    ort_major_minor = ".".join(ort_parts[:2])
    return f"cv{opencv_version}/ort{ort_major_minor}"


def _materialize(value: Any) -> Any:
    """Replace fixture-only runtime token markers recursively."""

    if isinstance(value, dict):
        return {key: _materialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_materialize(item) for item in value]
    if isinstance(value, str):
        return value.replace("${RUNTIME_SPACE_TOKEN}", _runtime_space_token())
    return value


def _load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return _materialize(json.load(handle))


def _role(snapshot: dict[str, Any], role: str) -> dict[str, Any]:
    return next(record for record in snapshot["observations"] if record["role"] == role)


def _field(snapshot: dict[str, Any], role: str, field: str) -> dict[str, Any]:
    return _role(snapshot, role)[field]


def _set_captured_at(snapshot: dict[str, Any], value: str) -> None:
    snapshot["captured_at"]["value"] = value


def _set_all_provenance_declared(value: Any) -> None:
    if isinstance(value, dict):
        if "provenance" in value:
            value["provenance"] = "declared"
        for child in value.values():
            _set_all_provenance_declared(child)
    elif isinstance(value, list):
        for child in value:
            _set_all_provenance_declared(child)


def _enrich_snapshot_with_database_evidence(snapshot: dict[str, Any], *, enrolled: bool) -> None:
    inventory = snapshot["database"]["vector_column_inventory"]
    inventory["discovery_complete"] = True
    for record in snapshot["observations"]:
        _field(snapshot, record["role"], "loaded_weight_hashes")["value"]["sface"] = (
            "sha256:0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
        )
    row_count = 1 if enrolled else 0
    snapshot["database"]["store_state"] = {
        "value": "enrolled" if enrolled else "empty",
        "provenance": "database_catalog",
    }
    model_id = _field(snapshot, "api", "model_id")["value"]
    preprocessing_id = _field(snapshot, "api", "preprocessing_id")["value"]
    sample = [0.0] * 128 if enrolled else []
    snapshot["database"]["embedding_provenance"] = {
        "value": {
            "row_counts": dict.fromkeys(VECTOR_COLUMN_IDENTITIES, row_count),
            "model_id": model_id,
            "preprocessing_id": preprocessing_id,
            "representative_vector": copy.deepcopy(sample),
            "centroid": copy.deepcopy(sample),
        },
        "provenance": "database_catalog",
    }


def _case_snapshot(case_name: str) -> dict[str, Any]:
    fixture_name = {
        "valid_enrolled_fir_store": "valid_enrolled_fir_store.json",
        "fourth_vector_column_undiscovered": "fourth_vector_column_undiscovered.json",
        "redaction_secret_input": "redaction_secret_input.json",
    }.get(case_name, "valid_empty_fir_store.json")
    if case_name.startswith("enrolled_store_"):
        fixture_name = "valid_enrolled_fir_store.json"
    snapshot = copy.deepcopy(_load_fixture(fixture_name))
    _enrich_snapshot_with_database_evidence(
        snapshot,
        enrolled=fixture_name == "valid_enrolled_fir_store.json",
    )
    if case_name == "freshness_boundary_minus_one":
        _set_captured_at(snapshot, "2026-09-20T12:00:01Z")
    elif case_name == "naive_captured_at_timestamp":
        _set_captured_at(snapshot, "2026-09-20T12:00:00")
    elif case_name == "future_dated_snapshot":
        _set_captured_at(snapshot, "2026-09-20T18:00:00Z")
    elif case_name == "api_worker_dimension_mismatch":
        _field(snapshot, "worker", "embedding_dimension")["value"] = 512
    elif case_name == "database_dimension_mismatch":
        for item in snapshot["database"]["vector_column_inventory"]["value"]:
            item["dimension"] = 512
    elif case_name == "model_id_mismatch":
        _field(snapshot, "worker", "model_id")["value"] = "opencv-sface+cv-alternate/ort99.99@128d/l2/cosine"
    elif case_name == "preprocessing_id_mismatch":
        _field(snapshot, "worker", "preprocessing_id")["value"] = "sface-align-v2"
    elif case_name == "missing_model_weight_hashes":
        _field(snapshot, "worker", "loaded_weight_hashes")["value"] = {}
    elif case_name == "database_identity_version_declared":
        database = snapshot["database"]
        for field_name in ("database_name", "role"):
            database["identity"][field_name]["provenance"] = "declared"
        database["server_version"]["provenance"] = "declared"
        database["extension_versions"]["provenance"] = "declared"
    elif case_name == "blank_database_identity":
        snapshot["database"]["identity"]["database_name"]["value"] = " "
    elif case_name == "empty_storage_id_list":
        snapshot["storage"]["volume_ids"]["value"] = []
    elif case_name == "stale_snapshot":
        _set_captured_at(snapshot, "2026-09-20T11:59:59Z")
    elif case_name == "auth_disabled":
        _field(snapshot, "api", "auth_enabled")["value"] = False
    elif case_name == "seeded_description_adapter":
        snapshot["description_adapter"]["is_stub"]["value"] = True
        snapshot["description_adapter"]["model_id"]["value"] = "seeded-fixtures"
    elif case_name == "image_digest_mismatch":
        _field(snapshot, "worker", "image_digest")["value"] = "sha256:worker-digest-does-not-match"
    elif case_name == "forbidden_storage":
        snapshot["storage"]["volume_ids"]["value"][0] = "acx-dev-pgdata"
    elif case_name == "compose_prefixed_forbidden_storage":
        snapshot["storage"]["volume_ids"]["value"][0] = "acx-dev_acx-dev-pgdata"
    elif case_name == "casefolded_forbidden_database":
        snapshot["database"]["identity"]["database_name"]["value"] = "ALT_CONTEXT"
    elif case_name == "default_tenant":
        snapshot["tenant_id"]["value"] = DEFAULT_TENANT_SENTINEL
    elif case_name == "all_declared_provenance":
        _set_all_provenance_declared(snapshot)
    elif case_name == "unparseable_model_id":
        _field(snapshot, "api", "model_id")["value"] = "stub-detector@test"
    elif case_name == "all_roles_512d_consistent":
        for record in snapshot["observations"]:
            _field(snapshot, record["role"], "embedding_dimension")["value"] = 512
            _field(snapshot, record["role"], "model_id")["value"] = _field(snapshot, record["role"], "model_id")[
                "value"
            ].replace("@128d/", "@512d/")
    elif case_name == "wrong_face_pipeline_profile":
        for record in snapshot["observations"]:
            _field(snapshot, record["role"], "effective_profile")["value"] = "stub"
    elif case_name == "foreign_model_space":
        for record in snapshot["observations"]:
            role = record["role"]
            _field(snapshot, role, "embedding_dimension")["value"] = 512
            _field(snapshot, role, "model_id")["value"] = "insightface-buffalo_l+onnx1.17@512d/l2/cosine"
    elif case_name == "unresolved_space_token":
        for record in snapshot["observations"]:
            _field(snapshot, record["role"], "model_id")["value"] = "opencv-sface+${RUNTIME_SPACE_TOKEN}@128d/l2/cosine"
    elif case_name == "partial_model_weight_hashes":
        _field(snapshot, "worker", "loaded_weight_hashes")["value"].pop("yunet")
    elif case_name == "non_hash_weight_value":
        _field(snapshot, "worker", "loaded_weight_hashes")["value"]["sface"] = "loaded"
    elif case_name == "divergent_role_weight_hashes":
        _field(snapshot, "worker", "loaded_weight_hashes")["value"]["sface"] = "sha256:" + "f" * 64
    elif case_name == "foreign_model_asset_hash":
        for record in snapshot["observations"]:
            _field(snapshot, record["role"], "loaded_weight_hashes")["value"] = {
                "yunet": "sha256:" + "f" * 64,
                "sface": "sha256:" + "e" * 64,
            }
    elif case_name == "auth_enabled_null":
        _field(snapshot, "api", "auth_enabled")["value"] = None
    elif case_name == "auth_enabled_string":
        _field(snapshot, "api", "auth_enabled")["value"] = "true"
    elif case_name == "malformed_observation_wrapper":
        _field(snapshot, "api", "auth_enabled").pop("provenance")
    elif case_name == "is_stub_null":
        snapshot["description_adapter"]["is_stub"]["value"] = None
    elif case_name == "hosted_description_adapter":
        snapshot["description_adapter"]["serving_profile"]["value"] = "hosted"
        snapshot["description_adapter"]["model_revision"]["value"] = ""
    elif case_name == "mutable_image_tag":
        for record in snapshot["observations"]:
            _field(snapshot, record["role"], "image_digest")["value"] = "acx-dev-fir:latest"
    elif case_name == "empty_image_digest":
        for record in snapshot["observations"]:
            _field(snapshot, record["role"], "image_digest")["value"] = ""
    elif case_name == "empty_vector_inventory":
        snapshot["database"]["vector_column_inventory"]["value"] = []
    elif case_name == "omitted_centroid_column":
        snapshot["database"]["vector_column_inventory"]["value"] = [
            item
            for item in snapshot["database"]["vector_column_inventory"]["value"]
            if f"{item['schema']}.{item['table']}.{item['column']}" != "public.mv_identity_cluster_centroids.centroid"
        ]
    elif case_name == "invalid_vector_column_identity":
        snapshot["database"]["vector_column_inventory"]["value"][0]["column"] = ""
    elif case_name == "incomplete_schema_discovery":
        snapshot["database"]["vector_column_inventory"]["discovery_complete"] = False
    elif case_name == "enrolled_store_foreign_model_stamp":
        snapshot["database"]["embedding_provenance"]["value"]["model_id"] = "foreign-model@1"
    elif case_name == "enrolled_store_non_finite_centroid":
        snapshot["database"]["embedding_provenance"]["value"]["centroid"] = [float("nan")] * 128
    elif case_name == "enrolled_store_missing_centroid_sample":
        del snapshot["database"]["embedding_provenance"]["value"]["centroid"]
    elif case_name == "enrolled_store_missing_provenance_summary":
        del snapshot["database"]["embedding_provenance"]
    elif case_name == "empty_store_with_rows":
        snapshot["database"]["embedding_provenance"]["value"]["row_counts"]["public.media_identities.embedding"] = 1
    elif case_name in {"fourth_vector_column_nonzero", "fourth_vector_column_zero"}:
        extra_identity = "public.audit_embeddings.embedding"
        snapshot["database"]["vector_column_inventory"]["value"].append(
            {
                "schema": "public",
                "table": "audit_embeddings",
                "column": "embedding",
                "dimension": 128,
                "provenance": "database_catalog",
            }
        )
        snapshot["database"]["embedding_provenance"]["value"]["row_counts"][extra_identity] = (
            1 if case_name == "fourth_vector_column_nonzero" else 0
        )
    elif case_name == "duplicate_worker_role":
        _role(snapshot, "fix-blob-ownership")["role"] = "worker"
    elif case_name == "unknown_role_present":
        _role(snapshot, "fix-blob-ownership")["role"] = "unknown"
    elif case_name == "schema_version_two":
        snapshot["schema_version"] = 2
    elif case_name == "missing_storage_section":
        del snapshot["storage"]
    elif case_name == "empty_forbidden_resource_policy":
        pass
    elif case_name == "malformed_timestamp":
        _set_captured_at(snapshot, "not-an-iso-timestamp")
    elif case_name == "keyword_value_dsn_secret":
        snapshot["database"]["identity"]["database_name"]["value"] = (
            "host=postgres port=5432 dbname=alt_context_dev_fir "
            f"user=acx_dev_fir password={DSN_PASSWORD} sslmode=disable"
        )
    elif case_name in {
        "valid_empty_fir_store",
        "valid_enrolled_fir_store",
        "fourth_vector_column_undiscovered",
        "redaction_secret_input",
        "malformed_policy_input",
    }:
        pass
    else:
        raise AssertionError(f"unhandled contract case: {case_name}")
    return snapshot


def _validator_result(case_name: str, snapshot: dict[str, Any]) -> Mapping[str, Any]:
    expected = CASE_OUTCOMES[case_name]
    try:
        validator = importlib.import_module(MODULE_NAME)
    except Exception as exc:  # RED must name the missing behavior, not leak ImportError.
        pytest.fail(
            f"{case_name}: expected status={expected[0]} exit_code={expected[1]} "
            f"reason_code={expected[2]}; missing validator behavior ({type(exc).__name__}: {exc})",
            pytrace=False,
        )

    function = getattr(validator, "validate_snapshot", None)
    if not callable(function):
        pytest.fail(
            f"{case_name}: expected status={expected[0]} exit_code={expected[1]} "
            f"reason_code={expected[2]}; validate_snapshot is not exposed",
            pytrace=False,
        )

    freshness_policy = _load_fixture("freshness_policy.json")
    isolation_policy = _load_fixture("isolation_policy.json")
    if case_name == "malformed_policy_input":
        freshness_policy["max_age_seconds"] = 0
    elif case_name == "empty_forbidden_resource_policy":
        isolation_policy["forbidden_resource_ids"] = {}

    try:
        result = function(
            snapshot,
            freshness_policy=freshness_policy,
            isolation_policy=isolation_policy,
            now=NOW,
        )
    except Exception as exc:
        pytest.fail(
            f"{case_name}: expected status={expected[0]} exit_code={expected[1]} "
            f"reason_code={expected[2]}; validator raised {type(exc).__name__}: {exc}",
            pytrace=False,
        )

    if hasattr(result, "to_dict"):
        result = result.to_dict()
    if not isinstance(result, Mapping):
        pytest.fail(
            f"{case_name}: expected status={expected[0]} exit_code={expected[1]} "
            f"reason_code={expected[2]}; result is not a mapping",
            pytrace=False,
        )
    return result


def _validate_custom_snapshot(
    snapshot: dict[str, Any],
    *,
    isolation_policy: dict[str, Any] | None = None,
) -> Mapping[str, Any]:
    validator = importlib.import_module(MODULE_NAME)
    return validator.validate_snapshot(
        snapshot,
        freshness_policy=_load_fixture("freshness_policy.json"),
        isolation_policy=isolation_policy or _load_fixture("isolation_policy.json"),
        now=NOW,
    )


def _assert_pinned_outcome(case_name: str, result: Mapping[str, Any]) -> None:
    expected_status, expected_exit_code, expected_reason = CASE_OUTCOMES[case_name]
    assert result.get("status") == expected_status, (
        f"{case_name}: expected status={expected_status} exit_code={expected_exit_code} reason_code={expected_reason}"
    )
    assert result.get("exit_code") == expected_exit_code, (
        f"{case_name}: expected status={expected_status} exit_code={expected_exit_code} reason_code={expected_reason}"
    )
    assert result.get("reason_code") == expected_reason, (
        f"{case_name}: expected status={expected_status} exit_code={expected_exit_code} reason_code={expected_reason}"
    )


@pytest.mark.parametrize("case_name", tuple(CASE_OUTCOMES)[:-2])
def test_pinned_runtime_snapshot_cases(case_name: str) -> None:
    """Every RED case targets a stable outcome, not an implementation helper."""

    result = _validator_result(case_name, _case_snapshot(case_name))
    _assert_pinned_outcome(case_name, result)


def test_snapshot_v1_is_role_keyed_and_closed() -> None:
    snapshot = _case_snapshot("valid_empty_fir_store")
    assert set(snapshot) == {
        "schema_version",
        "captured_at",
        "tenant_id",
        "observations",
        "database",
        "storage",
        "description_adapter",
    }
    assert snapshot["schema_version"] == 1
    assert {record["role"] for record in snapshot["observations"]} == set(ROLE_SET)
    for record in snapshot["observations"]:
        assert set(record) == {"role", *ROLE_FIELDS}
    assert set(snapshot["database"]) == set(DATABASE_FIELDS)
    assert set(snapshot["database"]["identity"]) == {"database_name", "role"}
    assert set(snapshot["storage"]) == set(STORAGE_FIELDS)
    assert set(snapshot["description_adapter"]) == set(DESCRIPTION_FIELDS)


def test_every_contract_field_has_provenance_and_an_observation_method() -> None:
    snapshot = _case_snapshot("valid_empty_fir_store")
    observed_paths: set[str] = set()

    def assert_wrapper(path: str, field: Mapping[str, Any], *, discovery_marker: bool = False) -> None:
        expected_keys = {"value", "provenance"}
        if discovery_marker:
            expected_keys.add("discovery_complete")
        assert set(field) == expected_keys, path
        assert isinstance(field["provenance"], str) and field["provenance"], path
        observed_paths.add(path)
        assert path in OBSERVATION_METHODS, path

    assert_wrapper("captured_at", snapshot["captured_at"])
    assert_wrapper("tenant_id", snapshot["tenant_id"])
    for record in snapshot["observations"]:
        for field_name in ROLE_FIELDS:
            assert_wrapper(f"observations[*].{field_name}", record[field_name])
    for field_name in ("server_version", "extension_versions"):
        assert_wrapper(f"database.{field_name}", snapshot["database"][field_name])
    assert_wrapper(
        "database.vector_column_inventory",
        snapshot["database"]["vector_column_inventory"],
        discovery_marker=True,
    )
    for field_name in ("database_name", "role"):
        assert_wrapper("database.identity", snapshot["database"]["identity"][field_name])
    assert_wrapper("database.store_state", snapshot["database"]["store_state"])
    assert_wrapper("database.embedding_provenance", snapshot["database"]["embedding_provenance"])
    for field_name in STORAGE_FIELDS:
        assert_wrapper(f"storage.{field_name}", snapshot["storage"][field_name])
    for field_name in DESCRIPTION_FIELDS:
        assert_wrapper(f"description_adapter.{field_name}", snapshot["description_adapter"][field_name])

    assert observed_paths == {path for path in OBSERVATION_METHODS if path != "database.identity"} | {
        "database.identity"
    }


def test_model_id_uses_opaque_fingerprinted_name_and_suffix_only() -> None:
    model_id = _field(_case_snapshot("valid_empty_fir_store"), "api", "model_id")["value"]
    name_part, suffix = model_id.rsplit("@", 1)
    assert suffix.split("/") == ["128d", "l2", "cosine"]
    assert name_part.startswith("opencv-sface+")
    opaque_name = name_part.removeprefix("opencv-sface+")
    assert opaque_name.startswith("cv")
    assert "/ort" in opaque_name
    # The opaque runtime token contributes one slash; the contract suffix has two.
    assert model_id.count("/") == 3
    assert "stub-detector@test" not in model_id


def _coarse_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _run_cli(tmp_path: Path, snapshot: dict[str, Any] | str) -> subprocess.CompletedProcess[str]:
    snapshot_path = tmp_path / "snapshot.json"
    freshness_path = tmp_path / "freshness-policy.json"
    isolation_path = tmp_path / "isolation-policy.json"
    snapshot_text = snapshot if isinstance(snapshot, str) else json.dumps(snapshot)
    snapshot_path.write_text(snapshot_text, encoding="utf-8")
    freshness_path.write_text(json.dumps(_load_fixture("freshness_policy.json")), encoding="utf-8")
    isolation_path.write_text(json.dumps(_load_fixture("isolation_policy.json")), encoding="utf-8")

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(APP_ROOT) if not existing_pythonpath else f"{APP_ROOT}{os.pathsep}{existing_pythonpath}"

    return subprocess.run(
        [
            sys.executable,
            "-m",
            MODULE_NAME,
            "--snapshot",
            str(snapshot_path),
            "--freshness-policy",
            str(freshness_path),
            "--isolation-policy",
            str(isolation_path),
            "--now",
            NOW,
        ],
        cwd=APP_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_truncated_snapshot_returns_snapshot_unreadable_envelope(tmp_path: Path) -> None:
    completed = _run_cli(tmp_path, '{"schema_version": 1')

    assert completed.returncode == 2
    result = json.loads(completed.stdout)
    assert result["status"] == "invalid"
    assert result["exit_code"] == 2
    assert result["reason_code"] == "snapshot_unreadable"
    assert completed.stderr.strip().startswith("snapshot_unreadable:")


def test_redaction_refuses_secret_and_keeps_positive_coarse_tokens_in_api_report() -> None:
    case_name = "redaction_secret_input"
    snapshot = _case_snapshot(case_name)
    result = _validator_result(case_name, snapshot)
    _assert_pinned_outcome(case_name, result)

    report_json = json.dumps(result.get("report", result), sort_keys=True)
    exit_reason = str(result.get("reason", ""))
    model_id = _field(snapshot, "api", "model_id")["value"]
    tenant_id = snapshot["tenant_id"]["value"]
    for surface in (report_json, exit_reason):
        assert SENTINEL not in surface
    assert _coarse_token(model_id) in report_json
    assert _coarse_token(tenant_id) in report_json
    assert exit_reason


def test_redaction_surfaces_cover_stdout_json_report_and_exit_reason(tmp_path: Path) -> None:
    case_name = "redaction_secret_input"
    snapshot = _case_snapshot(case_name)
    completed = _run_cli(tmp_path, snapshot)
    expected = CASE_OUTCOMES[case_name]
    if completed.returncode != expected[1] and (
        "No module named" in completed.stderr or "ImportError" in completed.stderr
    ):
        pytest.fail(
            f"{case_name}: expected status={expected[0]} exit_code={expected[1]} "
            f"reason_code={expected[2]}; validator CLI is missing",
            pytrace=False,
        )
    assert completed.returncode == expected[1], (
        f"{case_name}: expected status={expected[0]} exit_code={expected[1]} "
        f"reason_code={expected[2]} stderr={completed.stderr!r}"
    )

    stdout = completed.stdout
    report = json.loads(stdout)
    report_json = json.dumps(report, sort_keys=True)
    exit_reason = completed.stderr.strip()
    model_id = _field(snapshot, "api", "model_id")["value"]
    tenant_id = snapshot["tenant_id"]["value"]
    for surface in (stdout, report_json, exit_reason):
        assert SENTINEL not in surface
    assert _coarse_token(model_id) in stdout
    assert _coarse_token(tenant_id) in stdout
    assert _coarse_token(model_id) in report_json
    assert _coarse_token(tenant_id) in report_json
    assert expected[2] in exit_reason


def test_keyword_value_dsn_is_refused_and_never_emitted_in_cli_report(tmp_path: Path) -> None:
    case_name = "keyword_value_dsn_secret"
    snapshot = _case_snapshot(case_name)
    result = _validator_result(case_name, snapshot)
    _assert_pinned_outcome(case_name, result)

    completed = _run_cli(tmp_path, snapshot)
    assert completed.returncode == CASE_OUTCOMES[case_name][1]
    assert DSN_PASSWORD not in completed.stdout
    assert DSN_PASSWORD not in completed.stderr
    assert DSN_PASSWORD not in json.dumps(json.loads(completed.stdout), sort_keys=True)


@pytest.mark.parametrize(
    ("shape_name", "value_template"),
    (
        (
            "uri_password_first",
            "postgresql://collector@postgres/alt_context?password={secret}&sslmode=require",
        ),
        (
            "uri_password_last",
            "postgresql://collector@postgres/alt_context?sslmode=require&password={secret}",
        ),
        ("uri_api_key", "postgresql://postgres/alt_context?api_key={secret}"),
        ("pgpassword", "PGPASSWORD={secret}"),
        ("ado_pwd", "Server=pg;Pwd={secret};"),
        ("json_password", '{{"password":"{secret}"}}'),
        ("yaml_password", "password: {secret}"),
        ("auth_token", "auth_token={secret}"),
        ("client_secret", "client_secret={secret}"),
        ("bearer_token", "bearer_token={secret}"),
        ("dsn", "dsn={secret}"),
    ),
)
def test_credential_shapes_are_refused_and_never_emitted_in_cli_report(
    tmp_path: Path,
    shape_name: str,
    value_template: str,
) -> None:
    secret = f"harm01-{shape_name}-must-not-appear"
    snapshot = _case_snapshot("valid_empty_fir_store")
    snapshot["database"]["identity"]["database_name"]["value"] = value_template.format(secret=secret)

    result = _validate_custom_snapshot(snapshot)
    assert result["status"] == "invalid"
    assert result["exit_code"] == 2
    assert result["reason_code"] == "secret_shaped_input"

    completed = _run_cli(tmp_path, snapshot)
    assert completed.returncode == 2
    assert secret not in completed.stdout
    assert secret not in completed.stderr
    assert secret not in json.dumps(json.loads(completed.stdout), sort_keys=True)


def test_legitimate_collector_values_are_not_secret_shaped() -> None:
    snapshot = _case_snapshot("valid_empty_fir_store")
    snapshot["database"]["identity"]["database_name"]["value"] = "alt_context_dev_fir"
    snapshot["database"]["identity"]["role"]["value"] = "acx_dev_fir"
    snapshot["database"]["server_version"]["value"] = (
        "PostgreSQL 16.4 (Debian 16.4-1.pgdg120+1) on x86_64-pc-linux-gnu, "
        "compiled by gcc (Debian 12.2.0-14) 12.2.0, 64-bit"
    )
    snapshot["storage"]["volume_ids"]["value"][1] = "acx-dev-fir_acx_blobs"

    result = _validate_custom_snapshot(snapshot)
    assert result["status"] == "ready"
    assert result["exit_code"] == 0
    assert result["reason_code"] == "ready"


def test_compose_prefix_matches_only_foreign_forbidden_projects() -> None:
    isolation_policy = _load_fixture("isolation_policy.json")
    isolation_policy["forbidden_resource_ids"]["volumes"] = ["acx_blobs"]

    foreign_snapshot = _case_snapshot("valid_empty_fir_store")
    foreign_snapshot["storage"]["volume_ids"]["value"][0] = "acx-dev_acx_blobs"
    foreign_result = _validate_custom_snapshot(foreign_snapshot, isolation_policy=isolation_policy)
    assert foreign_result["status"] == "invalid"
    assert foreign_result["exit_code"] == 2
    assert foreign_result["reason_code"] == "forbidden_resource_id"

    own_snapshot = _case_snapshot("valid_empty_fir_store")
    own_snapshot["storage"]["volume_ids"]["value"][0] = "acx-dev-fir_acx_blobs"
    own_result = _validate_custom_snapshot(own_snapshot, isolation_policy=isolation_policy)
    assert own_result["status"] == "ready"
    assert own_result["exit_code"] == 0
    assert own_result["reason_code"] == "ready"


@pytest.mark.parametrize(
    ("storage_field", "category", "observed_value", "forbidden_value"),
    (
        ("network_ids", "networks", "acx-dev_acx-dev-net", "acx-dev-net"),
        ("blob_namespace", "blob_namespaces", "acx-dev_acx-dev", "acx-dev"),
    ),
)
def test_compose_prefixed_networks_and_blob_namespaces_are_refused(
    storage_field: str,
    category: str,
    observed_value: str,
    forbidden_value: str,
) -> None:
    snapshot = _case_snapshot("valid_empty_fir_store")
    storage_value = snapshot["storage"][storage_field]["value"]
    if isinstance(storage_value, list):
        storage_value[0] = observed_value
    else:
        snapshot["storage"][storage_field]["value"] = observed_value

    isolation_policy = _load_fixture("isolation_policy.json")
    isolation_policy["forbidden_resource_ids"][category] = [forbidden_value]
    result = _validate_custom_snapshot(snapshot, isolation_policy=isolation_policy)
    assert result["status"] == "invalid"
    assert result["exit_code"] == 2
    assert result["reason_code"] == "forbidden_resource_id"


def test_validator_model_constants_match_manifest() -> None:
    from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST

    validator = importlib.import_module(MODULE_NAME)
    source_files = "scripts/validate_fir_dev_runtime.py and recognition/infrastructure/face_pipeline/provenance.py"
    expected_hashes = {name: f"sha256:{MODEL_MANIFEST[name].sha256}" for name in ("yunet", "sface")}
    assert expected_hashes == validator.EXPECTED_MODEL_ASSET_HASHES, (
        f"{source_files}: EXPECTED_MODEL_ASSET_HASHES is out of parity with MODEL_MANIFEST"
    )

    sface = MODEL_MANIFEST["sface"]
    manifest_contract = (f"{sface.embedding_dim}d", sface.normalization, sface.metric)
    assert validator.EXPECTED_MODEL_CONTRACT["embedding_dimension"] == sface.embedding_dim, (
        f"{source_files}: EXPECTED_MODEL_CONTRACT embedding dimension is out of parity with MODEL_MANIFEST"
    )
    assert validator.EXPECTED_MODEL_CONTRACT["model_suffix"] == manifest_contract, (
        f"{source_files}: EXPECTED_MODEL_CONTRACT model suffix is out of parity with MODEL_MANIFEST"
    )


def test_row_counts_follow_discovered_inventory_and_drive_empty_state() -> None:
    nonzero_case = "fourth_vector_column_nonzero"
    nonzero_result = _validator_result(nonzero_case, _case_snapshot(nonzero_case))
    _assert_pinned_outcome(nonzero_case, nonzero_result)

    zero_case = "fourth_vector_column_zero"
    zero_result = _validator_result(zero_case, _case_snapshot(zero_case))
    _assert_pinned_outcome(zero_case, zero_result)


def test_compose_prefixed_forbidden_volume_id_is_refused() -> None:
    case_name = "compose_prefixed_forbidden_storage"
    _assert_pinned_outcome(case_name, _validator_result(case_name, _case_snapshot(case_name)))


def test_casefolded_forbidden_database_name_is_refused() -> None:
    case_name = "casefolded_forbidden_database"
    _assert_pinned_outcome(case_name, _validator_result(case_name, _case_snapshot(case_name)))


def test_validator_import_is_pure_in_a_subprocess() -> None:
    probe = "\n".join(
        (
            "import sys",
            f"import {MODULE_NAME}",
            "leaked = sorted(",
            "    name for name in sys.modules",
            "    if name == 'recognition' or name.startswith('recognition.')",
            "    or name == 'db' or name.startswith('db.')",
            "    or name == 'sqlalchemy' or name.startswith('sqlalchemy.')",
            ")",
            "if leaked:",
            "    raise SystemExit('leaked imports: ' + ','.join(leaked))",
        )
    )
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(APP_ROOT) if not existing_pythonpath else f"{APP_ROOT}{os.pathsep}{existing_pythonpath}"
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=APP_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    expected = CASE_OUTCOMES["import_purity"]
    if completed.returncode != expected[1] and (
        "No module named" in completed.stderr or "ImportError" in completed.stderr
    ):
        pytest.fail(
            f"import_purity: expected status={expected[0]} exit_code={expected[1]} "
            f"reason_code={expected[2]}; validator module is missing",
            pytrace=False,
        )
    assert completed.returncode == expected[1], (
        f"import_purity: expected status={expected[0]} exit_code={expected[1]} "
        f"reason_code={expected[2]} stderr={completed.stderr!r}"
    )
