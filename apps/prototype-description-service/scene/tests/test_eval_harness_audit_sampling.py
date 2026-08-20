"""DESCQUAL-2 audit sampling: margin-of-error n, strata, inclusion probabilities."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.eval_harness.audit_sampling import (
    AuditSamplingError,
    DeffOrder,
    allocate,
    design_effect,
    draw,
    project_strata_image_counts,
    sample_size_for_margin,
    size_for_margin,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIR12_MANIFEST = _REPO_ROOT / "benchmarks/manifests/fir12-selection-v1.json"

# Real FIR-12 `strata_counts` shape (objects, not ints). Image N=640.
FIR12_STRATA_COUNTS: dict[str, dict[str, int]] = {
    "A_true_occluder": {"images": 32, "unique_subjects_faces_gt0": 20},
    "B_eyewear": {"images": 80, "unique_subjects_faces_gt0": 47},
    "C_pose": {"images": 34, "unique_subjects_faces_gt0": 15},
    "D_capture": {"images": 87, "unique_subjects_faces_gt0": 40},
    "E_clean": {"images": 407, "unique_subjects_faces_gt0": 109},
}

FIR12_IMAGE_N = {
    "A_true_occluder": 32,
    "B_eyewear": 80,
    "C_pose": 34,
    "D_capture": 87,
    "E_clean": 407,
}


def _strata_counts() -> dict[str, dict[str, int]]:
    if not _FIR12_MANIFEST.is_file():
        return FIR12_STRATA_COUNTS
    payload = json.loads(_FIR12_MANIFEST.read_text())
    counts = payload["strata_counts"]
    if not isinstance(counts, dict):
        raise AuditSamplingError("fir12-selection-v1.json strata_counts is not an object")
    return counts


FIR12_STRATA = project_strata_image_counts(_strata_counts())


def _members(sizes: dict[str, int] | None = None) -> dict[str, list[str]]:
    sizes = sizes or FIR12_STRATA
    return {name: [f"{name}-{i:03d}" for i in range(size)] for name, size in sizes.items()}


def test_sample_size_margin_10_on_640():
    assert sample_size_for_margin(margin=0.10, population=640) == 84


def test_sample_size_margin_15_on_640():
    assert sample_size_for_margin(margin=0.15, population=640) == 41


def test_sample_size_margin_05_on_640():
    assert sample_size_for_margin(margin=0.05, population=640) == 241


def test_sample_size_b_eyewear_precision_floor():
    # Proportional share of n=84 would give B ~10; that cannot carry a comparative claim.
    assert sample_size_for_margin(margin=0.10, population=80) == 44


def test_adapter_projects_images_from_real_strata_counts():
    counts = _strata_counts()
    sizes = project_strata_image_counts(counts)
    assert sizes == FIR12_IMAGE_N
    assert sum(sizes.values()) == 640
    assert sizes["A_true_occluder"] != counts["A_true_occluder"]["unique_subjects_faces_gt0"]


def test_adapter_rejects_int_valued_hand_frame():
    with pytest.raises(AuditSamplingError, match="object with 'images'"):
        project_strata_image_counts({"A": 32, "B": 80, "C": 34, "D": 87, "E": 407})


def test_allocate_rejects_unprojected_strata_counts():
    with pytest.raises(AuditSamplingError, match="project_strata_image_counts"):
        allocate(strata_sizes=FIR12_STRATA_COUNTS, n=84)  # type: ignore[arg-type]


def test_allocate_accepts_projected_real_frame():
    allocation = allocate(
        strata_sizes=project_strata_image_counts(_strata_counts()),
        n=84,
    )
    assert sum(allocation.values()) == 84
    assert set(allocation) == set(FIR12_IMAGE_N)


def test_design_effect_mean_images_per_subject():
    assert design_effect(cluster_size=4.9, icc=0.2) == pytest.approx(1.78)


def test_clustered_size_applies_deff_to_n0_before_fpc():
    record = size_for_margin(margin=0.10, population=640, cluster_size=4.9, icc=0.2)
    assert record.n == 136
    assert record.deff_order is DeffOrder.DEFF_THEN_FPC
    assert record.deff_order == "deff_then_fpc"
    assert record.cluster_size == 4.9
    assert record.icc == 0.2
    assert record.deff == pytest.approx(1.78)
    assert record.n_deff == pytest.approx(record.n0 * record.deff)
    expected = math.ceil(record.n_deff / (1.0 + (record.n_deff - 1.0) / 640))
    assert record.n == expected == 136
    old_order = math.ceil(sample_size_for_margin(margin=0.10, population=640) * record.deff)
    assert old_order == 150
    assert record.n != old_order


def test_allocate_sums_to_n():
    allocation = allocate(strata_sizes=FIR12_STRATA, n=84)
    assert sum(allocation.values()) == 84
    assert set(allocation) == set(FIR12_STRATA)
    assert all(0 <= allocation[name] <= size for name, size in FIR12_STRATA.items())


def test_precision_floor_raises_b_above_proportional():
    proportional = allocate(strata_sizes=FIR12_STRATA, n=84)
    floored = allocate(strata_sizes=FIR12_STRATA, n=84, precision_floors={"B_eyewear": 0.10})
    assert floored["B_eyewear"] == 44
    assert floored["B_eyewear"] > proportional["B_eyewear"]
    assert sum(floored.values()) == 84
    assert all(0 <= floored[name] <= size for name, size in FIR12_STRATA.items())


def test_draw_is_deterministic_without_replacement_and_carries_pi():
    members = _members()
    allocation = allocate(strata_sizes=FIR12_STRATA, n=84, precision_floors={"B_eyewear": 0.10})
    first = draw(strata_members=members, allocation=allocation, seed=20260820)
    second = draw(strata_members=members, allocation=allocation, seed=20260820)
    other_seed = draw(strata_members=members, allocation=allocation, seed=7)

    assert first.units == second.units
    assert first.unit_ids != other_seed.unit_ids
    assert len(first.unit_ids) == len(set(first.unit_ids)) == 84
    counts: dict[str, int] = {}
    for unit in first.units:
        counts[unit.stratum] = counts.get(unit.stratum, 0) + 1
        n_h = allocation[unit.stratum]
        n_stratum = FIR12_STRATA[unit.stratum]
        assert 0 < unit.inclusion_probability <= 1
        assert unit.inclusion_probability == pytest.approx(n_h / n_stratum)
    assert counts == allocation


def test_draw_does_not_take_the_first_n():
    members = _members()
    allocation = allocate(strata_sizes=FIR12_STRATA, n=84)
    sample = draw(strata_members=members, allocation=allocation, seed=20260820)
    convenience = []
    for stratum in sorted(members):
        convenience.extend(sorted(members[stratum])[: allocation[stratum]])
    assert list(sample.unit_ids) != convenience


def test_draw_is_invariant_to_member_order():
    members = _members()
    reversed_members = {name: list(reversed(ids)) for name, ids in members.items()}
    allocation = allocate(strata_sizes=FIR12_STRATA, n=84)
    a = draw(strata_members=members, allocation=allocation, seed=11)
    b = draw(strata_members=reversed_members, allocation=allocation, seed=11)
    assert set(a.unit_ids) == set(b.unit_ids)


def test_sample_size_rejects_non_positive_margin():
    with pytest.raises(AuditSamplingError):
        sample_size_for_margin(margin=0.0, population=640)
