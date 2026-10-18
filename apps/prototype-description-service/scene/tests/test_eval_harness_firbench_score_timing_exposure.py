"""MCP16856 fixed-GT timing allocation; fake records, no pixels or models."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_score as core
from scripts.eval_harness import firbench_score_io as io


def inventory(counts):
    return SimpleNamespace(
        images={i: SimpleNamespace(sampling_arm=fc.SamplingArm.probability) for i in counts},
        faces={f"{i}-{j}": SimpleNamespace(image_id=i) for i, count in counts.items() for j in range(count)},
        psus={i: i for i in counts},
        folds=dict.fromkeys(counts, 0),
        test_fold=0,
    )


def row(image_id, ref, **overrides):
    fields = {
        "leg_key": "leg",
        "arm": fc.Arm.native,
        "fold": 0,
        "sampling_arm": fc.SamplingArm.probability,
        "timing_receipt_ref": ref,
        "image_id": image_id,
    }
    return SimpleNamespace(**(fields | overrides))


def capture_samples(monkeypatch):
    """Observe the allocation while retaining the real NumPy percentile."""
    calls = []
    quantile = io.np.quantile

    def capture(values, q, **kwargs):
        calls.append((list(values), q))
        return quantile(values, q, **kwargs)

    monkeypatch.setattr(io.np, "quantile", capture)
    return calls


def test_uneven_gt_counts_conserve_all_image_and_record_work(monkeypatch):
    inv = inventory({"one": 1, "three": 3, "empty": 0, "also-empty": 0})
    rows = [row("one", "a"), row("three", "b"), row("empty", "extra")]
    receipt = {
        "timing_receipt_ms": {
            "a": 6,
            "b": 24,
            "extra": 4,
            "leg/native/image:one": 2,
            "leg/native/image:three": 6,
            "leg/native/image:empty": 8,
            "leg/native/image:also-empty": 8,
        }
    }
    original = copy.deepcopy(receipt)
    calls = capture_samples(monkeypatch)
    # Image totals 8 and 30; empty work 20 / N_GT=4 adds 5 to every GT bin.
    assert io.timing_exposure(receipt, rows, inv, "leg") == (15, None)
    samples, q = calls.pop()
    assert samples == [13, 15, 15, 15]
    assert q == 0.95
    assert len(samples) == len(inv.faces) == 4
    assert sum(samples) == sum(receipt["timing_receipt_ms"].values()) == 58
    assert receipt == original


def test_extra_detections_change_cost_without_minting_bins(monkeypatch):
    inv = inventory({"i": 2, "empty": 0})
    rows = [row("i", "gt")]
    costs = {"gt": 10, "leg/native/image:empty": 6}
    calls = capture_samples(monkeypatch)
    assert io.timing_exposure({"timing_receipt_ms": costs}, rows, inv, "leg") == (8, None)
    assert calls[-1][0] == [8, 8]
    # Equal work split among arbitrarily many detector rows has the same p95.
    for i in range(10):
        ref = f"extra-{i}"
        rows.append(row("i" if i % 2 else "empty", ref))
        costs[ref] = 2
    assert io.timing_exposure({"timing_receipt_ms": costs}, rows, inv, "leg") == (18, None)
    assert calls[-1][0] == [18, 18]
    assert sum(calls[-1][0]) == sum(costs.values())


def test_empty_work_changes_linear_p95_and_real_guardrail_state_without_semantic_ms():
    inv = inventory({"low": 1, "high": 1, "empty": 0})
    rows = [row("low", "a"), row("high", "b")]
    receipt = {"timing_receipt_ms": {"a": 2, "b": 10, "leg/native/image:empty": 0}}
    guard = SimpleNamespace(
        id="timing",
        metric="p95_ms_per_face",
        role=fc.GuardrailRole.veto,
        rule="p95_ms_per_face <= 12 ms/GT_face",
    )
    decision = SimpleNamespace(guardrails=[guard])
    contexts = {"leg": {"tau": 0.5, "test": rows, "units": []}}

    def evaluate(pinned):
        serialized = json.dumps(pinned, sort_keys=True).encode()
        digest = hashlib.sha256(serialized).hexdigest()
        result, readings = io._guardrails(decision, {}, contexts, [], pinned, digest, inv, rows)
        assert json.dumps(pinned, sort_keys=True).encode() == serialized
        assert result[0]["value"] is None
        assert result[0]["timings_sha256"] == digest
        return result, readings

    # Linear p95 of [2,10] is 9.6; an empty-image cost of 8 adds 4 to each bin.
    assert io.timing_exposure(receipt, rows, inv, "leg")[0] == pytest.approx(9.6)
    first, readings = evaluate(receipt)
    assert first[0]["state"] == "pass"
    assert readings[guard.id].state is core.GuardrailState.pass_
    assert evaluate(receipt)[0] == first
    changed = copy.deepcopy(receipt)
    changed["timing_receipt_ms"]["leg/native/image:empty"] = 8
    assert io.timing_exposure(changed, rows, inv, "leg")[0] == pytest.approx(13.6)
    last, readings = evaluate(changed)
    assert last[0]["state"] == "fail"
    assert readings[guard.id].state is core.GuardrailState.fail
    assert last[0]["timings_sha256"] != first[0]["timings_sha256"]
    assert receipt["timing_receipt_ms"]["leg/native/image:empty"] == 0


def test_no_gt_scope_is_unscored_and_empty_images_create_no_bins(monkeypatch):
    inv = inventory({"empty": 0})
    calls = capture_samples(monkeypatch)
    receipt = {"timing_receipt_ms": {"extra": 7, "leg/native/image:empty": 9}}
    assert io.timing_exposure(receipt, [row("empty", "extra")], inv, "leg") == (
        None,
        "no_gt_face_timing_exposure",
    )
    assert calls == []


def test_only_primary_test_probability_native_scope_contributes(monkeypatch):
    inv = inventory({"i": 1, "empty": 0, "fit": 7, "sampled": 11})
    inv.folds["fit"] = 1
    inv.images["sampled"].sampling_arm = fc.SamplingArm.challenge
    rows = [
        row("i", "gt"),
        row("fit", "fit-ref", fold=1),
        row("sampled", "sample-ref", sampling_arm=fc.SamplingArm.challenge),
        row("i", "attr-ref", arm=fc.Arm.gt_crop_redetect),
        row("i", "other-ref", leg_key="other"),
    ]
    receipt = {
        "timing_receipt_ms": {
            "gt": 6,
            "leg/native/image:empty": 10,
            "fit-ref": 1000,
            "sample-ref": 1000,
            "attr-ref": 1000,
            "other-ref": 1000,
            "leg/native/image:fit": 1000,
            "leg/native/image:sampled": 1000,
        }
    }
    calls = capture_samples(monkeypatch)
    assert io.timing_exposure(receipt, rows, inv, "leg") == (16, None)
    assert calls[-1][0] == [16]
    # Excluded rows need no receipt and excluded images need no overhead.
    receipt["timing_receipt_ms"] = {"gt": 6, "leg/native/image:empty": 10}
    assert io.timing_exposure(receipt, rows, inv, "leg") == (16, None)


@pytest.mark.parametrize("receipt", [{}, {"timing_receipt_ms": None}, {"timing_receipt_ms": []}])
def test_explicit_ms_receipt_required(receipt):
    assert io.timing_exposure(receipt, [], inventory({"i": 1}), "leg") == (None, "timing_receipt_missing")


@pytest.mark.parametrize("missing", ["gt", "empty"])
def test_missing_in_scope_cost_is_unscored(missing):
    costs = {"gt": 6, "leg/native/image:empty": 10}
    del costs["gt" if missing == "gt" else "leg/native/image:empty"]
    assert io.timing_exposure(
        {"timing_receipt_ms": costs}, [row("i", "gt")], inventory({"i": 1, "empty": 0}), "leg"
    ) == (
        None,
        "incomplete_or_duplicate_timing_receipt" if missing == "gt" else "incomplete_timing_receipt",
    )


@pytest.mark.parametrize("ref", ["gt", "leg/native/image:i", "leg/native/image:empty"])
@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), -float("inf"), True, "3"])
def test_negative_nonfinite_or_untyped_cost_refused(ref, bad):
    costs = {"gt": 6, "leg/native/image:i": 0, "leg/native/image:empty": 10}
    costs[ref] = bad
    with pytest.raises(fc.FrameContractError, match="negative|finite number"):
        io.timing_exposure({"timing_receipt_ms": costs}, [row("i", "gt")], inventory({"i": 1, "empty": 0}), "leg")


def test_duplicate_and_unattributed_native_receipts_remain_unscored():
    inv = inventory({"i": 1})
    receipt = {"timing_receipt_ms": {"gt": 6}}
    assert io.timing_exposure(receipt, [row("i", "gt")] * 2, inv, "leg") == (
        None,
        "incomplete_or_duplicate_timing_receipt",
    )
    receipt["timing_receipt_ms"]["leg/native/orphan"] = 5
    assert io.timing_exposure(receipt, [row("i", "gt")], inv, "leg") == (
        None,
        "unattributed_native_timing_cost",
    )
