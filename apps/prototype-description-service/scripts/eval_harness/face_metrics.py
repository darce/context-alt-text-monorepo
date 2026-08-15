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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .manifest import AnnotationMode, ManifestError, parse_annotation_mode

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
SAMPLING_FRAME_FACE_ID = (
    "named_matched_probes_pooled_kfold_decisions: precision over accept/"
    "confusion; recall over enrolled (≥2 matched faces) only; detection "
    "misses excluded from FN (EVAL-16)"
)
SAMPLING_FRAME_UNKNOWN_REJECTION = (
    "stranger_probes_full_corpus_including_unpublishable: correct_reject="
    "decision=reject; false_accept=decision=accept"
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


@dataclass(frozen=True)
class ImageDetection:
    image: str
    pred_faces: int
    labeled_faces: int


@dataclass(frozen=True)
class ImageIdentities:
    image: str
    predicted: Sequence[str]
    labeled: Sequence[str]
    recognition_enabled: bool = True
    stranger_faces: int = 0


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

    Refuses unless the resolved mode *is* ``AnnotationMode.EXHAUSTIVE``.
    Omission, null, empty, unknown, and ``roster_only`` all raise
    ``ManifestError`` with a named invariant — there is no permissive default.
    """
    mode = parse_annotation_mode(annotation_mode)
    if mode is None:
        raise ManifestError(
            "detection_pr requires annotation_mode; omission is not exhaustive",
            invariant="detection_requires_annotation_mode",
        )
    if mode is not AnnotationMode.EXHAUSTIVE:
        raise ManifestError(
            "detection_pr refuses roster_only manifests; unlabeled non-roster "
            "faces would be scored as false positives",
            invariant="detection_refuses_roster_only",
        )
    tp = fp = fn = 0
    for item in items:
        tp += min(item.pred_faces, item.labeled_faces)
        fp += max(item.pred_faces - item.labeled_faces, 0)
        fn += max(item.labeled_faces - item.pred_faces, 0)
    return PrResult(true_positives=tp, false_positives=fp, false_negatives=fn)


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
# FIR-5 S3 §F — face-level identification over pooled decisions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FaceLevelIdPr:
    """Face-level identification P/R (0/0 → 0). Coupled to detection recall.

    Report id-recall *alongside* detection-recall: weak detection inflates
    id-recall on the easy detected subset (coupling caveat, §F / EVAL-16).
    ``detection_recall_coupling_flag`` is **computed** from required missed GT /
    unmatched detection counts — never a fail-open default (REF-27).
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
    - single-face confusion → FP only (excluded_single_face_recall)
    Precision/Recall use 0/0 → 0.

    ``missed_gt`` and ``unmatched_detections`` are **required** (no fail-open
    default of 0 — REF-27 / FIR5V11-05). Pass counts scoped to the same
    sampling frame as ``decisions`` (e.g. celebs01-only for headline).
    ``detection_recall_coupling_flag`` is True when either count is > 0
    (id-P/R denominators exclude detection failures — EVAL-16).
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
        predicted = (
            d.predicted_name if not isinstance(d, Mapping) else d.get("predicted_name")
        )
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
        # derived from fabricated zeros (FIR5RR-05).
        coupling = detection_coupling
    else:
        if detection_coupling is not None:
            raise ValueError(
                "detection_coupling override is only valid when missed_gt and "
                "unmatched_detections are both None (not-attributed frame); "
                "with real counts the flag is computed, not asserted"
            )
        coupling = (mg or 0) > 0 or (ud or 0) > 0
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

    @property
    def rate(self) -> float:
        """correct_rejects / (correct_rejects + false_accepts); 0/0 → 0."""
        return _ratio_zero(self.correct_rejects, self.correct_rejects + self.false_accepts)

    @property
    def meets_floor(self) -> bool:
        return self.n >= self.n_floor


def face_unknown_rejection(decisions: Sequence[Any]) -> UnknownRejectionResult:
    """Face-level unknown-rejection over stranger probes (pooled decisions).

    correct-reject = reject; false-accept = accept any name.
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
    n = correct + false_accept
    return UnknownRejectionResult(
        correct_rejects=correct,
        false_accepts=false_accept,
        n=n,
        sampling_frame=SAMPLING_FRAME_UNKNOWN_REJECTION,
        error_target=UNKNOWN_REJECTION_ERROR_TARGET,
        rate_numerator=correct,
        rate_denominator=n,
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
        clustering_metrics_at_cut(embeddings, identity_labels, d_cut, pair_floor=pair_floor)
        for d_cut in cuts
    )
    headline = clustering_metrics_at_cut(
        embeddings,
        identity_labels,
        round(1.0 - float(tau_op), 4),
        pair_floor=pair_floor,
    )
    return sweep, headline
