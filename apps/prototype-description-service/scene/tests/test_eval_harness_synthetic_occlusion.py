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
    SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES,
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
    assert all((f.media_id, f.box_index, "occluded") not in occluded_keys for f in headline)
    # Explicit empty set: caller asserts no occluded probes (fail-closed contract).
    assert len(filter_headline_probes(unoccluded, occluded_probe_keys=set())) == 3


def test_filter_headline_probes_fail_closed_on_none_keys():
    """EVAL-16: None occluded_probe_keys must not silently pass-through."""
    unoccluded = [_matched(1, 0, [1, 0, 0], "Alice")]
    with pytest.raises(ValueError, match="fail-closed"):
        filter_headline_probes(unoccluded, occluded_probe_keys=None)


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
        tau=0.0,
    )
    assert result.eligible is False
    assert result.ineligible_reason == "distinct_image_min_gallery"
    assert result.correct is None


def test_lt_2_distinct_identity_gallery_excluded_from_denominator():
    """EVAL-18: single-identity galleries leave the recovery denominator."""
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
        tau=0.0,
    )
    assert pair.eligible is False
    assert pair.gallery_n_identities == 1
    assert pair.ineligible_reason == "single_identity_gallery"
    assert pair.correct is None

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
        tau=0.0,
        tau_by_identity={"Alice": 0.0},
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert rollup.n_eligible == 0
    assert rollup.n_ineligible == 1
    assert rollup.accuracy is None


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
        tau=0.5,
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
        tau=0.5,
        tau_by_identity={"Alice": 0.5, "Bob": 0.5},
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert rollup.n_eligible == 1
    assert rollup.n_correct == 0
    assert rollup.n_re_detect_miss == 1
    assert rollup.accuracy == 0.0


def test_re_detect_miss_does_not_bypass_structural_gallery_gates():
    """EXP-22: eligibility is outcome-independent — miss does not enter the frame when gallery is deficient."""
    faces = [
        _matched(5, 0, [1, 0, 0], "Alice"),
        _matched(5, 1, [1, 0.05, 0], "Alice"),
        _matched(9, 0, [0, 1, 0], "Bob"),
        _matched(8, 0, [0, 1, 0.05], "Bob"),
    ]
    by_id = {"Alice": [faces[0], faces[1]], "Bob": [faces[2], faces[3]]}
    assert not has_distinct_image_gallery_support("Alice", 5, by_id)
    pair_miss = score_occlusion_pair(
        twin_embedding=None,
        true_name="Alice",
        source_media_id=5,
        box_index=0,
        kind="masked",
        by_identity=by_id,
        tau=0.5,
    )
    pair_hit = score_occlusion_pair(
        twin_embedding=_unit([1, 0, 0]),
        true_name="Alice",
        source_media_id=5,
        box_index=0,
        kind="masked",
        by_identity=by_id,
        tau=0.5,
    )
    # Same structural frame for miss and hit — no outcome-dependent membership.
    assert pair_miss.eligible is False
    assert pair_hit.eligible is False
    assert pair_miss.ineligible_reason == "distinct_image_min_gallery"
    assert pair_hit.ineligible_reason == "distinct_image_min_gallery"
    assert pair_miss.re_detect_miss is True
    assert pair_hit.re_detect_miss is False


def test_single_identity_gallery_excludes_miss_and_hit_alike():
    """EXP-22: deficient single-identity gallery never contributes a recovery failure."""
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
    ]
    by_id = {"Alice": faces}
    for emb in (None, _unit([1, 0, 0])):
        pair = score_occlusion_pair(
            twin_embedding=emb,
            true_name="Alice",
            source_media_id=1,
            box_index=0,
            kind="masked",
            by_identity=by_id,
            tau=0.0,
        )
        assert pair.eligible is False
        assert pair.ineligible_reason == "single_identity_gallery"
        assert pair.correct is None


def test_occlusion_open_set_threshold_rejects_low_similarity():
    """EVAL-18: open-set tau — low s_max is reject (incorrect), not closed-set name* win."""
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),
        _matched(4, 0, [0, 1, 0.05], "Bob"),
    ]
    pair = score_occlusion_pair(
        twin_embedding=_unit([0, 0, 1]),
        true_name="Alice",
        source_media_id=1,
        box_index=0,
        kind="masked",
        by_identity={"Alice": faces[:2], "Bob": faces[2:]},
        tau=0.9,
    )
    assert pair.eligible is True
    assert pair.correct is False
    assert pair.predicted_name is None  # rejected below tau


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
        tau=0.0,
        tau_by_identity={"Alice": 0.0, "Bob": 0.0},
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
        tau=0.0,
        tau_by_identity={"Alice": 0.0, "Bob": 0.0},
        walk_stability_asserted=False,
    )
    assert rollup.directional is True
    assert "walk_stability_not_asserted" in rollup.directional_reasons


def test_walk_stability_bound_helper():
    met, delta = assert_walk_stability(
        0.90, 0.91, n_eligible_a=ELIGIBLE_PAIR_FLOOR, n_eligible_b=ELIGIBLE_PAIR_FLOOR
    )
    assert met is True
    assert delta == pytest.approx(0.01)
    met2, delta2 = assert_walk_stability(
        0.90,
        0.90 + WALK_STABILITY_DELTA_BOUND + 0.01,
        n_eligible_a=ELIGIBLE_PAIR_FLOOR,
        n_eligible_b=ELIGIBLE_PAIR_FLOOR,
    )
    assert met2 is False
    assert delta2 is not None and delta2 > WALK_STABILITY_DELTA_BOUND
    # BOTH independent re-runs must clear the floor — one powered run is insufficient.
    met3, _ = assert_walk_stability(
        0.90, 0.90, n_eligible_a=ELIGIBLE_PAIR_FLOOR, n_eligible_b=ELIGIBLE_PAIR_FLOOR - 1
    )
    assert met3 is False  # under-powered re-run B → not met (would be True on a single-count bug)


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
        tau=0.0,
        tau_by_identity={"Alice": 0.0, "Bob": 0.0},
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
        tau=0.0,
        tau_by_identity={"Alice": 0.0, "Bob": 0.0},
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert good.accuracy == 1.0
    assert bad.accuracy == 0.0
    # With n_eligible=1 < floor BOTH are DIRECTIONAL — this proves the raw a_s
    # ACCURACY drops on a forced mis-assign. That the GATING (non-directional)
    # number can go red is proven separately below with >= floor eligible pairs.
    assert bad.accuracy < good.accuracy
    assert good.directional is True and bad.directional is True  # under-floor here


def _orthogonal_eligible_corpus(n: int) -> list:
    """n identities, each with 2 matched faces on DISTINCT media (distinct-image
    eligible) + mutually-orthogonal one-hot embeddings (argmax is unambiguous)."""
    faces = []
    mid = 1
    for i in range(n):
        e = [0.0] * n
        e[i] = 1.0
        faces.append(_matched(mid, 0, list(e), f"P{i}"))
        mid += 1
        faces.append(_matched(mid, 0, list(e), f"P{i}"))
        mid += 1
    return faces


def test_occlusion_gate_goes_red_when_floors_met():
    """With >= floor eligible pairs + asserted walk-stability the result is a GATING
    (non-directional) number; a forced mis-assign lowers IT — not just raw accuracy."""
    n = ELIGIBLE_PAIR_FLOOR  # 90
    faces = _orthogonal_eligible_corpus(n)

    def onehot(i: int) -> list:
        e = [0.0] * n
        e[i] = 1.0
        return e

    # One twin per identity, source = its first media (2*i+1); all argmax-correct.
    correct = [
        {"media_id": 2 * i + 1, "box_index": 0, "true_name": f"P{i}", "kind": "masked", "embedding": onehot(i)}
        for i in range(n)
    ]
    taus = {f"P{i}": 0.0 for i in range(n)}
    clean = score_occlusion_accuracy(correct, faces, tau=0.0, tau_by_identity=taus, walk_stability_asserted=True, walk_stability_delta=0.0)
    assert clean.n_eligible == n
    assert clean.directional is False  # floors met + walk-stability → a GATING number
    assert clean.accuracy == pytest.approx(1.0)

    # Flip one twin to a wrong identity → argmax mis-assigns → the GATING number drops.
    bad = list(correct)
    bad[0] = {**bad[0], "embedding": onehot(1)}  # P0 twin now looks like P1
    red = score_occlusion_accuracy(bad, faces, tau=0.0, tau_by_identity=taus, walk_stability_asserted=True, walk_stability_delta=0.0)
    assert red.directional is False  # still a gating number (floors still met)
    assert red.accuracy == pytest.approx((n - 1) / n)
    assert red.accuracy < clean.accuracy  # the GATE went RED


def test_tau_none_raises_pair_and_rollup():
    """FIR5RR-02: tau=None (run-578 closed-set argmax mode) must raise, not degrade."""
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),
        _matched(4, 0, [0, 1, 0.05], "Bob"),
    ]
    with pytest.raises(ValueError, match="tau is required"):
        score_occlusion_pair(
            twin_embedding=_unit([1, 0, 0]),
            true_name="Alice",
            source_media_id=1,
            box_index=0,
            kind="masked",
            by_identity={"Alice": faces[:2], "Bob": faces[2:]},
            tau=None,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="tau is required"):
        score_occlusion_accuracy(
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
            tau=None,  # type: ignore[arg-type]
        )


def test_bare_tau_only_call_raises_without_tau_by_identity():
    """FIR5CR-01: pooled-tau scoring of named identities must be an explicit
    opt-in — a bare tau-only call (and a map missing a named identity without
    the opt-in) raises instead of silently scoring twins at the pooled tau."""
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),
        _matched(4, 0, [0, 1, 0.05], "Bob"),
    ]
    inputs = [
        {
            "media_id": 1,
            "box_index": 0,
            "true_name": "Alice",
            "kind": "masked",
            "embedding": _unit([1, 0, 0]),
        }
    ]
    with pytest.raises(ValueError, match="tau_by_identity is required"):
        score_occlusion_accuracy(inputs, faces, tau=0.5)
    # Partial map without opt-in for the missing identity also raises.
    with pytest.raises(ValueError, match="'Bob'"):
        score_occlusion_accuracy(
            inputs, faces, tau=0.5, tau_by_identity={"Alice": 0.5}
        )
    # No named identities in the corpus → nothing to cover → no raise.
    strangers = [_matched(1, 0, [1, 0, 0], None), _matched(2, 0, [0, 1, 0], None)]
    rollup = score_occlusion_accuracy([], strangers, tau=0.5)
    assert rollup.n_eligible == 0


def test_twin_scored_at_own_identity_heldout_tau_not_tau_op():
    """FIR5RR-01 discriminator: occlusion accuracy must change when a probe's
    own-fold tau_k differs from tau_op — red under a tau_op regression.

    Twin s_max = 0.5. Own-identity held-out tau_k = 0.7 (reject → incorrect);
    a tau_op-regressed scorer using the fallback tau=0.3 would accept (correct).
    """
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),
        _matched(4, 0, [0, 1, 0], "Bob"),
    ]
    # cos(twin, Alice proto) = 0.5 exactly; cos vs Bob proto = 0.
    twin = _unit([0.5, 0.0, float(np.sqrt(0.75))])
    inputs = [
        {
            "media_id": 1,
            "box_index": 0,
            "true_name": "Alice",
            "kind": "masked",
            "embedding": twin,
        }
    ]
    at_own_tau = score_occlusion_accuracy(
        inputs,
        faces,
        tau=0.3,  # tau_op-style fallback — must NOT be used for Alice
        tau_by_identity={"Alice": 0.7, "Bob": 0.3},
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert at_own_tau.n_eligible == 1
    assert at_own_tau.n_correct == 0  # rejected at Alice's own held-out tau 0.7
    # Regression probe: scoring at the pooled fallback instead would flip it.
    # FIR5CR-01: the pooled path now needs the explicit per-identity opt-in.
    at_tau_op = score_occlusion_accuracy(
        inputs,
        faces,
        tau=0.3,
        tau_by_identity=None,
        allow_tau_fallback_for={"Alice", "Bob"},
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert at_tau_op.n_correct == 1
    assert at_own_tau.n_correct != at_tau_op.n_correct
    # Explicitly opted-in identities NOT in the map use the pooled tau.
    fallback_only = score_occlusion_accuracy(
        inputs,
        faces,
        tau=0.7,
        tau_by_identity={"Bob": 0.2},  # Alice opted-in → fallback 0.7 applies
        allow_tau_fallback_for={"Alice"},
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert fallback_only.n_correct == 0


def test_ineligible_miss_never_counts_as_re_detect_miss():
    """FIR5RR-14: re_detect_miss contributes only inside the eligible frame."""
    # Alice's only support is on the source media → distinct-image gate fails.
    faces = [
        _matched(5, 0, [1, 0, 0], "Alice"),
        _matched(5, 1, [1, 0.05, 0], "Alice"),
        _matched(9, 0, [0, 1, 0], "Bob"),
        _matched(8, 0, [0, 1, 0.05], "Bob"),
    ]
    rollup = score_occlusion_accuracy(
        [
            {
                "media_id": 5,
                "box_index": 0,
                "true_name": "Alice",
                "kind": "masked",
                "embedding": None,  # a miss — but on an INELIGIBLE row
            }
        ],
        faces,
        tau=0.5,
        tau_by_identity={"Alice": 0.5, "Bob": 0.5},
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert rollup.n_ineligible == 1
    assert rollup.n_eligible == 0
    assert rollup.n_re_detect_miss == 0  # ineligible miss excluded from the count
    assert rollup.pair_results[0].re_detect_miss is True  # informational only


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
    # Synthetic occluded twin of Alice whose occluded embedding now looks like Bob
    # → argmax MUST mis-assign, so a_s degrades below the clean baseline.
    a_s = score_occlusion_accuracy(
        [
            {
                "media_id": 1,
                "box_index": 0,
                "true_name": "Alice",
                "kind": "masked",
                "embedding": _unit([0, 1, 0]),
            }
        ],
        faces,
        tau=0.0,
        tau_by_identity={"Alice": 0.0, "Bob": 0.0},
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
        tau=0.0,
        tau_by_identity={"Alice": 0.0, "Bob": 0.0},
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
        tau=0.0,
        tau_by_identity={"Alice": 0.0, "Bob": 0.0},
        walk_stability_asserted=True,
        walk_stability_delta=0.0,
    )
    assert a_s.accuracy == 0.0  # occluded Alice twin mis-assigned to Bob
    assert a_r.accuracy == 1.0  # real-tagged Bob correct
    assert a_clean.accuracy == 1.0  # un-occluded Alice baseline correct
    # NUMERICALLY distinct quantities from separate inputs (not object-identity):
    assert a_s.accuracy != a_clean.accuracy
    assert a_s.accuracy < a_clean.accuracy  # occlusion degrades vs clean baseline
    assert a_s is not a_r and a_s is not a_clean


def test_threshold_rule_disclosure_is_self_contained_published_text():
    """FIR-12-BR-77/78: the threshold-rule disclosure is PUBLISHED output
    (spliced into FACE_BAKEOFF_PROTOCOL_DISCLOSURES by report.py and consumed
    by _entry_is_publishable), not source prose. An external reader of an eval
    report cannot evaluate ``accept_predicate.accepts`` — they can evaluate
    ``s_max >= tau``. This pins the exact string so a future reword of
    published output is a deliberate golden update, not a refactor side
    effect (a prior refactor pass substituted the inequality for a bare
    module pointer here and the full suite stayed green)."""
    threshold_disclosures = [
        d for d in SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES if "open-set threshold" in d
    ]
    assert len(threshold_disclosures) == 1
    assert threshold_disclosures[0] == (
        "occlusion recovery uses open-set threshold (s_max >= tau), not closed-set "
        "argmax; each twin is scored at its source identity's held-out fold tau_k "
        "(entity-disjoint — CAL-07/EVAL-07); pooled tau_op is a last-resort "
        "fallback gated behind an explicit per-identity opt-in "
        "(allow_tau_fallback_for) for identities with no held-out probe decision "
        "— not guaranteed entity-disjoint if the identity still entered fit "
        "galleries; single-identity galleries are excluded from the denominator "
        "(EVAL-18)"
    )
    # The mathematical statement must survive in the published text, not just
    # a pointer to source — a reader cannot evaluate the module, only the math.
    assert "s_max >= tau" in threshold_disclosures[0]
