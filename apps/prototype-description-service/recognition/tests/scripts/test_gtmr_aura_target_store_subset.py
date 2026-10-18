"""Bounded subset tests for the Aura target/store gate and the acceptance facade.

These tests prove the target/store helper and the facade on the rungs this lane owns, while the
loaded-runtime counterpart is not joined. They do not replace the frozen acceptance module and they
claim no runtime PASS.

* Direct helper cases call ``validate_target_store`` on the target- and store-owned pairs of the frozen
  44-pair packet, plus target-owned behaviour that has no frozen pair.
* Facade subset cases run the target, store, and shared-owned pairs through ``validate_aura_acceptance``.
  An in-memory stub replaces ``scripts.aura_loaded_runtime_gate`` for these cases only. The stub reports
  the runtime rung complete, so those outcomes are subset outcomes, not a runtime verdict.
* Runtime-owned pairs (licenses, preprocessing, source and database evidence, evidence binding) are
  excluded here and remain the frozen module's responsibility after the parent join.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import sys
import types
from collections.abc import Mapping
from typing import Any

import pytest

from recognition.tests.scripts.test_gtmr_aura_acceptance import (
    AURA_LABEL,
    NOW,
    PAIRS,
    SIBLING_LABEL,
    _add_nonzero_fourth_column,
    _assert_expectation,
    _aura_case,
    _base_case,
    _fixture,
    _pair_case,
    _sface_model_id,
)
from scripts import aura_target_store_gate as target_gate
from scripts import validate_auraface_runtime as facade
from scripts import validate_fir_dev_runtime as fir_validator

PAIR_BY_ID = {pair.case_id: pair for pair in PAIRS}
AURA_LABELS = ("dev-auraface", "staging-auraface", "prod-auraface")
RUNTIME_MODULE = "scripts.aura_loaded_runtime_gate"

# Target- and store-owned pairs. Every expected reason here is produced by this helper or by the reused
# FIR inventory and store rungs, never by the runtime helper.
TARGET_DIRECT_IDS = (
    "positive_enrolled_complete_evidence",
    "positive_empty_complete_evidence",
    "positive_discovered_zero_row_fourth_column",
    "positive_representative_norm_inside_tolerance",
    "representative_sqrt512_norm_refused",
    "representative_zero_vector_refused",
    "representative_norm_outside_tolerance_refused",
    "unlisted_staging_store_refused_under_prod_target",
    "observed_compose_project_outside_target_refused",
    "observed_network_outside_target_refused",
    "target_policy_category_missing_refused",
    "target_policy_category_not_list_refused",
    "target_policy_absent_refused",
    "mixed_persisted_stamps_refused",
    "foreign_only_persisted_stamp_refused",
    "enrolled_store_empty_persisted_set_refused",
    "empty_store_with_persisted_stamp_refused",
    "persisted_model_ids_duplicated_refused",
    "persisted_model_ids_incomplete_is_incomplete",
    "persisted_model_ids_absent_is_incomplete",
    "centroid_width_128_refused",
    "centroid_column_omitted_is_incomplete",
    "undiscovered_fourth_vector_column_is_incomplete",
    "vector_discovery_incomplete_is_incomplete",
    "discovered_nonzero_fourth_column_is_incomplete",
)
# Shared-owned pairs that the facade refuses before the target helper runs.
SHARED_FACADE_IDS = (
    "partial_loaded_weight_hashes_is_incomplete",
    "foreign_auraface_weight_digest_refused",
    "worker_weight_hash_divergence_refused",
    "sface_preprocessing_on_aura_identity_refused",
)
FACADE_SUBSET_IDS = TARGET_DIRECT_IDS + SHARED_FACADE_IDS


_USE_CASE_SNAPSHOT: Any = object()


def _complete_runtime_stub(snapshot: Any, *, aura_evidence: Any, acceptance_policy: Any) -> None:
    """Subset stub: reports the runtime rung complete. This is not a runtime verdict."""

    return None


@pytest.fixture
def runtime_stub(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    stub = types.ModuleType(RUNTIME_MODULE)
    stub.validate_loaded_runtime = _complete_runtime_stub  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUNTIME_MODULE, stub)
    return stub


def _facade_call(case: Mapping[str, Any], snapshot: Any = _USE_CASE_SNAPSHOT) -> dict[str, Any]:
    return dict(
        facade.validate_aura_acceptance(
            copy.deepcopy(case["snapshot"]) if snapshot is _USE_CASE_SNAPSHOT else snapshot,
            aura_evidence=copy.deepcopy(case["aura_evidence"]),
            freshness_policy=_fixture("freshness_policy.json"),
            isolation_policy=copy.deepcopy(case["isolation_policy"]),
            acceptance_policy=copy.deepcopy(case["acceptance_policy"]),
            now=NOW,
        )
    )


def _direct(case: Mapping[str, Any]) -> tuple[str, str] | None:
    return target_gate.validate_target_store(
        case["snapshot"],
        isolation_policy=case["isolation_policy"],
        acceptance_policy=case["acceptance_policy"],
    )


# --------------------------------------------------------------------------
# Direct target helper on the target- and store-owned frozen pairs
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", TARGET_DIRECT_IDS)
def test_direct_target_helper_matches_frozen_expectation(case_id: str) -> None:
    pair = PAIR_BY_ID[case_id]
    status, _exit_code, reasons = pair.expected
    result = _direct(_pair_case(pair))
    if status == "ready":
        assert result is None, f"{case_id}: expected complete (None), actual {result!r}"
        return
    assert result is not None, f"{case_id}: expected {status}, actual complete"
    assert result[0] == status and result[1] in reasons, (
        f"{case_id}: expected {status} in {sorted(reasons)}, actual {result!r}"
    )


@pytest.mark.parametrize("label", AURA_LABELS)
def test_direct_target_helper_accepts_each_operator_label(label: str) -> None:
    """Every operator-selected Aura label has a complete, self-consistent target identity."""

    assert _direct(_aura_case(label)) is None, f"{label}: complete target identity refused"


@pytest.mark.parametrize(
    ("policy", "expected"),
    (
        ({"target_label": "qa-auraface"}, ("invalid", "unknown_target_label")),
        ({"target_label": None}, ("invalid", "malformed_acceptance_policy")),
        ({}, ("invalid", "malformed_acceptance_policy")),
        ("prod-auraface", ("invalid", "malformed_acceptance_policy")),
    ),
)
def test_unknown_or_malformed_label_is_refused(policy: Any, expected: tuple[str, str]) -> None:
    case = _aura_case(AURA_LABEL)
    case["acceptance_policy"] = policy
    assert (
        target_gate.validate_target_store(
            case["snapshot"], isolation_policy=case["isolation_policy"], acceptance_policy=policy
        )
        == expected
    )


def test_policy_contract_is_bound_to_the_selected_label() -> None:
    """A prod-labelled acceptance with the staging resource contract is a contradiction, not a fill."""

    case = _aura_case(AURA_LABEL)
    staging_contract = _aura_case(SIBLING_LABEL)["isolation_policy"]
    assert target_gate.validate_target_store(
        case["snapshot"],
        isolation_policy=staging_contract,
        acceptance_policy=case["acceptance_policy"],
    ) == ("invalid", "target_identity_mismatch")


def test_sibling_space_stamp_is_refused_under_aura_target() -> None:
    """Identity can match the target while every role observes the SFace space: the Aura stamp rule refuses it."""

    case = _aura_case(AURA_LABEL)
    for record in case["snapshot"]["observations"]:
        record["model_id"]["value"] = _sface_model_id()
    assert _direct(case) == ("invalid", "model_space_contract_mismatch")


def test_missing_identity_observation_is_incomplete_not_invalid() -> None:
    case = _aura_case(AURA_LABEL)
    del case["snapshot"]["storage"]["network_ids"]["value"]
    assert _direct(case) == ("incomplete", "target_identity_unobserved")


def test_unknown_nonzero_column_on_enrolled_store_is_incomplete() -> None:
    """New target-owned rule: a populated extra column is unknown even when the shared store rung allows it."""

    case = _base_case("enrolled")
    _add_nonzero_fourth_column(case)
    control = fir_validator.validate_snapshot(
        case["snapshot"],
        freshness_policy=_fixture("freshness_policy.json"),
        isolation_policy=case["isolation_policy"],
        now=NOW,
        contract="candidate512",
    )
    assert control["status"] == "ready", "control: shared rung alone must not flag an enrolled extra column"
    assert _direct(case) == ("incomplete", "fir_store_state_unobserved")


# --------------------------------------------------------------------------
# Facade subset: target, store, and shared rungs with the runtime rung stubbed
# --------------------------------------------------------------------------


def test_facade_signature_is_the_frozen_abi() -> None:
    parameters = inspect.signature(facade.validate_aura_acceptance).parameters
    assert list(parameters) == [
        "snapshot",
        "aura_evidence",
        "freshness_policy",
        "isolation_policy",
        "acceptance_policy",
        "now",
    ]
    assert parameters["snapshot"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for name in list(parameters)[1:]:
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameters[name].default is inspect.Parameter.empty, name


@pytest.mark.parametrize("case_id", FACADE_SUBSET_IDS)
def test_facade_subset_matches_frozen_expectation(case_id: str, runtime_stub: types.ModuleType) -> None:
    pair = PAIR_BY_ID[case_id]
    _assert_expectation(_facade_call(_pair_case(pair)), pair.expected, case_id)


def test_malformed_store_wrapper_is_incomplete_before_shared_invalid(runtime_stub: types.ModuleType) -> None:
    """Additive evidence is checked first. The shared guard alone would emit a less specific invalid."""

    case = _aura_case(AURA_LABEL)
    del case["snapshot"]["database"]["store_state"]["provenance"]
    control = fir_validator.validate_snapshot(
        case["snapshot"],
        freshness_policy=_fixture("freshness_policy.json"),
        isolation_policy=case["isolation_policy"],
        now=NOW,
        contract="candidate512",
    )
    assert (control["status"], control["reason_code"]) == ("invalid", "malformed_observation_wrapper")
    result = _facade_call(case)
    assert (result["status"], result["exit_code"], result["reason_code"]) == (
        "incomplete",
        1,
        "fir_store_state_unobserved",
    )


def test_non_mapping_snapshot_is_refused_by_shared_guard(runtime_stub: types.ModuleType) -> None:
    case = _aura_case(AURA_LABEL)
    result = _facade_call(case, snapshot=None)
    assert (result["status"], result["exit_code"], result["reason_code"]) == (
        "invalid",
        2,
        "snapshot_schema_invalid",
    )


def test_facade_report_is_digest_only(runtime_stub: types.ModuleType) -> None:
    case = _aura_case(AURA_LABEL)
    report = _facade_call(case)["report"]
    assert set(report) == {"stage", "target_label", "snapshot_sha256", "aura_evidence_sha256"}
    assert report["target_label"] == AURA_LABEL
    assert report["snapshot_sha256"].startswith("sha256:") and len(report["snapshot_sha256"]) == 71


# --------------------------------------------------------------------------
# Offline CLI: JSON file inputs, required handles, redacted output, fail-closed
# --------------------------------------------------------------------------


def _write_inputs(tmp_path: Any, case: Mapping[str, Any]) -> list[str]:
    files = {
        "snapshot.json": case["snapshot"],
        "freshness.json": _fixture("freshness_policy.json"),
        "isolation.json": case["isolation_policy"],
        "aura_evidence.json": case["aura_evidence"],
        "acceptance.json": case["acceptance_policy"],
    }
    for name, payload in files.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    return [
        "--snapshot",
        str(tmp_path / "snapshot.json"),
        "--freshness-policy",
        str(tmp_path / "freshness.json"),
        "--isolation-policy",
        str(tmp_path / "isolation.json"),
        "--aura-evidence",
        str(tmp_path / "aura_evidence.json"),
        "--acceptance-policy",
        str(tmp_path / "acceptance.json"),
        "--now",
        NOW,
    ]


def test_cli_exit_codes_follow_status(tmp_path: Any, capsys: pytest.CaptureFixture[str], runtime_stub: Any) -> None:
    assert facade.main(_write_inputs(tmp_path, _aura_case(AURA_LABEL))) == 0
    ready = json.loads(capsys.readouterr().out)
    assert (ready["status"], ready["exit_code"], ready["reason_code"]) == ("ready", 0, "ready")

    negative = _aura_case(AURA_LABEL, store="enrolled")
    negative["snapshot"]["database"]["embedding_provenance"]["value"]["representative_vector"] = [1.0] * 512
    assert facade.main(_write_inputs(tmp_path, negative)) == 2
    assert json.loads(capsys.readouterr().out)["reason_code"] == "non_normalized_persisted_vector"

    incomplete = _aura_case(AURA_LABEL)
    del incomplete["snapshot"]["database"]["embedding_provenance"]["value"]["persisted_model_ids"]
    assert facade.main(_write_inputs(tmp_path, incomplete)) == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "embedding_provenance_unobserved"


def test_cli_refuses_unreadable_input_without_ready(tmp_path: Any, capsys: pytest.CaptureFixture[str]) -> None:
    argv = _write_inputs(tmp_path, _aura_case(AURA_LABEL))
    (tmp_path / "snapshot.json").write_text("{not json", encoding="utf-8")
    assert facade.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["reason_code"] == "input_unreadable"


def test_cli_requires_every_policy_handle(tmp_path: Any) -> None:
    argv = _write_inputs(tmp_path, _aura_case(AURA_LABEL))
    with pytest.raises(SystemExit) as excinfo:
        facade.main(argv[:-2])  # drop --now
    assert excinfo.value.code == 2


def test_cli_never_echoes_secret_shaped_policy(
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
    runtime_stub: Any,
) -> None:
    sentinel = "hunter2-sentinel-value"
    case = _aura_case(AURA_LABEL)
    case["acceptance_policy"]["password"] = sentinel
    assert facade.main(_write_inputs(tmp_path, case)) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["reason_code"] == "secret_shaped_input"
    assert sentinel not in captured.out and sentinel not in captured.err


@pytest.mark.skipif(
    importlib.util.find_spec(RUNTIME_MODULE) is not None,
    reason="runtime counterpart is joined; the unjoined fail-closed control does not apply",
)
def test_unjoined_runtime_rung_fails_closed_in_cli(tmp_path: Any, capsys: pytest.CaptureFixture[str]) -> None:
    """Without the counterpart, a complete target and store must not become ready."""

    assert facade.main(_write_inputs(tmp_path, _aura_case(AURA_LABEL))) == 2
    result = json.loads(capsys.readouterr().out)
    assert (result["status"], result["reason_code"]) == ("invalid", "validator_internal_error")
