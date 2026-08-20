"""Face bake-off score-time association, LOO gallery, open-set assignment (FIR-5 S3).

Implements §C–§E of the bake-off scoring architecture plus §F similar_people.
Pure functions of stored run-record boxes/embeddings + manifest GT — no network,
no product ClusteringSettings, no RNG.

Heuristics (docs/workbay/rules/engineering-heuristics.md,
docs/workbay/rules/graph-theory-heuristics.md — cite ids only):
- GRPH-07: Hungarian bipartite matching for ≥2-box association and similar_people
- EMB-02: mean prototype (bake-off choice; medoid is a common alternative)
- EMB-06/CAL-02: recognition = probe–gallery cosine vs τ; reject is first-class
- EVAL-07: face's τ_k never fit on its own held-out decision (pooled per-fold)
- CAL-07: subject-disjoint folds; fit-phase galleries restricted to fit identities
- GRPH-23/CAL-01: τ swept on a grid, not one global magic constant
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Literal

import numpy as np
from scipy.optimize import linear_sum_assignment

from scripts.eval_harness.accept_predicate import accepts

# §C
IOU_MATCH_THRESHOLD = 0.5

# §E
K_FOLDS = 5
TAU_GRID: tuple[float, ...] = tuple(round(0.20 + i * 0.05, 2) for i in range(15))  # 0.20..0.90

# Global fold-key sort sentinel for strangers (U+FFFF sorts after normal names).
STRANGER_SORT_KEY = "\uffff__stranger__"

DecisionKind = Literal["accept", "reject"]

# AUDIT-01/02 (FIR5RR-07): how the per-fold τ_k were obtained. "fitted" = every
# fold τ selected by open-set F1 on a non-empty fit set; "mid_grid_unfitted" =
# at least one fold fell back to the mid-grid default (single-subject corpus or
# no matched probes) — downstream consumers must treat all τ-dependent slices
# as DIRECTIONAL/non-gating. "error" is reserved (multi-subject empty fit
# raises instead of returning).
TauFitStatus = Literal["fitted", "mid_grid_unfitted", "error"]

# FIR5CR-06: fold protocol disclosure — single-sourced here, wired into the
# report's protocol_disclosures surface alongside the other disclosures.
FOLD_MEDIA_CORESIDENCY_DISCLOSURE = (
    "k-fold splits are subject-disjoint but not media-disjoint — a stranger "
    "face co-resident on a held-out identity's image can enter that "
    "identity's fit fold, so fit and read phases share image context "
    "(contextual dependency)"
)


# ---------------------------------------------------------------------------
# §A0 / §C — coordinate conversion + IoU association
# ---------------------------------------------------------------------------


def gt_normalized_centre_to_pixel_corner(
    *,
    cx: float,
    cy: float,
    w: float,
    h: float,
    image_size: Sequence[int],
) -> list[float]:
    """Convert GT normalized-centre box to pixel-corner [x, y, w, h] (§A0 / §C).

    ``image_size`` is ``[W, H]`` pixels from the face run-record.
    Detector ``bbox_px`` is already pixel-corner — never pass it through this.
    """
    width, height = int(image_size[0]), int(image_size[1])
    return [
        (cx - w / 2.0) * width,
        (cy - h / 2.0) * height,
        w * width,
        h * height,
    ]


def iou_pixel_corner(a: Sequence[float], b: Sequence[float]) -> float:
    """IoU of two [x, y, w, h] boxes in pixel-corner form."""
    ax, ay, aw, ah = (float(v) for v in a)
    bx, by, bw, bh = (float(v) for v in b)
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter_w = max(0.0, ix2 - ix1)
    inter_h = max(0.0, iy2 - iy1)
    inter = inter_w * inter_h
    if inter <= 0.0:
        return 0.0
    union = aw * ah + bw * bh - inter
    if union <= 0.0:
        return 0.0
    return float(inter / union)


@dataclass(frozen=True)
class AssociationPair:
    det_index: int
    gt_index: int
    iou: float
    name: str | None  # GT name; None = stranger


@dataclass(frozen=True)
class AssociationResult:
    """§C outcomes for one image."""

    pairs: tuple[AssociationPair, ...]  # accepted pairs (IoU >= threshold)
    unmatched_detections: tuple[int, ...]  # false detections (det-PR FP)
    unmatched_gt: tuple[int, ...]  # missed GT (det-PR FN)
    ious: tuple[tuple[int, int, float], ...]  # (det_i, gt_j, iou) for audit


def _gt_fields(gt: Any) -> tuple[float, float, float, float, str | None]:
    """Extract centre box + name from FaceBox-like or mapping."""
    if isinstance(gt, Mapping):
        return float(gt["x"]), float(gt["y"]), float(gt["w"]), float(gt["h"]), gt.get("name")
    return float(gt.x), float(gt.y), float(gt.w), float(gt.h), gt.name


def associate_detections(
    detections_bbox_px: Sequence[Sequence[float]],
    gt_boxes: Sequence[Any],
    image_size: Sequence[int],
    *,
    iou_threshold: float = IOU_MATCH_THRESHOLD,
) -> AssociationResult:
    """Match detector pixel-corner boxes to GT normalized-centre boxes (§C).

    - Exactly 1 GT box → highest-IoU detection (if ≥ threshold).
    - ≥2 GT boxes → Hungarian maximizing total IoU (GRPH-07); no greedy path.
    - Accept pair iff IoU ≥ ``iou_threshold`` (default 0.5).
    """
    n_det = len(detections_bbox_px)
    n_gt = len(gt_boxes)
    if n_det == 0 and n_gt == 0:
        return AssociationResult(pairs=(), unmatched_detections=(), unmatched_gt=(), ious=())
    if n_gt == 0:
        return AssociationResult(
            pairs=(),
            unmatched_detections=tuple(range(n_det)),
            unmatched_gt=(),
            ious=(),
        )
    if n_det == 0:
        return AssociationResult(
            pairs=(),
            unmatched_detections=(),
            unmatched_gt=tuple(range(n_gt)),
            ious=(),
        )

    gt_px: list[list[float]] = []
    gt_names: list[str | None] = []
    for gt in gt_boxes:
        cx, cy, w, h, name = _gt_fields(gt)
        gt_px.append(
            gt_normalized_centre_to_pixel_corner(
                cx=cx, cy=cy, w=w, h=h, image_size=image_size
            )
        )
        gt_names.append(name)

    # Detector boxes are already pixel-corner — no centre→corner shift (§A0).
    iou_matrix = np.zeros((n_det, n_gt), dtype=np.float64)
    iou_audit: list[tuple[int, int, float]] = []
    for i in range(n_det):
        for j in range(n_gt):
            val = iou_pixel_corner(detections_bbox_px[i], gt_px[j])
            iou_matrix[i, j] = val
            iou_audit.append((i, j, val))

    candidate_pairs: list[tuple[int, int, float]] = []
    if n_gt == 1:
        # Exactly-1 GT: highest-IoU detection only.
        best_i = int(np.argmax(iou_matrix[:, 0]))
        best_iou = float(iou_matrix[best_i, 0])
        if best_iou >= iou_threshold:
            candidate_pairs.append((best_i, 0, best_iou))
    else:
        # ≥2 GT: Hungarian maximize total IoU (cost = -IoU). GRPH-07.
        row_ind, col_ind = linear_sum_assignment(-iou_matrix)
        for r, c in zip(row_ind, col_ind, strict=True):
            iou_val = float(iou_matrix[r, c])
            if iou_val >= iou_threshold:
                candidate_pairs.append((int(r), int(c), iou_val))

    matched_det = {p[0] for p in candidate_pairs}
    matched_gt = {p[1] for p in candidate_pairs}
    pairs = tuple(
        AssociationPair(det_index=di, gt_index=gi, iou=iou, name=gt_names[gi])
        for di, gi, iou in sorted(candidate_pairs, key=lambda t: (t[0], t[1]))
    )
    return AssociationResult(
        pairs=pairs,
        unmatched_detections=tuple(i for i in range(n_det) if i not in matched_det),
        unmatched_gt=tuple(j for j in range(n_gt) if j not in matched_gt),
        ious=tuple(sorted(iou_audit)),
    )


# ---------------------------------------------------------------------------
# §D — leave-one-out gallery (mean prototypes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchedFace:
    """A detection §C-matched to a GT box (probe candidate)."""

    media_id: int
    path: str
    box_index: int  # GT box index in the entry's face_boxes
    det_index: int
    embedding: tuple[float, ...]
    true_name: str | None  # None = stranger
    bbox_px: tuple[float, ...] = ()

    @property
    def fold_identity_key(self) -> str:
        return self.true_name if self.true_name is not None else STRANGER_SORT_KEY

    def embedding_array(self) -> np.ndarray:
        return np.asarray(self.embedding, dtype=np.float64)


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize; never silently returns a zero vector for empty input."""
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        raise ValueError("refusing to L2-normalize a zero vector (empty prototype)")
    return vec / norm


def mean_prototype(embeddings: Sequence[np.ndarray]) -> np.ndarray:
    """L2-normalized MEAN of embeddings (EMB-02 bake-off choice).

    Note: a medoid (most-central exemplar) is a common alternative that is more
    robust to outliers; this bake-off intentionally uses the mean for parity
    with typical face-recognition gallery construction.
    """
    if not embeddings:
        raise ValueError("mean_prototype requires ≥1 embedding (enrolled identity)")
    stacked = np.stack([np.asarray(e, dtype=np.float64) for e in embeddings], axis=0)
    return _l2_normalize(stacked.mean(axis=0))


def matched_named_by_identity(
    matched: Sequence[MatchedFace],
) -> dict[str, list[MatchedFace]]:
    """Group §C-matched faces with a non-None true_name by identity."""
    out: dict[str, list[MatchedFace]] = defaultdict(list)
    for face in matched:
        if face.true_name is not None:
            out[face.true_name].append(face)
    return dict(out)


def is_enrolled_for_probe(true_name: str | None, identity_counts: Mapping[str, int]) -> bool:
    """§D: identity X is enrolled for probe f iff X has ≥2 matched faces.

    Equivalently: LOO prototype_X is non-empty (at least one other face of X).
    Strangers are never enrolled. Single-face identities are not enrolled for
    their own face (excluded_single_face_recall).
    """
    if true_name is None:
        return False
    return identity_counts.get(true_name, 0) >= 2


def build_loo_gallery(
    probe: MatchedFace,
    by_identity: Mapping[str, Sequence[MatchedFace]],
) -> dict[str, np.ndarray]:
    """Build LOO gallery prototypes for scoring ``probe`` (§D).

    - prototype_X for probe of X = L2-mean of X's *other* matched faces
    - prototype_Y (Y≠X) = L2-mean of *all* of Y's matched faces
    - identity with only the probe face contributes no prototype_X
    - never enrolls bare GT boxes; never zero-vector normalizes empty sets
    """
    gallery: dict[str, np.ndarray] = {}
    for name, faces in by_identity.items():
        if probe.true_name is not None and name == probe.true_name:
            others = [
                f
                for f in faces
                if not (
                    f.media_id == probe.media_id
                    and f.box_index == probe.box_index
                    and f.det_index == probe.det_index
                )
            ]
            if not others:
                continue  # not enrolled — no prototype_X
            gallery[name] = mean_prototype([f.embedding_array() for f in others])
        else:
            if not faces:
                continue
            gallery[name] = mean_prototype([f.embedding_array() for f in faces])
    return gallery


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two vectors (assume already L2-normalized preferred)."""
    aa = np.asarray(a, dtype=np.float64)
    bb = np.asarray(b, dtype=np.float64)
    na = float(np.linalg.norm(aa))
    nb = float(np.linalg.norm(bb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(aa / na, bb / nb))


def argmax_gallery(
    embedding: np.ndarray,
    gallery: Mapping[str, np.ndarray],
) -> tuple[float, str | None]:
    """Return (s_max, name*) over gallery; empty gallery → (-inf, None)."""
    if not gallery:
        return float("-inf"), None
    best_s = float("-inf")
    best_name: str | None = None
    # Stable name order for determinism when similarities tie.
    for name in sorted(gallery.keys()):
        s = cosine_similarity(embedding, gallery[name])
        if s > best_s or (s == best_s and (best_name is None or name < best_name)):
            best_s = s
            best_name = name
    return best_s, best_name


# ---------------------------------------------------------------------------
# §E — binary open-set assignment, k-fold τ, pooled decisions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenSetCounts:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return 0.0 if denom == 0 else self.true_positives / denom

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return 0.0 if denom == 0 else self.true_positives / denom

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        denom = p + r
        return 0.0 if denom == 0 else 2.0 * p * r / denom


def open_set_counts_at_tau(
    *,
    probes: Sequence[MatchedFace],
    by_identity: Mapping[str, Sequence[MatchedFace]],
    identity_counts: Mapping[str, int],
    tau: float,
) -> OpenSetCounts:
    """Open-set TP/FP/FN at threshold τ (§E table with enrolled qualifier)."""
    tp = fp = fn = 0
    for probe in probes:
        gallery = build_loo_gallery(probe, by_identity)
        s_max, name_star = argmax_gallery(probe.embedding_array(), gallery)
        accept = name_star is not None and accepts(s_max, tau)
        enrolled = is_enrolled_for_probe(probe.true_name, identity_counts)

        if probe.true_name is None:
            # Stranger: accept → FP (false-accept); reject → TN (not in P/R).
            if accept:
                fp += 1
            continue

        if accept:
            if name_star == probe.true_name:
                tp += 1
            else:
                fp += 1
                if enrolled:
                    fn += 1
        else:
            if enrolled:
                fn += 1
    return OpenSetCounts(true_positives=tp, false_positives=fp, false_negatives=fn)


def _largest_contiguous_plateau_indices(values: Sequence[float], target: float) -> list[int]:
    """Indices of the longest contiguous run where values[i] == target.

    On a LENGTH TIE between two equal-length runs, keep the LATER (higher-index)
    run. Since ``TAU_GRID`` is ascending, higher index == larger τ, so this
    honors §E's "residual ties → the larger τ" ACROSS equal-length plateaus, not
    only within one (the ``>=`` — a strict ``>`` would keep the earliest /
    most-permissive plateau, the false-accept bias §E forbids).
    """
    best_run: list[int] = []
    current: list[int] = []
    for i, v in enumerate(values):
        if v == target:
            current.append(i)
        else:
            if len(current) >= len(best_run):
                best_run = current
            current = []
    if len(current) >= len(best_run):
        best_run = current
    return best_run


def select_tau_open_set_f1(
    *,
    probes: Sequence[MatchedFace],
    by_identity: Mapping[str, Sequence[MatchedFace]],
    identity_counts: Mapping[str, int],
    tau_grid: Sequence[float] = TAU_GRID,
) -> float:
    """τ = argmax open-set F1; tie-break = grid τ closest to mean of largest max-F1 plateau.

    Residual ties → larger τ. Empty probe set → mid-grid default (no F1 signal).
    """
    if not probes:
        return float(tau_grid[len(tau_grid) // 2])

    f1s: list[float] = []
    for tau in tau_grid:
        counts = open_set_counts_at_tau(
            probes=probes,
            by_identity=by_identity,
            identity_counts=identity_counts,
            tau=float(tau),
        )
        f1s.append(counts.f1)

    max_f1 = max(f1s)
    plateau = _largest_contiguous_plateau_indices(f1s, max_f1)
    if not plateau:
        return float(tau_grid[-1])
    plateau_taus = [float(tau_grid[i]) for i in plateau]
    target = sum(plateau_taus) / len(plateau_taus)
    # Closest to plateau mean; residual ties → larger τ.
    best_tau = plateau_taus[0]
    best_dist = abs(best_tau - target)
    for t in plateau_taus[1:]:
        dist = abs(t - target)
        if dist < best_dist or (dist == best_dist and t > best_tau):
            best_tau = t
            best_dist = dist
    return best_tau


@dataclass(frozen=True)
class FaceDecision:
    """Pooled per-fold held-out decision for one probe face (§E / §F)."""

    media_id: int
    path: str
    box_index: int
    det_index: int
    true_name: str | None
    decision: DecisionKind
    predicted_name: str | None  # name* when accept; None when reject
    s_max: float
    name_star: str | None
    tau_k: float
    fold: int
    enrolled: bool
    excluded_single_face_recall: bool


@dataclass(frozen=True)
class AssignmentResult:
    """Full §C–§E scoring result for one leg."""

    matched: tuple[MatchedFace, ...]
    decisions: tuple[FaceDecision, ...]  # pooled held-out; one per matched probe
    tau_k: tuple[float, ...]  # length effective_k
    tau_op: float  # median(τ_k); context + clustering cut only
    association_by_media: dict[int, AssociationResult] = field(default_factory=dict)
    false_detections: int = 0
    missed_gt: int = 0
    excluded_single_face_recall: tuple[MatchedFace, ...] = ()
    # AUDIT-01/02 (FIR5RR-04): the caller-requested K and the K actually used
    # after the subject-count clamp. When they differ, provenance surfaces must
    # disclose the clamp — a published "K-fold" rate silently run at a smaller
    # K misstates the protocol.
    requested_k: int = K_FOLDS
    effective_k: int = K_FOLDS
    # FIR5RR-07: provenance of the τ_k values (see TauFitStatus).
    tau_fit_status: TauFitStatus = "fitted"


def global_fold_ranks(
    matched: Sequence[MatchedFace],
    *,
    k_folds: int = K_FOLDS,
) -> list[int]:
    """Subject-disjoint fold assignment (CAL-07).

    Named identity X's faces all share one fold. Each stranger face is its own
    subject (keyed by media_id/box/det). **Named and stranger subjects share one
    joint rank space** (sorted: named names first, then stranger keys) so small
    strata do not collide every subject into fold 0 via independent counters
    (REF-27 / FIR5V11-03). Round-robin-by-face is intentionally *not* used —
    that would put the same identity into both fit and read folds for ``τ_k``.
    """
    if k_folds < 1:
        raise ValueError("k_folds must be ≥ 1")
    # Joint subject list: named identities (sort key = name) then strangers.
    named_ids = sorted({m.true_name for m in matched if m.true_name is not None})
    stranger_keys = sorted(
        {
            (m.media_id, m.box_index, m.det_index)
            for m in matched
            if m.true_name is None
        }
    )
    # Unified rank so Alice+stranger with K=2 land in distinct folds (not both 0).
    subjects: list[tuple[str, str | tuple[int, int, int]]] = [
        ("named", name) for name in named_ids
    ] + [("stranger", key) for key in stranger_keys]
    subject_to_fold = {subj: i % k_folds for i, subj in enumerate(subjects)}
    ranks: list[int] = []
    for m in matched:
        if m.true_name is not None:
            ranks.append(subject_to_fold[("named", m.true_name)])
        else:
            ranks.append(
                subject_to_fold[("stranger", (m.media_id, m.box_index, m.det_index))]
            )
    return ranks


def collect_matched_faces(
    run_items: Sequence[Mapping[str, Any]],
    gt_by_media: Mapping[int, Sequence[Any]],
) -> tuple[list[MatchedFace], dict[int, AssociationResult], int, int]:
    """§C associate every run item; collect matched probes (+ det/miss counts)."""
    matched: list[MatchedFace] = []
    associations: dict[int, AssociationResult] = {}
    false_det = 0
    missed = 0
    for item in run_items:
        media_id = int(item["media_id"])
        path = str(item.get("path", ""))
        image_size = item["image_size"]
        faces = item.get("faces") or []
        gt_boxes = list(gt_by_media.get(media_id, ()))
        det_bboxes = [f["bbox_px"] for f in faces]
        assoc = associate_detections(det_bboxes, gt_boxes, image_size)
        associations[media_id] = assoc
        false_det += len(assoc.unmatched_detections)
        missed += len(assoc.unmatched_gt)
        for pair in assoc.pairs:
            face = faces[pair.det_index]
            emb = tuple(float(v) for v in face["embedding"])
            matched.append(
                MatchedFace(
                    media_id=media_id,
                    path=path,
                    box_index=pair.gt_index,
                    det_index=pair.det_index,
                    embedding=emb,
                    true_name=pair.name,
                    bbox_px=tuple(float(v) for v in face["bbox_px"]),
                )
            )
    return matched, associations, false_det, missed


def _subject_count(matched: Sequence[MatchedFace]) -> int:
    """Named identities + per-face stranger subjects (fold-key atoms)."""
    named = {m.true_name for m in matched if m.true_name is not None}
    strangers = {
        (m.media_id, m.box_index, m.det_index) for m in matched if m.true_name is None
    }
    return len(named) + len(strangers)


def assign_open_set_kfold(
    matched: Sequence[MatchedFace],
    *,
    k_folds: int = K_FOLDS,
    tau_grid: Sequence[float] = TAU_GRID,
) -> AssignmentResult:
    """§E k-fold binary open-set: fit τ_k on other folds; pool held-out decisions.

    Fit-phase galleries/counts are restricted to **fit-fold identities** (CAL-07)
    so held subjects cannot leak into threshold selection. Read-phase LOO still
    uses the full matched corpus so every enrolled identity remains identifiable.

    Identification / unknown-rejection consume ``decisions`` — never re-score at τ_op.

    Empty-fit guard (REF-27 / FIR5V11-03): ``k_folds`` is clamped to the subject
    count so subject-disjoint assignment can leave a non-empty fit set for every
    fold that holds probes. A multi-subject empty fit is rejected (raises —
    undefined τ). A SINGLE-subject corpus cannot have a subject-disjoint fit
    set at all: it falls back to the mid-grid τ and is flagged via
    ``tau_fit_status="mid_grid_unfitted"`` so downstream report slices are
    forced DIRECTIONAL/non-gating (FIR5RR-07) — the fallback is disclosed,
    never silent.
    """
    if k_folds < 1:
        raise ValueError("k_folds must be ≥ 1")
    by_identity = matched_named_by_identity(matched)
    identity_counts = {name: len(faces) for name, faces in by_identity.items()}
    n_subjects = _subject_count(matched)
    # Clamp K so each subject can occupy a distinct fold when possible; prevents
    # K >> named-identity-count empty-fit coincidence on small strata.
    effective_k = max(1, min(int(k_folds), n_subjects)) if matched else 1
    folds = global_fold_ranks(matched, k_folds=effective_k)

    # Per-fold τ_k from the other K−1 folds' probes — fit identities only.
    tau_ks: list[float] = []
    mid_grid = float(tau_grid[len(tau_grid) // 2])
    used_mid_grid = False
    for k in range(effective_k):
        train = [m for m, f in zip(matched, folds, strict=True) if f != k]
        read_has_probes = any(f == k for f in folds)
        if matched and not train and read_has_probes:
            # With joint subject ranking + K clamp this only arises for a single
            # subject (effective_k==1). Multi-subject empty fit is a hard error.
            if effective_k > 1 or n_subjects > 1:
                raise ValueError(
                    f"empty fit fold for τ selection: all {len(matched)} probes "
                    f"are in fold {k} (effective_k={effective_k}, "
                    f"requested_k={k_folds}, n_subjects={n_subjects}); add "
                    f"subject-disjoint identities so every τ_k has a non-empty fit set"
                )
            tau_ks.append(mid_grid)
            used_mid_grid = True
            continue
        if not train:
            # Empty read fold with empty train (no matched probes at all).
            tau_ks.append(mid_grid)
            used_mid_grid = True
            continue
        train_by_id = matched_named_by_identity(train)
        train_counts = {name: len(faces) for name, faces in train_by_id.items()}
        tau_ks.append(
            select_tau_open_set_f1(
                probes=train,
                by_identity=train_by_id,
                identity_counts=train_counts,
                tau_grid=tau_grid,
            )
        )

    decisions: list[FaceDecision] = []
    excluded: list[MatchedFace] = []
    for probe, fold in zip(matched, folds, strict=True):
        tau = tau_ks[fold]
        gallery = build_loo_gallery(probe, by_identity)
        s_max, name_star = argmax_gallery(probe.embedding_array(), gallery)
        accept = name_star is not None and accepts(s_max, tau)
        enrolled = is_enrolled_for_probe(probe.true_name, identity_counts)
        single_face_excl = (
            probe.true_name is not None and identity_counts.get(probe.true_name, 0) == 1
        )
        if single_face_excl:
            excluded.append(probe)
        decisions.append(
            FaceDecision(
                media_id=probe.media_id,
                path=probe.path,
                box_index=probe.box_index,
                det_index=probe.det_index,
                true_name=probe.true_name,
                decision="accept" if accept else "reject",
                predicted_name=name_star if accept else None,
                s_max=float(s_max) if s_max != float("-inf") else float("-inf"),
                name_star=name_star,
                tau_k=float(tau),
                fold=int(fold),
                enrolled=enrolled,
                excluded_single_face_recall=single_face_excl,
            )
        )

    # Stable order for determinism: sort decisions like the fold key.
    decisions_sorted = tuple(
        sorted(
            decisions,
            key=lambda d: (
                d.true_name if d.true_name is not None else STRANGER_SORT_KEY,
                d.media_id,
                d.box_index,
                d.det_index,
            ),
        )
    )
    tau_op = float(median(tau_ks)) if tau_ks else float(tau_grid[len(tau_grid) // 2])
    return AssignmentResult(
        matched=tuple(matched),
        decisions=decisions_sorted,
        tau_k=tuple(tau_ks),
        tau_op=tau_op,
        excluded_single_face_recall=tuple(excluded),
        requested_k=int(k_folds),
        effective_k=int(effective_k),
        tau_fit_status="mid_grid_unfitted" if used_mid_grid else "fitted",
    )


def score_face_assignment(
    run_items: Sequence[Mapping[str, Any]],
    gt_by_media: Mapping[int, Sequence[Any]],
    *,
    k_folds: int = K_FOLDS,
    tau_grid: Sequence[float] = TAU_GRID,
) -> AssignmentResult:
    """End-to-end §C association + §E k-fold assignment for one leg."""
    matched, associations, false_det, missed = collect_matched_faces(run_items, gt_by_media)
    result = assign_open_set_kfold(matched, k_folds=k_folds, tau_grid=tau_grid)
    return AssignmentResult(
        matched=result.matched,
        decisions=result.decisions,
        tau_k=result.tau_k,
        tau_op=result.tau_op,
        association_by_media=associations,
        false_detections=false_det,
        missed_gt=missed,
        excluded_single_face_recall=result.excluded_single_face_recall,
        requested_k=result.requested_k,
        effective_k=result.effective_k,
        tau_fit_status=result.tau_fit_status,
    )


# ---------------------------------------------------------------------------
# §F similar_people — per-photo Hungarian (DIRECTIONAL)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimilarPeopleAssignment:
    media_id: int
    path: str
    face_decisions: tuple[FaceDecision, ...]  # re-assigned; one per probe on photo


def similar_people_hungarian(
    *,
    probes_on_photo: Sequence[MatchedFace],
    by_identity: Mapping[str, Sequence[MatchedFace]],
    identity_counts: Mapping[str, int],
    tau_by_probe_key: Mapping[tuple[int, int, int], float],
) -> SimilarPeopleAssignment:
    """Per-photo one-to-one name assignment (Hungarian, maximize similarity).

    Distinct from §C (det↔GT) and from product Hungarian. Each face rejects if
    its assigned similarity is below its pooled per-fold τ_k. GRPH-07.
    """
    if not probes_on_photo:
        return SimilarPeopleAssignment(media_id=-1, path="", face_decisions=())

    media_id = probes_on_photo[0].media_id
    path = probes_on_photo[0].path

    # Gallery names present with ≥1 matched face (full prototypes; photo-local re-assign).
    # For each probe use LOO-aware exclusion only for its own identity row.
    # Build a shared name list; per-face LOO means rows differ — use full prototypes
    # of identities that are enrolled (≥2 faces) OR have ≥1 face when scoring strangers,
    # and apply LOO by zeroing self-contribution via per-face gallery rebuild.
    # Spec: face×gallery cosine matrix — gallery = enrolled roster identities.
    gallery_names = sorted(name for name, faces in by_identity.items() if len(faces) >= 1)
    n_faces = len(probes_on_photo)
    n_names = len(gallery_names)

    if n_names == 0:
        # No gallery → all reject.
        decisions = []
        for p in probes_on_photo:
            key = (p.media_id, p.box_index, p.det_index)
            tau = float(tau_by_probe_key[key])
            enrolled = is_enrolled_for_probe(p.true_name, identity_counts)
            decisions.append(
                FaceDecision(
                    media_id=p.media_id,
                    path=p.path,
                    box_index=p.box_index,
                    det_index=p.det_index,
                    true_name=p.true_name,
                    decision="reject",
                    predicted_name=None,
                    s_max=float("-inf"),
                    name_star=None,
                    tau_k=tau,
                    fold=-1,
                    enrolled=enrolled,
                    excluded_single_face_recall=(
                        p.true_name is not None and identity_counts.get(p.true_name, 0) == 1
                    ),
                )
            )
        return SimilarPeopleAssignment(
            media_id=media_id,
            path=path,
            face_decisions=tuple(decisions),
        )

    # Cost matrix: maximize similarity → minimize negative sim.
    # Rectangular Hungarian supports n_faces != n_names.
    sim = np.full((n_faces, n_names), -1.0, dtype=np.float64)
    for i, probe in enumerate(probes_on_photo):
        gallery = build_loo_gallery(probe, by_identity)
        for j, name in enumerate(gallery_names):
            if name in gallery:
                sim[i, j] = cosine_similarity(probe.embedding_array(), gallery[name])

    row_ind, col_ind = linear_sum_assignment(-sim)
    assigned_name: dict[int, tuple[str, float]] = {}
    for r, c in zip(row_ind, col_ind, strict=True):
        if r < n_faces and c < n_names:
            assigned_name[int(r)] = (gallery_names[int(c)], float(sim[r, c]))

    decisions = []
    for i, probe in enumerate(probes_on_photo):
        key = (probe.media_id, probe.box_index, probe.det_index)
        tau = float(tau_by_probe_key[key])
        enrolled = is_enrolled_for_probe(probe.true_name, identity_counts)
        if i in assigned_name:
            name_star, s = assigned_name[i]
            accept = accepts(s, tau)
        else:
            name_star, s = None, float("-inf")
            accept = False
        decisions.append(
            FaceDecision(
                media_id=probe.media_id,
                path=probe.path,
                box_index=probe.box_index,
                det_index=probe.det_index,
                true_name=probe.true_name,
                decision="accept" if accept else "reject",
                predicted_name=name_star if accept else None,
                s_max=s,
                name_star=name_star,
                tau_k=tau,
                fold=-1,
                enrolled=enrolled,
                excluded_single_face_recall=(
                    probe.true_name is not None and identity_counts.get(probe.true_name, 0) == 1
                ),
            )
        )
    return SimilarPeopleAssignment(
        media_id=media_id,
        path=path,
        face_decisions=tuple(
            sorted(decisions, key=lambda d: (d.box_index, d.det_index))
        ),
    )


def score_similar_people(
    matched: Sequence[MatchedFace],
    decisions: Sequence[FaceDecision],
    *,
    min_identities_on_photo: int = 2,
) -> tuple[SimilarPeopleAssignment, ...]:
    """Run §F similar_people on every photo with ≥2 distinct named GT identities."""
    tau_by_key = {
        (d.media_id, d.box_index, d.det_index): d.tau_k for d in decisions
    }
    by_identity = matched_named_by_identity(matched)
    identity_counts = {name: len(faces) for name, faces in by_identity.items()}

    by_media: dict[int, list[MatchedFace]] = defaultdict(list)
    for face in matched:
        by_media[face.media_id].append(face)

    results: list[SimilarPeopleAssignment] = []
    for media_id in sorted(by_media.keys()):
        faces = by_media[media_id]
        named = {f.true_name for f in faces if f.true_name is not None}
        if len(named) < min_identities_on_photo:
            continue
        results.append(
            similar_people_hungarian(
                probes_on_photo=faces,
                by_identity=by_identity,
                identity_counts=identity_counts,
                tau_by_probe_key=tau_by_key,
            )
        )
    return tuple(results)


__all__ = [
    "IOU_MATCH_THRESHOLD",
    "K_FOLDS",
    "TAU_GRID",
    "STRANGER_SORT_KEY",
    "TauFitStatus",
    "FOLD_MEDIA_CORESIDENCY_DISCLOSURE",
    "AssociationPair",
    "AssociationResult",
    "MatchedFace",
    "OpenSetCounts",
    "FaceDecision",
    "AssignmentResult",
    "SimilarPeopleAssignment",
    "gt_normalized_centre_to_pixel_corner",
    "iou_pixel_corner",
    "associate_detections",
    "mean_prototype",
    "matched_named_by_identity",
    "is_enrolled_for_probe",
    "build_loo_gallery",
    "cosine_similarity",
    "argmax_gallery",
    "open_set_counts_at_tau",
    "select_tau_open_set_f1",
    "global_fold_ranks",
    "collect_matched_faces",
    "assign_open_set_kfold",
    "score_face_assignment",
    "similar_people_hungarian",
    "score_similar_people",
]
