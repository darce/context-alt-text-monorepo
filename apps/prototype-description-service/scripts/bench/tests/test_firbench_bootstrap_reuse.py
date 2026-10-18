"""Exact-draw parity and bounded draw reuse for bootstrap_paired_delta's binary mean path.

Scope: the IID negative-control comparator only (metric="mean", no occasions, no
accepted mask, binary 0/1 legs). Every other input keeps the original slow loop.
Expectations come from an independent replay of random.Random(seed).randrange, from
closed forms or Fraction arithmetic, or from values pinned out of the unmodified
function (float.hex, bit-exact).
"""

from __future__ import annotations

import random
import sys
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

import numpy as np
import pytest

from scripts.bench import score_report as sr
from scripts.bench.score_report import ImageCounts, bootstrap_paired_delta
from scripts.bench.stack_pair import BenchError

S9_SEED = 2429382368
FLOAT_KEYS = ("ci_lower", "ci_upper", "ci_half_width", "p_value")


def _vec(n: int, p: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [1.0 if rng.random() < p else 0.0 for _ in range(n)]


def _interval_fields(deltas: list[float], reps: int, seed: int) -> dict:
    lower = sr.percentile_linear(deltas, 2.5)
    upper = sr.percentile_linear(deltas, 97.5)
    n_le = sum(1 for d in deltas if d <= 0.0)
    n_ge = sum(1 for d in deltas if d >= 0.0)
    p_raw = 2.0 * min(n_le / reps, n_ge / reps)
    return {
        "ci_lower": lower,
        "ci_upper": upper,
        "ci_half_width": (upper - lower) / 2.0,
        "p_value": min(1.0, max(p_raw, 1.0 / (reps + 1))),
        "bootstrap_resamples": reps,
        "bootstrap_seed": seed,
        "n_used": reps,
        "bootstrap_status": "ok",
        "resampling_unit": "image",
        "partial_occasions": 0,
    }


def _oracle(a: list, b: list, seed, reps: int) -> dict:
    """Original per-replicate loop, replayed with its own Random(seed)."""
    rng = random.Random(seed)
    n = len(a)
    deltas: list[float] = []
    for _ in range(reps):
        idxs = [rng.randrange(n) for _ in range(n)]
        deltas.append((sum(a[i] for i in idxs) / len(idxs)) - (sum(b[i] for i in idxs) / len(idxs)))
    return _interval_fields(deltas, reps, seed)


def _assert_bit_exact(iv, expected: dict) -> None:
    for key, want in expected.items():
        got = getattr(iv, key)
        if key in FLOAT_KEYS:
            assert got is not None and float(got).hex() == float(want).hex(), (key, got, want)
        else:
            assert got == want, (key, got, want)


# Pinned from the UNMODIFIED bootstrap_paired_delta on this VM (float.hex).
S9_DESIGNS = {
    "n660_B10000": ((660, 0.62, 11), (660, 0.55, 12), S9_SEED, 10000),
    "n660_B10000_reversed": ((660, 0.55, 12), (660, 0.62, 11), S9_SEED, 10000),
    "n660_B10000_identical": ((660, 0.4, 13), (660, 0.4, 13), S9_SEED, 10000),
    "n660_B10000_ones_zeros": ((660, 1.0, 0), (660, 0.0, 0), S9_SEED, 10000),
    "n480_B10000": ((480, 0.7, 21), (480, 0.3, 22), S9_SEED, 10000),
    "n1020_B10000": ((1020, 0.5, 31), (1020, 0.6, 32), S9_SEED, 10000),
    "n660_B2000_default": ((660, 0.62, 11), (660, 0.55, 12), 20260729, 2000),
}
S9_PINNED = {
    "n660_B10000": {
        "ci_lower": "-0x1.5b8a15b8a15a0p-6",
        "ci_upper": "0x1.5555555555550p-4",
        "ci_half_width": "0x1.ac37dac37dab8p-5",
        "p_value": "0x1.0ef34d6a161e5p-2",
    },
    "n660_B10000_reversed": {
        "ci_lower": "-0x1.5555555555550p-4",
        "ci_upper": "0x1.5b8a15b8a15a0p-6",
        "ci_half_width": "0x1.ac37dac37dab8p-5",
        "p_value": "0x1.0ef34d6a161e5p-2",
    },
    "n660_B10000_identical": {
        "ci_lower": "0x0.0p+0",
        "ci_upper": "0x0.0p+0",
        "ci_half_width": "0x0.0p+0",
        "p_value": "0x1.0000000000000p+0",
    },
    "n660_B10000_ones_zeros": {
        "ci_lower": "0x1.0000000000000p+0",
        "ci_upper": "0x1.0000000000000p+0",
        "ci_half_width": "0x0.0p+0",
        "p_value": "0x1.a3637230afb37p-14",
    },
    "n480_B10000": {
        "ci_lower": "0x1.4000000000001p-2",
        "ci_upper": "0x1.b777777777778p-2",
        "ci_half_width": "0x1.ddddddddddddcp-5",
        "p_value": "0x1.a3637230afb37p-14",
    },
    "n1020_B10000": {
        "ci_lower": "-0x1.1f1f1f1f1f1f2p-3",
        "ci_upper": "-0x1.c9c9c9c9c9ca0p-5",
        "ci_half_width": "0x1.5959595959594p-5",
        "p_value": "0x1.a3637230afb37p-14",
    },
    "n660_B2000_default": {
        "ci_lower": "-0x1.8d3018d3018c0p-6",
        "ci_upper": "0x1.4f2094f2094f0p-4",
        "ci_half_width": "0x1.b26c9b26c9b20p-5",
        "p_value": "0x1.1ba5e353f7ceep-2",
    },
}
# Occasion (PSU-shaped) and accepted-mask fallbacks, pinned from the unmodified function.
OCCASION_PINNED = {
    "ci_lower": "-0x1.6666666666668p-3",
    "ci_upper": "0x1.0000000000000p-2",
    "ci_half_width": "0x1.b333333333334p-3",
    "p_value": "0x1.6b851eb851eb8p-1",
    "resampling_unit": "occasion",
}
MASK_PINNED = {
    "ci_lower": "-0x1.d89d89d89d89cp-3",
    "ci_upper": "0x1.3b13b13b13b13p-2",
    "ci_half_width": "0x1.13b13b13b13b0p-2",
    "p_value": "0x1.cb4395810624ep-1",
    "resampling_unit": "image",
}


def _assert_pinned(iv, pinned: dict) -> None:
    for key, want in pinned.items():
        got = getattr(iv, key)
        if key in FLOAT_KEYS:
            assert float(got).hex() == want, (key, float(got).hex(), want)
        else:
            assert got == want, (key, got, want)


@pytest.mark.parametrize("label", sorted(S9_PINNED))
def test_s9_iid_designs_match_pinned_original_bit_exact(label: str) -> None:
    a_spec, b_spec, seed, reps = S9_DESIGNS[label]
    a, b = _vec(*a_spec), _vec(*b_spec)
    iv = bootstrap_paired_delta(a, b, seed, metric="mean", B=reps)
    _assert_pinned(iv, S9_PINNED[label])
    assert iv.n_used == reps and iv.bootstrap_status == "ok" and iv.bootstrap_resamples == reps


def test_occasion_psu_path_pinned_bit_exact() -> None:
    a, b = _vec(40, 0.6, 41), _vec(40, 0.5, 42)
    occasions = [f"o{i // 4}" for i in range(40)]
    iv = bootstrap_paired_delta(a, b, 20260729, metric="mean", occasion_ids=occasions, B=2000)
    _assert_pinned(iv, OCCASION_PINNED)


def test_accepted_mask_fallback_pinned_bit_exact() -> None:
    a, b = _vec(40, 0.6, 41), _vec(40, 0.5, 42)
    mask = [i % 3 != 0 for i in range(40)]
    iv = bootstrap_paired_delta(a, b, 20260729, metric="mean", accepted_mask=mask, B=2000)
    _assert_pinned(iv, MASK_PINNED)


@pytest.mark.parametrize("n", [1, 2, 3, 7, 33, 100])
@pytest.mark.parametrize("reps", [1, 17, 250])
@pytest.mark.parametrize("seed", [0, 2**31 - 1, 20260729])
def test_binary_mean_matches_independent_replay_bit_exact(n: int, reps: int, seed: int) -> None:
    a = _vec(n, 0.6, seed + 101)
    b = _vec(n, 0.45, seed + 202)
    _assert_bit_exact(bootstrap_paired_delta(a, b, seed, metric="mean", B=reps), _oracle(a, b, seed, reps))


def test_repeated_calls_same_key_reuse_draws_and_stay_exact(monkeypatch) -> None:
    n, reps, seed = 13, 37, 424242
    real_randrange = random.Random.randrange
    draws: list[int] = []

    def counting(self, *args, **kwargs):
        draws.append(1)
        return real_randrange(self, *args, **kwargs)

    monkeypatch.setattr(random.Random, "randrange", counting)
    per_call: list[int] = []
    for i in range(4):
        a = _vec(n, 0.3 + 0.1 * i, 500 + i)
        b = _vec(n, 0.7 - 0.1 * i, 600 + i)
        before = len(draws)
        iv = bootstrap_paired_delta(a, b, seed, metric="mean", B=reps)
        per_call.append(len(draws) - before)
        _assert_bit_exact(iv, _oracle(a, b, seed, reps))
    # Cold build may draw n*reps indices (or nothing if already cached); warm calls draw nothing.
    assert per_call[0] <= n * reps
    assert sum(per_call[1:]) == 0, per_call


def test_binary_mean_skips_per_draw_resample_loop(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("binary IID mean must not run the per-draw slow loop")

    monkeypatch.setattr(sr, "_resample_delta", forbidden)
    a, b = _vec(31, 0.5, 9), _vec(31, 0.4, 10)
    _assert_bit_exact(bootstrap_paired_delta(a, b, 77, metric="mean", B=64), _oracle(a, b, 77, 64))


def test_draw_counts_cache_rows_exact_bounded_readonly() -> None:
    cache = sr._binary_draw_counts
    cache.cache_clear()
    for seed in (1, 2, 3):
        bootstrap_paired_delta(_vec(12, 0.5, 1), _vec(12, 0.5, 2), seed, metric="mean", B=25)
    assert cache.cache_info().currsize <= 2
    counts = cache(12, 25, 3)
    assert counts.shape == (25, 12)
    assert counts.dtype == np.uint16
    assert not counts.flags.writeable
    assert (counts.sum(axis=1) == 12).all()
    rng = random.Random(3)
    for r in range(25):
        idxs = np.array([rng.randrange(12) for _ in range(12)])
        assert np.array_equal(counts[r], np.bincount(idxs, minlength=12))


def test_cell_cap_falls_back_to_original_loop(monkeypatch) -> None:
    monkeypatch.setattr(sr, "_BINARY_DRAW_MAX_CELLS", 100)
    real = sr._resample_delta
    calls: list[int] = []

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(sr, "_resample_delta", spy)
    a, b = _vec(20, 0.5, 3), _vec(20, 0.25, 4)
    _assert_bit_exact(bootstrap_paired_delta(a, b, 5, metric="mean", B=10), _oracle(a, b, 5, 10))
    assert len(calls) == 10


@pytest.mark.parametrize(
    "a,b",
    [
        ([0.5, 0.25, 1.0, 0.0, 0.75], [0.1, 0.9, 0.0, 0.5, 0.5]),
        ([2, 0, 1, 1, 0], [0, 1, 1, 2, 2]),
        ([float("nan"), 0.0, 1.0, 1.0], [0.0, 1.0, 0.0, 1.0]),
        ([True, 0, 1.0, False, 1], [0.0, True, 0, 1, 1]),
        ([-0.0, 1.0, 1.0, 0.0], [0.0, 1.0, 0.0, 1.0]),
    ],
)
def test_mixed_and_nonbinary_inputs_match_replay(a: list, b: list) -> None:
    _assert_bit_exact(bootstrap_paired_delta(a, b, 99, metric="mean", B=40), _oracle(a, b, 99, 40))


def test_nonbinary_values_take_original_resample_loop(monkeypatch) -> None:
    real = sr._resample_delta
    calls: list[int] = []

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(sr, "_resample_delta", spy)
    bootstrap_paired_delta([0.5, 0.25, 1.0, 0.0, 0.75], [0.1, 0.9, 0.0, 0.5, 0.5], 99, metric="mean", B=40)
    assert len(calls) == 40


def test_micro_metric_and_occasions_keep_resample_loop(monkeypatch) -> None:
    real = sr._resample_delta
    calls: list[int] = []

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(sr, "_resample_delta", spy)
    a = [ImageCounts(1, 0, 0), ImageCounts(0, 0, 1), ImageCounts(1, 0, 0)]
    b = [ImageCounts(0, 0, 1), ImageCounts(1, 0, 0), ImageCounts(0, 0, 0)]
    bootstrap_paired_delta(a, b, 3, metric="micro_recall", B=20)
    assert len(calls) == 20
    calls.clear()
    bootstrap_paired_delta(_vec(8, 0.5, 1), _vec(8, 0.5, 2), 3, metric="mean", occasion_ids=["x"] * 8, B=20)
    assert len(calls) == 20


@pytest.mark.parametrize("bad", [["1", "0"], [1, None]])
def test_non_numeric_labels_still_raise_type_error(bad: list) -> None:
    with pytest.raises(TypeError):
        bootstrap_paired_delta(bad, [0, 1], 1, metric="mean", B=5)


def test_identical_legs_closed_form() -> None:
    a = _vec(50, 0.4, 3)
    iv = bootstrap_paired_delta(a, list(a), 11, metric="mean", B=500)
    assert (iv.ci_lower, iv.ci_upper, iv.ci_half_width) == (0.0, 0.0, 0.0)
    assert iv.p_value == 1.0
    assert iv.n_used == 500 and iv.bootstrap_status == "ok"


def test_all_ones_vs_all_zeros_closed_form() -> None:
    n, reps = 40, 500
    iv = bootstrap_paired_delta([1.0] * n, [0.0] * n, 12, metric="mean", B=reps)
    assert (iv.ci_lower, iv.ci_upper, iv.ci_half_width) == (1.0, 1.0, 0.0)
    assert iv.p_value == 1.0 / (reps + 1)


def test_reversed_legs_negate_interval() -> None:
    a, b = _vec(120, 0.7, 21), _vec(120, 0.35, 22)
    fwd = bootstrap_paired_delta(a, b, 33, metric="mean", B=800)
    rev = bootstrap_paired_delta(b, a, 33, metric="mean", B=800)
    assert rev.ci_lower == pytest.approx(-fwd.ci_upper, abs=1e-12)
    assert rev.ci_upper == pytest.approx(-fwd.ci_lower, abs=1e-12)
    assert rev.ci_half_width == pytest.approx(fwd.ci_half_width, abs=1e-12)
    assert rev.p_value == fwd.p_value


def test_exact_fraction_counts_and_interval_within_float_tolerance() -> None:
    n, reps, seed = 5, 60, 7
    a = [1, 0, 1, 1, 0]
    b = [0, 0, 1, 0, 1]
    iv = bootstrap_paired_delta(a, b, seed, metric="mean", B=reps)
    rng = random.Random(seed)
    exact: list[Fraction] = []
    for _ in range(reps):
        idxs = [rng.randrange(n) for _ in range(n)]
        exact.append(Fraction(sum(a[i] for i in idxs), n) - Fraction(sum(b[i] for i in idxs), n))
    n_le = sum(1 for d in exact if d <= 0)
    n_ge = sum(1 for d in exact if d >= 0)
    assert iv.p_value == min(1.0, max(2.0 * min(n_le / reps, n_ge / reps), 1.0 / (reps + 1)))
    floats = [float(d) for d in exact]
    assert iv.ci_lower == pytest.approx(sr.percentile_linear(floats, 2.5), abs=1e-12)
    assert iv.ci_upper == pytest.approx(sr.percentile_linear(floats, 97.5), abs=1e-12)


def test_eviction_does_not_change_results() -> None:
    n, reps = 25, 90
    a, b = _vec(n, 0.5, 1), _vec(n, 0.5, 2)
    first = bootstrap_paired_delta(a, b, 101, metric="mean", B=reps)
    for seed in (102, 103, 104):
        bootstrap_paired_delta(a, b, seed, metric="mean", B=reps)
    again = bootstrap_paired_delta(a, b, 101, metric="mean", B=reps)
    assert vars(again) == vars(first)
    _assert_bit_exact(again, _oracle(a, b, 101, reps))


def test_concurrent_cold_and_warm_calls_are_exact() -> None:
    n, reps, seed = 30, 120, 777001
    cases = [(_vec(n, 0.2 + 0.1 * i, 900 + i), _vec(n, 0.8 - 0.1 * i, 950 + i)) for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(bootstrap_paired_delta, a, b, seed, metric="mean", B=reps) for a, b in cases]
        results = [f.result() for f in futures]
    for (a, b), iv in zip(cases, results, strict=True):
        _assert_bit_exact(iv, _oracle(a, b, seed, reps))


def test_numpy_import_failure_uses_original_loop(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "numpy", None)
    a, b = _vec(16, 0.5, 4), _vec(16, 0.3, 5)
    _assert_bit_exact(bootstrap_paired_delta(a, b, 6, metric="mean", B=30), _oracle(a, b, 6, 30))


def test_out_of_range_arguments_keep_original_behavior() -> None:
    with pytest.raises(BenchError) as exc:
        bootstrap_paired_delta([1.0, 0.0], [0.0, 1.0], 1, metric="mean", B=0)
    assert exc.value.code == "bootstrap_undefined"
    n = 65536
    a = [1.0 if i % 2 else 0.0 for i in range(n)]
    b = list(reversed(a))
    _assert_bit_exact(bootstrap_paired_delta(a, b, 8, metric="mean", B=1), _oracle(a, b, 8, 1))
    _assert_bit_exact(
        bootstrap_paired_delta([1.0, 0.0], [0.0, 1.0], True, metric="mean", B=9),
        _oracle([1.0, 0.0], [0.0, 1.0], True, 9),
    )


def test_inputs_not_mutated_and_global_random_state_untouched() -> None:
    a, b = _vec(64, 0.5, 13), _vec(64, 0.5, 14)
    a_before, b_before = list(a), list(b)
    state = random.getstate()
    bootstrap_paired_delta(a, b, 15, metric="mean", B=200)
    assert a == a_before and b == b_before
    assert random.getstate() == state
