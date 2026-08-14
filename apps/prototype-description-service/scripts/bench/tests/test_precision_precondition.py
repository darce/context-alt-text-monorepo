"""Precision precondition: bootstrap half-width, occasion rules, Holm."""

from __future__ import annotations

from scripts.bench.score_report import (
    BOOTSTRAP_RESAMPLES,
    CrossbenchTier,
    assign_tier,
    bootstrap_paired_delta,
    holm_bonferroni,
)


def test_green_identical_legs_half_width_zero() -> None:
    a = [1.0] * 6
    b = [1.0] * 6
    interval = bootstrap_paired_delta(a, b, seed=20260729, metric="mean")
    assert interval.ci_half_width == 0.0
    assert interval.ci_lower == 0.0
    assert interval.ci_upper == 0.0


def test_red_discordant_half_width_above_floor() -> None:
    a = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    b = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    interval = bootstrap_paired_delta(a, b, seed=20260729, metric="mean")
    assert interval.ci_half_width > 0.05
    ctx = {
        "named": True,
        "primary": False,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": interval.ci_half_width,
        "head_to_head_delta": 0.10,
        "holm_significant": True,
        "exhaustiveness_ok": True,
        "count_only": False,
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "ci_half_width_above_precision_floor"


def test_occasion_vs_media_resampling() -> None:
    # two occasions of three images: (+1,+1,+1) and (-1,-1,-1)
    a = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    b = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    occasions = ["A", "A", "A", "B", "B", "B"]
    media = bootstrap_paired_delta(a, b, seed=1, metric="mean")
    occ = bootstrap_paired_delta(a, b, seed=1, metric="mean", occasion_ids=occasions)
    assert occ.resampling_unit == "occasion"
    assert occ.ci_half_width != media.ci_half_width
    assert media.resampling_unit in {"image", "media"}


def test_partial_occasion_splits() -> None:
    a = [1.0, 1.0, 1.0, 0.0]
    b = [0.0, 0.0, 0.0, 1.0]
    # occasion A fully accepted (3); occasion B only one accepted image
    occasions = ["A", "A", "A", "B"]
    accepted_mask = [True, True, True, True]
    # Mark occasion B as partial by declaring its full size is 3
    interval = bootstrap_paired_delta(
        a,
        b,
        seed=2,
        metric="mean",
        occasion_ids=occasions,
        occasion_full_size={"A": 3, "B": 3},
        accepted_mask=accepted_mask,
    )
    assert interval.partial_occasions >= 1
    assert interval.resampling_unit == "occasion+image"


def test_holm_on_secondaries() -> None:
    # Three secondaries; first two tiny p, third large.
    result = holm_bonferroni(
        [("s1", 0.001), ("s2", 0.01), ("s3", 0.20)],
        alpha=0.05,
    )
    assert result["s1"]["holm_significant"] is True
    assert result["s3"]["holm_significant"] is False
    empty = holm_bonferroni([], alpha=0.05)
    assert empty == {}


def test_holm_family_size_does_not_shrink() -> None:
    # One computed p in a declared family of 3 must use threshold 0.05/3.
    result = holm_bonferroni([("s1", 0.04)], alpha=0.05, family_size=3)
    assert result["s1"]["holm_threshold"] == 0.05 / 3
    assert result["s1"]["holm_significant"] is False
    shrunk = holm_bonferroni([("s1", 0.04)], alpha=0.05)
    assert shrunk["s1"]["holm_threshold"] == 0.05
    assert shrunk["s1"]["holm_significant"] is True


def test_bootstrap_resamples_pinned() -> None:
    assert BOOTSTRAP_RESAMPLES == 2000


def test_unknown_metric_raises() -> None:
    from scripts.bench.stack_pair import BenchError

    try:
        bootstrap_paired_delta([1.0], [0.0], seed=1, metric="ratio")
    except BenchError as exc:
        assert exc.code == "config_invalid"
    else:
        raise AssertionError("unknown metric must fail closed")


def test_assign_tier_missing_half_width_is_fail_closed() -> None:
    ctx = {
        "named": True,
        "primary": True,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "ci_half_width_above_precision_floor"


def test_assign_tier_primary_emits_confirmatory() -> None:
    ctx = {
        "named": True,
        "primary": True,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "ok",
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.CONFIRMATORY
    assert reason is None


def test_assign_tier_holm_secondary_emits_confirmatory() -> None:
    ctx = {
        "named": True,
        "primary": False,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": True,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "ok",
    }
    tier, reason = assign_tier("detection_precision@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.CONFIRMATORY
    assert reason is None


def test_assign_tier_primary_name_does_not_bypass_flag() -> None:
    ctx = {
        "named": True,
        "primary": False,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "holm"


def test_bootstrap_p_uses_B_not_n_used() -> None:
    """Replaces the R2-07 vacuous all-same-sign red-proof (FIR-8 R3-01).

    Mixed-sign defined deltas plus dropped draws. Exact p must fail under
    `/n_used` AND under numerators that ignore undefined-as-zero.
    """
    import random

    from scripts.bench.score_report import ImageCounts, _resample_delta

    # 2 +1 images, 1 -1 image, 4 zero-denom (undefined when exclusively picked).
    a = [
        ImageCounts(1, 0, 0),
        ImageCounts(1, 0, 0),
        ImageCounts(0, 0, 1),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
    ]
    b = [
        ImageCounts(0, 0, 1),
        ImageCounts(0, 0, 1),
        ImageCounts(1, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
    ]
    B = 80
    seed = 7
    interval = bootstrap_paired_delta(a, b, seed=seed, metric="micro_recall", B=B)

    rng = random.Random(seed)
    n = len(a)
    n_le = n_ge = n_undef = 0
    n_defined_neg = n_defined_pos = 0
    for _ in range(B):
        picks = [rng.randrange(n) for _ in range(n)]
        delta = _resample_delta(a, b, picks, "micro_recall")
        if delta is None:
            n_undef += 1
            n_le += 1
            n_ge += 1
        else:
            if delta <= 0.0:
                n_le += 1
            if delta >= 0.0:
                n_ge += 1
            if delta < 0.0:
                n_defined_neg += 1
            if delta > 0.0:
                n_defined_pos += 1
    n_used = B - n_undef
    assert n_used < B
    assert n_undef > 0
    assert n_defined_neg > 0 and n_defined_pos > 0
    assert interval.n_used == n_used
    assert interval.bootstrap_status == "partial"
    # Hand-fixed (seed=7, B=80): n_le=22, n_ge=69, n_undef=1.
    # 2 * min(22, 69) / 80 = 0.55. Do not replay the production aggregator.
    p_expected = 0.55
    assert n_le == 22 and n_ge == 69 and n_undef == 1
    assert interval.p_value == p_expected
    # Mutations that must not collide with p_expected:
    p_over_n_used = min(1.0, max(2.0 * min(n_le / n_used, n_ge / n_used), 1.0 / (B + 1)))
    p_unadjusted = min(
        1.0,
        max(2.0 * min((n_le - n_undef) / B, (n_ge - n_undef) / B), 1.0 / (B + 1)),
    )
    assert p_over_n_used != p_expected
    assert p_unadjusted != p_expected
    # Hand-computed oracle for a singleton resample of image 0 (FIR-8 R4-12).
    # a[0] recall = tp/(tp+fn) = 1/(1+0) = 1; b[0] = 0/(0+1) = 0; Δ = 1.
    # Production _resample_delta is the SUT, not the oracle.
    assert a[0].tp == 1 and a[0].fn == 0
    assert b[0].tp == 0 and b[0].fn == 1
    hand_delta = (1 / 1) - (0 / 1)
    assert hand_delta == 1.0
    assert _resample_delta(a, b, [0], "micro_recall") == hand_delta


def test_assign_tier_partial_bootstrap_demotes_primary() -> None:
    ctx = {
        "named": True,
        "primary": True,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "partial",
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "bootstrap_status"


def test_assign_tier_partial_bootstrap_demotes_holm_secondary() -> None:
    ctx = {
        "named": True,
        "primary": False,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": True,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "bootstrap_series_mismatch",
    }
    tier, reason = assign_tier("detection_precision@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "bootstrap_status"


def test_empty_series_raises() -> None:
    from scripts.bench.stack_pair import BenchError

    try:
        bootstrap_paired_delta([], [], seed=1, metric="mean")
    except BenchError as exc:
        assert exc.code == "bootstrap_empty_series"
    else:
        raise AssertionError("empty series must fail closed")


def test_assign_tier_missing_bootstrap_status_is_fail_closed() -> None:
    from scripts.bench.stack_pair import BenchError

    ctx = {
        "named": True,
        "primary": True,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
    }
    try:
        assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    except BenchError as exc:
        assert exc.code == "bootstrap_status_missing"
    else:
        raise AssertionError("missing bootstrap_status must not default to ok")


def test_assign_tier_partial_nonsignificant_secondary_reasons_status() -> None:
    ctx = {
        "named": True,
        "primary": False,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "partial",
    }
    tier, reason = assign_tier("identification_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "bootstrap_status"


def test_padded_ci_uses_B_draw_space_not_survivors() -> None:
    """Exact ci_lower/ci_upper on mixed defined/undefined (FIR-8 R4-02)."""
    from scripts.bench.score_report import ImageCounts

    a = [
        ImageCounts(1, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
    ]
    b = [
        ImageCounts(0, 0, 1),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
    ]
    B = 20
    seed = 7
    interval = bootstrap_paired_delta(a, b, seed=seed, metric="micro_recall", B=B)
    assert interval.bootstrap_status == "partial"
    # Padded B-draw space (seed=7, B=20): 17 defined Δ=1.0 + 3 zeros.
    # Linear 2.5th/97.5th of [0]*3 + [1]*17: lower=0.0, upper=1.0.
    # Survivor-only percentiles of [1]*17 would be 1.0/1.0.
    assert interval.n_used == 17
    assert interval.ci_lower == 0.0
    assert interval.ci_upper == 1.0
    assert (interval.ci_lower, interval.ci_upper) != (1.0, 1.0)
