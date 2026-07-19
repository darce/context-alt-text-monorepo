"""FIR-5 S4: synthetic_occlusion — determinism, anchors, guards, can-fail (TEST-15).

TEST-08 / DATA-09: same seed → hash-identical occluder pixels.
TEST-15: occluded mis-assign drives a_s red.
Guards: distinct-image min-gallery, ≥2-identity DIRECTIONAL, re-detect-miss=0.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.eval_harness.face_assignment import MatchedFace, argmax_gallery
from scripts.eval_harness.landmark_cache import (
    CachedLandmark,
    LandmarkCache,
    LandmarkCacheProvenance,
)
from scripts.eval_harness.synthetic_occlusion import (
    ELIGIBLE_PAIR_FLOOR,
    WALK_STABILITY_DELTA_BOUND,
    anatomy_region_stats,
    apply_occlusion,
    assert_walk_stability,
    build_occlusion_gallery,
    filter_headline_probes,
    generate_twin_specs,
    has_distinct_image_gallery_support,
    occluder_pixel_mask,
    pixel_buffer_hash,
    render_twin,
    score_occlusion_accuracy,
    score_occlusion_pair,
    source_media_excluded_from_gallery,
)


def _unit(vec: list[float]) -> list[float]:
    a = np.asarray(vec, dtype=np.float64)
    n = float(np.linalg.norm(a))
    assert n > 0
    return (a / n).tolist()


def _matched(
    media_id: int,
    box_index: int,
    emb: list[float],
    true_name: str,
    *,
    det_index: int = 0,
) -> MatchedFace:
    return MatchedFace(
        media_id=media_id,
        path=f"{media_id}.jpg",
        box_index=box_index,
        det_index=det_index,
        embedding=tuple(_unit(emb)),
        true_name=true_name,
    )


def _frontal_lm(cx: float = 50.0, cy: float = 50.0, scale: float = 20.0) -> list[list[float]]:
    return [
        [cx - scale * 0.35, cy - scale * 0.15],
        [cx + scale * 0.35, cy - scale * 0.15],
        [cx, cy + scale * 0.05],
        [cx - scale * 0.30, cy + scale * 0.40],
        [cx + scale * 0.30, cy + scale * 0.40],
    ]


def _cache_one(
    media_id: int = 1,
    box_index: int = 0,
    name: str = "Alice",
    lm: list[list[float]] | None = None,
) -> LandmarkCache:
    landmarks = lm or _frontal_lm()
    entry = CachedLandmark(
        media_id=media_id,
        box_index=box_index,
        name=name,
        landmarks_px=tuple((float(p[0]), float(p[1])) for p in landmarks),
        bbox_px=(30.0, 30.0, 40.0, 40.0),
        det_score=0.95,
    )
    return LandmarkCache(
        provenance=LandmarkCacheProvenance.pinned_yunet(),
        entries=(entry,),
    )


# ---------------------------------------------------------------------------
# Determinism layer 2 (TEST-08)
# ---------------------------------------------------------------------------


def test_same_seed_hash_identical_occluder_pixels():
    img = np.full((100, 100, 3), 200, dtype=np.uint8)
    lm = _frontal_lm(50, 50, 18)
    for kind in ("masked", "sunglasses", "occlusion_other"):
        a = apply_occlusion(img, lm, kind, seed=12345)
        b = apply_occlusion(img, lm, kind, seed=12345)
        assert pixel_buffer_hash(a) == pixel_buffer_hash(b)
        assert a.dtype == np.uint8
        np.testing.assert_array_equal(a, b)


def test_different_seed_changes_pixels():
    img = np.full((100, 100, 3), 200, dtype=np.uint8)
    lm = _frontal_lm()
    a = apply_occlusion(img, lm, "masked", seed=1)
    b = apply_occlusion(img, lm, "masked", seed=2)
    assert pixel_buffer_hash(a) != pixel_buffer_hash(b)


# ---------------------------------------------------------------------------
# Anatomy anchors
# ---------------------------------------------------------------------------


def test_anatomy_anchors_mask_lower_face_sunglasses_eyes_patch_upper_or_cheek():
    h, w = 120, 120
    lm = _frontal_lm(60, 60, 22)

    mask_m = occluder_pixel_mask((h, w), lm, "masked", seed=0)
    stats_m = anatomy_region_stats(mask_m, lm)
    assert stats_m["lower_face_frac"] > 0.5  # mask → lower face / mouth

    mask_s = occluder_pixel_mask((h, w), lm, "sunglasses", seed=0)
    stats_s = anatomy_region_stats(mask_s, lm)
    assert stats_s["eye_band_frac"] > 0.4  # sunglasses → eye pair band

    # occlusion_other seed even → forehead (upper); odd → cheek (still not pure lower).
    mask_f = occluder_pixel_mask((h, w), lm, "occlusion_other", seed=0)
    stats_f = anatomy_region_stats(mask_f, lm)
    assert stats_f["upper_frac"] > 0.3 or stats_f["eye_band_frac"] > 0.2

    mask_c = occluder_pixel_mask((h, w), lm, "occlusion_other", seed=1)
    assert int(mask_c.sum()) > 0


# ---------------------------------------------------------------------------
# Twin generation + firewall / decoupling
# ---------------------------------------------------------------------------


def test_twins_generated_offline_for_every_cache_detected_roster_face():
    """Decoupling: twin count = cache named entries × kinds (not score-time probes)."""
    e1 = CachedLandmark(
        media_id=1,
        box_index=0,
        name="Alice",
        landmarks_px=tuple((float(p[0]), float(p[1])) for p in _frontal_lm(40, 40)),
        bbox_px=(20.0, 20.0, 40.0, 40.0),
        det_score=0.9,
    )
    e2 = CachedLandmark(
        media_id=2,
        box_index=0,
        name="Bob",
        landmarks_px=tuple((float(p[0]), float(p[1])) for p in _frontal_lm(50, 50)),
        bbox_px=(30.0, 30.0, 40.0, 40.0),
        det_score=0.9,
    )
    cache = LandmarkCache(
        provenance=LandmarkCacheProvenance.pinned_yunet(),
        entries=(e1, e2),
    )
    specs = generate_twin_specs(cache, kinds=("masked", "sunglasses", "occlusion_other"), seed=0)
    assert len(specs) == 2 * 3
    names = {(s.media_id, s.box_index, s.true_name) for s in specs}
    assert (1, 0, "Alice") in names
    assert (2, 0, "Bob") in names


def test_occluded_faces_absent_from_headline_probe_list():
    """Firewall: twins never enter headline identification set."""
    unoccluded = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.1, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),
    ]
    # Synthetic twin would be tagged (media_id, box_index, "occluded").
    occluded_keys = {(1, 0, "occluded")}
    headline = filter_headline_probes(unoccluded, occluded_probe_keys=occluded_keys)
    assert all(not ((f.media_id, f.box_index, "occluded") in occluded_keys) for f in headline)
    # Default path: callers simply do not add twin MatchedFaces.
    assert len(filter_headline_probes(unoccluded)) == 3


def test_twin_source_image_excluded_from_occlusion_gallery():
    faces = [
        _matched(10, 0, [1, 0, 0], "Alice"),  # source image
        _matched(10, 1, [1, 0.05, 0], "Alice"),  # same media — must also be excluded
        _matched(11, 0, [1, 0.1, 0], "Alice"),  # other media — stays
        _matched(20, 0, [0, 1, 0], "Bob"),
    ]
    by_id = {"Alice": [faces[0], faces[1], faces[2]], "Bob": [faces[3]]}
    gallery = build_occlusion_gallery("Alice", source_media_id=10, by_identity=by_id)
    # Gallery prototypes only — verify support faces for Alice exclude media 10.
    alice_support = [f for f in by_id["Alice"] if f.media_id != 10]
    assert source_media_excluded_from_gallery(alice_support, 10)
    assert "Alice" in gallery
    assert "Bob" in gallery
    # Mean of only media-11 Alice embedding.
    expected = np.asarray(faces[2].embedding, dtype=np.float64)
    np.testing.assert_allclose(gallery["Alice"], expected / np.linalg.norm(expected), atol=1e-6)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_distinct_image_min_gallery_two_faces_same_media_ineligible():
    """Two faces on the same media_id both vanish → identity ineligible for that twin."""
    faces = [
        _matched(5, 0, [1, 0, 0], "Alice"),
        _matched(5, 1, [1, 0.05, 0], "Alice"),  # same media_id only
        _matched(9, 0, [0, 1, 0], "Bob"),
        _matched(8, 0, [0, 1, 0.1], "Bob"),
    ]
    by_id = {"Alice": [faces[0], faces[1]], "Bob": [faces[2], faces[3]]}
    assert not has_distinct_image_gallery_support("Alice", 5, by_id)
    assert has_distinct_image_gallery_support("Bob", 9, by_id)

    result = score_occlusion_pair(
        twin_embedding=_unit([1, 0, 0]),
        true_name="Alice",
        source_media_id=5,
        box_index=0,
        kind="masked",
        by_identity=by_id,
    )
    assert result.eligible is False
    assert result.ineligible_reason == "distinct_image_min_gallery"
    assert result.correct is None


def test_lt_2_distinct_identity_gallery_marks_directional():
    """Single-identity argmax ≡ true_name vacuously 1.0 → DIRECTIONAL."""
    # Alice has faces on media 1 and 2; no other identities → gallery size 1.
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
    ]
    by_id = {"Alice": faces}
    pair = score_occlusion_pair(
        twin_embedding=_unit([1, 0, 0]),
        true_name="Alice",
        source_media_id=1,
        box_index=0,
        kind="masked",
        by_identity=by_id,
    )
    assert pair.eligible is True
    assert pair.gallery_n_identities == 1
    assert pair.correct is True  # vacuous top-1

    rollup = score_occlusion_accuracy(
        [
            {
                "media_id": 1,
                "box_index": 0,
                "true_name": "Alice",
                "kind": "masked",
                "embedding": _unit([1, 0, 0]),
            }
        ],
        faces,
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert rollup.directional is True
    assert any("gallery_lt_2" in r for r in rollup.directional_reasons)


def test_re_detect_miss_is_accuracy_zero_kept_in_n():
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),
        _matched(4, 0, [0, 1, 0.05], "Bob"),
    ]
    pair = score_occlusion_pair(
        twin_embedding=None,  # re-detect miss
        true_name="Alice",
        source_media_id=1,
        box_index=0,
        kind="sunglasses",
        by_identity={"Alice": faces[:2], "Bob": faces[2:]},
    )
    assert pair.eligible is True
    assert pair.re_detect_miss is True
    assert pair.correct is False

    rollup = score_occlusion_accuracy(
        [
            {
                "media_id": 1,
                "box_index": 0,
                "true_name": "Alice",
                "kind": "sunglasses",
                "embedding": None,
            }
        ],
        faces,
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert rollup.n_eligible == 1
    assert rollup.n_correct == 0
    assert rollup.n_re_detect_miss == 1
    assert rollup.accuracy == 0.0


def test_eligible_pair_floor_under_90_is_directional():
    """MLDATA-02: n_eligible < 90 → DIRECTIONAL (do not claim ≥90 guaranteed)."""
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),
        _matched(4, 0, [0, 1, 0.05], "Bob"),
    ]
    # Only a handful of pairs — well under floor.
    inputs = [
        {
            "media_id": 1,
            "box_index": 0,
            "true_name": "Alice",
            "kind": "masked",
            "embedding": _unit([1, 0, 0]),
        }
        for _ in range(5)
    ]
    rollup = score_occlusion_accuracy(
        inputs,
        faces,
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert rollup.n_eligible == 5
    assert rollup.n_eligible < ELIGIBLE_PAIR_FLOOR
    assert rollup.meets_pair_floor is False
    assert rollup.directional is True
    assert any("eligible_pairs=" in r for r in rollup.directional_reasons)


def test_walk_stability_not_asserted_is_directional():
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),
        _matched(4, 0, [0, 1, 0.05], "Bob"),
    ]
    rollup = score_occlusion_accuracy(
        [
            {
                "media_id": 1,
                "box_index": 0,
                "true_name": "Alice",
                "kind": "masked",
                "embedding": _unit([1, 0, 0]),
            }
        ],
        faces,
        walk_stability_asserted=False,
    )
    assert rollup.directional is True
    assert "walk_stability_not_asserted" in rollup.directional_reasons


def test_walk_stability_bound_helper():
    met, delta = assert_walk_stability(0.90, 0.91, n_eligible=ELIGIBLE_PAIR_FLOOR)
    assert met is True
    assert delta == pytest.approx(0.01)
    met2, delta2 = assert_walk_stability(
        0.90, 0.90 + WALK_STABILITY_DELTA_BOUND + 0.01, n_eligible=ELIGIBLE_PAIR_FLOOR
    )
    assert met2 is False
    assert delta2 is not None and delta2 > WALK_STABILITY_DELTA_BOUND


# ---------------------------------------------------------------------------
# OCCLUSION CAN-FAIL (TEST-15)
# ---------------------------------------------------------------------------


def test_occlusion_can_fail_misassign_drives_a_s_down():
    """An occluded embedding that argmax MUST mis-assign drives a_s red."""
    # Alice prototypes near [1,0,0]; Bob near [0,1,0].
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [0.99, 0.01, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),
        _matched(4, 0, [0.01, 0.99, 0], "Bob"),
    ]
    by_id = {"Alice": faces[:2], "Bob": faces[2:]}

    # Twin embedding of Alice that is closer to Bob → forced mis-assign.
    bad_emb = _unit([0, 1, 0])
    gallery = build_occlusion_gallery("Alice", 1, by_id)
    _s, name_star = argmax_gallery(np.asarray(bad_emb), gallery)
    assert name_star == "Bob"  # must mis-assign

    good_emb = _unit([1, 0, 0])
    good = score_occlusion_accuracy(
        [
            {
                "media_id": 1,
                "box_index": 0,
                "true_name": "Alice",
                "kind": "masked",
                "embedding": good_emb,
            }
        ],
        faces,
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    bad = score_occlusion_accuracy(
        [
            {
                "media_id": 1,
                "box_index": 0,
                "true_name": "Alice",
                "kind": "masked",
                "embedding": bad_emb,
            }
        ],
        faces,
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert good.accuracy == 1.0
    assert bad.accuracy == 0.0
    assert bad.accuracy < good.accuracy  # gating occlusion Δ goes red


def test_render_twin_uses_cached_landmarks_only():
    cache = _cache_one()
    specs = generate_twin_specs(cache, kinds=("masked",), seed=99)
    img = np.full((100, 100, 3), 180, dtype=np.uint8)
    out = render_twin(img, specs[0])
    assert out.shape == img.shape
    assert pixel_buffer_hash(out) == pixel_buffer_hash(
        apply_occlusion(img, specs[0].landmarks_px, "masked", seed=specs[0].seed)
    )


def test_a_s_a_r_a_clean_are_distinct_quantities():
    """S4 exposes a_s / a_r / a_clean as separate score_occlusion_accuracy calls."""
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),
        _matched(4, 0, [0, 1, 0.05], "Bob"),
    ]
    # Synthetic occluded twin of Alice — embedding still good.
    a_s = score_occlusion_accuracy(
        [
            {
                "media_id": 1,
                "box_index": 0,
                "true_name": "Alice",
                "kind": "masked",
                "embedding": _unit([1, 0, 0]),
            }
        ],
        faces,
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    # Real-tagged occlusion face (Bob) — also correct.
    a_r = score_occlusion_accuracy(
        [
            {
                "media_id": 3,
                "box_index": 0,
                "true_name": "Bob",
                "kind": "sunglasses",
                "embedding": _unit([0, 1, 0]),
            }
        ],
        faces,
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    # Clean un-occluded baseline for Alice source.
    a_clean = score_occlusion_accuracy(
        [
            {
                "media_id": 1,
                "box_index": 0,
                "true_name": "Alice",
                "kind": "masked",
                "embedding": _unit([1, 0, 0]),
            }
        ],
        faces,
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert a_s.accuracy == 1.0
    assert a_r.accuracy == 1.0
    assert a_clean.accuracy == 1.0
    # Distinct result objects (S5 demotion rule consumes these separately).
    assert a_s is not a_r
