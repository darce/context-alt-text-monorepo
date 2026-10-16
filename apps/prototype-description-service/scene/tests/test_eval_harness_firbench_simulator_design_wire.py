"""FB1-S9-WIRE-01: real small-R suites preserve estimands and typed floor counters.

These are software wire checks, not Monte Carlo acceptance evidence. All packets,
S0 seals, S3 outcomes, intervals and decisions come from the committed simulator.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_selftest as sim

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MASTER_SEED = 2208172209
_SUITES = ("null", "power", "floor", "stage")
_SIZING_KEYS = (
    "raw_n",
    "n_psu",
    "size_counts",
    "sum_squared_sizes",
    "size_weighted_mean",
    "deff",
    "attained_n_eff",
    "attained_n_eff_exact",
)


@pytest.fixture(scope="module")
def rows() -> dict[tuple[str, int], Mapping[str, Any]]:
    decision = fc.load_decision_manifest(_REPO_ROOT / "benchmarks/manifests/fir-bench-decision-v1.json")
    params = sim.load_params(Path(__file__).parent / "fixtures/firbench_sim_v1.json", decision=decision)
    runners = {
        "null": sim.run_null_suite,
        "power": sim.run_power_suite,
        "floor": sim.run_floor_suite,
        "stage": sim.run_stage_suite,
    }
    return {
        (suite, replicates): runners[suite](
            dataclasses.replace(params, suite=suite), replicates=replicates, seed=_MASTER_SEED
        )["semantic"]
        for suite in _SUITES
        for replicates in (1, 3)
    }


def _assert_sizing(sizing: Mapping[str, Any], icc: Fraction) -> None:
    counts = {int(size): count for size, count in sizing["size_counts"].items()}
    assert all(type(count) is int for count in counts.values())
    raw = sum(size * count for size, count in counts.items())
    sum_squared = sum(size * size * count for size, count in counts.items())
    mean = Fraction(sum_squared, raw)
    deff = 1 + (mean - 1) * icc
    n_eff = raw / deff
    for key, expected in (("raw_n", raw), ("n_psu", sum(counts.values())), ("sum_squared_sizes", sum_squared)):
        assert type(sizing[key]) is int and sizing[key] == expected
    assert sizing["size_weighted_mean"] == float(mean)
    assert sizing["deff"] == float(deff)
    assert sizing["attained_n_eff"] == float(n_eff)
    assert sizing["attained_n_eff_exact"] == f"{n_eff.numerator}/{n_eff.denominator}"


def _assert_design(design: Mapping[str, Any]) -> None:
    mated = design["mated"]
    assert set(mated) == set(_SIZING_KEYS)
    assert {key: design[key] for key in _SIZING_KEYS} == mated
    icc = Fraction(str(design["icc"]))
    for sizing in (mated, design["image"], design["nonmated"]):
        _assert_sizing(sizing, icc)
        assert sizing["n_psu"] == mated["n_psu"]
    # The nonmated branch counts known empty-image source units, not GT faces.
    assert design["nonmated"]["raw_n"] == design["background_units"] == 3000
    assert design["image"]["raw_n"] == mated["raw_n"] + 3000
    assert design["image"]["size_weighted_mean"] != mated["size_weighted_mean"]
    assert design["nonmated"]["size_weighted_mean"] != mated["size_weighted_mean"]
    for cell in design["cells"].values():
        _assert_sizing(cell, icc)
        assert cell["psu_floor_met"] is (cell["n_psu"] >= 30)


@pytest.mark.parametrize("suite", _SUITES)
@pytest.mark.parametrize("replicates", (1, 3))
def test_public_design_and_every_declared_branch_keep_their_own_estimand(
    rows: dict[tuple[str, int], Mapping[str, Any]], suite: str, replicates: int
) -> None:
    row = rows[suite, replicates]
    assert row["replicates_requested"] == row["replicates_completed"] == replicates
    assert row["n_boot"] == 10000
    assert row["full_acceptance_evidence"] is False
    assert row["passed"] is None
    design = row["design"]
    _assert_design(design)
    for name, branch in design.get("branches", {}).items():
        if name == "cell_only":
            assert branch["cells"] == design["cells"]
        else:
            _assert_design(branch)
    assert json.loads(json.dumps(row, allow_nan=False)) == row


@pytest.mark.parametrize("replicates", (1, 3))
def test_floor_success_is_a_boolean_with_a_separate_actual_integer_count(
    rows: dict[tuple[str, int], Mapping[str, Any]], replicates: int
) -> None:
    row = rows["floor", replicates]
    metrics = row["metrics"]
    assert metrics["at_floor_passed"] is True
    assert type(metrics["at_floor_pass_count"]) is int
    assert metrics["at_floor_pass_count"] == row["replicates_completed"]
    assert metrics["below_floor_reason"] == fc.InconclusiveReason.insufficient_independent_psus.value
    assert metrics["below_floor_reason_counts"] == {metrics["below_floor_reason"]: replicates}
    assert metrics["below_floor_interval_count"] == metrics["at_floor_insufficient_count"] == 0
    assert metrics["cell_below_floor_scored"] == 0
    branches = row["design"]["branches"]
    assert branches["floor_below"]["mated"]["n_psu"] == metrics["below_floor_psus"] == 49
    assert branches["floor_at"]["mated"]["n_psu"] == metrics["at_floor_psus"] == 50
    for branch in branches.values():
        assert all(cell["n_psu"] < 30 and cell["psu_floor_met"] is False for cell in branch["cells"].values())


@pytest.mark.parametrize("replicates", (1, 3))
def test_branch_sizes_and_cells_do_not_inherit_the_global_effective_size(
    rows: dict[tuple[str, int], Mapping[str, Any]], replicates: int
) -> None:
    branches = rows["null", replicates]["design"]["branches"]
    assert branches["step1_null"]["mated"]["attained_n_eff"] == 300
    assert branches["step2_boundary"]["mated"]["attained_n_eff"] == 400
    power = rows["power", replicates]["design"]
    assert power["mated"]["attained_n_eff"] == 115
    expected_cells = {"clear_mask": {"1": 23, "4": 12}, "clear_clear": {"1": 23, "4": 11}}
    for cell, counts in expected_cells.items():
        sizing = power["branches"]["cell_only"]["cells"][cell]
        assert sizing["size_counts"] == counts
        assert sizing["attained_n_eff"] < 115


@pytest.mark.parametrize("replicates", (1, 3))
def test_stage_wire_preserves_actual_small_r_counts(
    rows: dict[tuple[str, int], Mapping[str, Any]], replicates: int
) -> None:
    row = rows["stage", replicates]
    metrics = row["metrics"]
    assert row["design"]["mated"]["raw_n"] == metrics["n_mated"] == 138
    assert metrics["drop_count"] == 13 * replicates
    assert metrics["missed_delta_exact_count"] == 2 * replicates
    assert metrics["native_attribution_gaps"] == metrics["expected_native_attribution_gaps"] == 52 * replicates
    assert metrics["control_native_attribution_gaps"] == 0
    # Actual current-stage counts at the fixed seed; this wire fix cannot change planting.
    expected = {1: ((7, 20, 3, 3), (8, 21, 4, 3)), 3: ((31, 70, 9, 9), (23, 62, 15, 12))}
    for leg, counts in zip(("sface", "auraface"), expected[replicates], strict=True):
        observed = tuple(
            metrics[f"{key}_{leg}"]
            for key in ("control_missed", "planted_missed", "control_embedded_wrong", "planted_embedded_wrong")
        )
        assert all(type(count) is int for count in observed)
        assert observed == counts
        assert metrics[f"planted_embedded_{leg}"] == metrics[f"control_embedded_{leg}"] - 13 * replicates
