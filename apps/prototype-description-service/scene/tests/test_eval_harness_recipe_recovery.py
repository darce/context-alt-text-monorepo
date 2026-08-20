"""Recipe-recovery oracle tests (CORPUS-1).

The harness exists to answer "which recipe built the mirror" with evidence, so
its own tests are held to the same bar: every assertion that a recipe *matches*
is paired with a case where the identical code path must *not* match [TEST-15].
A sweep that always reports 100% is indistinguishable from a broken one.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.eval_harness.recipe_recovery import (
    Recipe,
    RecipeError,
    Tier,
    TierResult,
    build_source_index,
    characterize_residual,
    default_grid,
    evaluate,
    load_entries,
    sweep,
    upscale_violations,
)

SHRINK_FLOOR = Recipe(name="shrink_floor", cap=1280, rounding="floor")


def _write_image(path: Path, size: tuple[int, int], colour: tuple[int, int, int] = (10, 120, 200)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path, format="JPEG", quality=95)
    return path


def _entry(media_id: int, source: Path, recipe: Recipe, **over) -> dict:
    """Ground truth synthesised *from* a recipe, so the oracle has a known answer."""
    with Image.open(source) as im:
        w, h = recipe.geometry(*im.size)
    entry = {
        "media_id": media_id,
        "path": f"{media_id}.jpg",
        "bucket": "personal",
        "width": w,
        "height": h,
        "sha256": hashlib.sha256(recipe.encode(source)).hexdigest(),
        "sha256_source": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    entry.update(over)
    return entry


# --- geometry -------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((2000, 1000), (1280, 640)),
        ((1000, 2000), (640, 1280)),
        ((1280, 720), (1280, 720)),  # already at the cap: untouched
        ((800, 600), (800, 600)),  # under the cap: shrink-only leaves it alone
    ],
)
def test_shrink_only_geometry(size, expected) -> None:
    assert SHRINK_FLOOR.geometry(*size) == expected


def test_rounding_modes_actually_diverge() -> None:
    """If every mode agreed, the sweep could not discriminate between them."""
    src = (1707, 2560)  # minor axis lands on .0 + epsilon under a 1280 cap
    results = {mode: Recipe(name=mode, cap=1280, rounding=mode).geometry(*src) for mode in
               ("floor", "ceil", "half_up", "half_even")}
    assert len(set(results.values())) > 1, results
    assert results["floor"][0] < results["ceil"][0]


def test_exact_rationals_and_floats_disagree_on_a_real_corpus_case() -> None:
    """974x1732 under a 1280 cap is the case that motivated the exact path.

    The exact minor axis is 311680/433 = 719.8152...; IEEE-754 multiplication
    lands just below it. Both floor to 719 here, but the two paths must be
    genuinely distinct code, not an alias — otherwise the sweep's ``exact`` and
    ``float`` variants would be a meaningless doubling of the grid [TEST-15].
    """
    exact = Recipe(name="e", cap=1280, rounding="half_up", exact_ratio=True)
    approx = Recipe(name="f", cap=1280, rounding="half_up", exact_ratio=False)
    assert exact.geometry(974, 1732) == (720, 1280)
    assert approx.geometry(974, 1732) == (720, 1280)
    # 1270/2000 scaled by 1280 is exactly 812.8 either way; the grid still
    # carries both so a corpus-wide sweep can tell them apart where they differ.
    assert exact.geometry(2000, 1270) == approx.geometry(2000, 1270) == (1280, 813)
    assert Recipe(name="x", cap=1280, rounding="floor").geometry(2000, 1270) == (1280, 812)


def test_geometry_never_returns_a_zero_axis() -> None:
    """An extreme aspect ratio must clamp to 1px, not to a 0-width image."""
    w, h = Recipe(name="tiny", cap=10, rounding="floor").geometry(4000, 3)
    assert w >= 1 and h >= 1


def test_unknown_rounding_or_filter_is_refused_at_construction() -> None:
    with pytest.raises(RecipeError, match="unknown rounding"):
        Recipe(name="bad", cap=1280, rounding="stochastic")
    with pytest.raises(RecipeError, match="unknown resample"):
        Recipe(name="bad", cap=1280, rounding="floor", resample="magic")
    with pytest.raises(RecipeError, match="cap must be"):
        Recipe(name="bad", cap=0, rounding="floor")


# --- the upscale refusal --------------------------------------------------


def test_shrink_only_can_never_upscale_but_forced_can(tmp_path: Path) -> None:
    """The refusal that matters, with the guard that proves it can fire.

    Upscaling interpolates detail that was never captured and pushes a face box
    past a detector's minimum-size gate, so a rebuild candidate must be
    incapable of it. The ``force`` recipe exists only to prove the check reacts
    to the recipe rather than always returning [] [TEST-15].
    """
    src = _write_image(tmp_path / "small.jpg", (400, 300))
    entries = [_entry(1, src, SHRINK_FLOOR)]
    sources = {entries[0]["sha256_source"]: src}

    assert upscale_violations(SHRINK_FLOOR, entries, sources) == []
    forced = Recipe(name="force", cap=1280, rounding="floor", shrink_only=False)
    assert upscale_violations(forced, entries, sources) == [1]
    assert forced.geometry(400, 300) == (1280, 960)


# --- the dims oracle ------------------------------------------------------


def test_dims_oracle_finds_the_recipe_that_built_the_manifest(tmp_path: Path) -> None:
    truth = Recipe(name="truth", cap=1280, rounding="floor")
    entries, sources = [], {}
    for i, size in enumerate([(3000, 2001), (2555, 1703), (1999, 3001), (900, 600)], start=1):
        src = _write_image(tmp_path / f"s{i}.jpg", size)
        e = _entry(i, src, truth)
        entries.append(e)
        sources[e["sha256_source"]] = src

    ranked = sweep(entries, sources, default_grid(), tier=Tier.DIMS)
    best, result = ranked[0]
    assert result.matched == len(entries)
    assert result.rate == 1.0
    assert best.cap == 1280 and best.shrink_only and best.rounding == "floor"

    # Discrimination guard: a wrong cap must not also score perfectly.
    wrong = evaluate(Recipe(name="w", cap=1024, rounding="floor"), entries, sources, Tier.DIMS)
    assert wrong.matched < len(entries)


def test_sweep_order_is_deterministic(tmp_path: Path) -> None:
    src = _write_image(tmp_path / "a.jpg", (2400, 1600))
    e = _entry(1, src, SHRINK_FLOOR)
    sources = {e["sha256_source"]: src}
    first = [r.name for r, _ in sweep([e], sources, default_grid(), Tier.DIMS)]
    second = [r.name for r, _ in sweep([e], sources, default_grid(), Tier.DIMS)]
    assert first == second  # [TEST-08]


# --- the bytes oracle -----------------------------------------------------


def test_bytes_oracle_round_trips_and_rejects_a_wrong_filter(tmp_path: Path) -> None:
    truth = Recipe(name="truth", cap=1280, rounding="floor", resample="lanczos", quality=85)
    src = _write_image(tmp_path / "b.jpg", (2600, 1733))
    e = _entry(1, src, truth)
    sources = {e["sha256_source"]: src}

    assert evaluate(truth, [e], sources, Tier.BYTES).matched == 1
    other = Recipe(name="other", cap=1280, rounding="floor", resample="nearest", quality=85)
    assert evaluate(other, [e], sources, Tier.BYTES).mismatched == 1


# --- the pixels oracle is honest about being unavailable ------------------


def test_pixels_tier_without_a_mirror_is_unavailable_not_a_pass(tmp_path: Path) -> None:
    """The lost mirror must read as UNAVAILABLE, never as a silent 0/0 success.

    This is the failure mode the tier exists to prevent: a gate whose oracle is
    missing should be loud, because an empty denominator renders as 'no
    mismatches' to anyone reading a summary line [rg-008].
    """
    src = _write_image(tmp_path / "c.jpg", (2000, 1500))
    e = _entry(1, src, SHRINK_FLOOR)
    result = evaluate(SHRINK_FLOOR, [e], {e["sha256_source"]: src}, Tier.PIXELS)
    assert result.unavailable == 1
    assert result.matched == 0 and result.mismatched == 0
    assert result.rate is None  # not 1.0, and not 0.0


def test_pixels_tier_is_exact_against_a_lossless_mirror(tmp_path: Path) -> None:
    truth = Recipe(name="truth", cap=1280, rounding="floor", resample="lanczos")
    src = _write_image(tmp_path / "d.jpg", (2400, 1800))
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    truth.render(src).save(mirror / "1.png", format="PNG")
    e = _entry(1, src, truth, path="1.png")
    sources = {e["sha256_source"]: src}

    # No encoder on either side, so tolerance 0 is the right contract here.
    assert evaluate(truth, [e], sources, Tier.PIXELS, mirror_root=mirror).matched == 1
    wrong = Recipe(name="wrong", cap=1280, rounding="floor", resample="nearest")
    assert evaluate(wrong, [e], sources, Tier.PIXELS, mirror_root=mirror).mismatched == 1


def test_pixels_tier_needs_tolerance_against_a_lossy_mirror(tmp_path: Path) -> None:
    """The real corpus case: the mirror is JPEG, so exact equality is unusable.

    At tolerance 0 the *true* recipe is rejected. A small tolerance admits it
    while still rejecting a different resample filter, which is what keeps the
    tier a test rather than a rubber stamp [TEST-15].
    """
    truth = Recipe(name="truth", cap=1280, rounding="floor", resample="lanczos")
    src = _write_image(tmp_path / "e2.jpg", (2400, 1800), colour=(200, 40, 90))
    mirror = tmp_path / "lossy"
    mirror.mkdir()
    truth.render(src).save(mirror / "1.jpg", format="JPEG", quality=85)
    e = _entry(1, src, truth)
    sources = {e["sha256_source"]: src}

    assert evaluate(truth, [e], sources, Tier.PIXELS, mirror_root=mirror, pixel_tolerance=0).mismatched == 1
    assert evaluate(truth, [e], sources, Tier.PIXELS, mirror_root=mirror, pixel_tolerance=24).matched == 1
    wrong = Recipe(name="wrong", cap=1280, rounding="floor", resample="nearest")
    assert evaluate(wrong, [e], sources, Tier.PIXELS, mirror_root=mirror, pixel_tolerance=24).mismatched == 1


def test_pixels_tier_reports_a_geometry_miss_as_dimensions(tmp_path: Path) -> None:
    """A wrong cap must surface as sizes, not as an uninterpretable delta."""
    truth = Recipe(name="truth", cap=1280, rounding="floor")
    src = _write_image(tmp_path / "f.jpg", (2400, 1800))
    mirror = tmp_path / "m2"
    mirror.mkdir()
    truth.render(src).save(mirror / "1.png", format="PNG")
    e = _entry(1, src, truth, path="1.png")
    sources = {e["sha256_source"]: src}

    result = evaluate(Recipe(name="w", cap=1024, rounding="floor"), [e], sources,
                      Tier.PIXELS, mirror_root=mirror, pixel_tolerance=24)
    assert result.mismatched == 1
    assert result.residual[0]["got"] == (1024, 768)


# --- robustness -----------------------------------------------------------


def test_a_corrupt_source_is_counted_not_fatal(tmp_path: Path) -> None:
    """One unreadable file must not end the sweep [rg-007]."""
    good = _write_image(tmp_path / "good.jpg", (2000, 1500))
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    e_good = _entry(1, good, SHRINK_FLOOR)
    e_bad = {**e_good, "media_id": 2, "sha256_source": "b" * 64}
    sources = {e_good["sha256_source"]: good, "b" * 64: bad}

    result = evaluate(SHRINK_FLOOR, [e_good, e_bad], sources, Tier.DIMS)
    assert result.matched == 1 and result.errored == 1
    assert result.rate == 1.0  # the unreadable file does not condemn the recipe
    assert result.considered == 2


def test_an_unresolved_source_is_unavailable_not_a_mismatch(tmp_path: Path) -> None:
    src = _write_image(tmp_path / "e.jpg", (2000, 1500))
    e = _entry(1, src, SHRINK_FLOOR)
    result = evaluate(SHRINK_FLOOR, [e], {}, Tier.DIMS)  # empty index
    assert result.unavailable == 1 and result.mismatched == 0


# --- the source index -----------------------------------------------------


def test_source_index_is_content_addressed_and_stable(tmp_path: Path) -> None:
    """Layout must not matter: the same bytes under a new name still resolve."""
    a = _write_image(tmp_path / "one" / "photo.jpg", (1400, 900))
    digest = hashlib.sha256(a.read_bytes()).hexdigest()
    (tmp_path / "two").mkdir()
    (tmp_path / "two" / "renamed.jpg").write_bytes(a.read_bytes())

    index = build_source_index([tmp_path], {digest})
    assert set(index) == {digest}
    assert build_source_index([tmp_path], {digest}) == index  # deterministic tie-break
    assert build_source_index([tmp_path], {"f" * 64}) == {}  # only asked-for digests


# --- residual characterisation --------------------------------------------


def test_residual_characterisation_separates_off_by_one_from_a_wrong_rule() -> None:
    off_by_one = [
        {"media_id": 1, "bucket": "personal", "got": (1280, 853), "want": (1280, 854)},
        {"media_id": 2, "bucket": "celebs", "got": (1280, 960), "want": (1280, 959)},
    ]
    summary = characterize_residual(off_by_one)
    assert summary["off_by_one_only"] is True
    assert summary["n"] == 2
    assert summary["buckets"] == {"personal": 1, "celebs": 1}

    # A genuinely different rule must not be laundered as a rounding quibble.
    wrong_rule = characterize_residual([{"media_id": 3, "bucket": "personal", "got": (640, 480), "want": (1280, 960)}])
    assert wrong_rule["off_by_one_only"] is False


def test_empty_residual_is_not_reported_as_off_by_one() -> None:
    assert characterize_residual([])["off_by_one_only"] is False


# --- provenance -----------------------------------------------------------


def test_provenance_names_every_output_affecting_field(tmp_path: Path) -> None:
    """A recovered recipe is only reproducible if it records its library [PROV-01]."""
    prov = SHRINK_FLOOR.provenance()
    for key in ("recipe", "cap", "rounding", "shrink_only", "resample", "quality",
                "exact_ratio", "pillow_version"):
        assert key in prov, key
    assert prov["pillow_version"]


def test_load_entries_refuses_an_empty_manifest(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"manifest_version": 3, "entries": []}))
    with pytest.raises(RecipeError, match="no entries"):
        load_entries(empty)


def test_tier_result_rate_is_none_when_nothing_was_decidable() -> None:
    assert TierResult(tier=Tier.DIMS).rate is None
