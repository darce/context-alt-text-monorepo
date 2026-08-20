"""DESCQUAL-2 audit sampling: margin-of-error n, strata, inclusion probabilities."""

from __future__ import annotations

import json
import math
import random
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
    draw_two_stage,
    estimate_icc,
    kish_effective_cluster_size,
    project_strata_image_counts,
    project_strata_subject_image_counts,
    project_whole_frame_subject_image_counts,
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

# Vendored FIR-12 frame: DESCQUAL-2 clone does not otherwise ship this JSON.
# Derived whole-frame Kish a (AUDIT-11); identities joined across strata.
def _fir12_entries() -> list[object]:
    if not _FIR12_MANIFEST.is_file():
        raise FileNotFoundError(
            f"vendored FIR-12 frame missing at {_FIR12_MANIFEST}"
        )
    payload = json.loads(_FIR12_MANIFEST.read_text())
    entries = payload["entries"]
    if not isinstance(entries, list) or not entries:
        raise AuditSamplingError("fir12-selection-v1.json entries must be a non-empty list")
    return entries


WHOLE_FRAME = project_whole_frame_subject_image_counts(_fir12_entries())
WHOLE_FRAME_KISH_A = kish_effective_cluster_size(WHOLE_FRAME.sizes)


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


def test_whole_frame_join_merges_identity_across_strata():
    entries = [
        _entry("A_true_occluder", ["alice"]),
        _entry("B_eyewear", ["alice"]),
        _entry("B_eyewear", ["bob"]),
    ]
    frame = project_whole_frame_subject_image_counts(entries)
    assert sorted(frame.sizes) == [1, 2]
    assert kish_effective_cluster_size(frame.sizes) == pytest.approx(5 / 3)
    concat = [
        m
        for v in project_strata_subject_image_counts(entries).values()
        for m in v
    ]
    assert sorted(concat) == [1, 1, 1]
    assert kish_effective_cluster_size(concat) == pytest.approx(1.0)


def test_whole_frame_counts_unlabeled_and_multi_identity_images():
    entries = [
        _entry("E_clean", []),
        _entry("E_clean", []),
        _entry("B_eyewear", ["alice", "bob"]),
        _entry("C_pose", ["alice", "bob", "cara"]),
        _entry("D_capture", ["dana"]),
    ]
    frame = project_whole_frame_subject_image_counts(entries)
    assert frame.n_entries == 5
    assert frame.n_unlabeled == 2
    assert frame.n_multi_identity_images == 2
    assert frame.extra_memberships == 3
    assert sorted(frame.sizes) == [1, 1, 2, 2]


def test_whole_frame_kish_a_joins_identities_across_strata():
    entries = json.loads(_FIR12_MANIFEST.read_text())["entries"]
    assert len(entries) == 640
    frame = project_whole_frame_subject_image_counts(entries)
    assert frame.n_entries == 640
    assert len(frame.sizes) == 130
    assert sum(frame.sizes) == 544
    assert sum(m * m for m in frame.sizes) == 7020
    assert sum(m * (m - 1) for m in frame.sizes) == 6476
    assert frame.n_unlabeled == 115
    assert frame.n_multi_identity_images == 16
    assert frame.extra_memberships == 19
    a = kish_effective_cluster_size(frame.sizes)
    assert a == pytest.approx(7020 / 544)
    assert a == pytest.approx(12.904412, abs=1e-6)
    assert WHOLE_FRAME_KISH_A == pytest.approx(a)

    # The obvious composition splits a subject who appears in two strata
    # into two clusters and understates deff (a = 7.41 over 231 clusters).
    per_stratum = project_strata_subject_image_counts(entries)
    concat = [m for v in per_stratum.values() for m in v]
    assert len(concat) == 231
    split_a = kish_effective_cluster_size(concat)
    assert split_a == pytest.approx(7.408088, rel=1e-6)
    assert split_a < a


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
    assert design_effect(cluster_size=WHOLE_FRAME_KISH_A, icc=0.2) == pytest.approx(
        1.0 + (WHOLE_FRAME_KISH_A - 1.0) * 0.2
    )


def test_clustered_size_applies_deff_to_n0_before_fpc():
    record = size_for_margin(
        margin=0.10, population=640, cluster_size=WHOLE_FRAME_KISH_A, icc=0.2
    )
    assert record.n == 216
    assert record.deff_order is DeffOrder.DEFF_THEN_FPC
    assert record.deff_order == "deff_then_fpc"
    assert record.cluster_size == WHOLE_FRAME_KISH_A
    assert record.icc == 0.2
    assert record.deff == pytest.approx(1.0 + (WHOLE_FRAME_KISH_A - 1.0) * 0.2)
    assert record.n_deff == pytest.approx(record.n0 * record.deff)
    expected = math.ceil(record.n_deff / (1.0 + (record.n_deff - 1.0) / 640))
    assert record.n == expected == 216
    old_order = math.ceil(sample_size_for_margin(margin=0.10, population=640) * record.deff)
    assert old_order == 284
    assert record.n != old_order
    # Mean of the cluster vector is Σm / 130 = 544/130 ≈ 4.18, not 640/130 = 4.92
    # (that puts the 115 unlabeled images in the numerator).
    mean_m = sum(WHOLE_FRAME.sizes) / len(WHOLE_FRAME.sizes)
    assert mean_m == pytest.approx(544 / 130)
    mean_n = size_for_margin(margin=0.10, population=640, cluster_size=mean_m, icc=0.2).n
    assert mean_n == 127
    assert record.n - mean_n == 89


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


def _anova_clusters_icc(*, n_psu: int, icc: float) -> list[tuple[float, ...]]:
    """Balanced k=3 clusters whose ANOVA ICC equals `icc` (MSW=1)."""
    k = 3
    f_ratio = (1.0 + (k - 1.0) * icc) / (1.0 - icc)
    target_ss = f_ratio * (n_psu - 1) / k
    center = (n_psu - 1) / 2.0
    raw = [i - center for i in range(n_psu)]
    scale = math.sqrt(target_ss / sum(x * x for x in raw))
    return [(scale * x - 1.0, scale * x, scale * x + 1.0) for x in raw]


def _gaussian_clusters(
    *, n_psu: int, n_within: int, rho: float, seed: int
) -> list[tuple[float, ...]]:
    rng = random.Random(seed)
    sd_a = math.sqrt(rho)
    sd_e = math.sqrt(1.0 - rho)
    clusters = []
    for _ in range(n_psu):
        intercept = rng.gauss(0.0, sd_a)
        clusters.append(
            tuple(intercept + rng.gauss(0.0, sd_e) for _ in range(n_within))
        )
    return clusters


def test_fir12_icc_eligible_subject_counts():
    assert sum(1 for m in WHOLE_FRAME.sizes if m >= 2) == 76
    assert sum(1 for m in WHOLE_FRAME.sizes if m >= 3) == 65


def test_draw_two_stage_replicates_within_psu():
    clusters = {f"s{i}": [f"s{i}-{j}" for j in range(4)] for i in range(12)}
    sample = draw_two_stage(clusters=clusters, n_psu=6, n_within=3, seed=21)
    by_psu: dict[object, int] = {}
    for unit in sample.units:
        assert unit.psu_id is not None
        by_psu[unit.psu_id] = by_psu.get(unit.psu_id, 0) + 1
        assert str(unit.unit_id).startswith(str(unit.psu_id))
    assert len(by_psu) == 6
    assert set(by_psu.values()) == {3}
    assert len(sample.units) == 18


def test_draw_two_stage_is_deterministic_and_order_invariant():
    clusters = {f"s{i}": [f"s{i}-{j}" for j in range(5)] for i in range(10)}
    reversed_clusters = {
        name: list(reversed(units)) for name, units in reversed(list(clusters.items()))
    }
    a = draw_two_stage(clusters=clusters, n_psu=4, n_within=2, seed=11)
    b = draw_two_stage(clusters=clusters, n_psu=4, n_within=2, seed=11)
    c = draw_two_stage(clusters=reversed_clusters, n_psu=4, n_within=2, seed=11)
    other = draw_two_stage(clusters=clusters, n_psu=4, n_within=2, seed=7)
    assert a.units == b.units
    assert {(u.psu_id, u.unit_id) for u in a.units} == {
        (u.psu_id, u.unit_id) for u in c.units
    }
    assert {(u.psu_id, u.unit_id) for u in a.units} != {
        (u.psu_id, u.unit_id) for u in other.units
    }


def test_draw_two_stage_carries_two_stage_inclusion_probability():
    clusters = {"alice": ["a1", "a2", "a3", "a4"], "bob": ["b1", "b2", "b3"]}
    sample = draw_two_stage(clusters=clusters, n_psu=2, n_within=2, seed=3)
    assert len(sample.units) == 4
    by_psu = {u.psu_id: u for u in sample.units}
    alice_pi = 1.0 * (2 / 4)
    bob_pi = 1.0 * (2 / 3)
    for unit in sample.units:
        expected = alice_pi if unit.psu_id == "alice" else bob_pi
        assert unit.inclusion_probability == pytest.approx(expected)
    assert set(by_psu) == {"alice", "bob"}


def test_draw_two_stage_refuses_n_within_below_2():
    clusters = {"s0": ["a", "b", "c"]}
    with pytest.raises(AuditSamplingError, match="n_within must be >= 2"):
        draw_two_stage(clusters=clusters, n_psu=1, n_within=1, seed=1)


def test_draw_two_stage_refuses_psu_smaller_than_n_within():
    clusters = {"s0": ["a", "b"], "s1": ["c", "d", "e"]}
    with pytest.raises(AuditSamplingError, match="n_within"):
        draw_two_stage(clusters=clusters, n_psu=2, n_within=3, seed=1)


def test_two_stage_census_of_m3_subjects_is_195_images():
    clusters = {
        f"s{i}": tuple(f"s{i}-{j}" for j in range(m))
        for i, m in enumerate(WHOLE_FRAME.sizes)
        if m >= 3
    }
    assert len(clusters) == 65
    sample = draw_two_stage(clusters=clusters, n_psu=65, n_within=3, seed=20260820)
    assert len(sample.units) == 195
    assert len({u.psu_id for u in sample.units}) == 65


def test_estimate_icc_anova_known_fixture():
    clusters = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
    est = estimate_icc(clusters)
    assert est.n_psu == 3
    assert est.n_within == pytest.approx(2.0)
    assert est.n_obs == 6
    assert est.msb == pytest.approx(8.0)
    assert est.msw == pytest.approx(0.5)
    assert est.icc == pytest.approx(15 / 17)


def test_estimate_icc_fisher_z_ci_for_g65_k3_at_rho_02():
    clusters = _anova_clusters_icc(n_psu=65, icc=0.2)
    est = estimate_icc(clusters)
    assert est.icc == pytest.approx(0.2)
    assert est.n_psu == 65
    assert est.n_within == pytest.approx(3.0)
    assert est.lower == pytest.approx(0.045, abs=5e-4)
    assert est.upper == pytest.approx(0.360, abs=5e-4)
    low_n = size_for_margin(
        margin=0.10, population=640, cluster_size=WHOLE_FRAME_KISH_A, icc=0.045
    ).n
    high_n = size_for_margin(
        margin=0.10, population=640, cluster_size=WHOLE_FRAME_KISH_A, icc=0.360
    ).n
    assert low_n == 121
    assert high_n == 284


def test_estimate_icc_recovers_rho_on_synthetic_clusters():
    clusters = _gaussian_clusters(n_psu=65, n_within=3, rho=0.2, seed=20260820)
    est = estimate_icc(clusters)
    assert est.lower < 0.2 < est.upper
    assert est.lower == pytest.approx(0.045, abs=0.15)
    assert est.upper == pytest.approx(0.360, abs=0.15)


def test_estimate_icc_rejects_singletons_and_too_few_psus():
    with pytest.raises(AuditSamplingError, match="at least 2"):
        estimate_icc([(1.0, 2.0, 3.0), (4.0,)])
    with pytest.raises(AuditSamplingError, match="n_psu"):
        estimate_icc([(1.0, 2.0), (3.0, 4.0)])
    with pytest.raises(AuditSamplingError, match="non-empty"):
        estimate_icc([])
