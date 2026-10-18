"""Constructed offline pins for authoritative sidecar identity versus operator target."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from recognition.tests.scripts.test_gtmc_aura_v1_r3_pins import (
    NOW, _assert_outcome, _aura_case, _facade, _fixture, _snapshot_digest,
)
from scripts import aura_target_store_gate as target


def _case(role: str, field: str, member: str, sidecars: str):
    case = _aura_case(store="enrolled")
    for name in ((role,) if sidecars == "one" else ("api", "worker")):
        case["aura_evidence"]["runtime_roles"][name]["database_identity"]["value"][field] = "foreign_identity"
    twin = copy.deepcopy(case)
    del case["snapshot"]["database"]["identity"][field][member]
    return case, twin


def _helper(case):
    before = copy.deepcopy(case)
    result = target.validate_target_store(
        case["snapshot"], isolation_policy=case["isolation_policy"],
        acceptance_policy=case["acceptance_policy"], aura_evidence=case["aura_evidence"],
    )
    assert case == before, "helper must not backfill observations"
    return result


@pytest.mark.parametrize("role", ("api", "worker"))
@pytest.mark.parametrize("field", ("database_name", "role"))
@pytest.mark.parametrize("member", ("value", "provenance"))
@pytest.mark.parametrize("sidecars", ("one", "both"))
def test_sidecar_target_contradiction(role, field, member, sidecars):
    case, twin = _case(role, field, member, sidecars)
    for candidate in (case, twin):
        _assert_outcome(_facade(candidate), "invalid", "database_identity_divergent")
        assert _helper(candidate) == ("invalid", "database_identity_divergent")


@pytest.mark.parametrize("field,member", (("database_name", "value"), ("role", "provenance")))
def test_worker_sidecar_target_cli_exits_invalid(tmp_path: Path, field, member):
    case, _ = _case("worker", field, member, "one")
    case["aura_evidence"]["snapshot_sha256"] = _snapshot_digest(case["snapshot"])
    inputs = {**case, "freshness_policy": _fixture("freshness_policy.json")}
    command = [sys.executable, "-B", "-m", "scripts.validate_auraface_runtime", "--now", NOW]
    for key in ("snapshot", "aura_evidence", "isolation_policy", "acceptance_policy", "freshness_policy"):
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps(inputs[key]), encoding="utf-8")
        command.extend((f"--{key.replace('_', '-')}", str(path)))
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2
    _assert_outcome(json.loads(result.stdout), "invalid", "database_identity_divergent")


def test_matching_sidecars_missing_snapshot_stays_incomplete():
    case = _aura_case(store="enrolled")
    del case["snapshot"]["database"]["identity"]["database_name"]["value"]
    _assert_outcome(_facade(case), "incomplete", "target_identity_unobserved")
    assert target.validate_target_store(
        case["snapshot"], isolation_policy=case["isolation_policy"],
        acceptance_policy=case["acceptance_policy"],
    ) == ("incomplete", "target_identity_unobserved")
