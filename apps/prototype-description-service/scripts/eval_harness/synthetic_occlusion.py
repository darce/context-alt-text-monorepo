"""Seeded synthetic occlusion + open-set occlusion recovery (FIR-5 S4 / §D).

Generators (``masked`` / ``sunglasses`` / ``occlusion_other``) place fixed
anatomy-anchor occluders via affine warp from the **frozen landmark cache**.
No live leg detector during generation (firewall). Both legs re-detect+embed
on the **identical** occluded pixels after generation.

Occlusion metric = open-set paired accuracy: accept only when
``accept_predicate.accepts(s_max, tau)`` and ``name* == true_name`` against a gallery = identity
un-occluded faces excluding twin source media_id + other identities'
un-occluded prototypes. Guards: outcome-independent structural gallery
eligibility first (distinct-image min-gallery + multi-identity; EXP-22),
then re-detect-miss counts as fail *inside* the eligible frame, single-
identity galleries **excluded from the denominator** (EVAL-18), ≥90
eligible-pair floor, walk-stability bound (else DIRECTIONAL).

Protocol disclosures (EVAL-17): synthetic occluders are solid seeded
rectangles mapped onto MASKED/sunglasses/occlusion_other slice tags; the
twin universe is cached clean detections only (hard clean-detection
failures are structurally absent).

Heuristics (docs/workbay/rules/engineering-heuristics.md +
docs/workbay/rules/graph-theory-heuristics.md +
docs/workbay/rules/ml-systems-heuristics.md — ids only):
- TRACK-09: occlusion as degradation measurement
- CAL-01 / GRPH-23: per-occlusion-stratum
- TEST-08 / DATA-09: seed + pinned cv2 → hash-identical occluder pixels
- MLDATA-02: ≥90 eligible-pair floor
- EMB-03: occluded = low quality (re-detect miss counts as fail)
- EVAL-16 / EVAL-17 / EVAL-18: censoring order, disclosure honesty, open-set
- TEST-06 / TEST-15: can-fail + guard-fires fixtures
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np

from scripts.eval_harness.accept_predicate import accepts
from .face_assignment import (
    MatchedFace,
    argmax_gallery,
    cosine_similarity,
    matched_named_by_identity,
    mean_prototype,
)
from .landmark_cache import LANDMARK_CACHE_LEG_ASYMMETRY_DISCLOSURE, LandmarkCache
from .manifest import SliceTag

OcclusionKind = Literal["masked", "sunglasses", "occlusion_other"]

OCCLUSION_KINDS: tuple[OcclusionKind, ...] = (
    "masked",
    "sunglasses",
    "occlusion_other",
)

# Map generator kind → SliceTag value for reporting.
KIND_TO_SLICE_TAG: dict[OcclusionKind, SliceTag] = {
    "masked": SliceTag.MASKED,
    "sunglasses": SliceTag.SUNGLASSES,
    "occlusion_other": SliceTag.OCCLUSION_OTHER,
}

# ≥90 eligible-pair floor per tag (MLDATA-02). Below → DIRECTIONAL; not guaranteed.
ELIGIBLE_PAIR_FLOOR = 90

# Aggregate |Δ| bound across an independent re-run of ≥ floor pairs.
# If not asserted or not met → DIRECTIONAL (flag alone is insufficient).
WALK_STABILITY_DELTA_BOUND = 0.05

# Artifact-facing protocol disclosures (EVAL-17 / EVAL-18 / EXP-08 / EXP-22).
# Measured changes to generators remain FIR-6-owned; honesty about current
# posture is FIR-5.
SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES: tuple[str, ...] = (
    "synthetic occluders are solid seeded rectangles mapped onto "
    "MASKED/sunglasses/occlusion_other slice tags — not photo-realistic masks",
    "twin universe = cached clean detections only; hard clean-detection "
    "failures are structurally absent (EVAL-17)",
    "occlusion recovery uses open-set threshold (s_max >= tau; see accept_predicate.accepts), not closed-set "
    "argmax; each twin is scored at its source identity's held-out fold tau_k "
    "(entity-disjoint — CAL-07/EVAL-07); pooled tau_op is a last-resort "
    "fallback gated behind an explicit per-identity opt-in "
    "(allow_tau_fallback_for) for identities with no held-out probe decision "
    "— not guaranteed entity-disjoint if the identity still entered fit "
    "galleries; single-identity galleries are excluded from the denominator "
    "(EVAL-18)",
    "filter_headline_probes is fail-closed: occluded_probe_keys is required",
    # FIR5RR-09: only mated (named roster) twins exist in FIR-5.
    "occluded non-mated (stranger) behaviour is unmeasured — every occlusion "
    "twin is a mated named-roster probe; occluded-stranger false-accept "
    "measurement (stranger twins) is deferred to FIR-6",
    # EXP-08 / LOCV11-06: landmark cache is YuNet (candidate family); both legs
    # share the same twin-generation population, so faces only the incumbent
    # detects never enter the occlusion comparison set. Single-sourced from
    # landmark_cache (FIR5RR-11) — do not duplicate the string here.
    LANDMARK_CACHE_LEG_ASYMMETRY_DISCLOSURE,
    # EXP-22: structural gallery eligibility is outcome-independent.
    "occlusion denominator membership is outcome-independent: distinct-image "
    "min-gallery and multi-identity gallery gates run before re-detect miss "
    "or recovery scoring (EXP-22)",
)

# Named sampling frame for published occlusion recovery rates (AUDIT-01/02).
SAMPLING_FRAME_OCCLUSION_RECOVERY = (
    "eligible_twin_pairs: distinct_image_min_gallery AND gallery_n_identities>=2; "
    "re_detect_miss counts as incorrect only inside that frame"
)

# Determinism layer 2: pinned OpenCV warp (within one host profile).
_WARP_FLAGS = cv2.INTER_LINEAR
_WARP_BORDER_MODE = cv2.BORDER_CONSTANT
_WARP_BORDER_VALUE = (0, 0, 0)

# Occluder template size (pixels) before affine placement.
_TEMPLATE_SIZE = 64

# Solid BGR fill for occluder body (seed perturbs slightly but deterministically).
_BASE_FILL_BGR = (32, 32, 32)


def pin_cv2_threads() -> None:
    """Pin OpenCV to single-thread for hash-stable warps (determinism layer 2)."""
    cv2.setNumThreads(1)


def pixel_buffer_hash(image_u8: np.ndarray) -> str:
    """SHA-256 of the contiguous uint8 pixel buffer (within-host comparison)."""
    arr = np.ascontiguousarray(image_u8, dtype=np.uint8)
    return hashlib.sha256(arr.tobytes()).hexdigest()


def _seeded_fill_bgr(seed: int) -> tuple[int, int, int]:
    """Deterministic fill colour from seed (DATA-09 — no wall-clock RNG)."""
    # Simple LCG step from seed; stays in uint8.
    x = (int(seed) * 1103515245 + 12345) & 0x7FFFFFFF
    b = 20 + (x % 40)
    x = (x * 1103515245 + 12345) & 0x7FFFFFFF
    g = 20 + (x % 40)
    x = (x * 1103515245 + 12345) & 0x7FFFFFFF
    r = 20 + (x % 40)
    return (int(b), int(g), int(r))


def _landmarks5(landmarks: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
    arr = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
    if not np.isfinite(arr).all():
        raise ValueError("landmarks contain non-finite values")
    return arr


def _template_occluder(
    kind: OcclusionKind,
    *,
    seed: int,
    size: int = _TEMPLATE_SIZE,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (template BGRA/BGR, 3 source control points in template space).

    Anatomy anchors (fixed):
    - masked → lower-face / mouth bar (bottom half of template)
    - sunglasses → eye-pair bar (upper-mid horizontal band)
    - occlusion_other → cheek/forehead patch (seed chooses side/band)
    """
    fill = _seeded_fill_bgr(seed)
    tpl = np.zeros((size, size, 3), dtype=np.uint8)
    # Source control points in template coordinates (3 pts for getAffineTransform).
    if kind == "masked":
        # Lower-face bar: mouth region.
        y0, y1 = int(size * 0.45), size
        tpl[y0:y1, :, :] = fill
        src = np.array(
            [
                [size * 0.15, size * 0.70],  # right mouth-ish
                [size * 0.85, size * 0.70],  # left mouth-ish
                [size * 0.50, size * 0.55],  # upper mask edge near nose
            ],
            dtype=np.float32,
        )
    elif kind == "sunglasses":
        # Eye-pair horizontal band.
        y0, y1 = int(size * 0.25), int(size * 0.55)
        tpl[y0:y1, :, :] = fill
        src = np.array(
            [
                [size * 0.20, size * 0.40],  # right eye
                [size * 0.80, size * 0.40],  # left eye
                [size * 0.50, size * 0.25],  # brow mid
            ],
            dtype=np.float32,
        )
    else:
        # occlusion_other: cheek or forehead patch (seed bit).
        use_forehead = (int(seed) % 2) == 0
        if use_forehead:
            y0, y1 = int(size * 0.05), int(size * 0.30)
            x0, x1 = int(size * 0.25), int(size * 0.75)
            tpl[y0:y1, x0:x1, :] = fill
            src = np.array(
                [
                    [size * 0.30, size * 0.18],
                    [size * 0.70, size * 0.18],
                    [size * 0.50, size * 0.08],
                ],
                dtype=np.float32,
            )
        else:
            # Right cheek patch (image-left for frontal YuNet right-eye side).
            y0, y1 = int(size * 0.40), int(size * 0.75)
            x0, x1 = int(size * 0.05), int(size * 0.40)
            tpl[y0:y1, x0:x1, :] = fill
            src = np.array(
                [
                    [size * 0.15, size * 0.50],
                    [size * 0.35, size * 0.50],
                    [size * 0.25, size * 0.65],
                ],
                dtype=np.float32,
            )
    return tpl, src


def _destination_control_points(
    landmarks: np.ndarray,
    kind: OcclusionKind,
    *,
    seed: int,
) -> np.ndarray:
    """Map anatomy anchors from YuNet 5-point landmarks → 3 destination pts.

    YuNet order: 0 right_eye, 1 left_eye, 2 nose, 3 right_mouth, 4 left_mouth.
    """
    re, le, nose, rm, lm = landmarks
    eye_mid = 0.5 * (re + le)
    mouth_mid = 0.5 * (rm + lm)
    if kind == "masked":
        # Lower face: mouth corners + point below nose toward mouth.
        below_nose = nose + 0.35 * (mouth_mid - nose)
        dst = np.stack([rm, lm, below_nose], axis=0)
    elif kind == "sunglasses":
        # Eye pair + brow above eye mid.
        brow = eye_mid - 0.35 * (nose - eye_mid)
        dst = np.stack([re, le, brow], axis=0)
    else:
        use_forehead = (int(seed) % 2) == 0
        if use_forehead:
            brow_l = le - 0.45 * (nose - le)
            brow_r = re - 0.45 * (nose - re)
            brow_mid = eye_mid - 0.55 * (nose - eye_mid)
            dst = np.stack([brow_r, brow_l, brow_mid], axis=0)
        else:
            # Cheek near right eye / right mouth (anatomical right).
            cheek = re + 0.55 * (rm - re) + 0.25 * (re - le)
            dst = np.stack(
                [
                    re + 0.15 * (rm - re),
                    re + 0.45 * (rm - re) + 0.20 * (re - le),
                    cheek,
                ],
                axis=0,
            )
    return dst.astype(np.float32)


def apply_occlusion(
    image_bgr: np.ndarray,
    landmarks_px: np.ndarray | Sequence[Sequence[float]],
    kind: OcclusionKind,
    *,
    seed: int = 0,
) -> np.ndarray:
    """Paint a seeded anatomy-anchor occluder via ``cv2.warpAffine`` (layer 2).

    Same ``(kind, seed, landmarks, image)`` → hash-identical uint8 pixels under
    ``cv2.setNumThreads(1)`` + ``INTER_LINEAR`` + fixed ``borderMode`` on one host.
    """
    if kind not in OCCLUSION_KINDS:
        raise ValueError(f"unknown occlusion kind {kind!r}; expected one of {OCCLUSION_KINDS}")
    pin_cv2_threads()
    img = np.ascontiguousarray(image_bgr, dtype=np.uint8)
    if img.ndim != 3 or img.shape[2] != 3:
        raise ValueError(f"expected HxWx3 BGR uint8, got shape {img.shape}")
    lm = _landmarks5(landmarks_px)
    tpl, src_pts = _template_occluder(kind, seed=seed)
    dst_pts = _destination_control_points(lm, kind, seed=seed)
    m = cv2.getAffineTransform(src_pts, dst_pts)
    warped = cv2.warpAffine(
        tpl,
        m,
        (img.shape[1], img.shape[0]),
        flags=_WARP_FLAGS,
        borderMode=_WARP_BORDER_MODE,
        borderValue=_WARP_BORDER_VALUE,
    )
    # Alpha-less composite: non-zero template pixels overwrite (occluder body).
    mask = np.any(warped != 0, axis=2)
    out = img.copy()
    out[mask] = warped[mask]
    return out


def occluder_pixel_mask(
    image_shape: tuple[int, ...],
    landmarks_px: np.ndarray | Sequence[Sequence[float]],
    kind: OcclusionKind,
    *,
    seed: int = 0,
) -> np.ndarray:
    """Boolean mask of occluder coverage (for anatomy-anchor unit tests)."""
    h, w = int(image_shape[0]), int(image_shape[1])
    blank = np.zeros((h, w, 3), dtype=np.uint8)
    painted = apply_occlusion(blank, landmarks_px, kind, seed=seed)
    return np.any(painted != 0, axis=2)


@dataclass(frozen=True)
class OcclusionTwinSpec:
    """Offline twin descriptor (no embedding — generation is leg-agnostic)."""

    media_id: int
    box_index: int
    true_name: str
    kind: OcclusionKind
    seed: int
    landmarks_px: tuple[tuple[float, float], ...]

    @property
    def source_key(self) -> tuple[int, int]:
        return (self.media_id, self.box_index)


def generate_twin_specs(
    cache: LandmarkCache,
    *,
    kinds: Sequence[OcclusionKind] = OCCLUSION_KINDS,
    seed: int = 0,
) -> tuple[OcclusionTwinSpec, ...]:
    """Offline twin universe: every cache-detected named roster face × kinds.

    Decoupled from score-time probe sets (firewall). Coverage is detector-
    recall-dependent via the cache, not structurally every roster face.
    """
    specs: list[OcclusionTwinSpec] = []
    for entry in cache.named_roster_entries():
        for kind in kinds:
            # Per-face/kind sub-seed derived from global seed (DATA-09).
            face_seed = (
                int(seed)
                + 1_000_003 * int(entry.media_id)
                + 9_001 * int(entry.box_index)
                + 17 * (OCCLUSION_KINDS.index(kind) + 1)
            )
            specs.append(
                OcclusionTwinSpec(
                    media_id=entry.media_id,
                    box_index=entry.box_index,
                    true_name=entry.name,
                    kind=kind,
                    seed=face_seed,
                    landmarks_px=entry.landmarks_px,
                )
            )
    return tuple(specs)


def render_twin(
    image_bgr: np.ndarray,
    spec: OcclusionTwinSpec,
) -> np.ndarray:
    """Apply the twin's occluder to the source image pixels."""
    return apply_occlusion(
        image_bgr,
        spec.landmarks_px,
        spec.kind,
        seed=spec.seed,
    )


# ---------------------------------------------------------------------------
# §D occlusion scoring (open-set threshold at the identity's held-out fold τ_k)
# ---------------------------------------------------------------------------


def has_distinct_image_gallery_support(
    true_name: str,
    source_media_id: int,
    by_identity: Mapping[str, Sequence[MatchedFace]],
) -> bool:
    """Min-gallery guard: ≥1 un-occluded face of true_name on media_id ≠ source.

    Two faces on the **same** media_id both vanish when that image is excluded —
    counting ≥2 faces is insufficient.
    """
    faces = by_identity.get(true_name, ())
    return any(f.media_id != source_media_id for f in faces)


def build_occlusion_gallery(
    true_name: str,
    source_media_id: int,
    by_identity: Mapping[str, Sequence[MatchedFace]],
) -> dict[str, np.ndarray]:
    """Source-image-excluded LOO gallery for occlusion recovery (open-set τ).

    - prototype_X = mean of X's un-occluded faces with media_id ≠ source
    - prototype_Y = mean of all of Y's un-occluded faces (Y ≠ X)
    """
    gallery: dict[str, np.ndarray] = {}
    for name, faces in by_identity.items():
        if name == true_name:
            others = [f for f in faces if f.media_id != source_media_id]
            if not others:
                continue
            gallery[name] = mean_prototype([f.embedding_array() for f in others])
        else:
            if not faces:
                continue
            gallery[name] = mean_prototype([f.embedding_array() for f in faces])
    return gallery


def gallery_identity_count(gallery: Mapping[str, np.ndarray]) -> int:
    return len(gallery)


@dataclass(frozen=True)
class OcclusionPairResult:
    """One eligible twin pair score (or ineligible skip)."""

    media_id: int
    box_index: int
    true_name: str
    kind: OcclusionKind
    eligible: bool
    correct: bool | None  # None when ineligible
    re_detect_miss: bool
    predicted_name: str | None
    gallery_n_identities: int
    ineligible_reason: str | None = None


@dataclass(frozen=True)
class OcclusionAccuracy:
    """Open-set accuracy rollup for one occlusion stratum (a_s / a_r / a_clean)."""

    accuracy: float | None  # None when n_eligible == 0
    n_eligible: int
    n_correct: int
    n_re_detect_miss: int
    n_ineligible: int
    directional: bool
    directional_reasons: tuple[str, ...]
    pair_results: tuple[OcclusionPairResult, ...] = ()
    walk_stability_asserted: bool = False
    walk_stability_delta: float | None = None
    tau: float | None = None
    sampling_frame: str = SAMPLING_FRAME_OCCLUSION_RECOVERY
    # Denominator for published accuracy (AUDIT-02): eligible pairs only.
    rate_numerator: int = 0  # n_correct
    rate_denominator: int = 0  # n_eligible

    @property
    def meets_pair_floor(self) -> bool:
        return self.n_eligible >= ELIGIBLE_PAIR_FLOOR


def score_occlusion_pair(
    *,
    twin_embedding: np.ndarray | Sequence[float] | None,
    true_name: str,
    source_media_id: int,
    box_index: int,
    kind: OcclusionKind,
    by_identity: Mapping[str, Sequence[MatchedFace]],
    tau: float,
) -> OcclusionPairResult:
    """Score one twin: open-set recovery (s_max ≥ tau ∧ name* == true).

    ``tau`` is REQUIRED (FIR5RR-02): ``tau=None`` was a silent closed-set
    argmax (the run-578 hard-fail mode) and is rejected loudly. Pass the
    twin's source identity's held-out fold ``tau_k`` (entity-disjoint).

    Eligibility order is **outcome-independent** (EXP-22 / EVAL-18):

    1. Distinct-image min-gallery (structural).
    2. Multi-identity gallery (structural; single-identity leaves the
       denominator — rank metrics cannot express 'no one here').
    3. Only then: re-detect miss → incorrect *inside* the eligible frame, or
       score the embedding.

    Gallery gates therefore run whether the twin re-detects or not, so a
    deficient gallery cannot contribute failures on miss and exclusions on
    success for the same unit.
    """
    if tau is None:  # defensive: keyword misuse must not regress to closed-set
        raise ValueError(
            "tau is required (FIR5RR-02): tau=None silently degraded to "
            "closed-set argmax; pass the identity's held-out fold tau_k"
        )
    # 1–2) Structural gallery eligibility (independent of twin outcome).
    if not has_distinct_image_gallery_support(true_name, source_media_id, by_identity):
        return OcclusionPairResult(
            media_id=source_media_id,
            box_index=box_index,
            true_name=true_name,
            kind=kind,
            eligible=False,
            correct=None,
            re_detect_miss=twin_embedding is None,
            predicted_name=None,
            gallery_n_identities=0,
            ineligible_reason="distinct_image_min_gallery",
        )

    gallery = build_occlusion_gallery(true_name, source_media_id, by_identity)
    n_ids = gallery_identity_count(gallery)

    if n_ids < 2:
        return OcclusionPairResult(
            media_id=source_media_id,
            box_index=box_index,
            true_name=true_name,
            kind=kind,
            eligible=False,
            correct=None,
            re_detect_miss=twin_embedding is None,
            predicted_name=None,
            gallery_n_identities=n_ids,
            ineligible_reason="single_identity_gallery",
        )

    # 3) Outcome inside the eligible frame.
    if twin_embedding is None:
        return OcclusionPairResult(
            media_id=source_media_id,
            box_index=box_index,
            true_name=true_name,
            kind=kind,
            eligible=True,
            correct=False,
            re_detect_miss=True,
            predicted_name=None,
            gallery_n_identities=n_ids,
        )

    emb = np.asarray(twin_embedding, dtype=np.float64)
    s_max, name_star = argmax_gallery(emb, gallery)
    accept = name_star is not None and accepts(s_max, float(tau))
    correct = bool(accept and name_star == true_name)
    return OcclusionPairResult(
        media_id=source_media_id,
        box_index=box_index,
        true_name=true_name,
        kind=kind,
        eligible=True,
        correct=correct,
        re_detect_miss=False,
        predicted_name=name_star if accept else None,
        gallery_n_identities=n_ids,
    )


def _rollup_pairs(
    pairs: Sequence[OcclusionPairResult],
    *,
    walk_stability_asserted: bool = False,
    walk_stability_delta: float | None = None,
    walk_stability_bound: float = WALK_STABILITY_DELTA_BOUND,
    tau: float | None = None,
) -> OcclusionAccuracy:
    eligible = [p for p in pairs if p.eligible]
    ineligible = [p for p in pairs if not p.eligible]
    n_eligible = len(eligible)
    n_correct = sum(1 for p in eligible if p.correct)
    # FIR5RR-14: re-detect misses count ONLY inside the eligible frame — an
    # ineligible row's miss must never reach n_re_detect_miss (its outcome
    # fields are informational; it left the denominator structurally).
    n_miss = sum(1 for p in eligible if p.re_detect_miss)
    accuracy = None if n_eligible == 0 else n_correct / n_eligible

    reasons: list[str] = []
    if n_eligible < ELIGIBLE_PAIR_FLOOR:
        reasons.append(
            f"eligible_pairs={n_eligible}<floor={ELIGIBLE_PAIR_FLOOR}"
        )
    # Safety net: single-identity pairs should already be ineligible (EVAL-18).
    if any(p.eligible and p.gallery_n_identities < 2 for p in pairs):
        reasons.append("gallery_lt_2_distinct_identities")
    if not walk_stability_asserted or walk_stability_delta is None:
        # A bare asserted=True with NO measured |Δ| must NOT keep a gating number
        # (flag alone is insufficient — the aggregate-Δ bound must be measured).
        reasons.append("walk_stability_not_asserted")
    elif walk_stability_delta > walk_stability_bound:
        reasons.append(
            f"walk_stability_delta={walk_stability_delta}>bound={walk_stability_bound}"
        )

    return OcclusionAccuracy(
        accuracy=accuracy,
        n_eligible=n_eligible,
        n_correct=n_correct,
        n_re_detect_miss=n_miss,
        n_ineligible=len(ineligible),
        directional=bool(reasons),
        directional_reasons=tuple(reasons),
        pair_results=tuple(pairs),
        walk_stability_asserted=walk_stability_asserted,
        walk_stability_delta=walk_stability_delta,
        tau=tau,
        sampling_frame=SAMPLING_FRAME_OCCLUSION_RECOVERY,
        rate_numerator=n_correct,
        rate_denominator=n_eligible,
    )


def score_occlusion_accuracy(
    pair_inputs: Sequence[Mapping[str, Any]],
    unoccluded_matched: Sequence[MatchedFace],
    *,
    tau: float,
    tau_by_identity: Mapping[str, float] | None = None,
    allow_tau_fallback_for: set[str] | frozenset[str] | None = None,
    walk_stability_asserted: bool = False,
    walk_stability_delta: float | None = None,
    walk_stability_bound: float = WALK_STABILITY_DELTA_BOUND,
) -> OcclusionAccuracy:
    """Compute a_s / a_r / a_clean-style open-set accuracy over twin/real/clean pairs.

    Each input mapping keys:
      - media_id, box_index, true_name, kind
      - embedding: sequence[float] | None  (None = re-detect miss)

    Threshold selection (FIR5RR-01 / CAL-07 / EVAL-07): each twin is scored at
    ``tau_by_identity[true_name]`` — its source identity's held-out fold
    ``tau_k`` (subject-disjoint folds pin every face of an identity to one
    fold, so this is entity-disjoint for the twin's own identity). ``tau`` is
    REQUIRED (FIR5RR-02: ``None`` was a silent closed-set argmax).

    ``tau_by_identity`` coverage is REQUIRED (FIR5CR-01): when
    ``unoccluded_matched`` contains named identities, every one of them must
    have a ``tau_k`` in the map. Scoring a twin at pooled ``tau`` is a
    documented last-resort path gated behind ``allow_tau_fallback_for`` — an
    explicit per-identity opt-in reserved for identities provably absent from
    the pooled fold decisions (they contributed no held-out probe). The
    fallback is NOT guaranteed entity-disjoint if the identity still entered
    fit galleries; a bare tau-only call raises rather than silently scoring
    twins at the pooled operating point.
    """
    if tau is None:
        raise ValueError(
            "tau is required (FIR5RR-02): tau=None silently degraded to "
            "closed-set argmax; pass tau_op as the fallback threshold"
        )
    by_identity = matched_named_by_identity(unoccluded_matched)
    taus = dict(tau_by_identity) if tau_by_identity is not None else {}
    allowed_fallback = set(allow_tau_fallback_for or ())
    uncovered = sorted(set(by_identity) - set(taus) - allowed_fallback)
    if uncovered:
        raise ValueError(
            "tau_by_identity is required (FIR5CR-01): named identities "
            f"{uncovered} have no held-out fold tau_k; scoring them at the "
            "pooled tau silently drops entity-disjointness. Pass their tau_k, "
            "or opt in via allow_tau_fallback_for ONLY for identities provably "
            "absent from the pooled fold decisions"
        )
    results: list[OcclusionPairResult] = []
    for item in pair_inputs:
        true_name = str(item["true_name"])
        results.append(
            score_occlusion_pair(
                twin_embedding=item.get("embedding"),
                true_name=true_name,
                source_media_id=int(item["media_id"]),
                box_index=int(item["box_index"]),
                kind=item["kind"],  # type: ignore[arg-type]
                by_identity=by_identity,
                tau=float(taus.get(true_name, tau)),
            )
        )
    return _rollup_pairs(
        results,
        walk_stability_asserted=walk_stability_asserted,
        walk_stability_delta=walk_stability_delta,
        walk_stability_bound=walk_stability_bound,
        tau=tau,
    )


def assert_walk_stability(
    accuracy_a: float | None,
    accuracy_b: float | None,
    *,
    n_eligible_a: int,
    n_eligible_b: int,
    bound: float = WALK_STABILITY_DELTA_BOUND,
    floor: int = ELIGIBLE_PAIR_FLOOR,
) -> tuple[bool, float | None]:
    """Independent re-run aggregate-Δ check. Returns (met, |Δ|).

    Only meaningful when BOTH independent runs have ≥ floor eligible pairs and
    non-None accuracy; otherwise returns (False, delta_or_None). A single run
    clearing the floor is insufficient — both re-runs must be adequately powered.
    """
    if (
        accuracy_a is None
        or accuracy_b is None
        or n_eligible_a < floor
        or n_eligible_b < floor
    ):
        delta = (
            None
            if accuracy_a is None or accuracy_b is None
            else abs(float(accuracy_a) - float(accuracy_b))
        )
        return False, delta
    delta = abs(float(accuracy_a) - float(accuracy_b))
    return delta <= bound, delta


def filter_headline_probes(
    matched: Sequence[MatchedFace],
    *,
    occluded_probe_keys: set[tuple[int, int, str]] | None = None,
) -> tuple[MatchedFace, ...]:
    """Headline identification set: un-occluded matched faces only (fail-closed).

    Twins never enter the headline set. ``occluded_probe_keys`` marks synthetic
    twin identities as ``(media_id, box_index, "occluded")``; any face flagged
    as occluded is stripped.

    Fail-closed (EVAL-16): ``occluded_probe_keys`` is **required**. Pass an
    explicit empty set only when the caller has determined there are no
    occluded probes. ``None`` raises rather than silently pass-through.
    """
    if occluded_probe_keys is None:
        raise ValueError(
            "occluded_probe_keys is required (fail-closed); pass an explicit "
            "empty set when no occluded probes exist"
        )
    out: list[MatchedFace] = []
    for face in matched:
        key = (face.media_id, face.box_index, "occluded")
        if key in occluded_probe_keys:
            continue
        out.append(face)
    return tuple(out)


def source_media_excluded_from_gallery(
    gallery_faces: Sequence[MatchedFace],
    source_media_id: int,
) -> bool:
    """Firewall helper: True iff no gallery face shares the twin's source media_id."""
    return all(f.media_id != source_media_id for f in gallery_faces)


def anatomy_region_stats(
    mask: np.ndarray,
    landmarks_px: np.ndarray | Sequence[Sequence[float]],
) -> dict[str, float]:
    """Fraction of occluder mass in lower-face / eye-band / upper for pin tests."""
    lm = _landmarks5(landmarks_px)
    re, le, nose, rm, lm_pt = lm
    eye_y = float(0.5 * (re[1] + le[1]))
    mouth_y = float(0.5 * (rm[1] + lm_pt[1]))
    nose_y = float(nose[1])
    # Bands relative to face vertical span.
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return {"lower_face_frac": 0.0, "eye_band_frac": 0.0, "upper_frac": 0.0}
    total = float(len(ys))
    lower = float(np.sum(ys >= (nose_y + mouth_y) / 2.0))
    eye_band = float(np.sum((ys >= eye_y - 0.15 * abs(mouth_y - eye_y)) & (ys <= nose_y)))
    upper = float(np.sum(ys < eye_y))
    return {
        "lower_face_frac": lower / total,
        "eye_band_frac": eye_band / total,
        "upper_frac": upper / total,
    }


__all__ = [
    "OCCLUSION_KINDS",
    "KIND_TO_SLICE_TAG",
    "ELIGIBLE_PAIR_FLOOR",
    "WALK_STABILITY_DELTA_BOUND",
    "SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES",
    "SAMPLING_FRAME_OCCLUSION_RECOVERY",
    "OcclusionKind",
    "OcclusionTwinSpec",
    "OcclusionPairResult",
    "OcclusionAccuracy",
    "pin_cv2_threads",
    "pixel_buffer_hash",
    "apply_occlusion",
    "occluder_pixel_mask",
    "generate_twin_specs",
    "render_twin",
    "has_distinct_image_gallery_support",
    "build_occlusion_gallery",
    "gallery_identity_count",
    "score_occlusion_pair",
    "score_occlusion_accuracy",
    "assert_walk_stability",
    "filter_headline_probes",
    "source_media_excluded_from_gallery",
    "anatomy_region_stats",
    "cosine_similarity",
]
