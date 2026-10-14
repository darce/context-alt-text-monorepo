"""GTMR Aura acceptance: repinned RED contract for the target-bound recognition gate.

This module repins the RED module first committed as 69c24a0. It is tests only.
Production code is unchanged in this lane. The parent records these REDs before
the separate minimal shared-prefix correction and the additive Aura interface.

Repin changes
-------------
* ``aura_prefix_overlay`` is removed. No test here changes ``EXPECTED_CONTRACTS``.
  The overlay masked every rung after the model-prefix rung. Each rung is now
  measured through the entrypoint that owns it.
* The static literal license RED is removed. License authority stays in
  ``MODEL_MANIFEST``. The Aura acceptance contract observes the loaded license
  digests and compares them with that pin.
* The canonical production prefix is ``insightface-auraface+``, because
  ``EmbeddingModelManifest.model_id`` prepends the framework. The shipped
  ``candidate512`` contract still pins ``auraface+``. That is an existing-behavior
  RED here, not a fix.

Classification
--------------
``test_control_*``  Existing behavior on unchanged production. Must stay green
                    through the shared prefix correction and the additive Aura
                    interface.
``test_red_*``      Existing behavior that is wrong. Fails today on a real
                    behavioral mismatch through the shipped entrypoint
                    ``scripts.validate_fir_dev_runtime.validate_snapshot``. No
                    overlay and no monkeypatch.
``test_future_*``   Proposed additive Aura interface ``AURA_ENTRYPOINT``. Until it
                    exists, each case fails with a ``FUTURE-INTERFACE-ABSENT``
                    marker. That marker is a repin proposal, not behavioral
                    evidence. It never counts as proof of a mismatch.

Repin map (superseded id -> current id)
---------------------------------------
test_red_production_identity_refused_by_shipped_candidate512
    -> unchanged name; existing RED
test_control_prefix_overlay_alone_accepts_production_identity
    -> removed with the overlay
test_red_non_unit_aura_representative_vector_is_refused
    -> test_future_aura_acceptance_contract[representative_sqrt512_norm_refused]
test_red_unenumerated_sibling_store_refused_when_target_bound
    -> test_future_aura_acceptance_contract[unlisted_staging_store_refused_under_prod_target]
test_red_candidate512_contract_pins_auraface_license_digest
    -> removed; replaced by test_future_aura_acceptance_contract[auraface_license_*]
test_red_enrolled_aura_store_refuses_mixed_persisted_model_ids
    -> test_future_aura_acceptance_contract[mixed_persisted_stamps_refused]
new existing RED
    -> test_red_obsolete_auraface_prefix_identity_must_be_refused

Evidence boundary
-----------------
Positive Aura evidence is a fixture of observations. Expected values (source pins
from ``MODEL_MANIFEST``, the approved source, the operator-selected target) are
never written into an observation field. A missing observation is deleted, never
backfilled. Observed fixture literals are tied to the source pins by a control,
so the two cannot drift apart silently.

Offline only: no DB, network, GPU, secrets, or model load.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from recognition.application import health
from recognition.application.embedding import manifest as embedding_manifest
from recognition.infrastructure.embeddings.face_pipeline_adapter import (
    auraface_embedding_model_manifest,
    sface_embedding_model_manifest,
)
from recognition.infrastructure.face_pipeline.aligner import FivePointAligner
from recognition.infrastructure.face_pipeline.model_space import ModelSpace
from recognition.infrastructure.face_pipeline.provenance import AURAFACE_REVISION, MODEL_MANIFEST
from shared.health import HealthStatus

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "unit" / "fixtures" / "fir_dev_runtime"
VALIDATOR_MODULE = "scripts.validate_fir_dev_runtime"
# Proposed additive interface. Not shipped; imported lazily so its absence is a
# named FUTURE marker, never an ImportError that could pass for behavior.
AURA_ENTRYPOINT_MODULE = "scripts.validate_auraface_runtime"
AURA_ENTRYPOINT = "validate_aura_acceptance"
AURA_EVIDENCE_SCHEMA_VERSION = 1
NOW = "2026-09-20T12:01:00Z"
AURA_LABEL = "prod-auraface"
SIBLING_LABEL = "staging-auraface"
VECTOR_DIM = 512
# Production norm rule: db/models/identity.py CHECK abs(vector_norm(embedding) - 1.0) < 0.01.
NORM_TOLERANCE = 0.01
APPROVED_SOURCE_GIT_SHA = "75fbf3101e58d3dc11cbcf00e3cefd9a10696d6f"
APPROVED_SOURCE_TREE = "23610e691a27c2d4d1933a2dcbbcbdbff360adee"
# Recorded but unapproved anchors from earlier provenance. Not the approved source.
STALE_SOURCE_GIT_SHA = "0d3ff19d14d70cba0aca5613564d894e2fcb09b1"
STALE_SOURCE_TREE = "1fb33a6fea186fc19f17e7b61fcfeff4262cb3ee"
YUNET_SHA256 = f"sha256:{MODEL_MANIFEST['yunet'].sha256}"
AURA_WEIGHT_SHA256 = f"sha256:{MODEL_MANIFEST['auraface'].sha256}"
INSIGHTFACE_512_MODEL_ID = "insightface-buffalo_l+cv5.0@512d/l2/cosine"
ZERO_DIGEST = "sha256:" + "0" * 64
ALT_DIGEST = "sha256:" + "2" * 64
ROLE_NAMES = ("api", "worker", "fix-blob-ownership")
EVIDENCE_ROLES = ("api", "worker")
VECTOR_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("public", "media_identities", "embedding"),
    ("public", "identity_cluster_representatives", "embedding"),
    ("public", "mv_identity_cluster_centroids", "centroid"),
)

# Observed fixture literals for the positive runtime evidence. They are literals,
# not reads from MODEL_MANIFEST, so a positive never fills an expected pin in as an
# observation. test_control_observed_fixture_literals_match_source_pins ties them to
# the source authority.
OBSERVED_YUNET_LICENSE_SHA256 = "sha256:c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958"
OBSERVED_AURA_LICENSE_SHA256 = "sha256:609e2cb599f84aaa41d8ef29d8fdb04d164fab22e8d9292ca34a599d0f56a338"
OBSERVED_AURA_PREPROCESSING: dict[str, Any] = {
    "input_size": [112, 112],
    "channel_order": "RGB",
    "input_mean": 127.5,
    "input_scale": 1.0 / 127.5,
    "alignment_template_id": "arcface-112",
    "output_l2_normalized": False,
    "pipeline_normalization": "l2",
}

Outcome = tuple[str, int, str]
Expect = tuple[str, int, frozenset[str]]
READY: Expect = ("ready", 0, frozenset({"ready"}))


def _invalid(*reasons: str) -> Expect:
    return ("invalid", 2, frozenset(reasons))


def _incomplete(*reasons: str) -> Expect:
    return ("incomplete", 1, frozenset(reasons))


# --------------------------------------------------------------------------
# Identity builders (production emitters; no overlay)
# --------------------------------------------------------------------------


def _validator() -> Any:
    return importlib.import_module(VALIDATOR_MODULE)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _aura_manifest() -> Any:
    return auraface_embedding_model_manifest()


def _aura_model_id() -> str:
    return _aura_manifest().model_id


def _canonical_aura_prefix() -> str:
    return f"{_aura_manifest().framework}-auraface+"


def _obsolete_aura_model_id() -> str:
    """The pre-correction identity: the production emitter without its framework prefix."""

    canonical = _aura_model_id()
    prefix = f"{_aura_manifest().framework}-"
    if not canonical.startswith(prefix):
        raise AssertionError(f"production emitter is no longer framework-qualified: {canonical!r}")
    return canonical.removeprefix(prefix)


def _aura_preprocessing_id() -> str:
    return FivePointAligner(space=ModelSpace.AURAFACE).template_id


def _sface_model_id() -> str:
    return sface_embedding_model_manifest().model_id


def _unit_vector(dimension: int, scale: float = 1.0) -> list[float]:
    component = scale / math.sqrt(dimension)
    return [component] * dimension


def _snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _target_identities(label: str) -> dict[str, str]:
    """Proposed identities for ``acx-<label>`` under the spec's naming rules."""

    underscored = label.replace("-", "_")
    return {
        "compose_project": f"acx-{label}",
        "network": f"acx-{label}-net",
        "database_name": f"alt_context_{underscored}",
        "role": f"acx_{underscored}",
        "pgdata": f"/opt/acx-backend/data/{label}-pgdata",
        "blob_volume": f"acx-{label}_acx_blobs",
        "blob_namespace": f"acx-{label}",
    }


def _required_identities(label: str) -> dict[str, list[str]]:
    identity = _target_identities(label)
    return {
        "volumes": [identity["pgdata"], identity["blob_volume"]],
        "networks": [identity["network"]],
        "compose_projects": [identity["compose_project"]],
        "database_names": [identity["database_name"]],
        "database_roles": [identity["role"]],
        "blob_namespaces": [identity["blob_namespace"]],
    }


def _inventory_identities(snapshot: Mapping[str, Any]) -> set[str]:
    return {
        f"{item['schema']}.{item['table']}.{item['column']}"
        for item in snapshot["database"]["vector_column_inventory"]["value"]
    }


def _role(snapshot: Mapping[str, Any], role: str) -> dict[str, Any]:
    return next(record for record in snapshot["observations"] if record["role"] == role)


def _all_roles(snapshot: dict[str, Any], field: str, value: Any) -> None:
    for record in snapshot["observations"]:
        record[field]["value"] = value


def _worker(snapshot: dict[str, Any], field: str, value: Any) -> None:
    _role(snapshot, "worker")[field]["value"] = value


def _set_inventory_dimension(snapshot: dict[str, Any], column: str, dimension: int) -> None:
    for item in snapshot["database"]["vector_column_inventory"]["value"]:
        if item["column"] == column:
            item["dimension"] = dimension


def _drop_inventory_column(snapshot: dict[str, Any], column: str) -> None:
    inventory = snapshot["database"]["vector_column_inventory"]
    inventory["value"] = [item for item in inventory["value"] if item["column"] != column]


def _add_undiscovered_column(snapshot: dict[str, Any]) -> None:
    snapshot["database"]["vector_column_inventory"]["value"].append(
        {
            "schema": "public",
            "table": "audit_embeddings",
            "column": "embedding",
            "dimension": None,
            "provenance": "declared",
        }
    )


def _aura_snapshot(
    label: str = AURA_LABEL,
    *,
    store: str = "empty",
    model_id: str | None = None,
) -> dict[str, Any]:
    """Production-shaped AuraFace observations for one target on the FIR snapshot fixture.

    No overlay: the production identity is written as observed. The shipped candidate512
    contract refuses it at the model-prefix rung, which is existing RED
    ``test_red_production_identity_refused_by_shipped_candidate512``.
    """

    snapshot = _fixture("valid_empty_fir_store.json")
    target = _target_identities(label)
    observed_model_id = model_id if model_id is not None else _aura_model_id()
    preprocessing_id = _aura_preprocessing_id()
    for record in snapshot["observations"]:
        record["effective_profile"]["value"] = "auraface"
        record["embedding_dimension"]["value"] = VECTOR_DIM
        record["model_id"]["value"] = observed_model_id
        record["preprocessing_id"]["value"] = preprocessing_id
        record["loaded_weight_hashes"]["value"] = {"yunet": YUNET_SHA256, "auraface": AURA_WEIGHT_SHA256}
        record["source_git_sha"]["value"] = APPROVED_SOURCE_GIT_SHA
    storage = snapshot["storage"]
    storage["volume_ids"]["value"] = [target["pgdata"], target["blob_volume"]]
    storage["network_ids"]["value"] = [target["network"]]
    storage["compose_project"]["value"] = target["compose_project"]
    storage["blob_namespace"]["value"] = target["blob_namespace"]
    identity = snapshot["database"]["identity"]
    identity["database_name"]["value"] = target["database_name"]
    identity["role"]["value"] = target["role"]
    inventory = snapshot["database"]["vector_column_inventory"]
    inventory["discovery_complete"] = True
    inventory["value"] = [
        {"schema": schema, "table": table, "column": column, "dimension": VECTOR_DIM, "provenance": "database_catalog"}
        for schema, table, column in VECTOR_COLUMNS
    ]
    enrolled = store == "enrolled"
    sample = _unit_vector(VECTOR_DIM) if enrolled else []
    snapshot["database"]["store_state"] = {
        "value": "enrolled" if enrolled else "empty",
        "provenance": "database_catalog",
    }
    snapshot["database"]["embedding_provenance"] = {
        "value": {
            "row_counts": dict.fromkeys(_inventory_identities(snapshot), 1 if enrolled else 0),
            "model_id": observed_model_id,
            "preprocessing_id": preprocessing_id,
            "representative_vector": list(sample),
            "centroid": list(sample),
            "persisted_model_ids": [observed_model_id] if enrolled else [],
            "persisted_model_ids_complete": True,
        },
        "provenance": "database_catalog",
    }
    return snapshot


def _baseline_snapshot() -> dict[str, Any]:
    """Production-true SFace observations on the existing FIR empty-store fixture."""

    snapshot = _fixture("valid_empty_fir_store.json")
    model_id = _sface_model_id()
    preprocessing_id = FivePointAligner().template_id
    for record in snapshot["observations"]:
        record["model_id"]["value"] = model_id
        record["preprocessing_id"]["value"] = preprocessing_id
    snapshot["database"]["vector_column_inventory"]["discovery_complete"] = True
    snapshot["database"]["store_state"] = {"value": "empty", "provenance": "database_catalog"}
    snapshot["database"]["embedding_provenance"] = {
        "value": {
            "row_counts": dict.fromkeys(_inventory_identities(snapshot), 0),
            "model_id": model_id,
            "preprocessing_id": preprocessing_id,
            "representative_vector": [],
            "centroid": [],
        },
        "provenance": "database_catalog",
    }
    return snapshot


def _isolation_policy(
    *,
    target: str | None = None,
    forbidden: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    policy = _fixture("isolation_policy.json")
    for category, values in (forbidden or {}).items():
        policy["forbidden_resource_ids"][category].extend(values)
    if target is not None:
        policy["required_target_resource_ids"] = _required_identities(target)
    return policy


def _validate(
    snapshot: Mapping[str, Any],
    *,
    contract: str = "candidate512",
    isolation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = _validator().validate_snapshot(
        snapshot,
        freshness_policy=_fixture("freshness_policy.json"),
        isolation_policy=dict(isolation) if isolation is not None else _isolation_policy(),
        now=NOW,
        contract=contract,
    )
    return dict(result)


def _outcome(result: Mapping[str, Any]) -> Outcome:
    return (result["status"], result["exit_code"], result["reason_code"])


def _describe(outcome: Outcome) -> str:
    return f"status={outcome[0]} exit_code={outcome[1]} reason_code={outcome[2]}"


def _assert_outcome(result: Mapping[str, Any], expected: Outcome, context: str) -> None:
    actual = _outcome(result)
    assert actual == expected, f"{context}: expected {_describe(expected)}; actual {_describe(actual)}"


def _assert_refused_for(result: Mapping[str, Any], reasons: frozenset[str], context: str) -> None:
    actual = _outcome(result)
    assert actual[0] == "invalid" and actual[1] == 2 and actual[2] in reasons, (
        f"{context}: expected invalid exit_code=2 with reason_code in {sorted(reasons)}; actual {_describe(actual)}"
    )


def _assert_expectation(result: Mapping[str, Any], expected: Expect, context: str) -> None:
    status, exit_code, reasons = expected
    actual = _outcome(result)
    assert actual[0] == status and actual[1] == exit_code and actual[2] in reasons, (
        f"{context}: expected status={status} exit_code={exit_code} reason_code in {sorted(reasons)}; "
        f"actual {_describe(actual)}"
    )


# --------------------------------------------------------------------------
# Proposed additive Aura evidence (separately versioned sidecar, not snapshot v1)
# --------------------------------------------------------------------------


def _aura_role_evidence(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    identity = snapshot["database"]["identity"]
    return {
        "loaded_license_hashes": {
            "value": {"yunet": OBSERVED_YUNET_LICENSE_SHA256, "auraface": OBSERVED_AURA_LICENSE_SHA256},
            "provenance": "runtime_loaded_artifact",
        },
        "preprocessing_contract": {
            "value": copy.deepcopy(OBSERVED_AURA_PREPROCESSING),
            "provenance": "runtime_probe",
        },
        "source_tree": {"value": APPROVED_SOURCE_TREE, "provenance": "binary_identity"},
        "database_identity": {
            "value": {
                "database_name": identity["database_name"]["value"],
                "role": identity["role"]["value"],
            },
            "provenance": "database_catalog",
        },
    }


def _aura_evidence(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    role_evidence = _aura_role_evidence(snapshot)
    return {
        "schema_version": AURA_EVIDENCE_SCHEMA_VERSION,
        "snapshot_sha256": _snapshot_digest(snapshot),
        "runtime_roles": {role: copy.deepcopy(role_evidence) for role in EVIDENCE_ROLES},
    }


def _acceptance_policy(label: str) -> dict[str, Any]:
    return {
        "target_label": label,
        "approved_source_git_sha": APPROVED_SOURCE_GIT_SHA,
        "approved_source_tree": APPROVED_SOURCE_TREE,
    }


def _aura_case(label: str = AURA_LABEL, *, store: str = "empty", model_id: str | None = None) -> dict[str, Any]:
    """One complete acceptance input: snapshot, Aura evidence sidecar, and policies."""

    snapshot = _aura_snapshot(label, store=store, model_id=model_id)
    return {
        "snapshot": snapshot,
        "aura_evidence": _aura_evidence(snapshot),
        "isolation_policy": _isolation_policy(target=label),
        "acceptance_policy": _acceptance_policy(label),
    }


def _base_case(base: str) -> dict[str, Any]:
    return _aura_case(store=base)


def _prov(case: dict[str, Any]) -> dict[str, Any]:
    return case["snapshot"]["database"]["embedding_provenance"]["value"]


def _inventory(case: dict[str, Any]) -> dict[str, Any]:
    return case["snapshot"]["database"]["vector_column_inventory"]


def _evidence_role(case: dict[str, Any], role: str) -> dict[str, Any]:
    return case["aura_evidence"]["runtime_roles"][role]


def _target_policy(case: dict[str, Any]) -> dict[str, Any]:
    return case["isolation_policy"]["required_target_resource_ids"]


def _noop(case: dict[str, Any]) -> None:
    return None


def _set_prov(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        _prov(case)[key] = copy.deepcopy(value)

    return mutate


def _del_prov(key: str) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        del _prov(case)[key]

    return mutate


def _scale_representative(scale: float) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        _prov(case)["representative_vector"] = _unit_vector(VECTOR_DIM, scale)

    return mutate


def _add_zero_row_fourth_column(case: dict[str, Any]) -> None:
    _inventory(case)["value"].append(
        {
            "schema": "public",
            "table": "audit_embeddings",
            "column": "embedding",
            "dimension": VECTOR_DIM,
            "provenance": "database_catalog",
        }
    )
    _prov(case)["row_counts"]["public.audit_embeddings.embedding"] = 0


def _add_nonzero_fourth_column(case: dict[str, Any]) -> None:
    _add_zero_row_fourth_column(case)
    _prov(case)["row_counts"]["public.audit_embeddings.embedding"] = 1


def _replace_with_sibling_identity(case: dict[str, Any]) -> None:
    """Whole staging store observed under the production target. Identity group is one factor."""

    sibling = _aura_case(SIBLING_LABEL)
    case["snapshot"] = sibling["snapshot"]
    case["aura_evidence"] = sibling["aura_evidence"]


def _set_storage(field: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        case["snapshot"]["storage"][field]["value"] = copy.deepcopy(value)

    return mutate


def _set_target_category(category: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        _target_policy(case)[category] = copy.deepcopy(value)

    return mutate


def _del_target_category(category: str) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        del _target_policy(case)[category]

    return mutate


def _del_target_policy(case: dict[str, Any]) -> None:
    del case["isolation_policy"]["required_target_resource_ids"]


def _set_evidence(role: str, section: str, value: Any, *, key: str = "value") -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        _evidence_role(case, role)[section][key] = copy.deepcopy(value)

    return mutate


def _set_evidence_nested(
    role: str,
    section: str,
    inner_key: str,
    value: Any,
) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        _evidence_role(case, role)[section]["value"][inner_key] = copy.deepcopy(value)

    return mutate


def _del_evidence(role: str, section: str) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        del _evidence_role(case, role)[section]

    return mutate


def _del_evidence_license(role: str, key: str) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        del _evidence_role(case, role)["loaded_license_hashes"]["value"][key]

    return mutate


def _set_evidence_license(roles: tuple[str, ...], key: str, value: str) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        for role in roles:
            _evidence_role(case, role)["loaded_license_hashes"]["value"][key] = value

    return mutate


def _set_evidence_provenance(role: str, section: str, provenance: str) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        _evidence_role(case, role)[section]["provenance"] = provenance

    return mutate


def _set_snapshot_role_field(role: str, field: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        _role(case["snapshot"], role)[field]["value"] = copy.deepcopy(value)

    return mutate


def _set_snapshot_all_roles(field: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(case: dict[str, Any]) -> None:
        _all_roles(case["snapshot"], field, copy.deepcopy(value))

    return mutate


@dataclass(frozen=True)
class Pair:
    """One acceptance case: a base, a mutation, the pinned expectation, and its declared factor.

    ``factor_root`` names the single observation field the mutation may change (``""`` means no
    change). ``None`` marks the whole staging identity group as one documented factor.
    ``rebind`` recomputes the evidence snapshot hash after mutation, except where the binding
    itself is the factor under test.
    """

    case_id: str
    base: str
    mutate: Callable[[dict[str, Any]], None]
    expected: Expect
    factor_root: str | None
    rebind: bool = True


_EVIDENCE_DIGEST = "aura_evidence/snapshot_sha256"
_REPRESENTATIVE = "snapshot/database/embedding_provenance/value/representative_vector"
_PERSISTED = "snapshot/database/embedding_provenance/value/persisted_model_ids"
_INVENTORY = "snapshot/database/vector_column_inventory"
_ROLE_WEIGHTS = "snapshot/observations/<role>/loaded_weight_hashes"
_ROLE_SOURCE = "snapshot/observations/<role>/source_git_sha"
_ROLE_PREPROC = "snapshot/observations/<role>/preprocessing_id"
_EVIDENCE_LICENSE = "aura_evidence/runtime_roles/<role>/loaded_license_hashes"
_EVIDENCE_PREPROC = "aura_evidence/runtime_roles/<role>/preprocessing_contract"
_EVIDENCE_SOURCE_TREE = "aura_evidence/runtime_roles/<role>/source_tree"
_EVIDENCE_DBID = "aura_evidence/runtime_roles/<role>/database_identity"
_BOUNDARY_TARGET_REASONS = ("malformed_isolation_policy", "malformed_target_policy")

# Each negative differs from its base by exactly one declared factor. Positives are the
# independent controls that show the same base is ready before a single factor is changed.
PAIRS: tuple[Pair, ...] = (
    # Positive controls
    Pair("positive_enrolled_complete_evidence", "enrolled", _noop, READY, ""),
    Pair("positive_empty_complete_evidence", "empty", _noop, READY, ""),
    Pair(
        "positive_discovered_zero_row_fourth_column",
        "empty",
        _add_zero_row_fourth_column,
        READY,
        "snapshot/database",
    ),
    Pair(
        "positive_representative_norm_inside_tolerance",
        "enrolled",
        _scale_representative(1.0 + 0.9 * NORM_TOLERANCE),
        READY,
        _REPRESENTATIVE,
    ),
    # Norm rung (persisted representative must be unit length within the production tolerance)
    Pair(
        "representative_sqrt512_norm_refused",
        "enrolled",
        _set_prov("representative_vector", [1.0] * VECTOR_DIM),
        _invalid("non_normalized_persisted_vector"),
        _REPRESENTATIVE,
    ),
    Pair(
        "representative_zero_vector_refused",
        "enrolled",
        _set_prov("representative_vector", [0.0] * VECTOR_DIM),
        _invalid("non_normalized_persisted_vector"),
        _REPRESENTATIVE,
    ),
    Pair(
        "representative_norm_outside_tolerance_refused",
        "enrolled",
        _scale_representative(1.0 + 1.1 * NORM_TOLERANCE),
        _invalid("non_normalized_persisted_vector"),
        _REPRESENTATIVE,
    ),
    # Target binding (positive identities derived from the operator-selected target)
    Pair(
        "unlisted_staging_store_refused_under_prod_target",
        "empty",
        _replace_with_sibling_identity,
        _invalid("target_identity_mismatch", "forbidden_resource_id"),
        None,
    ),
    Pair(
        "observed_compose_project_outside_target_refused",
        "empty",
        _set_storage("compose_project", "acx-staging-auraface"),
        _invalid("target_identity_mismatch"),
        "snapshot/storage/compose_project",
    ),
    Pair(
        "observed_network_outside_target_refused",
        "empty",
        _set_storage("network_ids", ["acx-staging-auraface-net"]),
        _invalid("target_identity_mismatch"),
        "snapshot/storage/network_ids",
    ),
    Pair(
        "target_policy_category_missing_refused",
        "empty",
        _del_target_category("database_roles"),
        _invalid(*_BOUNDARY_TARGET_REASONS),
        "isolation_policy/required_target_resource_ids/database_roles",
    ),
    Pair(
        "target_policy_category_not_list_refused",
        "empty",
        _set_target_category("volumes", "acx-prod-auraface_acx_blobs"),
        _invalid(*_BOUNDARY_TARGET_REASONS),
        "isolation_policy/required_target_resource_ids/volumes",
    ),
    Pair(
        "target_policy_absent_refused",
        "empty",
        _del_target_policy,
        _invalid(*_BOUNDARY_TARGET_REASONS),
        "isolation_policy/required_target_resource_ids",
    ),
    # Persisted model stamps (exclusive Aura store; readiness predicate is not acceptance)
    Pair(
        "mixed_persisted_stamps_refused",
        "enrolled",
        _set_prov("persisted_model_ids", [_aura_model_id(), INSIGHTFACE_512_MODEL_ID]),
        _invalid("mixed_persisted_models", "persisted_model_stamp_mismatch"),
        _PERSISTED,
    ),
    Pair(
        "foreign_only_persisted_stamp_refused",
        "enrolled",
        _set_prov("persisted_model_ids", [INSIGHTFACE_512_MODEL_ID]),
        _invalid("persisted_model_stamp_mismatch"),
        _PERSISTED,
    ),
    Pair(
        "enrolled_store_empty_persisted_set_refused",
        "enrolled",
        _set_prov("persisted_model_ids", []),
        _invalid("persisted_model_stamp_mismatch"),
        _PERSISTED,
    ),
    Pair(
        "empty_store_with_persisted_stamp_refused",
        "empty",
        _set_prov("persisted_model_ids", [_aura_model_id()]),
        _invalid("persisted_model_stamp_mismatch"),
        _PERSISTED,
    ),
    Pair(
        "persisted_model_ids_duplicated_refused",
        "enrolled",
        _set_prov("persisted_model_ids", [_aura_model_id(), _aura_model_id()]),
        _invalid("persisted_model_ids_not_distinct"),
        _PERSISTED,
    ),
    Pair(
        "persisted_model_ids_incomplete_is_incomplete",
        "enrolled",
        _set_prov("persisted_model_ids_complete", False),
        _incomplete("embedding_provenance_unobserved"),
        "snapshot/database/embedding_provenance/value/persisted_model_ids_complete",
    ),
    Pair(
        "persisted_model_ids_absent_is_incomplete",
        "enrolled",
        _del_prov("persisted_model_ids"),
        _incomplete("embedding_provenance_unobserved"),
        _PERSISTED,
    ),
    # License evidence (observed loaded digests compared with the MODEL_MANIFEST pins)
    Pair(
        "auraface_license_absent_on_worker_is_incomplete",
        "empty",
        _del_evidence_license("worker", "auraface"),
        _incomplete("incomplete_license_evidence"),
        _EVIDENCE_LICENSE,
    ),
    Pair(
        "auraface_license_tampered_all_roles_refused",
        "empty",
        _set_evidence_license(EVIDENCE_ROLES, "auraface", ALT_DIGEST),
        _invalid("license_hash_mismatch"),
        _EVIDENCE_LICENSE,
    ),
    Pair(
        "auraface_license_divergent_worker_refused",
        "empty",
        _set_evidence_license(("worker",), "auraface", ALT_DIGEST),
        _invalid("role_license_hash_mismatch", "license_hash_mismatch"),
        _EVIDENCE_LICENSE,
    ),
    Pair(
        "yunet_license_tampered_all_roles_refused",
        "empty",
        _set_evidence_license(EVIDENCE_ROLES, "yunet", ALT_DIGEST),
        _invalid("license_hash_mismatch"),
        _EVIDENCE_LICENSE,
    ),
    Pair(
        "license_observation_declared_is_incomplete",
        "empty",
        _set_evidence_provenance("api", "loaded_license_hashes", "declared"),
        _incomplete("observation_provenance_declared"),
        _EVIDENCE_LICENSE,
    ),
    # Preprocessing evidence (loaded runtime contract compared with the source-owned pin)
    Pair(
        "preprocessing_contract_absent_is_incomplete",
        "empty",
        _del_evidence("api", "preprocessing_contract"),
        _incomplete("incomplete_preprocessing_evidence"),
        _EVIDENCE_PREPROC,
    ),
    Pair(
        "preprocessing_channel_order_bgr_refused",
        "empty",
        _set_evidence_nested("api", "preprocessing_contract", "channel_order", "BGR"),
        _invalid("preprocessing_contract_mismatch"),
        "aura_evidence/runtime_roles/<role>/preprocessing_contract/value/channel_order",
    ),
    Pair(
        "preprocessing_output_l2_normalized_refused",
        "empty",
        _set_evidence_nested("api", "preprocessing_contract", "output_l2_normalized", True),
        _invalid("preprocessing_contract_mismatch"),
        "aura_evidence/runtime_roles/<role>/preprocessing_contract/value/output_l2_normalized",
    ),
    Pair(
        "preprocessing_alignment_template_sface_refused",
        "empty",
        _set_evidence_nested("api", "preprocessing_contract", "alignment_template_id", "sface-5pt-112"),
        _invalid("preprocessing_contract_mismatch"),
        "aura_evidence/runtime_roles/<role>/preprocessing_contract/value/alignment_template_id",
    ),
    # Source and store join (API and worker must agree on the approved binary and database)
    Pair(
        "worker_source_git_sha_divergent_refused",
        "empty",
        _set_snapshot_role_field("worker", "source_git_sha", STALE_SOURCE_GIT_SHA),
        _invalid("role_source_identity_mismatch"),
        _ROLE_SOURCE,
    ),
    Pair(
        "stale_source_anchor_all_roles_unapproved_refused",
        "empty",
        _set_snapshot_all_roles("source_git_sha", STALE_SOURCE_GIT_SHA),
        _invalid("source_identity_unapproved"),
        _ROLE_SOURCE,
    ),
    Pair(
        "worker_source_tree_divergent_refused",
        "empty",
        _set_evidence("worker", "source_tree", STALE_SOURCE_TREE),
        _invalid("role_source_identity_mismatch"),
        _EVIDENCE_SOURCE_TREE,
    ),
    Pair(
        "source_tree_observation_declared_is_incomplete",
        "empty",
        _set_evidence_provenance("worker", "source_tree", "declared"),
        _incomplete("observation_provenance_declared"),
        _EVIDENCE_SOURCE_TREE,
    ),
    Pair(
        "worker_database_identity_divergent_refused",
        "empty",
        _set_evidence_nested("worker", "database_identity", "database_name", "alt_context_prod_auraface_replica"),
        _invalid("database_identity_divergent", "target_identity_mismatch"),
        _EVIDENCE_DBID,
    ),
    # Evidence binding (the sidecar must describe this snapshot)
    Pair(
        "evidence_bound_to_other_snapshot_refused",
        "enrolled",
        lambda case: case["aura_evidence"].__setitem__("snapshot_sha256", ALT_DIGEST),
        _invalid("evidence_snapshot_mismatch"),
        _EVIDENCE_DIGEST,
        rebind=False,
    ),
    # Shared rungs that the prefix rung masks today; they must keep their existing reasons
    Pair(
        "partial_loaded_weight_hashes_is_incomplete",
        "empty",
        lambda case: _all_roles(case["snapshot"], "loaded_weight_hashes", {"yunet": YUNET_SHA256}),
        _incomplete("incomplete_loaded_weight_hashes"),
        _ROLE_WEIGHTS,
    ),
    Pair(
        "foreign_auraface_weight_digest_refused",
        "empty",
        _set_snapshot_all_roles("loaded_weight_hashes", {"yunet": YUNET_SHA256, "auraface": ZERO_DIGEST}),
        _invalid("model_asset_hash_unexpected"),
        _ROLE_WEIGHTS,
    ),
    Pair(
        "worker_weight_hash_divergence_refused",
        "empty",
        lambda case: _worker(case["snapshot"], "loaded_weight_hashes", {"yunet": YUNET_SHA256, "auraface": ZERO_DIGEST}),
        _invalid("role_loaded_weight_hash_mismatch"),
        _ROLE_WEIGHTS,
    ),
    Pair(
        "centroid_width_128_refused",
        "empty",
        lambda case: _set_inventory_dimension(case["snapshot"], "centroid", 128),
        _invalid("database_dimension_mismatch"),
        _INVENTORY,
    ),
    Pair(
        "centroid_column_omitted_is_incomplete",
        "empty",
        lambda case: _drop_inventory_column(case["snapshot"], "centroid"),
        _incomplete("vector_column_coverage_incomplete"),
        _INVENTORY,
    ),
    Pair(
        "undiscovered_fourth_vector_column_is_incomplete",
        "empty",
        lambda case: _add_undiscovered_column(case["snapshot"]),
        _incomplete("vector_inventory_incomplete"),
        _INVENTORY,
    ),
    Pair(
        "vector_discovery_incomplete_is_incomplete",
        "empty",
        lambda case: _inventory(case).__setitem__("discovery_complete", False),
        _incomplete("vector_inventory_discovery_incomplete"),
        _INVENTORY,
    ),
    Pair(
        "sface_preprocessing_on_aura_identity_refused",
        "empty",
        _set_snapshot_all_roles("preprocessing_id", "sface-5pt-112"),
        _invalid("model_space_contract_mismatch"),
        _ROLE_PREPROC,
    ),
    Pair(
        "discovered_nonzero_fourth_column_is_incomplete",
        "empty",
        _add_nonzero_fourth_column,
        _incomplete("fir_store_state_unobserved"),
        "snapshot/database",
    ),
)
PAIR_IDS = [pair.case_id for pair in PAIRS]
assert len(PAIR_IDS) == len(set(PAIR_IDS)), "pair ids must be unique"


def _pair_case(pair: Pair) -> dict[str, Any]:
    case = _base_case(pair.base)
    pair.mutate(case)
    if pair.rebind:
        case["aura_evidence"]["snapshot_sha256"] = _snapshot_digest(case["snapshot"])
    return case


def _normalize_path(path: tuple[str, ...]) -> str:
    return "/".join("<role>" if key in ROLE_NAMES else key for key in path)


def _changed_factors(left: Any, right: Any, path: tuple[str, ...] = ()) -> set[str]:
    """Normalized paths whose value differs. Role-keyed observations and runtime roles collapse to <role>."""

    if isinstance(left, Mapping) and isinstance(right, Mapping):
        changed: set[str] = set()
        for key in set(left) | set(right):
            child = (*path, str(key))
            if key not in left or key not in right:
                changed.add(_normalize_path(child))
            else:
                changed |= _changed_factors(left[key], right[key], child)
        return changed
    if (
        isinstance(left, list)
        and isinstance(right, list)
        and path[-1:] == ("observations",)
        and len(left) == len(right)
        and all(isinstance(item, Mapping) and "role" in item for item in (*left, *right))
    ):
        left_by_role = {item["role"]: item for item in left}
        right_by_role = {item["role"]: item for item in right}
        if set(left_by_role) != set(right_by_role):
            return {_normalize_path(path)}
        changed = set()
        for role in left_by_role:
            changed |= _changed_factors(left_by_role[role], right_by_role[role], (*path, role))
        return changed
    if left != right:
        return {_normalize_path(path)}
    return set()


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


# --------------------------------------------------------------------------
# Future interface access: absence is a named marker, never behavioral proof
# --------------------------------------------------------------------------


def _future_entrypoint(case_id: str, expected: Expect) -> Callable[..., Mapping[str, Any]]:
    """Resolve the proposed entrypoint, or fail with a named FUTURE marker (never a bare ImportError).

    The absence is decided outside any ``except`` block so pytest cannot chain the import error
    into the report as if it were evidence.
    """

    status, exit_code, reasons = expected
    absent: str | None = None
    try:
        module = importlib.import_module(AURA_ENTRYPOINT_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != AURA_ENTRYPOINT_MODULE:
            raise
        module = None
        absent = f"{AURA_ENTRYPOINT_MODULE} is not importable"
    if module is not None:
        function = getattr(module, AURA_ENTRYPOINT, None)
        if callable(function):
            return function
        absent = f"{AURA_ENTRYPOINT} is not exposed by {AURA_ENTRYPOINT_MODULE}"
    pytest.fail(
        f"FUTURE-INTERFACE-ABSENT {case_id}: {absent}; pinned expectation status={status} "
        f"exit_code={exit_code} reason_code in {sorted(reasons)}. Repin proposal marker only; "
        "not behavioral evidence.",
        pytrace=False,
    )


def _future_acceptance(case_id: str, case: Mapping[str, Any], expected: Expect) -> dict[str, Any]:
    function = _future_entrypoint(case_id, expected)
    return dict(
        function(
            copy.deepcopy(case["snapshot"]),
            aura_evidence=copy.deepcopy(case["aura_evidence"]),
            freshness_policy=_fixture("freshness_policy.json"),
            isolation_policy=copy.deepcopy(case["isolation_policy"]),
            acceptance_policy=copy.deepcopy(case["acceptance_policy"]),
            now=NOW,
        )
    )


# --------------------------------------------------------------------------
# Controls: existing behavior on unchanged production
# --------------------------------------------------------------------------


def test_control_baseline_sface_identity_remains_ready_under_baseline128() -> None:
    result = _validate(_baseline_snapshot(), contract="baseline128")
    _assert_outcome(result, ("ready", 0, "ready"), "production SFace identity under baseline128")


def test_control_canonical_aura_prefix_is_emitter_framework_qualified() -> None:
    assert _aura_manifest().framework == "insightface"
    assert _canonical_aura_prefix() == "insightface-auraface+"
    assert _aura_model_id().startswith("insightface-auraface+")
    assert _aura_model_id().endswith("@512d/l2/cosine")


def test_control_obsolete_identity_differs_only_by_framework_prefix() -> None:
    obsolete = _obsolete_aura_model_id()
    assert obsolete.startswith("auraface+")
    assert obsolete.split("@", 1)[0].removeprefix("auraface+") == (
        _aura_model_id().split("@", 1)[0].removeprefix("insightface-auraface+")
    )
    assert obsolete.split("@", 1)[1] == _aura_model_id().split("@", 1)[1]


def test_control_sibling_insightface_identity_refused_under_candidate512() -> None:
    snapshot = _aura_snapshot()
    _all_roles(snapshot, "model_id", INSIGHTFACE_512_MODEL_ID)
    _assert_outcome(
        _validate(snapshot),
        ("invalid", 2, "model_space_contract_mismatch"),
        "sibling insightface-buffalo_l 512D identity under candidate512",
    )


@pytest.mark.parametrize(
    ("case_id", "mutate", "expected"),
    (
        pytest.param(
            "worker_runtime_token_divergence",
            lambda s: _worker(s, "model_id", "insightface-auraface+cv0.0.0/ort0.0/np0.0@512d/l2/cosine"),
            ("invalid", 2, "model_contract_mismatch"),
            id="worker_runtime_token_divergence",
        ),
        pytest.param(
            "worker_embedding_dimension_divergence",
            lambda s: _worker(s, "embedding_dimension", 128),
            ("invalid", 2, "role_embedding_dimension_mismatch"),
            id="worker_embedding_dimension_divergence",
        ),
        pytest.param(
            "worker_image_digest_divergence",
            lambda s: _worker(s, "image_digest", ALT_DIGEST),
            ("invalid", 2, "role_image_digest_mismatch"),
            id="worker_image_digest_divergence",
        ),
        pytest.param(
            "mutable_image_tag_on_all_roles",
            lambda s: _all_roles(s, "image_digest", "acx-prod-auraface:latest"),
            ("invalid", 2, "unpinned_image_digest"),
            id="mutable_image_tag_on_all_roles",
        ),
        pytest.param(
            "auth_disabled_on_api",
            lambda s: _role(s, "api")["auth_enabled"].__setitem__("value", False),
            ("invalid", 2, "auth_disabled"),
            id="auth_disabled_on_api",
        ),
    ),
)
def test_control_pre_prefix_rungs_refuse_each_defect(
    case_id: str,
    mutate: Callable[[dict[str, Any]], None],
    expected: Outcome,
) -> None:
    """These rungs run before the model-prefix rung, so production identity reaches them today."""

    snapshot = _aura_snapshot()
    mutate(snapshot)
    _assert_outcome(_validate(snapshot), expected, case_id)


def test_control_enumerated_sibling_identity_is_refused_by_isolation_rung() -> None:
    snapshot = _aura_snapshot(SIBLING_LABEL)
    policy = _isolation_policy(forbidden={"compose_projects": [f"acx-{SIBLING_LABEL}"]})
    _assert_outcome(
        _validate(snapshot, isolation=policy),
        ("invalid", 2, "forbidden_resource_id"),
        "staging sibling identity explicitly enumerated as forbidden",
    )


def test_control_shared_baseline_non_unit_representative_stays_ready() -> None:
    """Global norm guard: the shared store rung does not gain a norm requirement for baseline SFace."""

    snapshot = _baseline_snapshot()
    snapshot["database"]["store_state"] = {"value": "enrolled", "provenance": "database_catalog"}
    provenance = snapshot["database"]["embedding_provenance"]["value"]
    provenance["row_counts"] = dict.fromkeys(_inventory_identities(snapshot), 1)
    provenance["representative_vector"] = [1.0] * 128
    provenance["centroid"] = [1.0] * 128
    _assert_outcome(
        _validate(snapshot, contract="baseline128"),
        ("ready", 0, "ready"),
        "enrolled baseline SFace store with a non-unit 128-wide representative",
    )


def test_control_auraface_manifest_pins_weights_license_and_preprocessing() -> None:
    entry = MODEL_MANIFEST["auraface"]
    assert entry.sha256 == "a7933ea5330113b01c9b60351d8f4c33003f145d8470ac5f0e52ee2effe25c60"
    assert entry.size_bytes == 260_694_151
    assert entry.license_sha256 == "609e2cb599f84aaa41d8ef29d8fdb04d164fab22e8d9292ca34a599d0f56a338"
    assert AURAFACE_REVISION == entry.source_ref == "af6d057c9b0ec4071d4c49c80e3539258798b609"
    assert (entry.framework, entry.embedding_dim, entry.normalization, entry.metric) == (
        "insightface",
        512,
        "l2",
        "cosine",
    )
    preprocessing = entry.preprocessing
    assert preprocessing is not None
    assert preprocessing.input_size == (112, 112)
    assert preprocessing.channel_order == "RGB"
    assert preprocessing.input_mean == 127.5
    assert preprocessing.input_scale == pytest.approx(1.0 / 127.5)
    assert preprocessing.alignment_template_id == "arcface-112"
    assert preprocessing.output_l2_normalized is False
    assert _aura_preprocessing_id() == preprocessing.alignment_template_id


def test_control_observed_fixture_literals_match_source_pins() -> None:
    """Observed fixture literals equal the source authority; positives never derive from pins at runtime."""

    aura = MODEL_MANIFEST["auraface"]
    yunet = MODEL_MANIFEST["yunet"]
    preprocessing = aura.preprocessing
    assert preprocessing is not None
    assert OBSERVED_AURA_LICENSE_SHA256 == f"sha256:{aura.license_sha256}"
    assert OBSERVED_YUNET_LICENSE_SHA256 == f"sha256:{yunet.license_sha256}"
    assert tuple(OBSERVED_AURA_PREPROCESSING["input_size"]) == preprocessing.input_size
    assert OBSERVED_AURA_PREPROCESSING["channel_order"] == preprocessing.channel_order
    assert OBSERVED_AURA_PREPROCESSING["input_mean"] == preprocessing.input_mean
    assert OBSERVED_AURA_PREPROCESSING["input_scale"] == pytest.approx(preprocessing.input_scale)
    assert OBSERVED_AURA_PREPROCESSING["alignment_template_id"] == preprocessing.alignment_template_id
    assert OBSERVED_AURA_PREPROCESSING["output_l2_normalized"] is preprocessing.output_l2_normalized
    assert OBSERVED_AURA_PREPROCESSING["alignment_template_id"] == _aura_preprocessing_id()


def test_control_readiness_predicate_accepts_mixed_persisted_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: readiness alone is not exclusivity proof, so REDs below must live in acceptance."""

    monkeypatch.setattr(embedding_manifest, "active_embedding_model_id", _aura_model_id)
    result = health.check_active_embedding_model(persisted_model_ids=[_aura_model_id(), INSIGHTFACE_512_MODEL_ID])
    assert result.status is HealthStatus.OK, f"readiness status changed: {result.status!r} ({result.detail})"
    assert "persisted_spaces=2" in result.detail, f"unexpected readiness detail: {result.detail}"


@pytest.mark.parametrize("pair", PAIRS, ids=PAIR_IDS)
def test_control_future_pairs_mutate_only_declared_factor(pair: Pair) -> None:
    """Fixture integrity: each negative changes exactly its declared factor and nothing else."""

    before = _base_case(pair.base)
    after = copy.deepcopy(before)
    pair.mutate(after)
    changed = _changed_factors(before, after)
    if pair.factor_root is None:
        assert changed, f"{pair.case_id}: group factor did not change"
        assert before["isolation_policy"] == after["isolation_policy"], f"{pair.case_id}: policy changed"
        assert before["acceptance_policy"] == after["acceptance_policy"], f"{pair.case_id}: policy changed"
        assert all(path.split("/", 1)[0] in {"snapshot", "aura_evidence"} for path in changed), pair.case_id
        return
    if pair.factor_root == "":
        assert not changed, f"{pair.case_id}: positive control changed {sorted(changed)}"
        return
    assert changed, f"{pair.case_id}: declared factor {pair.factor_root!r} did not change"
    outside = sorted(path for path in changed if not _under(path, pair.factor_root))
    assert not outside, f"{pair.case_id}: changed outside declared factor {pair.factor_root!r}: {outside}"


# --------------------------------------------------------------------------
# Existing-behavior REDs: fail today through the shipped entrypoint
# --------------------------------------------------------------------------


def test_red_production_identity_refused_by_shipped_candidate512() -> None:
    """Existing RED. Rung: runtime contract, model prefix (validate_fir_dev_runtime.py:83 and :798).

    The production emitter writes ``insightface-auraface+...``. The shipped candidate512
    contract pins ``auraface+``, so the production identity is refused before any later rung runs.
    """

    snapshot = _aura_snapshot()
    model_id = snapshot["observations"][0]["model_id"]["value"]
    result = _validate(snapshot, contract="candidate512")
    _assert_outcome(
        result,
        ("ready", 0, "ready"),
        f"production-emitted AuraFace identity {model_id!r} under shipped candidate512 "
        f"(prefix {_validator().EXPECTED_CONTRACTS['candidate512']['model_name_prefix']!r})",
    )


def test_red_obsolete_auraface_prefix_identity_must_be_refused() -> None:
    """Existing RED, obsolete-prefix negative. The pre-correction ``auraface+`` identity must be refused.

    Today the shipped contract accepts it, which is the defect the production-prefix correction removes.
    """

    snapshot = _aura_snapshot(model_id=_obsolete_aura_model_id())
    result = _validate(snapshot, contract="candidate512")
    _assert_refused_for(
        result,
        frozenset({"model_space_contract_mismatch"}),
        f"obsolete identity {_obsolete_aura_model_id()!r} under shipped candidate512",
    )


# --------------------------------------------------------------------------
# Future Aura acceptance completeness contract (proposal; interface absent today)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("pair", PAIRS, ids=PAIR_IDS)
def test_future_aura_acceptance_contract(pair: Pair) -> None:
    case = _pair_case(pair)
    result = _future_acceptance(pair.case_id, case, pair.expected)
    _assert_expectation(result, pair.expected, pair.case_id)
