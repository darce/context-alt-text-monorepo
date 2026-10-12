"""GTMR Aura acceptance: causal RED for the target-bound recognition contract.

First artifact of the RED-only authoring lane. It runs against unchanged
production code and does not import the not-yet-written
``scripts/validate_auraface_runtime.py``; every RED fails on a real behavioral
mismatch, never on a missing module.

Surfaces exercised, all offline (no DB, network, GPU, secrets, or model load):

* ``scripts.validate_fir_dev_runtime.validate_snapshot`` under the shared
  ``candidate512`` contract, using the existing FIR snapshot and policy
  fixtures as base observations;
* production identity emitters: ``auraface_embedding_model_manifest``,
  ``sface_embedding_model_manifest``, ``FivePointAligner``, ``MODEL_MANIFEST``;
* ``recognition.application.health.check_active_embedding_model`` for the
  readiness-only characterization.

Classification
--------------
``test_control_*``  pass on unchanged production and pin behavior the
                    implementation must keep.
``test_red_*``      fail on unchanged production on a real mismatch with the
                    Aura acceptance contract; each names the rung that accepts
                    or refuses incorrectly.

Prefix overlay
--------------
The shared ``candidate512`` contract pins ``model_name_prefix = "auraface+"``.
The production adapter emits ``insightface-auraface+<space>@512d/l2/cosine``
because ``EmbeddingModelManifest.model_id`` prepends the framework. Against the
shipped contract, every production-true AuraFace snapshot is refused at the
runtime-contract rung before the store, target, and vector rungs run. Controls
and REDs for those later rungs therefore use the ``aura_prefix_overlay``
fixture: a test-local monkeypatch that changes only that prefix and is restored
afterwards. ``test_red_production_identity_refused_by_shipped_candidate512``
measures the shipped contract with no overlay, and
``test_control_prefix_overlay_alone_accepts_production_identity`` shows the
overlay is the only difference.

Acceptance inputs proposed by these REDs (not yet implemented)
--------------------------------------------------------------
``isolation_policy["required_target_resource_ids"]``
    Positive identities of the declared target, using the existing isolation
    categories. An observed identity outside this set is refused.
``embedding_provenance.value["persisted_model_ids"]``
    Every persisted model stamp in the store. Vocabulary follows
    ``check_active_embedding_model(persisted_model_ids=...)``.
"""

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Callable, Iterator, Mapping
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
NOW = "2026-09-20T12:01:00Z"
AURA_LABEL = "prod-auraface"
SIBLING_LABEL = "staging-auraface"
VECTOR_DIM = 512
YUNET_SHA256 = f"sha256:{MODEL_MANIFEST['yunet'].sha256}"
AURA_WEIGHT_SHA256 = f"sha256:{MODEL_MANIFEST['auraface'].sha256}"
AURA_LICENSE_SHA256 = f"sha256:{MODEL_MANIFEST['auraface'].license_sha256}"
INSIGHTFACE_512_MODEL_ID = "insightface-buffalo_l+cv5.0@512d/l2/cosine"
ZERO_DIGEST = "sha256:" + "0" * 64
ALT_DIGEST = "sha256:" + "2" * 64
VECTOR_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("public", "media_identities", "embedding"),
    ("public", "identity_cluster_representatives", "embedding"),
    ("public", "mv_identity_cluster_centroids", "centroid"),
)

Outcome = tuple[str, int, str]


# --------------------------------------------------------------------------
# Fixtures and identity builders (existing fixtures; production emitters)
# --------------------------------------------------------------------------


def _validator() -> Any:
    return importlib.import_module(VALIDATOR_MODULE)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _aura_model_id() -> str:
    return auraface_embedding_model_manifest().model_id


def _aura_contract_prefix() -> str:
    return f"{auraface_embedding_model_manifest().framework}-auraface+"


def _aura_preprocessing_id() -> str:
    return FivePointAligner(space=ModelSpace.AURAFACE).template_id


def _sface_model_id() -> str:
    return sface_embedding_model_manifest().model_id


def _unit_vector(dimension: int) -> list[float]:
    component = 1.0 / math.sqrt(dimension)
    return [component] * dimension


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


def _aura_snapshot(label: str = AURA_LABEL, *, store: str = "empty") -> dict[str, Any]:
    """Production-shaped AuraFace observations for one target on the FIR snapshot fixture."""

    snapshot = _fixture("valid_empty_fir_store.json")
    target = _target_identities(label)
    model_id = _aura_model_id()
    preprocessing_id = _aura_preprocessing_id()
    for record in snapshot["observations"]:
        record["effective_profile"]["value"] = "auraface"
        record["embedding_dimension"]["value"] = VECTOR_DIM
        record["model_id"]["value"] = model_id
        record["preprocessing_id"]["value"] = preprocessing_id
        record["loaded_weight_hashes"]["value"] = {"yunet": YUNET_SHA256, "auraface": AURA_WEIGHT_SHA256}
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
            "model_id": model_id,
            "preprocessing_id": preprocessing_id,
            "representative_vector": list(sample),
            "centroid": list(sample),
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


def _string_leaves(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _string_leaves(child)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for child in value:
            yield from _string_leaves(child)
    elif isinstance(value, str):
        yield value


@pytest.fixture
def aura_prefix_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test-local correction of only ``candidate512.model_name_prefix``; restored after each test."""

    monkeypatch.setitem(_validator().EXPECTED_CONTRACTS["candidate512"], "model_name_prefix", _aura_contract_prefix())


# --------------------------------------------------------------------------
# Controls: pass on unchanged production; pin behavior that must be kept
# --------------------------------------------------------------------------


def test_control_baseline_sface_identity_remains_ready_under_baseline128() -> None:
    result = _validate(_baseline_snapshot(), contract="baseline128")
    _assert_outcome(result, ("ready", 0, "ready"), "production SFace identity under baseline128")


def test_control_prefix_overlay_alone_accepts_production_identity(aura_prefix_overlay: None) -> None:
    result = _validate(_aura_snapshot())
    _assert_outcome(result, ("ready", 0, "ready"), "production AuraFace identity, empty store, prefix overlay only")


@pytest.mark.parametrize(
    ("case_id", "mutate", "expected"),
    (
        pytest.param(
            "sibling_insightface_512_identity",
            lambda s: _all_roles(s, "model_id", INSIGHTFACE_512_MODEL_ID),
            ("invalid", 2, "model_space_contract_mismatch"),
            id="sibling_insightface_512_identity",
        ),
        pytest.param(
            "sface_preprocessing_on_aura_identity",
            lambda s: _all_roles(s, "preprocessing_id", "sface-5pt-112"),
            ("invalid", 2, "model_space_contract_mismatch"),
            id="sface_preprocessing_on_aura_identity",
        ),
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
            "partial_loaded_weight_hashes",
            lambda s: _all_roles(s, "loaded_weight_hashes", {"yunet": YUNET_SHA256}),
            ("incomplete", 1, "incomplete_loaded_weight_hashes"),
            id="partial_loaded_weight_hashes",
        ),
        pytest.param(
            "foreign_auraface_weight_digest",
            lambda s: _all_roles(s, "loaded_weight_hashes", {"yunet": YUNET_SHA256, "auraface": ZERO_DIGEST}),
            ("invalid", 2, "model_asset_hash_unexpected"),
            id="foreign_auraface_weight_digest",
        ),
        pytest.param(
            "worker_weight_hash_divergence",
            lambda s: _worker(s, "loaded_weight_hashes", {"yunet": YUNET_SHA256, "auraface": ZERO_DIGEST}),
            ("invalid", 2, "role_loaded_weight_hash_mismatch"),
            id="worker_weight_hash_divergence",
        ),
        pytest.param(
            "centroid_width_128",
            lambda s: _set_inventory_dimension(s, "centroid", 128),
            ("invalid", 2, "database_dimension_mismatch"),
            id="centroid_width_128",
        ),
        pytest.param(
            "centroid_column_omitted",
            lambda s: _drop_inventory_column(s, "centroid"),
            ("incomplete", 1, "vector_column_coverage_incomplete"),
            id="centroid_column_omitted",
        ),
        pytest.param(
            "undiscovered_fourth_vector_column",
            _add_undiscovered_column,
            ("incomplete", 1, "vector_inventory_incomplete"),
            id="undiscovered_fourth_vector_column",
        ),
        pytest.param(
            "vector_discovery_incomplete",
            lambda s: s["database"]["vector_column_inventory"].__setitem__("discovery_complete", False),
            ("incomplete", 1, "vector_inventory_discovery_incomplete"),
            id="vector_discovery_incomplete",
        ),
    ),
)
def test_control_aura_contract_rungs_refuse_each_defect(
    aura_prefix_overlay: None,
    case_id: str,
    mutate: Callable[[dict[str, Any]], None],
    expected: Outcome,
) -> None:
    snapshot = _aura_snapshot()
    mutate(snapshot)
    _assert_outcome(_validate(snapshot), expected, case_id)


def test_control_enrolled_aura_store_with_unit_representative_is_ready(aura_prefix_overlay: None) -> None:
    snapshot = _aura_snapshot(store="enrolled")
    _assert_outcome(_validate(snapshot), ("ready", 0, "ready"), "enrolled AuraFace store, unit vectors")


def test_control_enrolled_aura_store_refuses_foreign_model_stamp(aura_prefix_overlay: None) -> None:
    snapshot = _aura_snapshot(store="enrolled")
    snapshot["database"]["embedding_provenance"]["value"]["model_id"] = INSIGHTFACE_512_MODEL_ID
    _assert_outcome(
        _validate(snapshot),
        ("invalid", 2, "persisted_model_stamp_mismatch"),
        "enrolled AuraFace store with foreign model stamp",
    )


def test_control_enrolled_aura_store_refuses_wrong_length_representative(aura_prefix_overlay: None) -> None:
    snapshot = _aura_snapshot(store="enrolled")
    snapshot["database"]["embedding_provenance"]["value"]["representative_vector"] = _unit_vector(128)
    _assert_outcome(
        _validate(snapshot),
        ("invalid", 2, "non_finite_persisted_vector"),
        "enrolled AuraFace store with 128-wide representative",
    )


def test_control_enrolled_aura_store_accepts_matching_persisted_model_ids(aura_prefix_overlay: None) -> None:
    snapshot = _aura_snapshot(store="enrolled")
    snapshot["database"]["embedding_provenance"]["value"]["persisted_model_ids"] = [_aura_model_id()]
    _assert_outcome(
        _validate(snapshot),
        ("ready", 0, "ready"),
        "enrolled AuraFace store whose only persisted model id is the target model",
    )


def test_control_enumerated_sibling_identity_is_refused_today() -> None:
    snapshot = _aura_snapshot(SIBLING_LABEL)
    policy = _isolation_policy(forbidden={"compose_projects": [f"acx-{SIBLING_LABEL}"]})
    _assert_outcome(
        _validate(snapshot, isolation=policy),
        ("invalid", 2, "forbidden_resource_id"),
        "staging sibling identity explicitly enumerated as forbidden",
    )


def test_control_target_bound_policy_accepts_the_declared_target(aura_prefix_overlay: None) -> None:
    snapshot = _aura_snapshot(AURA_LABEL)
    _assert_outcome(
        _validate(snapshot, isolation=_isolation_policy(target=AURA_LABEL)),
        ("ready", 0, "ready"),
        "production target identities under a target-bound policy",
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


def test_control_readiness_predicate_accepts_mixed_persisted_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: readiness alone is not exclusivity proof, so REDs below must live in acceptance."""

    monkeypatch.setattr(embedding_manifest, "active_embedding_model_id", _aura_model_id)
    result = health.check_active_embedding_model(persisted_model_ids=[_aura_model_id(), INSIGHTFACE_512_MODEL_ID])
    assert result.status is HealthStatus.OK, f"readiness status changed: {result.status!r} ({result.detail})"
    assert "persisted_spaces=2" in result.detail, f"unexpected readiness detail: {result.detail}"


# --------------------------------------------------------------------------
# REDs: fail on unchanged production with a real behavioral mismatch
# --------------------------------------------------------------------------


def test_red_production_identity_refused_by_shipped_candidate512() -> None:
    """Rung: runtime contract (model prefix). The production AuraFace identity must be accepted.

    Shipped contract pins ``auraface+``; the adapter emits ``insightface-auraface+``.
    The FIR validator suite builds its candidate512 snapshots with the fixture-only ``auraface+`` form,
    which the shipped contract accepts, so that suite never exercises the identity production emits.
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


def test_red_non_unit_aura_representative_vector_is_refused(aura_prefix_overlay: None) -> None:
    """Rung: persisted-store vector check. Production embeddings are L2-normalized (``raw / norm``).

    The shipped check tests only finiteness and width, so a finite, non-unit 512-wide vector is accepted.
    """

    snapshot = _aura_snapshot(store="enrolled")
    snapshot["database"]["embedding_provenance"]["value"]["representative_vector"] = [1.0] * VECTOR_DIM
    result = _validate(snapshot)
    _assert_refused_for(
        result,
        frozenset({"non_normalized_persisted_vector", "non_finite_persisted_vector"}),
        "enrolled AuraFace store whose representative vector has L2 norm sqrt(512)",
    )


def test_red_unenumerated_sibling_store_refused_when_target_bound(aura_prefix_overlay: None) -> None:
    """Rung: target identity. A staging store must be refused under a prod-auraface target, even when unlisted.

    Shipped isolation only refuses identities explicitly enumerated as forbidden.
    """

    snapshot = _aura_snapshot(SIBLING_LABEL)
    result = _validate(snapshot, isolation=_isolation_policy(target=AURA_LABEL))
    _assert_refused_for(
        result,
        frozenset({"target_identity_mismatch", "forbidden_resource_id"}),
        f"staging-auraface store observed under a {AURA_LABEL} target-bound policy",
    )


def test_red_candidate512_contract_pins_auraface_license_digest() -> None:
    """Literal config contract: the Aura acceptance contract must pin the license digest, not only weights."""

    contract = _validator().EXPECTED_CONTRACTS["candidate512"]
    pinned = set(_string_leaves(contract))
    assert AURA_LICENSE_SHA256 in pinned, (
        f"candidate512 must pin the AuraFace license digest {AURA_LICENSE_SHA256}; "
        f"pinned top-level keys={sorted(contract)}; asset_hashes keys={sorted(contract['asset_hashes'])}"
    )


def test_red_enrolled_aura_store_refuses_mixed_persisted_model_ids(aura_prefix_overlay: None) -> None:
    """Rung: persisted-store model stamps. A gallery holding a foreign persisted model is not exclusively Aura.

    Readiness accepts this (see the readiness characterization control). The acceptance contract must not.
    """

    snapshot = _aura_snapshot(store="enrolled")
    snapshot["database"]["embedding_provenance"]["value"]["persisted_model_ids"] = [
        _aura_model_id(),
        INSIGHTFACE_512_MODEL_ID,
    ]
    result = _validate(snapshot)
    _assert_refused_for(
        result,
        frozenset({"persisted_model_stamp_mismatch", "mixed_persisted_models"}),
        "enrolled AuraFace store with persisted_model_ids = [aura, insightface-512]",
    )
