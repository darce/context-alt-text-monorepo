"""Offline R1/R2 and TEST-15 pins, using constructed frozen observations and real gates.

No collected runtime evidence is claimed. Inputs remain unchanged by validation.
TEST-15: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/engineering.md#test-15
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from recognition.tests.scripts.test_gtmc_aura_compound_roles import _strip_repair_snapshot
from recognition.tests.scripts.test_gtmr_aura_acceptance import (
    INSIGHTFACE_512_MODEL_ID,
    NOW,
    STALE_SOURCE_TREE,
    ZERO_DIGEST,
    _aura_case,
    _baseline_snapshot,
    _fixture,
    _role,
    _snapshot_digest,
)
from scripts import aura_target_store_gate as target
from scripts.validate_auraface_runtime import validate_aura_acceptance
from scripts.validate_fir_dev_runtime import validate_snapshot

REPAIR = "fix-blob-ownership"
IDENTITY_PATHS = (
    ("storage", "volume_ids"),
    ("storage", "network_ids"),
    ("storage", "compose_project"),
    ("database", "identity", "database_name"),
    ("database", "identity", "role"),
    ("storage", "blob_namespace"),
)
STORE_PATHS = (
    (("database", "store_state"), "fir_store_state_unobserved"),
    (("database", "embedding_provenance"), "embedding_provenance_unobserved"),
    (("database", "vector_column_inventory"), "vector_inventory_incomplete"),
)
MISSING_PATHS = tuple((path, "target_identity_unobserved") for path in IDENTITY_PATHS) + STORE_PATHS
RUNTIME_NULLS = (
    ("auth_enabled", "invalid", "auth_disabled"),
    ("model_id", "invalid", "unparseable_model_id"),
    ("loaded_weight_hashes", "incomplete", "incomplete_loaded_weight_hashes"),
    ("embedding_dimension", "invalid", "role_embedding_dimension_mismatch"),
    ("effective_profile", "invalid", "unexpected_face_pipeline_profile"),
    ("preprocessing_id", "invalid", "model_contract_mismatch"),
)


def _wrapper(case: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    current = case["snapshot"]
    for key in path:
        current = current[key]
    return current


def _facade(case: dict[str, Any]) -> dict[str, Any]:
    case["aura_evidence"]["snapshot_sha256"] = _snapshot_digest(case["snapshot"])
    before = copy.deepcopy(case)
    result = validate_aura_acceptance(
        case["snapshot"],
        aura_evidence=case["aura_evidence"],
        freshness_policy=_fixture("freshness_policy.json"),
        isolation_policy=case["isolation_policy"],
        acceptance_policy=case["acceptance_policy"],
        now=NOW,
    )
    assert case == before, "validation must not backfill or mutate observations"
    return result


def _shared(case: dict[str, Any], *, contract: str = "candidate512", aura: bool = True) -> dict[str, Any]:
    before = copy.deepcopy(case)
    result = validate_snapshot(
        case["snapshot"],
        freshness_policy=_fixture("freshness_policy.json"),
        isolation_policy=case["isolation_policy"],
        now=NOW,
        contract=contract,
        aura_acceptance=aura,
    )
    assert case == before, "shared validation must preserve observations"
    return result


def _assert_outcome(result: dict[str, Any], status: str, reason: str) -> None:
    assert (result["status"], result["exit_code"], result["reason_code"]) == (
        status, {"ready": 0, "incomplete": 1, "invalid": 2}[status], reason,
    )


@pytest.mark.parametrize(
    "field,value,reason",
    (
        ("auth_enabled", False, "auth_disabled"),
        ("model_id", INSIGHTFACE_512_MODEL_ID, "model_contract_mismatch"),
        ("model_id", "garbage", "unparseable_model_id"),
        ("loaded_weight_hashes", None, "role_loaded_weight_hash_mismatch"),
        ("embedding_dimension", 128, "role_embedding_dimension_mismatch"),
        ("effective_profile", "bogus", "unexpected_face_pipeline_profile"),
    ),
    ids=("auth_false", "sibling_model", "garbage_model", "wrong_weights", "dimension_128", "bogus_profile"),
)
def test_facade_full_repair_contradiction(field: str, value: Any, reason: str) -> None:
    case = _aura_case(store="enrolled")
    repair = _role(case["snapshot"], REPAIR)
    if field == "loaded_weight_hashes":
        repair[field]["value"]["auraface"] = ZERO_DIGEST
    else:
        repair[field]["value"] = value
    _assert_outcome(_facade(case), "invalid", reason)


@pytest.mark.parametrize("field,status,reason", RUNTIME_NULLS, ids=[row[0] for row in RUNTIME_NULLS])
def test_facade_full_repair_null_runtime(field: str, status: str, reason: str) -> None:
    case = _aura_case(store="enrolled")
    _role(case["snapshot"], REPAIR)[field]["value"] = None
    _assert_outcome(_facade(case), status, reason)


def test_facade_full_repair_all_runtime_null_is_refused() -> None:
    case = _aura_case(store="enrolled")
    repair = _role(case["snapshot"], REPAIR)
    for field, _, _ in RUNTIME_NULLS:
        repair[field]["value"] = None
    _assert_outcome(_facade(case), "invalid", "unparseable_model_id")


@pytest.mark.parametrize("path,reason", MISSING_PATHS, ids=[".".join(row[0]) for row in MISSING_PATHS])
@pytest.mark.parametrize("member", ("value", "provenance"))
def test_facade_missing_target_wrapper_is_incomplete(path: tuple[str, ...], reason: str, member: str) -> None:
    case = _aura_case(store="enrolled")
    del _wrapper(case, path)[member]
    _assert_outcome(_facade(case), "incomplete", reason)


@pytest.mark.parametrize("path", IDENTITY_PATHS + (STORE_PATHS[2][0],), ids=lambda path: ".".join(path))
@pytest.mark.parametrize("member", ("value", "provenance"))
@pytest.mark.parametrize("contradiction", ("auth", "source_tree"))
def test_facade_missing_wrapper_keeps_present_contradiction(
    path: tuple[str, ...], member: str, contradiction: str,
) -> None:
    case = _aura_case(store="enrolled")
    del _wrapper(case, path)[member]
    if contradiction == "auth":
        _role(case["snapshot"], "worker")["auth_enabled"]["value"] = False
        reason = "auth_disabled"
    else:
        case["aura_evidence"]["runtime_roles"]["worker"]["source_tree"]["value"] = STALE_SOURCE_TREE
        reason = "role_source_identity_mismatch"
    _assert_outcome(_facade(case), "invalid", reason)


@pytest.mark.parametrize("role", ("api", "worker"))
@pytest.mark.parametrize("missing", ("null", "empty", "partial"))
def test_shared_present_weight_contradiction_outranks_incomplete(role: str, missing: str) -> None:
    case = _aura_case(store="enrolled")
    weights = _role(case["snapshot"], role)["loaded_weight_hashes"]
    if missing == "null":
        weights["value"] = None
    elif missing == "empty":
        weights["value"] = {}
    else:
        del weights["value"]["auraface"]
    peer = "worker" if role == "api" else "api"
    _role(case["snapshot"], peer)["loaded_weight_hashes"]["value"]["auraface"] = ZERO_DIGEST
    _assert_outcome(_shared(case), "invalid", "role_loaded_weight_hash_mismatch")


@pytest.mark.parametrize("role", ("api", "worker"))
@pytest.mark.parametrize("contradiction", ("stamp", "vector"))
def test_shared_continues_after_incomplete_to_store_contradiction(role: str, contradiction: str) -> None:
    case = _aura_case(store="enrolled")
    _role(case["snapshot"], role)["loaded_weight_hashes"]["value"] = None
    summary = case["snapshot"]["database"]["embedding_provenance"]["value"]
    if contradiction == "stamp":
        summary["model_id"] = INSIGHTFACE_512_MODEL_ID
        reason = "persisted_model_stamp_mismatch"
    else:
        summary["representative_vector"][0] = float("nan")
        reason = "non_finite_persisted_vector"
    _assert_outcome(_shared(case), "invalid", reason)


@pytest.mark.parametrize("missing", ("store_wrapper", "persisted_ids", "identity_wrapper"))
def test_target_collects_contradiction_after_missing_evidence(missing: str) -> None:
    case = _aura_case(store="enrolled")
    if missing == "store_wrapper":
        del case["snapshot"]["database"]["store_state"]["provenance"]
    elif missing == "persisted_ids":
        del case["snapshot"]["database"]["embedding_provenance"]["value"]["persisted_model_ids"]
    else:
        del case["snapshot"]["storage"]["volume_ids"]["value"]
    case["snapshot"]["storage"]["network_ids"]["value"] = ["acx-wrong-target-net"]
    assert target.validate_target_store(
        case["snapshot"], isolation_policy=case["isolation_policy"], acceptance_policy=case["acceptance_policy"],
    ) == ("invalid", "target_identity_mismatch")


@pytest.mark.parametrize(
    "model_id,expected",
    ((INSIGHTFACE_512_MODEL_ID, ("invalid", "model_contract_mismatch")),
     (None, ("incomplete", "active_stamp_unobserved"))),
    ids=("sibling", "null"),
)
def test_target_full_repair_stamp_is_checked(model_id: Any, expected: tuple[str, str]) -> None:
    case = _aura_case(store="enrolled")
    _role(case["snapshot"], REPAIR)["model_id"]["value"] = model_id
    assert target.validate_target_store(
        case["snapshot"], isolation_policy=case["isolation_policy"], acceptance_policy=case["acceptance_policy"],
    ) == expected


@pytest.mark.parametrize("identity_only", (False, True), ids=("full", "identity_only"))
def test_healthy_repair_shapes_are_ready_without_backfill(identity_only: bool) -> None:
    case = _aura_case(store="enrolled")
    if identity_only:
        _strip_repair_snapshot(case["snapshot"])
    _assert_outcome(_facade(case), "ready", "ready")
    if identity_only:
        assert set(_role(case["snapshot"], REPAIR)) == {"role", "image_digest", "source_git_sha"}


@pytest.mark.parametrize("contract", ("candidate512", "baseline128"))
def test_strict_defaults_refuse_identity_only_repair(contract: str) -> None:
    case = _aura_case()
    if contract == "baseline128":
        case["snapshot"] = _baseline_snapshot()
    _strip_repair_snapshot(case["snapshot"])
    _assert_outcome(_shared(case, contract=contract, aura=False), "invalid", "snapshot_schema_invalid")


def test_aura_mode_rejects_baseline128() -> None:
    with pytest.raises(ValueError, match="Aura acceptance requires candidate512"):
        _shared(_aura_case(), contract="baseline128")


# C82 F1/F4: missing target identity must not hide a present store contradiction.
@pytest.mark.parametrize("path", IDENTITY_PATHS, ids=lambda path: ".".join(path))
@pytest.mark.parametrize("member", ("value", "provenance"))
def test_missing_identity_keeps_persisted_sibling_invalid(path: tuple[str, ...], member: str) -> None:
    case = _aura_case(store="enrolled")
    del _wrapper(case, path)[member]
    case["snapshot"]["database"]["embedding_provenance"]["value"]["persisted_model_ids"] = [
        INSIGHTFACE_512_MODEL_ID,
    ]
    before = copy.deepcopy(case)
    assert target.validate_target_store(
        case["snapshot"], isolation_policy=case["isolation_policy"], acceptance_policy=case["acceptance_policy"],
    ) == ("invalid", "persisted_model_stamp_mismatch")
    assert case == before
    _assert_outcome(_facade(case), "invalid", "persisted_model_stamp_mismatch")


# C82R-HV1-F1: missing store wrappers cannot hide an authoritative census contradiction.
@pytest.mark.parametrize("path", (STORE_PATHS[0][0], STORE_PATHS[2][0]), ids=lambda path: ".".join(path))
@pytest.mark.parametrize("member", ("value", "provenance"))
def test_missing_store_wrapper_keeps_persisted_sibling_invalid(path: tuple[str, ...], member: str) -> None:
    case = _aura_case(store="enrolled")
    summary = case["snapshot"]["database"]["embedding_provenance"]["value"]
    summary["persisted_model_ids"] = [INSIGHTFACE_512_MODEL_ID]
    before = copy.deepcopy(case)
    assert target.validate_target_store(
        case["snapshot"], isolation_policy=case["isolation_policy"], acceptance_policy=case["acceptance_policy"],
    ) == ("invalid", "persisted_model_stamp_mismatch")
    assert case == before
    _assert_outcome(_facade(case), "invalid", "persisted_model_stamp_mismatch")
    del _wrapper(case, path)[member]
    before = copy.deepcopy(case)
    assert target.validate_target_store(
        case["snapshot"], isolation_policy=case["isolation_policy"], acceptance_policy=case["acceptance_policy"],
    ) == ("invalid", "persisted_model_stamp_mismatch")
    assert case == before
    _assert_outcome(_facade(case), "invalid", "persisted_model_stamp_mismatch")


def test_missing_store_state_with_persisted_sibling_cli_exits_invalid(tmp_path: Path) -> None:
    case = _aura_case(store="enrolled")
    case["snapshot"]["database"]["embedding_provenance"]["value"]["persisted_model_ids"] = [
        INSIGHTFACE_512_MODEL_ID,
    ]
    del case["snapshot"]["database"]["store_state"]["value"]
    case["aura_evidence"]["snapshot_sha256"] = _snapshot_digest(case["snapshot"])
    inputs = {**case, "freshness_policy": _fixture("freshness_policy.json")}
    command = [sys.executable, "-B", "-m", "scripts.validate_auraface_runtime", "--now", NOW]
    for key in ("snapshot", "aura_evidence", "isolation_policy", "acceptance_policy", "freshness_policy"):
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps(inputs[key]), encoding="utf-8")
        command.extend((f"--{key.replace('_', '-')}", str(path)))
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2, result.stdout
    _assert_outcome(json.loads(result.stdout), "invalid", "persisted_model_stamp_mismatch")


# C82 F2: the missing-member exemption belongs exclusively to Aura acceptance.
@pytest.mark.parametrize("contract", ("candidate512", "baseline128"))
@pytest.mark.parametrize("path", IDENTITY_PATHS + (STORE_PATHS[2][0],), ids=lambda path: ".".join(path))
@pytest.mark.parametrize("member", ("value", "provenance"))
def test_strict_missing_wrapper_is_invalid(contract: str, path: tuple[str, ...], member: str) -> None:
    case = _aura_case(store="enrolled")
    if contract == "baseline128":
        case["snapshot"] = _baseline_snapshot()
    del _wrapper(case, path)[member]
    _assert_outcome(_shared(case, contract=contract, aura=False), "invalid", "malformed_observation_wrapper")


# C82 F3: missing evidence does not admit unknown wrapper keys.
@pytest.mark.parametrize("path,reason", MISSING_PATHS, ids=[".".join(row[0]) for row in MISSING_PATHS])
@pytest.mark.parametrize("member", ("value", "provenance"))
def test_missing_wrapper_with_extra_key_is_invalid(path: tuple[str, ...], reason: str, member: str) -> None:
    case = _aura_case(store="enrolled")
    wrapper = _wrapper(case, path)
    del wrapper[member]
    wrapper["unknown_evidence_key"] = "constructed"
    _assert_outcome(_facade(case), "invalid", "malformed_observation_wrapper")
