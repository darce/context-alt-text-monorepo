"""Face-recognition P/R as pure functions over recorded responses (no network).

Two levels (scope note definitions):
- detection: faces found vs faces labeled present, identity-agnostic, count-based.
- identification: named-identity assertions vs labeled identities. Wrong-name
  (asserted name not labeled present) is the top-severity error class — every
  instance is listed individually, never only aggregated.

Edge ledger: zero-face precision is None (never 1.0); stranger true rejection
counted, not penalized; duplicate identities deduped (by identity, not face);
policy-disabled images excluded; micro AND per-identity macro (Fair-SA: one
over-represented person must not mask another's failures).

FIR-5 S3 extensions (§F):
- face-level identification P/R over pooled per-fold decisions (0/0 → 0)
- face-level unknown-rejection over stranger probes
- single-linkage clustering purity / false-merge / false-split (GRPH-18)

FIR-5 S3d (Fair-SA demographic rollup):
- per-cohort face-level ID P/R keyed by roster identity (GoldenManifest.roster_cohorts)
- single-subject celebs01 image-level demographic_cohort fallback only
- multi-face image-only cohort EXCLUDED (anti-mis-attribution)
- always DIRECTIONAL (no demographic n-floor); report-only (CAL-06 — no per-cohort τ)

Heuristics: EVAL-02/04, GRPH-18, PERF-05/GRPH-17 (O(n²) all-pairs fine at Golden-150);
FAIR-01/02/03/06, CAL-06, PROV-04, EVAL-04 (S3d).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .manifest import AnnotationMode, ManifestError, ScoreInvariant, parse_annotation_mode

# Re-exports of the canonical ScoreInvariant members. New call sites should
# import ScoreInvariant directly.
IDENTIFICATION_UNBOXED_INVARIANT = (
    ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS
)
DETECTION_UNCOVERED_FACE_COUNT_INVARIANT = (
    ScoreInvariant.DETECTION_REFUSES_UNCOVERED_FACE_COUNT
)
DETECTION_EMPTY_OBSERVATIONS_INVARIANT = ScoreInvariant.DETECTION_REFUSES_EMPTY_OBSERVATIONS
IDENTIFICATION_EMPTY_OBSERVATIONS_INVARIANT = (
    ScoreInvariant.IDENTIFICATION_REFUSES_EMPTY_OBSERVATIONS
)

# Clustering pair floors + degenerate guard (§F).
CLUSTER_PAIR_FLOOR = 20
# Unknown-rejection n floor: Wilson 95% half-width ≤ ~15% at p̂=0.5
# (n=43 → ±14.3%; scope sizing table). AUDIT-04 / FIR5V11-02.
UNKNOWN_REJECTION_N_FLOOR = 43
# FIR5RR-13: the Wilson target treats the n=43 stranger probes as independent
# Bernoulli trials. They are not — stranger probes cluster within images and
# within (unnamed) individuals, so the effective sample size is smaller than
# nominal and the stated half-width is optimistic. n_floor=43 is kept; the
# dependence is disclosed rather than silently assumed away.
UNKNOWN_REJECTION_ERROR_TARGET = (
    "Wilson_95_halfwidth_le_15pct_at_p0.5 (n=43 → ±14.3%); assumes independent "
    "trials — stranger probes cluster within images/individuals, so effective "
    "n may be lower and the half-width optimistic (trial dependence disclosed)"
)

# Named sampling frames for published rates (AUDIT-01/02).
# EVAL-16: detection misses count as identification FN (not excluded).
SAMPLING_FRAME_FACE_ID = (
    "named_matched_probes_pooled_kfold_decisions_plus_missed_gt: precision "
    "over accept/confusion; recall denominator = TP + decision-FN + "
    "missed_gt (EVAL-16: detector-missed named GT is an identification FN); "
    "unmatched_detections disclosed via detection_recall_coupling_flag"
)
# AUDIT-07 / EVAL-16: observation unit is matched stranger probes PLUS
# missed_stranger_gt (caller-supplied). Missed strangers enter the
# denominator as failures so a detector that skips hard strangers cannot
# keep unknown-rejection perfect by exclusion.
SAMPLING_FRAME_UNKNOWN_REJECTION = (
    "stranger_probes_matched_plus_missed_gt: correct_reject=decision=reject; "
    "false_accept=decision=accept; missed_stranger_gt counted as failure in "
    "denominator (EVAL-16 / AUDIT-07); caller must pass missed_stranger_gt "
    "scoped to the same frame as decisions"
)
# AUDIT-07 / EVAL-23: positional claims require box-grounded L→R order.
# When compared_images=0 every claim unit has π=0 — status=not_evaluable,
# never a numeric pass/fail accuracy for adoption.
SAMPLING_FRAME_POSITIONAL = (
    "box_grounded_LtoR_name_sequences: position i must match; requires "
    "face_boxes (labeled_order_known) and centre-ordered predicted names "
    "(predicted_left_to_right); when compared_images=0 status=not_evaluable "
    "π=0 for box-grounded identity claims (EVAL-23 / AUDIT-07)"
)
POSITIONAL_EVAL_SCORED = "scored"
POSITIONAL_EVAL_NOT_EVALUABLE = "not_evaluable"
POSITIONAL_VACUITY_SIGNAL = (
    "positional identification not evaluable on this corpus, "
    "π=0 for box-grounded identity claims"
)
SAMPLING_FRAME_DEMOGRAPHIC_COHORT = (
    "named_matched_probes_in_cohort: roster_cohorts primary, single-subject "
    "celebs01 media fallback; strangers excluded; always DIRECTIONAL; "
    # FIR5RR-05: detection is image-level and is NOT re-attributed per cohort.
    "detection misses are excluded (missed_gt/unmatched_detections not "
    "attributed per cohort — emitted as null, never fabricated zeros); "
    "detection_recall_coupling_flag is inherited from full-corpus totals "
    "(null = unknown)"
)
SAMPLING_FRAME_CLUSTERING = (
    "named_matched_faces_pairwise: P_same/P_diff pair floors; M==0 "
    "all-singletons guard; single-linkage diagnostic (GRPH-18)"
)


def named_box_name(box: Any) -> str | None:
    """Authoritative namedness predicate for face_metrics (VLM6-R2-A-01 / RA-02 / RA-03).

    **Rule (explicit):** a box is named iff, after normalization, a non-empty
    string remains. Normalization is:

    1. Read ``name`` from a Mapping or object attribute; missing/``None`` → anonymous.
    2. Coerce to ``str``.
    3. Remove Unicode category ``Cf`` (format controls) — zero-width space/joiner/
       non-joiner, BOM, soft hyphen, and other invisible format chars that
       ``str.strip()`` does **not** remove (RA-03).
    4. ``str.strip()`` of Unicode whitespace (ASCII space, NBSP, ideographic
       space, tabs, …).
    5. Empty after (3)+(4) → ``None`` (anonymous); else return the remaining text.

    Every face_metrics site that decides "is this box named?" / extracts a
    display name for ordering **must** call this function — not an inline
    ``str(name).strip()`` or truthiness check (RA-02). Association still uses
    ``face_assignment.gt_box_name`` (strip-only); that surface is out of this
    module's ownership — keep the rules aligned when that module is next open.
    """
    if isinstance(box, Mapping):
        raw = box.get("name")
    else:
        raw = getattr(box, "name", None)
    if raw is None:
        return None
    # Cf = format controls (ZWSP U+200B, ZWJ U+200D, ZWNJ U+200C, BOM U+FEFF,
    # soft hyphen U+00AD, …). Not covered by str.strip() whitespace.
    without_format = "".join(
        ch for ch in str(raw) if unicodedata.category(ch) != "Cf"
    )
    text = without_format.strip()
    return text if text else None


@dataclass(frozen=True)
class ImageDetection:
    image: str
    pred_faces: int
    labeled_faces: int
    matched_faces: int | None = None


@dataclass(frozen=True)
class ImageIdentities:
    image: str
    predicted: Sequence[str]
    labeled: Sequence[str]
    recognition_enabled: bool = True
    stranger_faces: int = 0
    # False when labeled L→R order cannot be established (legacy entries with
    # empty/missing face_boxes). Positional scoring excludes these; set-based
    # identification_pr ignores the flag and still uses ``labeled`` as a set.
    labeled_order_known: bool = True
    # Optional wire identity rows + image size for centre-based L→R (VLM6-B-03).
    # When set, ``positional_identification`` re-orders via
    # ``predicted_left_to_right`` (centre-x + leftmost-wins dedup). report.py
    # must populate these; raw ``predicted`` alone cannot recover centre order.
    predicted_rows: Sequence[Any] | None = None
    image_width: float | None = None
    image_height: float | None = None


def nearest_rank_percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..1). Deterministic, no numpy/interpolation.

    Caller guarantees a non-empty ``values`` sequence.
    """
    if not values:
        raise ValueError("nearest_rank_percentile requires a non-empty values sequence")
    ordered = sorted(float(v) for v in values)
    return ordered[min(int(q * len(ordered)), len(ordered) - 1)]


def latency_summary(
    values: Sequence[float],
    *,
    unit: str = "s",
    wall_clock_s: float | None = None,
    throughput_n: int | None = None,
    decimals: int = 3,
) -> dict[str, Any] | None:
    """Canonical latency/throughput block for eval-harness runners (VLM6-RH-04).

    One schema for face_pass / florence_describe / describe_baseline consumers —
    seconds preferred, with n/mean/min/p50/p95/p99/max plus optional throughput.
    Returns ``None`` when ``values`` is empty (no timed samples).
    """
    if not values:
        return None
    if unit not in ("s", "ms"):
        raise ValueError(f"latency_summary unit must be 's' or 'ms', got {unit!r}")
    vals = [float(v) for v in values]
    n = len(vals)
    out: dict[str, Any] = {
        "unit": unit,
        "n": n,
        "mean": round(sum(vals) / n, decimals),
        "min": round(min(vals), decimals),
        "p50": round(nearest_rank_percentile(vals, 0.50), decimals),
        "p95": round(nearest_rank_percentile(vals, 0.95), decimals),
        "p99": round(nearest_rank_percentile(vals, 0.99), decimals),
        "max": round(max(vals), decimals),
    }
    if wall_clock_s is not None:
        wall = float(wall_clock_s)
        out["wall_clock_s"] = round(wall, 1)
        if throughput_n is not None and wall > 0 and throughput_n > 0:
            out["images_per_min"] = round(float(throughput_n) / (wall / 60.0), 1)
        else:
            out["images_per_min"] = None
    return out


def normalized_centre_order_key(
    centre_x: float,
    centre_y: float,
    name: str,
) -> tuple[float, float, str]:
    """Canonical L→R sort key for centre-ordered identity sequences (rg-005).

    One pure key shared by ``predicted_left_to_right``,
    ``sort_identity_rows_by_normalized_centre``, and ``labeled_left_to_right``.
    Order: increasing centre-x (viewer-left → right), then centre-y, then name.
    Never rely on input-array stability for metric / freeze byte-stability.
    """
    return (float(centre_x), float(centre_y), str(name))


def wire_bbox_normalized_centre(
    bbox: Any,
    *,
    image_width: float | None,
    image_height: float | None,
) -> tuple[float, float] | None:
    """Convert wire absolute-pixel corner ``{x,y,width,height}`` → normalized centre.

    Manifest face boxes and ``labeled_left_to_right`` use normalized centre-point
    coords (0..1). Wire identities from ``/media/identities`` carry absolute-pixel
    corner bboxes (A-08). Centre-x and corner-x are not order-equivalent when face
    widths differ (VLM6-RH-03) — normalize with captured image size before sorting.
    Returns ``None`` when bbox or dimensions are unusable (never invents coords).
    Degenerate box size (``width <= 0`` or ``height <= 0``) is unpositionable —
    same as missing dims (S3-07).
    """
    if not isinstance(bbox, Mapping):
        return None
    if image_width is None or image_height is None:
        return None
    try:
        width_px = float(image_width)
        height_px = float(image_height)
        x = float(bbox["x"])
        y = float(bbox["y"])
        w = float(bbox["width"])
        h = float(bbox["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if width_px <= 0 or height_px <= 0:
        return None
    if w <= 0 or h <= 0:
        return None
    return ((x + w / 2.0) / width_px, (y + h / 2.0) / height_px)


def predicted_left_to_right(
    identities: Sequence[Any] | None,
    *,
    image_width: float | None = None,
    image_height: float | None = None,
) -> list[str] | None:
    """Canonical predicted L→R for positional scoring (VLM6-B-03 / VLM6-RH-03).

    **Production callers must use this** (not raw name lists / corner-x sorts)
    when building ``ImageIdentities.predicted`` for ``positional_identification``.
    Corner-x and centre-x disagree when face widths differ; leftmost-wins name
    dedup mirrors ``labeled_left_to_right`` so sequence cardinalities match.

    Sorts wire identity rows using ``wire_bbox_normalized_centre`` + the shared
    ``normalized_centre_order_key`` (cx, cy, name) so both this API and
    ``sort_identity_rows_by_normalized_centre`` share one centre-x rule (S3-01 /
    rg-005). **Leftmost-wins duplicate-name dedup** mirrors
    ``labeled_left_to_right`` (VLM6-R4-08).

    Namedness (VLM6-R2-A-01 / HARM-06 / RA-02): routes every row through
    ``named_box_name`` — the single face_metrics predicate shared with
    ``labeled_left_to_right`` and ``sort_identity_rows_by_normalized_centre``.
    Whitespace-only and format-control-only names are anonymous (skipped);
    padded names are stripped before ordering.

    Returns:
    - ``None`` when ``identities`` is None (unknown).
    - Ordered unique names when rows are present. Unpositioned / unnormalizable
      named rows sort after positioned ones (stable by name) and still participate
      in leftmost-wins dedup. Empty input → ``[]``.
    """
    if identities is None:
        return None
    if not identities:
        return []
    positioned: list[tuple[float, float, str]] = []
    unpositioned: list[str] = []
    for entry in identities:
        name = named_box_name(entry)
        if name is None:
            continue
        if isinstance(entry, Mapping):
            bbox = entry.get("bbox")
        else:
            bbox = getattr(entry, "bbox", None)
        centre = wire_bbox_normalized_centre(bbox, image_width=image_width, image_height=image_height)
        if centre is None:
            unpositioned.append(name)
        else:
            positioned.append((centre[0], centre[1], name))
    positioned.sort(key=lambda t: normalized_centre_order_key(t[0], t[1], t[2]))
    unpositioned.sort()
    return _leftmost_unique_names([name for _, _, name in positioned] + unpositioned)


def _leftmost_unique_names(names: Sequence[str]) -> list[str]:
    """Leftmost-wins name dedup (single definition for labeled + predicted paths)."""
    ordered: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


# Canonical alias — one object identity (RV3-04 / TEST-15). report.py and tests
# must import this name; a re-clone that agrees on one fixture must not pass.
predicted_names_for_positional = predicted_left_to_right


def sort_identity_rows_by_normalized_centre(
    identities: Sequence[Any],
    *,
    image_width: float | None,
    image_height: float | None,
) -> list[dict[str, Any]]:
    """Re-order wire identity dict rows by normalized centre (no name dedup).

    Used by runners that store full identity rows (face_pass). Keeps every row so
    face_count/name multiset is preserved; only sort key is corrected (VLM6-RH-03).
    Sort key is the shared ``normalized_centre_order_key`` (cx, cy, name) — same
    rule as ``predicted_left_to_right`` before name dedup (S3-01 / rg-005).
    Unpositioned rows follow positioned ones (stable secondary key = name).

    Namedness (RA-02): the tertiary name component comes from ``named_box_name``
    (stripped / format-stripped; anonymous → ``""``). Rows are not filtered —
    storage must keep the full multiset — but the key must not fork an inline
    ``str(row.get("name") or "")`` that disagrees with L→R paths on padding or
    invisible names. Row ``name`` fields are left unchanged.
    """
    positioned: list[tuple[float, float, str, dict[str, Any]]] = []
    unpositioned: list[tuple[str, dict[str, Any]]] = []
    for entry in identities:
        if not isinstance(entry, Mapping):
            continue
        row = dict(entry)
        # Single namedness predicate — never raw row["name"] for the sort key.
        name = named_box_name(entry) or ""
        centre = wire_bbox_normalized_centre(row.get("bbox"), image_width=image_width, image_height=image_height)
        if centre is None:
            unpositioned.append((name, row))
        else:
            positioned.append((centre[0], centre[1], name, row))
    positioned.sort(key=lambda t: normalized_centre_order_key(t[0], t[1], t[2]))
    unpositioned.sort(key=lambda t: t[0])
    return [t[-1] for t in positioned] + [t[1] for t in unpositioned]


@dataclass(frozen=True)
class LabeledOrderResult:
    """Labeled L→R names plus degradation disclosure (VLM6-R2-G-01 / HARM-07).

    ``order_degraded`` is True when any named box used the per-box x-only
    fallback (missing ``y``). Report consumers should aggregate image-level
    counts into ``faces.identity_ordering`` — suggested field
    ``labeled_y_missing_images`` (do not overload ``degraded_images``, which
    means predicted identity_ordering stamp == DEGRADED; S2-07 / rg-015).
    """

    names: list[str] | None
    y_missing_count: int = 0
    order_degraded: bool = False


def _labeled_box_order_key(x: float, y: float | None, name: str) -> tuple:
    """Per-box L→R sort key — never invents y=0.0 (HARM-07 / VLM6-R2-G-01).

    - y present: ``(x, 0, y, name)`` — equivalent to ``normalized_centre_order_key``
      (x, y, name) with a constant present-flag.
    - y absent:  ``(x, 1, 0.0, name)`` — primary x only for spatial placement;
      the missing-flag separates these from a real top-of-frame y=0.0 box at
      the same x. Name is a determinism tertiary, not a spatial claim; when
      any box takes this branch the image is ``order_degraded``.
    """
    if y is not None:
        return (float(x), 0, float(y), str(name))
    return (float(x), 1, 0.0, str(name))


def labeled_order(face_boxes: Sequence[Any] | None) -> LabeledOrderResult:
    """Named L→R with per-box missing-y fallback + degradation counter.

    See ``labeled_left_to_right`` for order semantics. Prefer this entry when
    the caller must surface ``order_degraded`` / ``y_missing_count`` (anchor
    report disclosure; VLM6-R2-G-01).

    ``y`` coercion (RA-04 source): ``None``, blank/whitespace string, or any
    non-numeric value → missing (``None``). Missing y uses the per-box x-only
    key and sets ``order_degraded=True`` — never raises, never invents ``0.0``.
    """
    if not face_boxes:
        return LabeledOrderResult(names=None)
    # (x, y|None, name)
    named: list[tuple[float, float | None, str]] = []
    named_missing_x = 0
    for box in face_boxes:
        # Single namedness predicate (VLM6-R2-A-01 / HARM-06 / RA-02/RA-03).
        name = named_box_name(box)
        if name is None:
            continue
        if isinstance(box, Mapping):
            x = box.get("x")
            y = box.get("y")
        else:
            x = getattr(box, "x", None)
            y = getattr(box, "y", None)
        if x is None:
            named_missing_x += 1
            continue
        # Blank / whitespace / non-numeric y → missing (None), not ValueError.
        # Same ordering branch as y is None (order_degraded); no third state (RA-04).
        y_val: float | None = None
        if y is not None:
            try:
                y_val = float(y)
            except (TypeError, ValueError):
                y_val = None
        named.append((float(x), y_val, name))
    # Named boxes exist but none carry x → manifest defect, not empty order.
    if not named and named_missing_x > 0:
        return LabeledOrderResult(names=None)
    # Boxes present but none named (all strangers): established empty order.
    y_missing = sum(1 for _, y, _ in named if y is None)
    named.sort(key=lambda t: _labeled_box_order_key(t[0], t[1], t[2]))
    return LabeledOrderResult(
        names=_leftmost_unique_names([name for _, _, name in named]),
        y_missing_count=y_missing,
        order_degraded=y_missing > 0,
    )


def labeled_left_to_right(face_boxes: Sequence[Any] | None) -> list[str] | None:
    """Named identities left-to-right by face-box centre, or None if unknown.

    ``present_identities`` is stored alphabetically (draft_labels) or in XMP
    write order (export_identities) — neither is spatial. Curated ``face_boxes``
    carry centre-point coords; sort named boxes by the shared
    ``normalized_centre_order_key`` (x, y, name) so ties never depend on input
    array order (S3-02 / EVAL-04).

    Returns:
    - ``None`` when ``face_boxes`` is missing/empty — order cannot be
      established; the image must be excluded from positional scoring (never
      fall back to stored ``present_identities`` order).
    - ``None`` when boxes are present and at least one is named but **every**
      named box lacks an ``x`` coordinate — malformed ground truth, not an
      empty labeled order. Scoring as ``[]`` would charge every predicted name
      as a positional miss (VLM6-R4-08).
    - Ordered unique names when boxes are present. Anonymous boxes (``name``
      None/empty/whitespace/format-control-only — via ``named_box_name``) are
      skipped. **Duplicate names keep the leftmost occurrence only** so the
      sequence cardinality matches what ``predicted`` can hold (one slot per
      distinct identity, as ``present_identities`` is a set-like list). Later
      same-name boxes are ignored, not multi-counted.
    - ``[]`` when boxes are present but all anonymous (order established, nobody
      named) — distinct from the malformed-GT ``None`` case above.

    HARM-07 / rg-015 / VLM6-R2-G-01: never invent ``y=0.0``. Fallback is
    **per-box**: boxes with ``y`` keep the centre key; boxes missing ``y`` sort
    by ``x`` alone in the same pass (missing-flag secondary — not a whole-image
    collapse to ``(x, name)`` that discards real y on sibling boxes). Use
    ``labeled_order`` when the degradation counter is required.
    """
    return labeled_order(face_boxes).names


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _ratio_zero(numerator: int, denominator: int) -> float:
    """§F convention: 0/0 → 0 (face-level ID P/R and open-set F1)."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


@dataclass(frozen=True)
class IdentityPr:
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float | None:
        return _ratio(self.true_positives, self.true_positives + self.false_positives)

    @property
    def recall(self) -> float | None:
        return _ratio(self.true_positives, self.true_positives + self.false_negatives)


@dataclass(frozen=True)
class PrResult:
    true_positives: int
    false_positives: int
    false_negatives: int
    true_rejections: int = 0
    wrong_names: list[tuple[str, str]] = field(default_factory=list)
    per_identity: dict[str, IdentityPr] = field(default_factory=dict)
    excluded_images: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        return _ratio(self.true_positives, self.true_positives + self.false_positives)

    @property
    def recall(self) -> float | None:
        return _ratio(self.true_positives, self.true_positives + self.false_negatives)

    @property
    def macro_precision(self) -> float | None:
        values = [pr.precision for pr in self.per_identity.values() if pr.precision is not None]
        return sum(values) / len(values) if values else None

    @property
    def macro_recall(self) -> float | None:
        values = [pr.recall for pr in self.per_identity.values() if pr.recall is not None]
        return sum(values) / len(values) if values else None


def detection_pr(
    items: Sequence[ImageDetection],
    *,
    annotation_mode: AnnotationMode | str | None = None,
) -> PrResult:
    """Count-based detection P/R: per image TP=min(pred,labeled), overshoot=FP, undershoot=FN.

    When ``matched_faces`` is set, TP is the IoU-matched count (FIR-8 localization pin).
    Refuses unless the resolved mode *is* ``AnnotationMode.EXHAUSTIVE``.
    Omission, null, empty, unknown, and ``roster_only`` all raise
    ``ManifestError`` with a named invariant — there is no permissive default.
    """
    mode = parse_annotation_mode(annotation_mode)
    if mode is None:
        raise ManifestError(
            "detection_pr requires annotation_mode; omission is not exhaustive",
            invariant=ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE,
        )
    if mode is not AnnotationMode.EXHAUSTIVE:
        raise ManifestError(
            "detection_pr refuses roster_only manifests; unlabeled non-roster "
            "faces would be scored as false positives",
            invariant=ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY,
        )
    tp = fp = fn = 0
    for item in items:
        if item.matched_faces is None:
            tp += min(item.pred_faces, item.labeled_faces)
            fp += max(item.pred_faces - item.labeled_faces, 0)
            fn += max(item.labeled_faces - item.pred_faces, 0)
            continue
        matched = item.matched_faces
        bound = min(item.pred_faces, item.labeled_faces)
        if matched < 0 or matched > bound:
            raise ValueError("matched_faces_out_of_bounds")
        tp += matched
        fp += max(item.pred_faces - matched, 0)
        fn += max(item.labeled_faces - matched, 0)
    return PrResult(true_positives=tp, false_positives=fp, false_negatives=fn)


def boxed_identity_names(entry: Mapping[str, Any]) -> frozenset[str]:
    """Names that have a per-face box. Unnamed boxes are detection-only."""
    names: set[str] = set()
    for box in entry.get("face_boxes") or []:
        name = box.get("name") if isinstance(box, Mapping) else getattr(box, "name", None)
        if name:
            names.add(str(name))
    return frozenset(names)


def unboxed_identity_claims(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Identity claims in ``present_identities`` with no matching named box."""
    boxed = boxed_identity_names(entry)
    return tuple(
        str(name) for name in (entry.get("present_identities") or []) if str(name) not in boxed
    )


def require_exhaustive_box_coverage(entries: Sequence[Mapping[str, Any]]) -> None:
    """Refuse exhaustive detection when boxes cannot witness ``face_count``.

    An ``exhaustive`` stamp whose ``len(face_boxes) != face_count`` is not a
    coverage witness. Load-time already checks this; the raw-mapping lattice
    must not trust the stamp alone (S2R4-04).
    """
    holes: list[str] = []
    first_index: int | None = None
    first_path: str | None = None
    for index, entry in enumerate(entries):
        # Absent key ≡ empty list. Fusion flatten and GoldenEntry.model_dump
        # both emit face_boxes; a raw mapping that omits it cannot witness
        # face_count (S2R5-07). 0 boxes vs face_count=0 is covered, not a hole.
        n_boxes = len(entry.get("face_boxes") or [])
        face_count = int(entry.get("face_count") or 0)
        if n_boxes == face_count:
            continue
        path = str(entry.get("path", f"entry[{index}]"))
        if first_index is None:
            first_index = index
            first_path = path
        holes.append(f"{path} len(face_boxes)={n_boxes} != face_count={face_count}")
    if holes:
        raise ManifestError(
            "detection P/R cannot be computed from an exhaustive stamp whose "
            "boxes do not cover face_count: " + "; ".join(holes),
            invariant=DETECTION_UNCOVERED_FACE_COUNT_INVARIANT,
            entry_index=first_index,
            entry_path=first_path,
        )


def _recognition_enabled(entry: Mapping[str, Any]) -> bool:
    """Match identification_pr: policy-disabled rows are not live claims."""
    policy = entry.get("policy") or {}
    if isinstance(policy, Mapping):
        return bool(policy.get("recognition_enabled", True))
    return bool(getattr(policy, "recognition_enabled", True))


def require_boxed_identification_gt(entries: Sequence[Mapping[str, Any]]) -> None:
    """Refuse identification scoring when any claim lacks per-face box lineage.

    Does not drop the unboxed entries from the denominator and does not
    substitute 0.0 — the metric is not computable honestly (EVAL-03).
    Policy-disabled rows are not live claims (same population as
    identification_pr) and must not refuse an otherwise boxed score (S2R4-06).
    """
    holes: list[str] = []
    first_index: int | None = None
    first_path: str | None = None
    for index, entry in enumerate(entries):
        if not _recognition_enabled(entry):
            continue
        unboxed = unboxed_identity_claims(entry)
        if not unboxed:
            continue
        path = str(entry.get("path", f"entry[{index}]"))
        if first_index is None:
            first_index = index
            first_path = path
        holes.append(f"{path} unboxed={list(unboxed)}")
    if holes:
        raise ManifestError(
            "identification P/R cannot be computed from identity claims that "
            "carry no per-face box lineage: " + "; ".join(holes),
            invariant=IDENTIFICATION_UNBOXED_INVARIANT,
            entry_index=first_index,
            entry_path=first_path,
        )


def identification_pr(items: Sequence[ImageIdentities]) -> PrResult:
    tp = fp = fn = true_rejections = 0
    wrong_names: list[tuple[str, str]] = []
    excluded: list[str] = []
    per_identity_counts: dict[str, dict[str, int]] = {}

    def counts(name: str) -> dict[str, int]:
        return per_identity_counts.setdefault(name, {"tp": 0, "fp": 0, "fn": 0})

    for item in items:
        if not item.recognition_enabled:
            excluded.append(item.image)
            continue
        predicted = sorted(set(item.predicted))
        labeled = set(item.labeled)
        # Stranger true rejection: the image has non-roster faces and the model
        # asserted no wrong name on it — the strangers were correctly left
        # unnamed. Counted even when a labeled roster person is also present and
        # correctly named (a common mixed case), not only on all-empty images.
        if item.stranger_faces > 0 and not any(name not in labeled for name in predicted):
            true_rejections += 1
        for name in predicted:
            if name in labeled:
                tp += 1
                counts(name)["tp"] += 1
            else:
                fp += 1
                counts(name)["fp"] += 1
                wrong_names.append((item.image, name))
        for name in labeled:
            if name not in predicted:
                fn += 1
                counts(name)["fn"] += 1

    per_identity = {
        name: IdentityPr(true_positives=c["tp"], false_positives=c["fp"], false_negatives=c["fn"])
        for name, c in sorted(per_identity_counts.items())
    }
    return PrResult(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_rejections=true_rejections,
        wrong_names=wrong_names,
        per_identity=per_identity,
        excluded_images=excluded,
    )


# ---------------------------------------------------------------------------
# Positional (left-to-right) identification — discriminates swaps (A-02)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionalIdResult:
    """Ordered name-binding score: position i must match, not just the name set.

    ``identification_pr`` reduces predictions to ``sorted(set(...))``, so a
    left/right swap of two correctly-detected people scores identically to the
    correct interleave. This metric keeps sequence order and therefore penalises
    swaps: position_hits drops while the set-based P/R stays the same.

    When ``compared_images == 0`` every box-grounded identity claim has π=0
    (EVAL-23 / AUDIT-07): ``evaluable`` is False, ``status`` is
    ``not_evaluable``, and ``vacuity_signal`` carries the machine-readable
    block reason. Callers must not treat ``position_accuracy is None`` alone
    as a soft skip — consume ``status`` / ``vacuity_signal`` for the gate.
    """

    position_hits: int
    position_total: int
    exact_order_images: int
    compared_images: int
    swap_images: int  # same multiset of names, different order
    excluded_images: list[str] = field(default_factory=list)
    # VLM6-B-10: loud vacuity when π=0 (sr-007 centralised status values).
    evaluable: bool = True
    status: str = POSITIONAL_EVAL_SCORED
    vacuity_signal: str | None = None
    sampling_frame: str = SAMPLING_FRAME_POSITIONAL

    @property
    def position_accuracy(self) -> float | None:
        # None when no positions compared (including full-corpus π=0 vacuity).
        return _ratio(self.position_hits, self.position_total)

    @property
    def exact_order_rate(self) -> float | None:
        return _ratio(self.exact_order_images, self.compared_images)


def positional_identification(items: Sequence[ImageIdentities]) -> PositionalIdResult:
    """Score predicted vs labeled name sequences left-to-right (order-sensitive).

    For each recognition-enabled image with known labeled order, pad the shorter
    sequence with ``None`` and count position-wise equality. An image whose
    predicted multiset equals the labeled multiset but whose order differs is
    counted as a ``swap_image``. Empty/empty images are skipped (nothing to
    order). Images with ``recognition_enabled=False`` or
    ``labeled_order_known=False`` (no face_boxes to establish L→R) are listed
    in ``excluded_images`` and never compared in stored alphabetical order.

    Predicted order (VLM6-B-03): when ``item.predicted_rows`` is set, re-order
    via ``predicted_left_to_right`` (centre-x + leftmost-wins dedup). Otherwise
    apply leftmost-wins dedup on the stored name sequence so duplicate faces
    cannot inflate position_total relative to labeled L→R cardinality.
    """
    hits = total = exact = compared = swaps = 0
    excluded: list[str] = []
    for item in items:
        if not item.recognition_enabled or not item.labeled_order_known:
            excluded.append(item.image)
            continue
        if item.predicted_rows is not None:
            ordered = predicted_left_to_right(
                item.predicted_rows,
                image_width=item.image_width,
                image_height=item.image_height,
            )
            predicted = list(ordered) if ordered is not None else []
        else:
            # Partial B-03 without wire rows: still dedupe leftmost-wins so
            # [Alice, Alice, Bob] vs labeled [Alice, Bob] is not a 1/3 hit.
            predicted = _leftmost_unique_names(list(item.predicted))
        labeled = list(item.labeled)
        if not predicted and not labeled:
            continue
        compared += 1
        n = max(len(predicted), len(labeled))
        for i in range(n):
            total += 1
            pred_i = predicted[i] if i < len(predicted) else None
            lab_i = labeled[i] if i < len(labeled) else None
            if pred_i is not None and pred_i == lab_i:
                hits += 1
        if predicted == labeled:
            exact += 1
        elif sorted(predicted) == sorted(labeled):
            swaps += 1
    evaluable = compared > 0
    return PositionalIdResult(
        position_hits=hits,
        position_total=total,
        exact_order_images=exact,
        compared_images=compared,
        swap_images=swaps,
        excluded_images=excluded,
        evaluable=evaluable,
        status=POSITIONAL_EVAL_SCORED if evaluable else POSITIONAL_EVAL_NOT_EVALUABLE,
        vacuity_signal=None if evaluable else POSITIONAL_VACUITY_SIGNAL,
        sampling_frame=SAMPLING_FRAME_POSITIONAL,
    )


# ---------------------------------------------------------------------------
# FIR-5 S3 §F — face-level identification over pooled decisions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FaceLevelIdPr:
    """Face-level identification P/R (0/0 → 0). Coupled to detection recall.

    EVAL-16: ``missed_gt`` is folded into ``false_negatives`` so detector-missed
    named subjects lower id-recall. ``detection_recall_coupling_flag`` remains
    additional disclosure when misses or unmatched detections are present
    (never a fail-open default — REF-27).
    """

    true_positives: int
    false_positives: int
    false_negatives: int
    n_named_probes: int
    n_recall_eligible: int  # enrolled faces (not excluded_single_face_recall)
    wrong_names: tuple[tuple[int, int, str, str], ...]  # media_id, box_index, true, pred
    # None = unknown/not attributable in this frame (FIR5RR-05) — never a
    # fabricated False. Serializes as null.
    detection_recall_coupling_flag: bool | None
    sampling_frame: str = SAMPLING_FRAME_FACE_ID
    # Explicit rate denominators for AUDIT-02 (n/N honesty).
    precision_numerator: int = 0  # TP
    precision_denominator: int = 0  # TP+FP
    recall_numerator: int = 0  # TP
    recall_denominator: int = 0  # TP+FN
    # None = miss counts are not attributed in this sampling frame (per-cohort
    # demographic rollup) — never a fabricated 0 (FIR5RR-05). Defaults are None
    # (not-attributed), never fail-open zeros (FIR5CR-03); attribution is
    # all-or-nothing — both None or both ints.
    missed_gt: int | None = None
    unmatched_detections: int | None = None

    @property
    def precision(self) -> float:
        return _ratio_zero(self.true_positives, self.true_positives + self.false_positives)

    @property
    def recall(self) -> float:
        return _ratio_zero(self.true_positives, self.true_positives + self.false_negatives)


def face_identification_pr(
    decisions: Sequence[Any],
    *,
    missed_gt: int | None,
    unmatched_detections: int | None,
    detection_coupling: bool | None = None,
    sampling_frame: str = SAMPLING_FRAME_FACE_ID,
) -> FaceLevelIdPr:
    """Face-level ID P/R over pooled per-fold decisions for *named* probes (§F).

    - accept & name* == true → TP
    - accept & name* != true → FP on name*; FN on true iff enrolled
    - reject of enrolled → FN
    - missed_gt (attributed) → FN each (EVAL-16: detector miss is id error)
    - single-face confusion → FP only (excluded_single_face_recall)
    Precision/Recall use 0/0 → 0.

    ``missed_gt`` is **named-only** (S3-04 / EVAL-16 / EVAL-19): count of
    detector-missed ground-truth boxes whose ``true_name is not None``.
    Unmatched stranger GT must not enter this FN fold-in — route those to
    ``face_unknown_rejection(..., missed_stranger_gt=...)`` instead.
    ``AssignmentResult.missed_gt`` and the headline association path both emit
    named-only counts so the full-corpus and headline observation units agree.

    ``missed_gt`` and ``unmatched_detections`` are **required** (no fail-open
    default of 0 — REF-27 / FIR5V11-05). Pass counts scoped to the same
    sampling frame as ``decisions`` (e.g. celebs01-only for headline).
    ``detection_recall_coupling_flag`` is True when either count is > 0
    (additional disclosure alongside the FN fold-in — EVAL-16).
    Stranger false-accepts live only in the separate unknown-rejection metric.

    FIR5RR-05: a frame that CANNOT attribute detection misses (the per-cohort
    demographic rollup — detection is image-level) passes ``missed_gt=None``
    and ``unmatched_detections=None`` with ``detection_coupling`` inherited
    from the parent totals (or ``None`` = unknown). Fabricating ``0`` counts
    (and a ``False`` coupling flag) in such a frame is forbidden.
    ``detection_coupling`` may only accompany all-None counts. Attribution is
    all-or-nothing (FIR5CR-03): exactly one of ``missed_gt`` /
    ``unmatched_detections`` being ``None`` raises — a frame either attributes
    both counts or neither.
    """
    tp = fp = fn = 0
    n_named = 0
    n_recall_eligible = 0
    wrong: list[tuple[int, int, str, str]] = []

    for d in decisions:
        true_name = d.true_name if not isinstance(d, Mapping) else d.get("true_name")
        if true_name is None:
            continue
        n_named += 1
        decision = d.decision if not isinstance(d, Mapping) else d["decision"]
        predicted = d.predicted_name if not isinstance(d, Mapping) else d.get("predicted_name")
        enrolled = d.enrolled if not isinstance(d, Mapping) else bool(d.get("enrolled"))

        if enrolled:
            n_recall_eligible += 1

        if decision == "accept":
            if predicted == true_name:
                tp += 1
            else:
                fp += 1
                if enrolled:
                    fn += 1
                # media_id/box_index only label a wrong-name row — read them here
                # (tolerantly on the Mapping path) so a reject decision supplied as
                # a dict without those keys does not KeyError before the branch.
                media_id = d.media_id if not isinstance(d, Mapping) else int(d.get("media_id", -1))
                box_index = d.box_index if not isinstance(d, Mapping) else int(d.get("box_index", -1))
                wrong.append((media_id, box_index, str(true_name), str(predicted)))
        else:
            # reject
            if enrolled:
                fn += 1

    mg = None if missed_gt is None else int(missed_gt)
    ud = None if unmatched_detections is None else int(unmatched_detections)
    if (mg is None) != (ud is None):
        raise ValueError(
            "missed_gt and unmatched_detections must be attributed together "
            "(all-or-nothing — FIR5CR-03): got "
            f"missed_gt={mg!r}, unmatched_detections={ud!r}; a frame either "
            "attributes both detection-miss counts or neither"
        )
    if mg is None and ud is None:
        # Not-attributed frame: coupling is inherited (or unknown), never
        # derived from fabricated zeros (FIR5RR-05). Missed-GT FN fold-in
        # is also skipped (cannot invent a count).
        coupling = detection_coupling
    else:
        if detection_coupling is not None:
            raise ValueError(
                "detection_coupling override is only valid when missed_gt and "
                "unmatched_detections are both None (not-attributed frame); "
                "with real counts the flag is computed, not asserted"
            )
        coupling = (mg or 0) > 0 or (ud or 0) > 0
        # EVAL-16 / VLM6-B-01: detector-missed named GT is an identification FN.
        # Coupling flag stays as additional disclosure, not the only signal.
        fn += mg or 0
    return FaceLevelIdPr(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        n_named_probes=n_named,
        n_recall_eligible=n_recall_eligible,
        wrong_names=tuple(sorted(wrong)),
        detection_recall_coupling_flag=coupling,
        sampling_frame=sampling_frame,
        precision_numerator=tp,
        precision_denominator=tp + fp,
        recall_numerator=tp,
        recall_denominator=tp + fn,
        missed_gt=mg,
        unmatched_detections=ud,
    )


# ---------------------------------------------------------------------------
# FIR-5 S3d — demographic Fair-SA rollup (DIRECTIONAL always; no n-floor)
# ---------------------------------------------------------------------------

# Named probes whose identity is absent from roster_cohorts and ineligible for
# single-subject celebs01 fallback. Legible bucket (PROV-04) — never silently drop.
UNLABELED_COHORT_KEY = "unlabeled"

DEMOGRAPHIC_SECTION_HEADER = "demographic Fair-SA (DIRECTIONAL)"


@dataclass(frozen=True)
class DemographicRollup:
    """Per-cohort face-level ID P/R. Always DIRECTIONAL (no demographic n-floor).

    FAIR-01/02/03/06: disaggregated P/R + n per cohort; CAL-06: report only
    (never adjusts τ). Empty ``by_cohort`` still carries ``section_header`` so
    missing cohorts are not a silent skip.
    """

    by_cohort: dict[str, FaceLevelIdPr]
    directional: bool = True
    directional_reasons: tuple[str, ...] = ("no demographic n-floor",)
    section_header: str = DEMOGRAPHIC_SECTION_HEADER

    def __post_init__(self) -> None:
        # Frozen dataclass: directional is always True for this task (EVAL-04).
        object.__setattr__(self, "directional", True)


def _decision_media_id(d: Any) -> int | None:
    if isinstance(d, Mapping):
        mid = d.get("media_id")
        return int(mid) if mid is not None else None
    mid = getattr(d, "media_id", None)
    return int(mid) if mid is not None else None


def _resolve_cohort(
    true_name: str,
    media_id: int | None,
    roster_cohorts: Mapping[str, str],
    single_subject_cohort_by_media: Mapping[int, str] | None,
) -> str:
    """PRIMARY roster identity → FALLBACK single-subject celebs01 media map.

    Multi-face image-level demographic_cohort must NOT appear in
    ``single_subject_cohort_by_media`` (caller contract; S3d anti-mis-attribution).
    """
    cohort = roster_cohorts.get(true_name)
    if cohort is not None:
        return cohort
    if single_subject_cohort_by_media is not None and media_id is not None:
        fallback = single_subject_cohort_by_media.get(media_id)
        if fallback is not None:
            return fallback
    return UNLABELED_COHORT_KEY


def demographic_rollup(
    decisions: Sequence[Any],
    roster_cohorts: Mapping[str, str],
    *,
    single_subject_cohort_by_media: Mapping[int, str] | None = None,
    parent_detection_coupling: bool | None = None,
) -> DemographicRollup:
    """Per-cohort face-level identification P/R (Fair-SA; always DIRECTIONAL).

    Cohort resolution (load-bearing):
    1. PRIMARY: ``roster_cohorts[true_name]`` — person attribute via matched
       named GT box / roster identity.
    2. FALLBACK: ``single_subject_cohort_by_media[media_id]`` — caller-built map
       of *single-subject celebs01* entries only (exactly one named GT identity
       and provenance CELEB). Multi-face entries MUST NOT be in this map; those
       faces are excluded from image-level cohort attribution (anti-mis-
       attribution invariant). Named probes with no roster/fallback cohort land
       under ``UNLABELED_COHORT_KEY`` (never silently dropped).
    3. Strangers (``true_name is None``) have no cohort — excluded.

    Reuses ``face_identification_pr`` counting: accept&name*==true→TP;
    accept&name*!=true→FP (+ FN iff enrolled); reject-of-enrolled→FN; 0/0→0.

    Empty ``roster_cohorts`` / no eligible probes → empty ``by_cohort`` with
    ``section_header`` still set (not KeyError, not silent skip). Does **not**
    adjust τ (CAL-06).
    """
    buckets: dict[str, list[Any]] = {}
    for d in decisions:
        true_name = d.true_name if not isinstance(d, Mapping) else d.get("true_name")
        if true_name is None:
            continue  # strangers: no cohort
        media_id = _decision_media_id(d)
        cohort = _resolve_cohort(
            str(true_name),
            media_id,
            roster_cohorts,
            single_subject_cohort_by_media,
        )
        buckets.setdefault(cohort, []).append(d)

    # Cohort P/R reuses the same counting; detection coupling is not
    # re-attributed per cohort (detection is image-level). FIR5RR-05: the miss
    # fields are emitted as None ("not attributed"), never fabricated zeros,
    # and the coupling flag is inherited from the parent full-corpus totals
    # (None = unknown when the caller has no parent frame).
    by_cohort = {
        cohort: face_identification_pr(
            group,
            missed_gt=None,
            unmatched_detections=None,
            detection_coupling=parent_detection_coupling,
            sampling_frame=SAMPLING_FRAME_DEMOGRAPHIC_COHORT,
        )
        for cohort, group in sorted(buckets.items())
    }
    return DemographicRollup(by_cohort=by_cohort)


# ---------------------------------------------------------------------------
# Face-level unknown-rejection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnknownRejectionResult:
    correct_rejects: int
    false_accepts: int
    n: int
    n_floor: int = UNKNOWN_REJECTION_N_FLOOR
    sampling_frame: str = SAMPLING_FRAME_UNKNOWN_REJECTION
    error_target: str = UNKNOWN_REJECTION_ERROR_TARGET
    # rate = correct_rejects / n; denominators retained for redaction honesty.
    rate_numerator: int = 0
    rate_denominator: int = 0
    # EVAL-16 / AUDIT-07: stranger GT boxes the detector never matched.
    # Counted in n and as rate failures so exclusion cannot keep rate=1.0.
    missed_stranger_gt: int = 0

    @property
    def rate(self) -> float:
        """correct_rejects / (correct + false_accept + missed_stranger_gt); 0/0 → 0."""
        return _ratio_zero(
            self.correct_rejects,
            self.correct_rejects + self.false_accepts + self.missed_stranger_gt,
        )

    @property
    def meets_floor(self) -> bool:
        return self.n >= self.n_floor


def face_unknown_rejection(
    decisions: Sequence[Any],
    *,
    missed_stranger_gt: int,
) -> UnknownRejectionResult:
    """Face-level unknown-rejection over stranger probes (pooled decisions).

    correct-reject = reject; false-accept = accept any name.

    ``missed_stranger_gt`` is **required** (S3-03 / AUDIT-07 / sr-001): no
    fail-open default of 0. Callers must pass the frame-scoped count of
    unmatched GT boxes with ``true_name is None`` (association ``unmatched_gt``
    whose name is None). Omitting the kwarg is a TypeError — a production call
    that forgets attribution cannot silently publish rate=1.0.

    Missed strangers enter the denominator as failures so a detector that skips
    hard strangers cannot keep unknown-rejection perfect by exclusion
    (EVAL-16 / VLM6-B-08). Pass ``0`` only when the frame truly has zero
    unmatched stranger GT.
    """
    correct = 0
    false_accept = 0
    for d in decisions:
        true_name = d.true_name if not isinstance(d, Mapping) else d.get("true_name")
        if true_name is not None:
            continue
        decision = d.decision if not isinstance(d, Mapping) else d["decision"]
        if decision == "reject":
            correct += 1
        else:
            false_accept += 1
    missed = max(0, int(missed_stranger_gt))
    n = correct + false_accept + missed
    return UnknownRejectionResult(
        correct_rejects=correct,
        false_accepts=false_accept,
        n=n,
        sampling_frame=SAMPLING_FRAME_UNKNOWN_REJECTION,
        error_target=UNKNOWN_REJECTION_ERROR_TARGET,
        rate_numerator=correct,
        rate_denominator=n,
        missed_stranger_gt=missed,
    )


# ---------------------------------------------------------------------------
# Single-linkage clustering (GRPH-18 diagnostic; O(n²) — PERF-05/GRPH-17)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClusteringMetrics:
    """Single-linkage cut metrics at one d_cut (§F)."""

    d_cut: float
    n_faces: int
    n_clusters: int
    purity: float
    false_merge: float  # #(diff-id pairs in same cluster) / M; 0 if M==0
    false_split: float  # #(same-id pairs in diff clusters) / P_same; 0 if P_same==0
    p_same: int
    p_diff: int
    m_co_clustered: int  # M
    labels: tuple[int, ...]  # cluster id per face (stable order of input)
    directional: bool
    directional_reasons: tuple[str, ...]


def _cosine_distance_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Pairwise cosine distance d = 1 − cos; embeddings shape (N, D)."""
    # L2-normalize rows
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    unit = embeddings / norms
    sim = unit @ unit.T
    return 1.0 - sim


def single_linkage_labels(distance: np.ndarray, d_cut: float) -> list[int]:
    """Connected components of the d ≤ d_cut graph (= single-linkage cut).

    GRPH-18: single-linkage *is* the transitive-closure chaining failure mode;
    false-merge/false-split measure it. Diagnostic only, not the product clusterer.
    """
    n = distance.shape[0]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # Prefer lower root for determinism.
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if distance[i, j] <= d_cut:
                union(i, j)

    roots = [find(i) for i in range(n)]
    root_to_id: dict[int, int] = {}
    labels: list[int] = []
    next_id = 0
    for r in roots:
        if r not in root_to_id:
            root_to_id[r] = next_id
            next_id += 1
        labels.append(root_to_id[r])
    return labels


def clustering_metrics_at_cut(
    embeddings: Sequence[Sequence[float]],
    identity_labels: Sequence[str],
    d_cut: float,
    *,
    pair_floor: int = CLUSTER_PAIR_FLOOR,
) -> ClusteringMetrics:
    """Purity / false-merge / false-split at distance cut d_cut (§F).

    Operates on faces matched to *named* GT only (caller excludes strangers).
    DIRECTIONAL when P_same < floor OR P_diff < floor OR M == 0.
    M == 0 (all-singletons) is a *separate* guard from pair floors — purity≡1.0
    and false-merge 0/0 are vacuous; can co-occur with P_same,P_diff ≥ floor.
    Single-cluster is NOT a 0-denominator case (there M = C(N,2) > 0).
    """
    n = len(embeddings)
    if n == 0:
        return ClusteringMetrics(
            d_cut=d_cut,
            n_faces=0,
            n_clusters=0,
            purity=0.0,
            false_merge=0.0,
            false_split=0.0,
            p_same=0,
            p_diff=0,
            m_co_clustered=0,
            labels=(),
            directional=True,
            directional_reasons=("empty",),
        )

    emb = np.asarray(embeddings, dtype=np.float64)
    dist = _cosine_distance_matrix(emb)
    labels = single_linkage_labels(dist, d_cut)
    n_clusters = len(set(labels))

    # Pair counts
    p_same = p_diff = m = diff_in_same = same_in_diff = 0
    for i in range(n):
        for j in range(i + 1, n):
            same_id = identity_labels[i] == identity_labels[j]
            same_cluster = labels[i] == labels[j]
            if same_id:
                p_same += 1
            else:
                p_diff += 1
            if same_cluster:
                m += 1
                if not same_id:
                    diff_in_same += 1
            else:
                if same_id:
                    same_in_diff += 1

    # Purity = (1/N) * sum_clusters max_identity |cluster ∩ identity|
    clusters: dict[int, list[int]] = {}
    for idx, lab in enumerate(labels):
        clusters.setdefault(lab, []).append(idx)
    purity_sum = 0
    for members in clusters.values():
        id_counts: dict[str, int] = {}
        for idx in members:
            name = identity_labels[idx]
            id_counts[name] = id_counts.get(name, 0) + 1
        purity_sum += max(id_counts.values())
    purity = purity_sum / n

    false_merge = _ratio_zero(diff_in_same, m)
    false_split = _ratio_zero(same_in_diff, p_same)

    reasons: list[str] = []
    if p_same < pair_floor:
        reasons.append(f"p_same<{pair_floor}")
    if p_diff < pair_floor:
        reasons.append(f"p_diff<{pair_floor}")
    if m == 0:
        reasons.append("m==0")  # all-singletons; independent of pair floors

    return ClusteringMetrics(
        d_cut=float(d_cut),
        n_faces=n,
        n_clusters=n_clusters,
        purity=float(purity),
        false_merge=float(false_merge),
        false_split=float(false_split),
        p_same=p_same,
        p_diff=p_diff,
        m_co_clustered=m,
        labels=tuple(labels),
        directional=bool(reasons),
        directional_reasons=tuple(reasons),
    )


def clustering_sweep(
    embeddings: Sequence[Sequence[float]],
    identity_labels: Sequence[str],
    *,
    tau_grid: Sequence[float],
    tau_op: float,
    pair_floor: int = CLUSTER_PAIR_FLOOR,
) -> tuple[tuple[ClusteringMetrics, ...], ClusteringMetrics]:
    """Sweep d_cut ∈ {1−τ : τ in §E grid}; headline point d_cut = 1 − τ_op."""
    # Stable unique cuts from the grid.
    cuts = sorted({round(1.0 - float(t), 4) for t in tau_grid})
    sweep = tuple(
        clustering_metrics_at_cut(embeddings, identity_labels, d_cut, pair_floor=pair_floor) for d_cut in cuts
    )
    headline = clustering_metrics_at_cut(
        embeddings,
        identity_labels,
        round(1.0 - float(tau_op), 4),
        pair_floor=pair_floor,
    )
    return sweep, headline
