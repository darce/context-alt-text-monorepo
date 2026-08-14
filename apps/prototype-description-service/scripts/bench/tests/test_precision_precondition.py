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
        "cluster_ok": True,
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


def test_bootstrap_resamples_pinned() -> None:
    assert BOOTSTRAP_RESAMPLES == 2000
