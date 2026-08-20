"""DESCQUAL-2 audit sampling: margin-of-error n, strata, inclusion probabilities."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.eval_harness.audit_sampling import (
    Allocation,
    AuditSamplingError,
    ClusterSpec,
    DeffOrder,
    allocate,
    design_effect,
    draw,
    kish_effective_cluster_size,
    project_strata_image_counts,
    project_strata_subject_image_counts,
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

# Frozen-frame Kish a = Σ m_i² / Σ m_i (AUDIT-11); not the arithmetic mean.
WHOLE_FRAME_KISH_A = 12.90
B_EYEWEAR_KISH_A = 2.36


def _entry(stratum: str, identities: list[str]) -> dict[str, object]:
    return {"stratum": stratum, "present_identities": identities}


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


def test_kish_effective_cluster_size_is_not_the_mean():
    sizes = (1, 1, 4)
    assert kish_effective_cluster_size(sizes) == pytest.approx(3.0)
    assert sum(sizes) / len(sizes) == pytest.approx(2.0)
    assert kish_effective_cluster_size(sizes) != pytest.approx(sum(sizes) / len(sizes))
    assert kish_effective_cluster_size((3, 3, 3)) == pytest.approx(3.0)


def test_kish_effective_cluster_size_rejects_empty_and_non_positive():
    with pytest.raises(AuditSamplingError, match="non-empty"):
        kish_effective_cluster_size(())
    with pytest.raises(AuditSamplingError, match="finite number > 0"):
        kish_effective_cluster_size((1, 0))
    with pytest.raises(AuditSamplingError, match="finite number > 0"):
        kish_effective_cluster_size((1, -2))
    with pytest.raises(AuditSamplingError, match="finite number > 0"):
        kish_effective_cluster_size((1, float("nan")))
    with pytest.raises(AuditSamplingError, match="finite number > 0"):
        kish_effective_cluster_size((1, float("inf")))


def test_design_effect_kish_effective_size():
    assert design_effect(cluster_size=WHOLE_FRAME_KISH_A, icc=0.2) == pytest.approx(3.38)


def test_clustered_size_applies_deff_to_n0_before_fpc():
    record = size_for_margin(
        margin=0.10, population=640, cluster_size=WHOLE_FRAME_KISH_A, icc=0.2
    )
    assert record.n == 216
    assert record.deff_order is DeffOrder.DEFF_THEN_FPC
    assert record.deff_order == "deff_then_fpc"
    assert record.cluster_size == WHOLE_FRAME_KISH_A
    assert record.icc == 0.2
    assert record.deff == pytest.approx(3.38)
    assert record.n_deff == pytest.approx(record.n0 * record.deff)
    expected = math.ceil(record.n_deff / (1.0 + (record.n_deff - 1.0) / 640))
    assert record.n == expected == 216
    old_order = math.ceil(sample_size_for_margin(margin=0.10, population=640) * record.deff)
    assert old_order == 284
    assert record.n != old_order
    mean_n = size_for_margin(margin=0.10, population=640, cluster_size=4.9, icc=0.2).n
    assert mean_n == 136
    assert record.n - mean_n == 80


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
    record = floored.floors["B_eyewear"]
    assert record.n == 44
    assert record.deff_order is DeffOrder.FPC_ONLY
    assert record.deff == 1.0
    assert record.cluster_size is None
    assert record.icc is None


def test_allocate_refuses_when_precision_floors_exceed_n():
    # n=30 pilot: proportional B=4; B_eyewear ±10 pp floor needs 44 unclustered.
    proportional = allocate(strata_sizes=FIR12_STRATA, n=30)
    assert proportional["B_eyewear"] == 4
    with pytest.raises(
        AuditSamplingError, match=r"precision floors require n>=44, got n=30"
    ):
        allocate(
            strata_sizes=FIR12_STRATA,
            n=30,
            precision_floors={"B_eyewear": 0.10},
        )


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
    assert counts == dict(allocation)
    assert counts == allocation.counts


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


def test_clustered_b_eyewear_precision_floor_is_49():
    n0 = (1.96 * 1.96) * 0.5 * 0.5 / (0.10 * 0.10)
    cluster_size = B_EYEWEAR_KISH_A
    icc = 0.2
    deff = 1.0 + (cluster_size - 1.0) * icc
    n_deff = n0 * deff
    n_raw = n_deff / (1.0 + (n_deff - 1.0) / 80)
    assert math.ceil(n_raw) == 49
    assert math.ceil(n0 / (1.0 + (n0 - 1.0) / 80)) == 44
    mean_n = size_for_margin(margin=0.10, population=80, cluster_size=80 / 47, icc=icc).n
    assert mean_n == 47

    spec = ClusterSpec(cluster_size=cluster_size, icc=icc)
    expected = size_for_margin(
        margin=0.10, population=80, cluster_size=cluster_size, icc=icc
    )
    assert expected.n == 49
    assert expected.deff_order is DeffOrder.DEFF_THEN_FPC
    assert expected.deff == pytest.approx(deff)
    assert expected.n_deff == pytest.approx(n_deff)

    unclustered = allocate(
        strata_sizes=FIR12_STRATA, n=84, precision_floors={"B_eyewear": 0.10}
    )
    clustered = allocate(
        strata_sizes=FIR12_STRATA,
        n=84,
        precision_floors={"B_eyewear": 0.10},
        cluster_params={"B_eyewear": spec},
    )
    assert isinstance(clustered, Allocation)
    assert unclustered["B_eyewear"] == 44
    assert clustered["B_eyewear"] == 49
    assert clustered["B_eyewear"] != unclustered["B_eyewear"]
    assert sum(clustered.values()) == 84
    record = clustered.floors["B_eyewear"]
    assert record == expected
    assert record.n == 49
    assert record.deff_order is DeffOrder.DEFF_THEN_FPC
    assert record.deff_order == "deff_then_fpc"
    assert record.deff == pytest.approx(1.272)
    assert record.cluster_size == pytest.approx(cluster_size)
    assert record.icc == 0.2
    assert record.n / record.deff == pytest.approx(49 / deff)


def test_allocate_without_cluster_params_stays_deff_blind():
    allocation = allocate(
        strata_sizes=FIR12_STRATA, n=84, precision_floors={"B_eyewear": 0.10}
    )
    record = allocation.floors["B_eyewear"]
    assert allocation["B_eyewear"] == 44
    assert record.deff_order is DeffOrder.FPC_ONLY
    assert record.deff == 1.0
    assert record.cluster_size is None


def test_subject_image_counts_feed_kish_a():
    entries = [
        _entry("B_eyewear", ["alice"]),
        _entry("B_eyewear", ["alice"]),
        _entry("B_eyewear", ["alice"]),
        _entry("B_eyewear", ["alice"]),
        _entry("B_eyewear", ["bob"]),
        _entry("B_eyewear", ["cara"]),
        _entry("E_clean", ["dana"]),
        _entry("E_clean", ["dana"]),
        _entry("E_clean", []),
    ]
    sizes = project_strata_subject_image_counts(entries)
    assert sizes == {"B_eyewear": (4, 1, 1), "E_clean": (2,)}
    assert kish_effective_cluster_size(sizes["B_eyewear"]) == pytest.approx(3.0)
    assert kish_effective_cluster_size(sizes["E_clean"]) == pytest.approx(2.0)
    a = kish_effective_cluster_size(sizes["B_eyewear"])
    spec = ClusterSpec(cluster_size=a, icc=0.2)
    record = size_for_margin(
        margin=0.10, population=80, cluster_size=spec.cluster_size, icc=spec.icc
    )
    mean_record = size_for_margin(margin=0.10, population=80, cluster_size=2.0, icc=0.2)
    assert a == pytest.approx(3.0)
    assert spec.cluster_size != pytest.approx(2.0)
    assert record.n == 51
    assert mean_record.n == 48
    assert record.n != mean_record.n


def test_empty_present_identities_contribute_no_cluster():
    sizes = project_strata_subject_image_counts(
        [
            _entry("E_clean", ["Pat"]),
            _entry("E_clean", []),
            _entry("A_true_occluder", []),
        ]
    )
    assert sizes == {"E_clean": (1,)}
    assert "A_true_occluder" not in sizes


def test_subject_image_counts_reject_bare_string_identities():
    with pytest.raises(AuditSamplingError, match="sequence of names"):
        project_strata_subject_image_counts(
            [{"stratum": "E_clean", "present_identities": "Pat"}]
        )
    with pytest.raises(AuditSamplingError, match="sequence of objects"):
        project_strata_subject_image_counts("not-entries")  # type: ignore[arg-type]
    with pytest.raises(AuditSamplingError, match="missing 'stratum'"):
        project_strata_subject_image_counts([{"present_identities": ["Pat"]}])
    with pytest.raises(AuditSamplingError, match="non-empty str"):
        project_strata_subject_image_counts([_entry("E_clean", [""])])


def test_cluster_spec_rejects_out_of_bounds():
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        ClusterSpec(cluster_size=0.5, icc=0.2)
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        ClusterSpec(cluster_size=float("nan"), icc=0.2)
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        ClusterSpec(cluster_size=float("inf"), icc=0.2)
    with pytest.raises(AuditSamplingError, match="icc"):
        ClusterSpec(cluster_size=2.0, icc=-0.1)
    with pytest.raises(AuditSamplingError, match="icc"):
        ClusterSpec(cluster_size=2.0, icc=2.0)
    with pytest.raises(AuditSamplingError, match="icc"):
        ClusterSpec(cluster_size=2.0, icc=float("nan"))


def test_design_effect_rejects_non_finite_as_audit_error():
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        design_effect(cluster_size=float("nan"), icc=0.2)
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        size_for_margin(margin=0.10, population=80, cluster_size=float("nan"), icc=0.2)
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        size_for_margin(margin=0.10, population=80, cluster_size=float("inf"), icc=0.2)


def test_size_for_margin_rejects_overflow_derived_nan_as_audit_error():
    # Finite inputs that overflow n_deff to inf, then n = inf/inf = nan,
    # which math.ceil used to raise a raw ValueError (BR-10 only covered input nan).
    spec = ClusterSpec(cluster_size=1e308, icc=1.0)
    with pytest.raises(AuditSamplingError, match="non-finite"):
        size_for_margin(
            margin=0.10,
            population=640,
            cluster_size=spec.cluster_size,
            icc=spec.icc,
        )
    with pytest.raises(AuditSamplingError, match="non-finite"):
        size_for_margin(margin=0.10, population=640, cluster_size=1e308, icc=1.0)


def test_allocate_rejects_unknown_cluster_params_stratum():
    with pytest.raises(AuditSamplingError, match="cluster_params"):
        allocate(
            strata_sizes=FIR12_STRATA,
            n=84,
            precision_floors={"B_eyewear": 0.10},
            cluster_params={"not_a_stratum": ClusterSpec(cluster_size=2.0, icc=0.2)},
        )


def test_allocate_rejects_cluster_params_without_precision_floor():
    with pytest.raises(AuditSamplingError, match="no precision floor"):
        allocate(
            strata_sizes=FIR12_STRATA,
            n=84,
            cluster_params={"E_clean": ClusterSpec(cluster_size=2.0, icc=0.2)},
        )
    with pytest.raises(AuditSamplingError, match="no precision floor"):
        allocate(
            strata_sizes=FIR12_STRATA,
            n=84,
            precision_floors={"B_eyewear": 0.10},
            cluster_params={"E_clean": ClusterSpec(cluster_size=2.0, icc=0.2)},
        )


def test_allocation_source_dicts_cannot_mutate_constructed_object():
    counts = {"E_clean": 10, "B_eyewear": 4}
    floors = {}
    alloc = Allocation(counts=counts, floors=floors)
    counts["E_clean"] = 0
    floors["B_eyewear"] = size_for_margin(margin=0.10, population=80)
    assert alloc["E_clean"] == 10
    assert dict(alloc) == {"E_clean": 10, "B_eyewear": 4}
    assert "B_eyewear" not in alloc.floors


def test_allocation_hash_equal_for_equal_mappings():
    floor = size_for_margin(margin=0.10, population=80)
    a = Allocation(
        counts={"E_clean": 10, "B_eyewear": 4},
        floors={"B_eyewear": floor},
    )
    b = Allocation(
        counts={"B_eyewear": 4, "E_clean": 10},
        floors={"B_eyewear": floor},
    )
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1
    different = Allocation(counts={"E_clean": 10, "B_eyewear": 4}, floors={})
    assert a != different
    assert hash(a) != hash(different)


def test_allocation_item_assignment_raises():
    alloc = Allocation(counts={"E_clean": 10}, floors={})
    with pytest.raises(TypeError):
        alloc["E_clean"] = 0
    with pytest.raises(TypeError):
        alloc.counts["E_clean"] = 0
