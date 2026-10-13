"""GTMC-V-PARTIAL-02: a partial loaded-runtime record must not hide a present contradiction.

Tests only. This module adds no production code, no stub, and no monkeypatch. It drives the real
loaded-runtime helper ``scripts.aura_loaded_runtime_gate.validate_loaded_runtime`` and the real acceptance
facade ``scripts.validate_auraface_runtime.validate_aura_acceptance`` on inputs built by the frozen
``_aura_case`` builder from ``test_gtmr_aura_acceptance``.

Rule under test
---------------
An absent required observation is ``incomplete``. A present observation that contradicts its pin or its
peer is ``invalid``. Absence of one field on a record must not suppress the comparison of another present
field on that record. Each family below has two variants, a named variant from the brief and its mirror in
which the absent field and the wrong field are swapped. Each variant runs for both evidence roles:

* license: ``loaded_license_hashes.value.yunet`` absent, observed ``auraface`` digest wrong (mirror: the reverse).
* weights: ``loaded_weight_hashes.value.yunet`` absent, observed ``auraface`` digest wrong (mirror: the reverse).
* preprocessing: ``preprocessing_contract.value.input_size`` absent, observed ``channel_order`` ``BGR``
  (mirror: ``channel_order`` absent, observed ``input_size`` wrong).

Classification
--------------
``test_red_*``      Fails on unchanged source. The present contradiction is hidden behind the absent field and
                    the outcome is ``incomplete``. Helper and facade are separate tests so the failing layer is
                    visible.
``test_control_*``  Passes on unchanged source. Absence alone is ``incomplete``, contradiction alone is
                    ``invalid``, a stale sidecar binding is refused before the partial rung, the healthy case is
                    ``ready``, and each mutation changes only its declared factor. The absent-plus-contradiction
                    conjunction is therefore the only factor that fails.

Sidecar binding: every mutated snapshot is rebound with the canonical digest before validation, so no RED can
pass or fail on ``evidence_snapshot_mismatch``. ``test_control_stale_binding_is_refused_before_partial_rung``
pins that ordering.

Canon: https://github.com/darce/heuristics-canon. Rows applied: TEST-15 (a deliberately introduced partial
contradiction must be caught and kept as a regression), PROV-01 (each loaded digest and preprocessing value is
compared with its authority), EMB-01 (one model contract per comparison). RES-02 does not apply: every call is
an in-process pure function.

Offline and bounded: pure in-process validators; no DB, network, GPU, secrets, or model load.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from recognition.tests.scripts.test_gtmr_aura_acceptance import (
    EVIDENCE_ROLES,
    NOW,
    ZERO_DIGEST,
    _aura_case,
    _changed_factors,
    _fixture,
    _role,
    _snapshot_digest,
    _under,
)
from scripts import aura_loaded_runtime_gate as loaded_gate
from scripts import validate_auraface_runtime as facade

RUNTIME_MODULE = "scripts.aura_loaded_runtime_gate"
# Bound at collection, before any test can install a stub. Every runtime-rung assertion compares against it.
REAL_RUNTIME = loaded_gate
SIDECAR_BINDING = "aura_evidence/snapshot_sha256"
WRONG_INPUT_SIZE = [224, 224]

# Reason sets name the contradiction. They are closed: a reason outside the set fails the test.
LICENSE_INVALID = frozenset({"license_hash_mismatch", "role_license_hash_mismatch"})
PREPROCESSING_INVALID = frozenset({"preprocessing_contract_mismatch"})
WEIGHTS_INVALID = frozenset({"model_asset_hash_unexpected", "role_loaded_weight_hash_mismatch"})

HEALTHY = ("ready", "ready")
Mutation = Callable[[dict[str, Any], str], None]


def _evidence(case: dict[str, Any], role: str) -> dict[str, Any]:
    return case["aura_evidence"]["runtime_roles"][role]


def _snapshot_weights(case: dict[str, Any], role: str) -> dict[str, Any]:
    return _role(case["snapshot"], role)["loaded_weight_hashes"]["value"]


def _license_remove(key: str) -> Mutation:
    def mutate(case: dict[str, Any], role: str) -> None:
        del _evidence(case, role)["loaded_license_hashes"]["value"][key]

    return mutate


def _license_corrupt(key: str) -> Mutation:
    def mutate(case: dict[str, Any], role: str) -> None:
        _evidence(case, role)["loaded_license_hashes"]["value"][key] = ZERO_DIGEST

    return mutate


def _preprocessing_remove(key: str) -> Mutation:
    def mutate(case: dict[str, Any], role: str) -> None:
        del _evidence(case, role)["preprocessing_contract"]["value"][key]

    return mutate


def _preprocessing_corrupt(key: str, value: Any) -> Mutation:
    def mutate(case: dict[str, Any], role: str) -> None:
        _evidence(case, role)["preprocessing_contract"]["value"][key] = copy.deepcopy(value)

    return mutate


def _weights_remove(key: str) -> Mutation:
    def mutate(case: dict[str, Any], role: str) -> None:
        del _snapshot_weights(case, role)[key]

    return mutate


def _weights_corrupt(key: str) -> Mutation:
    def mutate(case: dict[str, Any], role: str) -> None:
        _snapshot_weights(case, role)[key] = ZERO_DIGEST

    return mutate


@dataclass(frozen=True)
class Variant:
    """One absent field paired with one present, contradictory field on the same record.

    ``remove`` makes the absent field absent. ``corrupt`` makes the other field present and wrong.
    ``missing_reason`` is the incomplete code when only the absence is present. ``root`` is the declared
    factor, using the frozen module's normalized ``<role>`` path form.
    """

    case_id: str
    remove: Mutation
    corrupt: Mutation
    expected_invalid: frozenset[str]
    missing_reason: str
    root: str


VARIANTS: tuple[Variant, ...] = (
    Variant(
        case_id="license_yunet_absent_auraface_wrong",
        remove=_license_remove("yunet"),
        corrupt=_license_corrupt("auraface"),
        expected_invalid=LICENSE_INVALID,
        missing_reason="incomplete_license_evidence",
        root="aura_evidence/runtime_roles/<role>/loaded_license_hashes",
    ),
    Variant(
        case_id="license_auraface_absent_yunet_wrong",
        remove=_license_remove("auraface"),
        corrupt=_license_corrupt("yunet"),
        expected_invalid=LICENSE_INVALID,
        missing_reason="incomplete_license_evidence",
        root="aura_evidence/runtime_roles/<role>/loaded_license_hashes",
    ),
    Variant(
        case_id="preprocessing_input_size_absent_channel_bgr",
        remove=_preprocessing_remove("input_size"),
        corrupt=_preprocessing_corrupt("channel_order", "BGR"),
        expected_invalid=PREPROCESSING_INVALID,
        missing_reason="incomplete_preprocessing_evidence",
        root="aura_evidence/runtime_roles/<role>/preprocessing_contract",
    ),
    Variant(
        case_id="preprocessing_channel_order_absent_input_size_wrong",
        remove=_preprocessing_remove("channel_order"),
        corrupt=_preprocessing_corrupt("input_size", WRONG_INPUT_SIZE),
        expected_invalid=PREPROCESSING_INVALID,
        missing_reason="incomplete_preprocessing_evidence",
        root="aura_evidence/runtime_roles/<role>/preprocessing_contract",
    ),
    Variant(
        case_id="weights_yunet_absent_auraface_wrong",
        remove=_weights_remove("yunet"),
        corrupt=_weights_corrupt("auraface"),
        expected_invalid=WEIGHTS_INVALID,
        missing_reason="incomplete_loaded_weight_hashes",
        root="snapshot/observations/<role>/loaded_weight_hashes",
    ),
    Variant(
        case_id="weights_auraface_absent_yunet_wrong",
        remove=_weights_remove("auraface"),
        corrupt=_weights_corrupt("yunet"),
        expected_invalid=WEIGHTS_INVALID,
        missing_reason="incomplete_loaded_weight_hashes",
        root="snapshot/observations/<role>/loaded_weight_hashes",
    ),
)
VARIANT_BY_ID: dict[str, Variant] = {variant.case_id: variant for variant in VARIANTS}
CASES: tuple[tuple[Variant, str], ...] = tuple((variant, role) for variant in VARIANTS for role in EVIDENCE_ROLES)
CASE_IDS: list[str] = [f"{variant.case_id}-{role}" for variant, role in CASES]
assert len(CASE_IDS) == len(set(CASE_IDS)), "case ids must be unique"


def _build(variant: Variant, role: str, *, remove: bool, corrupt: bool, rebind: bool = True) -> dict[str, Any]:
    """Genuine ``_aura_case`` input with the requested mutation. The sidecar is rebound unless told not to."""

    case = _aura_case()
    if remove:
        variant.remove(case, role)
    if corrupt:
        variant.corrupt(case, role)
    if rebind:
        case["aura_evidence"]["snapshot_sha256"] = _snapshot_digest(case["snapshot"])
    return case


def _assert_bound(case: dict[str, Any]) -> None:
    """Fixture precondition: the sidecar binds the snapshot under test, so any outcome is about its content."""

    assert case["aura_evidence"]["snapshot_sha256"] == _snapshot_digest(case["snapshot"]), (
        "sidecar snapshot_sha256 must bind the mutated snapshot under test"
    )


def _assert_real_runtime_rung() -> None:
    """The facade imports its runtime rung lazily from sys.modules. Prove the real module answers."""

    assert sys.modules.get(RUNTIME_MODULE) is REAL_RUNTIME, (
        "runtime rung resolved to something other than the real module"
    )


def _helper_outcome(case: dict[str, Any]) -> tuple[str, str]:
    result = loaded_gate.validate_loaded_runtime(
        copy.deepcopy(case["snapshot"]),
        aura_evidence=copy.deepcopy(case["aura_evidence"]),
        acceptance_policy=copy.deepcopy(case["acceptance_policy"]),
    )
    return HEALTHY if result is None else (result[0], result[1])


def _facade_result(case: dict[str, Any]) -> dict[str, Any]:
    _assert_real_runtime_rung()
    return dict(
        facade.validate_aura_acceptance(
            copy.deepcopy(case["snapshot"]),
            aura_evidence=copy.deepcopy(case["aura_evidence"]),
            freshness_policy=_fixture("freshness_policy.json"),
            isolation_policy=copy.deepcopy(case["isolation_policy"]),
            acceptance_policy=copy.deepcopy(case["acceptance_policy"]),
            now=NOW,
        )
    )


def _describe(result: dict[str, Any]) -> str:
    return (
        f"status={result['status']} exit_code={result['exit_code']} "
        f"reason_code={result['reason_code']} stage={result['report']['stage']}"
    )


# --------------------------------------------------------------------------
# RED: a present contradiction beside an absent field must be invalid
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("variant", "role"), CASES, ids=CASE_IDS)
def test_red_partial_contradiction_is_invalid_at_helper(variant: Variant, role: str) -> None:
    case = _build(variant, role, remove=True, corrupt=True)
    _assert_bound(case)
    status, reason = _helper_outcome(case)
    assert status == "invalid" and reason in variant.expected_invalid, (
        f"{variant.case_id} role={role} helper: expected invalid with reason in "
        f"{sorted(variant.expected_invalid)}; actual status={status} reason={reason}. "
        "The present contradiction is hidden by the absent field on the same record."
    )


@pytest.mark.parametrize(("variant", "role"), CASES, ids=CASE_IDS)
def test_red_partial_contradiction_is_invalid_at_facade(variant: Variant, role: str) -> None:
    case = _build(variant, role, remove=True, corrupt=True)
    _assert_bound(case)
    result = _facade_result(case)
    assert (result["status"], result["exit_code"]) == ("invalid", 2) and result["reason_code"] in (
        variant.expected_invalid
    ), (
        f"{variant.case_id} role={role} facade: expected invalid exit_code=2 with reason in "
        f"{sorted(variant.expected_invalid)}; actual {_describe(result)}"
    )


# --------------------------------------------------------------------------
# Controls: each factor alone behaves correctly on unchanged source
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("variant", "role"), CASES, ids=CASE_IDS)
def test_control_absence_alone_is_incomplete(variant: Variant, role: str) -> None:
    case = _build(variant, role, remove=True, corrupt=False)
    _assert_bound(case)
    assert _helper_outcome(case) == ("incomplete", variant.missing_reason), (
        f"{variant.case_id} role={role} helper: missing-only must stay incomplete"
    )
    result = _facade_result(case)
    assert (result["status"], result["exit_code"], result["reason_code"]) == (
        "incomplete",
        1,
        variant.missing_reason,
    ), f"{variant.case_id} role={role} facade: missing-only must stay incomplete; actual {_describe(result)}"


@pytest.mark.parametrize(("variant", "role"), CASES, ids=CASE_IDS)
def test_control_contradiction_alone_is_invalid(variant: Variant, role: str) -> None:
    case = _build(variant, role, remove=False, corrupt=True)
    _assert_bound(case)
    status, reason = _helper_outcome(case)
    assert status == "invalid" and reason in variant.expected_invalid, (
        f"{variant.case_id} role={role} helper: contradiction with all fields present must be invalid; "
        f"actual status={status} reason={reason}"
    )
    result = _facade_result(case)
    assert (result["status"], result["exit_code"]) == ("invalid", 2) and result["reason_code"] in (
        variant.expected_invalid
    ), f"{variant.case_id} role={role} facade: contradiction alone must be invalid; actual {_describe(result)}"


@pytest.mark.parametrize(("variant", "role"), CASES, ids=CASE_IDS)
def test_control_partial_mutation_changes_only_declared_factor(variant: Variant, role: str) -> None:
    before = _aura_case()
    after = _build(variant, role, remove=True, corrupt=True)
    changed = _changed_factors(before, after)
    assert changed, f"{variant.case_id} role={role}: the declared factor did not change"
    outside = sorted(path for path in changed if path != SIDECAR_BINDING and not _under(path, variant.root))
    assert not outside, f"{variant.case_id} role={role}: changed outside declared factor {variant.root!r}: {outside}"
    assert before["isolation_policy"] == after["isolation_policy"], f"{variant.case_id}: isolation policy changed"
    assert before["acceptance_policy"] == after["acceptance_policy"], f"{variant.case_id}: acceptance policy changed"


def test_control_stale_binding_is_refused_before_partial_rung() -> None:
    """Why the rebind matters: a stale digest is refused by the binding rung, which runs before the partial rung."""

    variant = VARIANT_BY_ID["weights_yunet_absent_auraface_wrong"]
    case = _build(variant, "api", remove=True, corrupt=True, rebind=False)
    assert _helper_outcome(case) == ("invalid", "evidence_snapshot_mismatch")


def test_control_healthy_case_is_ready_at_helper_and_facade() -> None:
    case = _aura_case()
    _assert_bound(case)
    assert _helper_outcome(case) == HEALTHY
    result = _facade_result(case)
    assert (result["status"], result["exit_code"], result["reason_code"]) == ("ready", 0, "ready"), _describe(result)


def test_control_runtime_rung_is_the_real_loaded_module() -> None:
    _assert_real_runtime_rung()
    assert Path(REAL_RUNTIME.__file__).as_posix().endswith("/scripts/aura_loaded_runtime_gate.py")
    assert REAL_RUNTIME.validate_loaded_runtime.__module__ == RUNTIME_MODULE
