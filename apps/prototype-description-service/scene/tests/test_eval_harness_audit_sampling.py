"""DESCQUAL-2 audit sampling: margin-of-error n, strata, inclusion probabilities."""

from __future__ import annotations

import pytest

from scripts.eval_harness.audit_sampling import (
    AuditSamplingError,
    allocate,
    design_effect,
    draw,
    inflate_for_clustering,
    sample_size_for_margin,
)

# Frozen FIR-12 frame (benchmarks/manifests/fir12-selection-v1.json): N=640.
FIR12_STRATA = {"A": 32, "B": 80, "C": 34, "D": 87, "E": 407}


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


def test_design_effect_mean_images_per_subject():
    assert design_effect(cluster_size=4.9, icc=0.2) == pytest.approx(1.78)


def test_inflate_for_clustering_rounds_up():
    deff = design_effect(cluster_size=4.9, icc=0.2)
    assert inflate_for_clustering(n=84, deff=deff) == 150


def test_allocate_sums_to_n():
    allocation = allocate(strata_sizes=FIR12_STRATA, n=84)
    assert sum(allocation.values()) == 84
    assert set(allocation) == set(FIR12_STRATA)
    assert all(0 <= allocation[name] <= size for name, size in FIR12_STRATA.items())


def test_precision_floor_raises_b_above_proportional():
    proportional = allocate(strata_sizes=FIR12_STRATA, n=84)
    floored = allocate(strata_sizes=FIR12_STRATA, n=84, precision_floors={"B": 0.10})
    assert floored["B"] == 44
    assert floored["B"] > proportional["B"]
    assert sum(floored.values()) == 84
    assert all(0 <= floored[name] <= size for name, size in FIR12_STRATA.items())


def test_draw_is_deterministic_without_replacement_and_carries_pi():
    members = _members()
    allocation = allocate(strata_sizes=FIR12_STRATA, n=84, precision_floors={"B": 0.10})
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
