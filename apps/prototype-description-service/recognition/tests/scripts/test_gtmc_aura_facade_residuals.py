"""Offline c82 residual pins; constructed observations are not runtime evidence.

TEST-15: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/engineering.md#test-15
"""
import copy
import json
import subprocess
import sys

import pytest

from recognition.tests.scripts.test_gtmc_aura_compound_roles import _strip_repair_snapshot
from recognition.tests.scripts.test_gtmc_aura_v1_r3_pins import (
    MISSING_PATHS, IDENTITY_PATHS, _assert_outcome, _facade, _shared, _wrapper,
)
from recognition.tests.scripts.test_gtmr_aura_acceptance import (
    NOW, STALE_SOURCE_TREE, ZERO_DIGEST, _aura_case, _baseline_snapshot, _fixture, _role, _snapshot_digest,
)
from scripts.aura_loaded_runtime_gate import validate_loaded_runtime


@pytest.mark.parametrize("role", ("api", "worker"))
@pytest.mark.parametrize("wrong_field,missing_field", (("database_name", "role"), ("role", "database_name")))
@pytest.mark.parametrize("layer", ("helper", "facade"))
def test_partial_snapshot_identity_keeps_sidecar_contradiction(role, wrong_field, missing_field, layer):
    # Fold both missing modes into each row, retaining a full-record control.
    for missing_member in (None, "value", "provenance"):
        case = _aura_case(store="enrolled")
        identity = case["aura_evidence"]["runtime_roles"][role]["database_identity"]
        assert identity["provenance"] == "database_catalog"
        identity["value"][wrong_field] = "constructed_wrong_identity"
        if missing_member is not None:
            del case["snapshot"]["database"]["identity"][missing_field][missing_member]
        case["aura_evidence"]["snapshot_sha256"] = _snapshot_digest(case["snapshot"])
        before = copy.deepcopy(case)
        if layer == "facade":
            _assert_outcome(_facade(case), "invalid", "database_identity_divergent")
        else:
            assert validate_loaded_runtime(
                case["snapshot"], aura_evidence=case["aura_evidence"],
                acceptance_policy=case["acceptance_policy"],
            ) == ("invalid", "database_identity_divergent"), missing_member
        assert case == before


@pytest.mark.parametrize("wrong_field,missing_field", (("database_name", "role"), ("role", "database_name")))
def test_partial_snapshot_identity_cli_exits_invalid(tmp_path, wrong_field, missing_field):
    for missing_member in ("value", "provenance"):
        case = _aura_case(store="enrolled")
        identity = case["aura_evidence"]["runtime_roles"]["api"]["database_identity"]
        assert identity["provenance"] == "database_catalog"
        identity["value"][wrong_field] = "constructed_wrong_identity"
        del case["snapshot"]["database"]["identity"][missing_field][missing_member]
        case["aura_evidence"]["snapshot_sha256"] = _snapshot_digest(case["snapshot"])
        before = copy.deepcopy(case)
        inputs = {**case, "freshness_policy": _fixture("freshness_policy.json")}
        command = [sys.executable, "-B", "-m", "scripts.validate_auraface_runtime", "--now", NOW]
        for key in ("snapshot", "aura_evidence", "isolation_policy", "acceptance_policy", "freshness_policy"):
            path = tmp_path / f"{key}.json"
            path.write_text(json.dumps(inputs[key]), encoding="utf-8")
            command.extend((f"--{key.replace('_', '-')}", str(path)))
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        assert result.returncode == 2, (missing_member, result.stdout)
        _assert_outcome(json.loads(result.stdout), "invalid", "database_identity_divergent")
        assert case == before
        for key in inputs:
            assert json.loads((tmp_path / f"{key}.json").read_text(encoding="utf-8")) == inputs[key]


def test_role03_identity_only_producer_is_ready():
    case = _aura_case(store="enrolled")
    _strip_repair_snapshot(case["snapshot"])
    _assert_outcome(_facade(case), "ready", "ready")
    assert set(_role(case["snapshot"], "fix-blob-ownership")) == {"role", "image_digest", "source_git_sha"}


@pytest.mark.parametrize("missing", ("worker", "census"))
@pytest.mark.parametrize("contradiction", ("schema", "auth", "source"))
def test_compound01_present_contradiction_wins(missing, contradiction):
    case = _aura_case(store="enrolled")
    if missing == "worker":
        del case["aura_evidence"]["runtime_roles"]["worker"]
    else:
        del case["snapshot"]["database"]["embedding_provenance"]["value"]["persisted_model_ids"]
    if contradiction == "schema":
        case["aura_evidence"]["schema_version"] = 2
        reason = "unsupported_aura_evidence_schema"
    elif contradiction == "auth":
        _role(case["snapshot"], "api")["auth_enabled"]["value"] = False
        reason = "auth_disabled"
    else:
        case["aura_evidence"]["runtime_roles"]["api"]["source_tree"]["value"] = STALE_SOURCE_TREE
        reason = "source_identity_unapproved" if missing == "worker" else "role_source_identity_mismatch"
    _assert_outcome(_facade(case), "invalid", reason)


@pytest.mark.parametrize("role", ("api", "worker"))
@pytest.mark.parametrize("family", ("license", "weights", "preprocessing"))
@pytest.mark.parametrize("layer", ("helper", "facade"))
def test_partial02_present_field_is_compared(role, family, layer):
    case = _aura_case(store="enrolled")
    evidence = case["aura_evidence"]["runtime_roles"][role]
    if family == "license":
        value = evidence["loaded_license_hashes"]["value"]
        del value["yunet"]
        value["auraface"] = ZERO_DIGEST
        reason = "role_license_hash_mismatch"
    elif family == "weights":
        value = _role(case["snapshot"], role)["loaded_weight_hashes"]["value"]
        del value["yunet"]
        value["auraface"] = ZERO_DIGEST
        reason = "role_loaded_weight_hash_mismatch"
    else:
        value = evidence["preprocessing_contract"]["value"]
        del value["input_size"]
        value["channel_order"] = "BGR"
        reason = "preprocessing_contract_mismatch"
    if layer == "facade":
        _assert_outcome(_facade(case), "invalid", reason)
    else:
        case["aura_evidence"]["snapshot_sha256"] = _snapshot_digest(case["snapshot"])
        before = copy.deepcopy(case)
        assert validate_loaded_runtime(case["snapshot"], aura_evidence=case["aura_evidence"], acceptance_policy=case["acceptance_policy"]) == ("invalid", reason)
        assert case == before


@pytest.mark.parametrize("role", ("api", "worker"))
@pytest.mark.parametrize("wrong_field,missing_field", (("database_name", "role"), ("role", "database_name")))
@pytest.mark.parametrize("layer", ("helper", "facade"))
def test_db_identity_present_contradiction_wins(role, wrong_field, missing_field, layer):
    case = _aura_case(store="enrolled")
    identity = case["aura_evidence"]["runtime_roles"][role]["database_identity"]
    assert identity["provenance"] == "database_catalog"
    identity["value"][wrong_field] = "constructed_wrong_identity"

    def assert_invalid():
        if layer == "facade":
            _assert_outcome(_facade(case), "invalid", "database_identity_divergent")
        else:
            case["aura_evidence"]["snapshot_sha256"] = _snapshot_digest(case["snapshot"])
            before = copy.deepcopy(case)
            assert validate_loaded_runtime(
                case["snapshot"], aura_evidence=case["aura_evidence"],
                acceptance_policy=case["acceptance_policy"],
            ) == ("invalid", "database_identity_divergent")
            assert case == before

    assert_invalid()
    del identity["value"][missing_field]
    assert_invalid()


@pytest.mark.parametrize("path,reason", MISSING_PATHS, ids=[".".join(p) for p, _ in MISSING_PATHS])
@pytest.mark.parametrize("member", ("value", "provenance"))
def test_r2_missing_member_is_incomplete(path, reason, member):
    case = _aura_case(store="enrolled")
    del _wrapper(case, path)[member]
    _assert_outcome(_facade(case), "incomplete", reason)


@pytest.mark.parametrize("contract", ("candidate512", "baseline128"))
@pytest.mark.parametrize("path", IDENTITY_PATHS + (("database", "vector_column_inventory"),), ids=lambda p: ".".join(p))
@pytest.mark.parametrize("member", ("value", "provenance"))
def test_f2_strict_mode_keeps_schema_fence(contract, path, member):
    case = _aura_case()
    if contract == "baseline128":
        case["snapshot"] = _baseline_snapshot()
    del _wrapper(case, path)[member]
    _assert_outcome(_shared(case, contract=contract, aura=False), "invalid", "malformed_observation_wrapper")


@pytest.mark.parametrize("path,reason", MISSING_PATHS, ids=[".".join(p) for p, _ in MISSING_PATHS])
@pytest.mark.parametrize("member", ("value", "provenance"))
def test_f3_extra_key_prevents_missing_member_exemption(path, reason, member):
    case = _aura_case(store="enrolled")
    wrapper = _wrapper(case, path)
    del wrapper[member]
    wrapper["unknown"] = "constructed"
    _assert_outcome(_facade(case), "invalid", "malformed_observation_wrapper")
