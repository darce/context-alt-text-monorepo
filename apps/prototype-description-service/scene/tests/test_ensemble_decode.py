"""VLM-4 Slice 2a: ensemble-decode core vote math on stubbed logits.

Logit-only baseline vote, explicit/attention weights path, adaptive
plausibility masking, bounded grid views, determinism [AGT-03].
"""

from __future__ import annotations

import math

import pytest

from scene.infrastructure.vlm.ensemble_decode import (
    HARD_VIEW_CAP,
    EnsembleDecodeConfig,
    ViewBox,
    ViewStrategy,
    WeightingMode,
    build_grid_views,
    combine_token_distributions,
)


def _lp(p: float) -> float:
    return math.log(p)


def test_uniform_vote_prefers_token_agreed_across_views():
    """Two views agree on 'bicycle'; one view alone hallucinates 'table' hard."""
    views = [
        {"bicycle": _lp(0.6), "table": _lp(0.2)},
        {"bicycle": _lp(0.5), "table": _lp(0.3)},
        {"table": _lp(0.5), "bicycle": _lp(0.3)},
    ]
    combined = combine_token_distributions(views)
    winner = next(iter(combined))
    assert winner == "bicycle"
    expected_bicycle = (_lp(0.6) + _lp(0.5) + _lp(0.3)) / 3
    assert combined["bicycle"] == pytest.approx(expected_bicycle)


def test_explicit_weights_shift_the_vote():
    """A dominant per-view weight (attention-mass stand-in) flips the winner."""
    views = [
        {"a": _lp(0.9), "b": _lp(0.05)},
        {"b": _lp(0.9), "a": _lp(0.05)},
    ]
    uniform = combine_token_distributions(views)
    assert set(uniform) == {"a", "b"}
    weighted = combine_token_distributions(views, weights=[0.05, 0.95])
    assert next(iter(weighted)) == "b"


def test_confidence_weighting_favors_the_more_certain_view():
    views = [
        {"a": _lp(0.99), "b": _lp(0.005)},  # very confident in a
        {"b": _lp(0.4), "a": _lp(0.35)},  # lukewarm about b
    ]
    combined = combine_token_distributions(views, weighting_mode=WeightingMode.CONFIDENCE)
    assert next(iter(combined)) == "a"


def test_adaptive_plausibility_masks_globally_implausible_token():
    """'zebra' never exceeds alpha * global-best probability in ANY view -> masked."""
    views = [
        {"bicycle": _lp(0.8), "zebra": _lp(0.01)},
        {"bicycle": _lp(0.7), "zebra": _lp(0.02)},
    ]
    combined = combine_token_distributions(views, plausibility_alpha=0.1)
    assert "zebra" not in combined
    assert "bicycle" in combined
    unmasked = combine_token_distributions(views, plausibility_alpha=0.0)
    assert "zebra" in unmasked


def test_plausibility_keeps_token_plausible_in_one_view():
    """A token strong in a single view survives masking (per-view max governs)."""
    views = [
        {"sign": _lp(0.75), "mural": _lp(0.01)},
        {"mural": _lp(0.6), "sign": _lp(0.2)},
    ]
    combined = combine_token_distributions(views, plausibility_alpha=0.5)
    assert "mural" in combined and "sign" in combined


def test_combined_output_is_deterministic_and_sorted():
    views = [
        {"a": _lp(0.4), "b": _lp(0.4), "c": _lp(0.1)},
        {"b": _lp(0.4), "a": _lp(0.4), "c": _lp(0.1)},
    ]
    first = combine_token_distributions(views)
    second = combine_token_distributions(views)
    assert list(first) == list(second)
    scores = list(first.values())
    assert scores == sorted(scores, reverse=True)
    # Equal-score tokens tie-break lexicographically.
    assert list(first)[:2] == ["a", "b"]


def test_invalid_inputs_raise_explicit_errors():
    with pytest.raises(ValueError):
        combine_token_distributions([])
    with pytest.raises(ValueError):
        combine_token_distributions([{}])
    views = [{"a": _lp(0.5)}, {"a": _lp(0.5)}]
    with pytest.raises(ValueError):
        combine_token_distributions(views, weights=[1.0])
    with pytest.raises(ValueError):
        combine_token_distributions(views, weights=[-1.0, 2.0])
    with pytest.raises(ValueError):
        combine_token_distributions(views, weights=[0.0, 0.0])
    with pytest.raises(ValueError):
        combine_token_distributions(views, plausibility_alpha=1.5)


def test_config_enforces_hard_view_cap_and_alpha_range():
    assert EnsembleDecodeConfig().n_views == 4
    assert EnsembleDecodeConfig().view_strategy is ViewStrategy.GRID
    with pytest.raises(ValueError):
        EnsembleDecodeConfig(n_views=HARD_VIEW_CAP + 1)
    with pytest.raises(ValueError):
        EnsembleDecodeConfig(n_views=0)
    with pytest.raises(ValueError):
        EnsembleDecodeConfig(plausibility_alpha=1.01)


def test_build_grid_views_full_image_first_and_within_bounds():
    views = build_grid_views(400, 300, 4)
    assert len(views) == 4
    assert views[0] == ViewBox(0, 0, 400, 300)
    for box in views[1:]:
        assert 0 <= box.left < box.right <= 400
        assert 0 <= box.top < box.bottom <= 300


def test_build_grid_views_complete_grid_tiles_exactly():
    # 5 views = full image + a complete 2x2 grid partition.
    views = build_grid_views(400, 300, 5)
    assert len(views) == 5
    sub_area = sum((b.right - b.left) * (b.bottom - b.top) for b in views[1:])
    assert sub_area == 400 * 300


def test_build_grid_views_bounds():
    assert len(build_grid_views(100, 100, 1)) == 1
    with pytest.raises(ValueError):
        build_grid_views(100, 100, HARD_VIEW_CAP + 1)
    with pytest.raises(ValueError):
        build_grid_views(0, 100, 2)
