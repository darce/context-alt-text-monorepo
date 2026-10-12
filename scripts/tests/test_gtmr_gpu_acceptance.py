"""Causal RED for the GTMR action61 WordPress-receipt predicate (GTMSMOKE-1).

Authored before the separate implementation: the native parent records these
results against the unchanged production checker before any acceptance code
exists. Every test runs the production ``check_bundle`` entry point through the
existing bundle fixture ``scripts/test_gpu_burst_evidence.py::_custom_bundle``.
Nothing here touches secrets, runtime services, databases, GPUs, or corpora.

Causal design
-------------
``test_control_*`` tests are healthy controls. They must pass on unchanged
production and must keep passing after any fix. Each ``test_red_*`` test differs
from a healthy control by exactly one receipt factor (``tier`` or model
lineage). Its lifecycle checks are asserted to pass, so a RED failure can only
come from the WP-receipt predicate.

Contract source
---------------
action61 strict acceptance rejects CPU output and mismatched lineage, and every
output must walk back to its model evidence (PROV-01, "Every output walks back
to its evidence", Model Cards / AI Engineering). The live smoke already enforces
these rules per item: ``scripts/gpu_burst_smoke.py:2110`` requires
``tier == "final_gpu"`` and ``:2114`` requires the expected model identity. The
lifecycle verdict's ``wp_descriptions`` check (``scripts/gpu_burst_evidence.py:1889-1910``)
does not apply either rule to receipts.

Out of scope here: a RED for uncached final_gpu proof, GPU model-process/offload
receipts, input/prompt/preprocess/runtime lineage, restricted-PG durability and
isolation, and load-revision attribution. Unchanged production exposes no
representable field for those, so a RED on them would be import or schema noise.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_CHECKER = REPO_ROOT / "scripts" / "gpu_burst_evidence.py"
EXISTING_FIXTURES = REPO_ROOT / "scripts" / "test_gpu_burst_evidence.py"

# The fixture's RUNNING interval is 00:10Z-00:30Z; this receipt sits inside it.
RECEIPT_AT = "2026-09-01T00:20:00Z"
PINNED_MODEL = "example-org/burst-model@rev-pinned"
OTHER_MODEL = "example-org/other-model@rev-other"
STOP_PRINCIPAL = "gpu-reaper"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load_module("gtmr_gpu_evidence_checker", EVIDENCE_CHECKER)
fixtures = _load_module("gtmr_existing_gpu_burst_fixtures", EXISTING_FIXTURES)


def _bundle(tmp_path: Path, *, receipts: object = None, history: object = None) -> Path:
    kwargs: dict[str, object] = {}
    if receipts is not None:
        kwargs["receipts"] = receipts
    if history is not None:
        kwargs["history"] = history
    return fixtures._custom_bundle(tmp_path, **kwargs)


def _verdict(bundle: Path, *, principal: str = STOP_PRINCIPAL) -> dict[str, Any]:
    return evidence.check_bundle(
        bundle,
        since=fixtures.SINCE,
        until=fixtures.UNTIL,
        expected_stop_principal=principal,
    )


def _check(verdict: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    matches = [check for check in verdict["checks"] if check["name"] == name]
    assert len(matches) == 1, [check["name"] for check in verdict["checks"]]
    return matches[0]


def _assert_only_wp_predicate_can_differ(verdict: Mapping[str, Any]) -> None:
    lifecycle_failures = [
        check["name"] for check in verdict["checks"] if check["name"] != "wp_descriptions" and not check["passed"]
    ]
    assert lifecycle_failures == [], (
        f"lifecycle checks must pass so that only the WP-receipt predicate is under test: {lifecycle_failures}"
    )


def _receipts(*items: Mapping[str, object]) -> dict[str, object]:
    return {"items": [dict(item) for item in items]}


def _final_item(description: str, model_id: str = PINNED_MODEL) -> dict[str, object]:
    return {
        "description": description,
        "generated_at": RECEIPT_AT,
        "tier": "final_gpu",
        "provenance": {"model_id": model_id},
    }


# ---- healthy controls: must pass on unchanged production and after any fix ----


def test_control_final_gpu_receipt_with_lineage_proves_wp_predicate(tmp_path: Path) -> None:
    verdict = _verdict(_bundle(tmp_path, receipts=_receipts(_final_item("a red bicycle beside a brick wall"))))

    assert _check(verdict, "wp_descriptions")["passed"] is True
    assert verdict["passed"] is True, verdict["failures"]


def test_control_draft_plus_final_receipts_keep_the_final_proof(tmp_path: Path) -> None:
    # A fix must not reject a receipt set merely because it also holds a CPU draft.
    draft = {
        "description": "cpu draft",
        "generated_at": RECEIPT_AT,
        "tier": "provisional_cpu",
        "provenance": {"model_id": PINNED_MODEL},
    }
    verdict = _verdict(_bundle(tmp_path, receipts=_receipts(draft, _final_item("gpu description"))))

    assert _check(verdict, "wp_descriptions")["passed"] is True
    assert verdict["passed"] is True, verdict["failures"]


def test_control_one_model_identity_across_receipts_passes(tmp_path: Path) -> None:
    verdict = _verdict(
        _bundle(
            tmp_path,
            receipts=_receipts(_final_item("first description"), _final_item("second description")),
        )
    )

    assert _check(verdict, "wp_descriptions")["passed"] is True
    assert verdict["passed"] is True, verdict["failures"]


def test_control_legacy_tierless_receipts_without_lineage_still_pass(tmp_path: Path) -> None:
    # Same shape as test_receipt_generated_at_is_accepted: no tier, no provenance.
    legacy = {"items": [{"description": "one", "generated_at": RECEIPT_AT}]}
    verdict = _verdict(_bundle(tmp_path, receipts=legacy))

    assert _check(verdict, "wp_descriptions")["passed"] is True
    assert verdict["passed"] is True, verdict["failures"]


def test_control_receipts_stay_optional_at_the_lifecycle_level(tmp_path: Path) -> None:
    # The lower-level bundle stays usable without receipts. Requiring them is the
    # acceptance layer's obligation, not this checker's.
    verdict = _verdict(_bundle(tmp_path))
    wp = _check(verdict, "wp_descriptions")

    assert wp["passed"] is True
    assert "optional" in wp["detail"]
    assert verdict["passed"] is True, verdict["failures"]


def test_control_wrong_stop_principal_still_fails(tmp_path: Path) -> None:
    verdict = _verdict(
        _bundle(tmp_path, receipts=_receipts(_final_item("gpu description"))), principal="human-operator"
    )

    assert _check(verdict, "expected_stop_principal")["passed"] is False
    assert verdict["passed"] is False


def test_control_history_without_stopped_baseline_still_fails(tmp_path: Path) -> None:
    history = {
        "instance_id": fixtures.INSTANCE_ID,
        "observations": [
            {"state": "RUNNING", "timestamp": fixtures.RUNNING_AT},
            {"state": "STOPPED", "timestamp": fixtures.STOPPED_AT},
        ],
    }
    verdict = _verdict(_bundle(tmp_path, history=history, receipts=_receipts(_final_item("gpu description"))))

    assert _check(verdict, "state_history_burst")["passed"] is False
    assert verdict["passed"] is False


# ---- causal REDs: must fail on unchanged production (each differs from a control by one factor) ----


def test_red_provisional_cpu_only_receipts_do_not_prove_gpu_burst(tmp_path: Path) -> None:
    # Control: final_gpu + PINNED_MODEL. Only the tier differs.
    draft = {
        "description": "cpu draft",
        "generated_at": RECEIPT_AT,
        "tier": "provisional_cpu",
        "provenance": {"model_id": PINNED_MODEL},
    }
    verdict = _verdict(_bundle(tmp_path, receipts=_receipts(draft)))

    _assert_only_wp_predicate_can_differ(verdict)
    wp = _check(verdict, "wp_descriptions")
    assert wp["passed"] is False, f"provisional_cpu-only receipts satisfied the GPU burst predicate: {wp['detail']}"


def test_red_receipts_with_two_model_identities_do_not_prove_one_burst(tmp_path: Path) -> None:
    # Control: two final_gpu receipts with PINNED_MODEL. Only the second model identity differs.
    mixed = _receipts(_final_item("first description", PINNED_MODEL), _final_item("second description", OTHER_MODEL))
    verdict = _verdict(_bundle(tmp_path, receipts=mixed))

    _assert_only_wp_predicate_can_differ(verdict)
    wp = _check(verdict, "wp_descriptions")
    assert wp["passed"] is False, f"receipts with two model identities satisfied one burst's predicate: {wp['detail']}"


def test_red_final_gpu_receipt_without_model_lineage_does_not_prove_burst(tmp_path: Path) -> None:
    # Control: the same final_gpu receipt with provenance.model_id. Only the lineage is absent.
    no_lineage = {"description": "gpu description", "generated_at": RECEIPT_AT, "tier": "final_gpu"}
    verdict = _verdict(_bundle(tmp_path, receipts=_receipts(no_lineage)))

    _assert_only_wp_predicate_can_differ(verdict)
    wp = _check(verdict, "wp_descriptions")
    assert wp["passed"] is False, f"final_gpu receipt without model lineage satisfied the predicate: {wp['detail']}"
