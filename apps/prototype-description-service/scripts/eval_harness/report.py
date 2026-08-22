"""Score a run record and build JSON + markdown reports (regression-harness pattern).

Split Phase: the fetch phase writes a run record (raw remote responses +
provenance); this module is the pure score phase — re-runnable offline,
bit-identical for unchanged inputs. The JSON artifact is an additive extension
of the E19-1 benchmark schema (``metrics``/``faces`` sections).

The ignore-list (a JSON file persisted next to the reports) splits triaged
wrong-name pairs into ``ignored_wrong_names`` for operator presentation only.
The wrong-name floor gate still counts **all** observed wrong names (live +
ignored) so an operator-supplied side file cannot zero out a hard gate (F1-5).
"""

from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from .caption_metrics import (
    LONG_SENTENCE_BAND,
    SHORT_SENTENCE_BAND,
    CaptionScores,
    aggregate_gated_scores,
    fabricated_fact_rate,
    fabrication_by_kind,
    insertion_rate,
    name_precision,
    score_caption,
    score_hallucination,
    wrong_name_image_rate,
)
from .face_assignment import (
    FOLD_MEDIA_CORESIDENCY_DISCLOSURE,
    TAU_GRID,
    associate_detections,
    gt_box_name,
    score_face_assignment,
)
from .face_metrics import (
    CLUSTER_PAIR_FLOOR,
    DETECTION_EMPTY_OBSERVATIONS_INVARIANT,
    DETECTION_UNCOVERED_FACE_COUNT_INVARIANT,
    IDENTIFICATION_EMPTY_OBSERVATIONS_INVARIANT,
    POSITIONAL_EVAL_NOT_EVALUABLE,
    SAMPLING_FRAME_CLUSTERING,
    SAMPLING_FRAME_FACE_ID,
    SAMPLING_FRAME_UNKNOWN_REJECTION,
    UNKNOWN_REJECTION_ERROR_TARGET,
    UNKNOWN_REJECTION_N_FLOOR,
    IDENTIFICATION_UNBOXED_INVARIANT,
    ImageDetection,
    ImageIdentities,
    clustering_sweep,
    demographic_rollup,
    detection_pr,
    face_identification_pr,
    face_unknown_rejection,
    identification_pr,
    labeled_order,
    named_box_name,
    positional_identification,
    predicted_names_for_positional,
    require_boxed_identification_gt,
    require_exhaustive_box_coverage,
)
from .manifest import (
    AnnotationMode,
    ManifestError,
    Provenance,
    ProvenanceSource,
    ReferenceFact,
    ScoreInvariant,
    SliceTag,
    SpatialFact,
    parse_annotation_mode,
    refusal_explanation,
)
from .placement_metrics import PlacementScores, placement_accuracy, score_placement
from .schema import SCHEMA, DocKind
from .synthetic_occlusion import (
    ELIGIBLE_PAIR_FLOOR,
    SAMPLING_FRAME_OCCLUSION_RECOVERY,
    SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES,
    assert_walk_stability,
    score_occlusion_accuracy,
)

# Protocol / canon pin (REF-25..28 / FIR5V11-06). Code SHAs alone do not name
# the evaluation protocol version the rates were computed under.
# FIR5RR-10: the pin is INTENTIONAL AND FROZEN for the FIR-5 protocol — it is
# bumped only when the protocol itself is re-authored (a new canon revision
# that changes measured semantics), never as a routine chore alongside code
# changes. A drifting pin would silently relabel rates computed under the
# old protocol.
FACE_BAKEOFF_CANON_VERSION = "0.11.0"
FACE_BAKEOFF_PROTOCOL_ID = "fir-5-face-bakeoff-v0.11.0"

# Release-surface label (RLSE-11): gate_proposal is never a release artifact.
GATE_PROPOSAL_RELEASE_SURFACE = "proposal_only_not_release"

# roster_only is more restrictive: it can only narrow an exhaustive stamp.
_MODE_RESTRICTIVENESS = {
    AnnotationMode.EXHAUSTIVE: 0,
    AnnotationMode.ROSTER_ONLY: 1,
}
if frozenset(_MODE_RESTRICTIVENESS) != frozenset(AnnotationMode):
    raise RuntimeError(
        "_MODE_RESTRICTIVENESS keys drifted from AnnotationMode: "
        f"table={sorted(member.value for member in _MODE_RESTRICTIVENESS)} "
        f"enum={sorted(member.value for member in AnnotationMode)}"
    )


def _mode_restrictiveness(mode: AnnotationMode) -> int:
    """Lattice rank for most-restrictive-wins. Unknown tokens refuse typed."""
    rank = _MODE_RESTRICTIVENESS.get(mode)
    if rank is None:
        raise ManifestError(
            f"unrecognised annotation_mode {mode!r}; "
            f"expected one of {[member.value for member in AnnotationMode]}",
            invariant=ScoreInvariant.DETECTION_UNRECOGNISED_ANNOTATION_MODE,
        )
    return rank


def _invariant_is(actual: object, *members: ScoreInvariant) -> bool:
    """Identity match against canonical ScoreInvariant members (S2R5-08)."""
    return any(actual is member for member in members)

# Aliases for the two historical sentences. Markdown looks up by the fired
# invariant via refusal_explanation — these names are not a default reason.
DETECTION_REFUSED_EXPLANATION = refusal_explanation(
    ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
)
IDENTIFICATION_REFUSED_EXPLANATION = refusal_explanation(
    ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS
)

# Bake-off protocol posture disclosed on every scored face artifact (FIR5RC-07).
# Measured protocol changes (weighted prototypes, ambiguity margin, matched
# non-mate impostors) are FIR-6 S4/S5-owned; FIR-5 owns honest disclosure.
FACE_BAKEOFF_PROTOCOL_DISCLOSURES: tuple[str, ...] = (
    "mean_prototype is an unweighted raw mean — one blurred face moves the "
    "identity centroid (EMB-02); weighted/medoid prototypes are FIR-6-owned",
    "open-set accept is raw cosine vs τ with no ambiguity/margin penalty "
    "(EMB-09); product ternary accept|suggest|reject is FIR-6-owned",
    "impostors are pooled zero-effort strangers rather than matched non-mates (CAL-04 posture declared in FIR-6 plan)",
    "pooled decisions mix heterogeneous per-fold τ_k (subject-disjoint folds; "
    "fit galleries restricted to fit identities — CAL-07)",
    "identification P/R runs only over §C-matched named decisions; missed "
    "detections and unmatched faces are excluded from FN (EVAL-16); stranger "
    "false-accepts live only in unknown-rejection (EVAL-18)",
    # IDX-01/07/11 deferred design (disclosure now; measurement later).
    "exact-vs-index separation of concerns and contender-set retrieval design "
    "are S4/S5 measurement-time items (IDX-01/07/11) — not measured here",
    # FIR5RR-13: unknown-rejection error target assumes independent trials.
    "unknown-rejection trials are not independent — stranger probes cluster "
    "within images and within individuals, so the Wilson error target's "
    "nominal n overstates the effective sample size (n_floor=43 kept; "
    "dependence disclosed on the slice's error_target)",
    # FIR5RR-15: fit-vs-read gallery cardinality asymmetry.
    "fit-phase galleries are restricted to fit-fold identities (CAL-07) while "
    "read-phase LOO galleries span the full matched corpus — τ_k is selected "
    "against a lower-cardinality gallery than the one held-out probes are "
    "read against, so read-time argmax competition is harder than fit-time",
    # FIR5CR-06: fold protocol — single-sourced from face_assignment.
    FOLD_MEDIA_CORESIDENCY_DISCLOSURE,
    *SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES,
)

# Sampling-frame registry referenced from provenance (AUDIT-01 / REF-25..28).
FACE_BAKEOFF_SAMPLING_FRAMES: dict[str, str] = {
    "headline_identification": (
        "celebs01_named_matched_probes (provenance.source==CELEB); "
        + SAMPLING_FRAME_FACE_ID
        # FIR5RR-12: error/missing run-record items never reach assignment —
        # their media contribute nothing to these numerators/denominators and
        # are surfaced in `failures` (and, when celebs01, in the headline
        # association provenance notes).
        + "; error-item media excluded from scoring (listed in failures)"
    ),
    "full_corpus_identification": "full_corpus_" + SAMPLING_FRAME_FACE_ID,
    "unknown_rejection": SAMPLING_FRAME_UNKNOWN_REJECTION,
    "occlusion_recovery": SAMPLING_FRAME_OCCLUSION_RECOVERY,
    "clustering": SAMPLING_FRAME_CLUSTERING,
    # VLM6-R2-C-02: detection P/R population (named + anonymous GT boxes).
    # Same string shape as other FACE_BAKEOFF_SAMPLING_FRAMES entries.
    # wG2 / wH1: geometry-incomplete GT (null/invalid y) are excluded from
    # spatial association and are NOT detector FNs — the honest identity is
    # tp+fn+geometry_incomplete_gt = n_gt that entered association (EVAL-03).
    "detection": (
        "all_gt_boxes_on_scoreable_media_via_association: named and anonymous "
        "GT share one population (HARM-01 / EVAL-16); TP=IoU-matched pairs; "
        "FN=unmatched complete GT (named missed_gt + missed_stranger_gt); "
        "FP=unmatched detections; geometry_incomplete_gt = GT boxes excluded "
        "from IoU (null/invalid centre-y; not detector FN); "
        "tp+fn+geometry_incomplete_gt equals GT boxes that reached association; "
        "association_complete=false when geometry_incomplete_gt>0; "
        "error-item media excluded from association (listed in failures)"
    ),
}

EVAL_MODES = ("standard", "context_distractor", "name_ablation")

# ALTQ-1 v3 three-surface: the title contract band (3-8 words, findings-derived).
TITLE_WORD_BAND = (3, 8)


class Audience(StrEnum):
    """Who may receive the scored report artifact.

    PUBLIC is hub-safe: only publishable corpus items. LOCAL is the full
    operator view and remains the default for offline triage.
    """

    PUBLIC = "public"
    LOCAL = "local"


class IdentityOrdering(StrEnum):
    """Identity L→R ordering quality (sr-007; VLM6-RH-06).

    Lives here, not in ``cli``: ``report`` is the consumer, and ``report`` must
    not import ``cli`` (VLM6-RH-07). ``cli`` re-exports it for the producer side.
    Never compare against raw ``"positional"`` / ``"degraded"`` literals — the
    token ``degraded`` is also an unrelated describe-route status, so an untyped
    literal collides across two domains and a typo silently takes neither branch.
    """

    POSITIONAL = "positional"
    DEGRADED = "degraded"


class ScoreVerdict(StrEnum):
    """Machine-readable pass/fail for a scored caption+face report (VLM-6 S2A).

    ``pass_ungated`` is reserved for ``--rubric-gate skip`` runs that clear every
    other exit gate: the artifact must not be readable as a gated pass (F1d-1).

    ``not_ready`` is reserved for runs where a scored category has sampling
    probability π=0 (no measurable claim units) — readiness is the weakest
    category (EVAL-23), so this is never adoption-eligible and never collides
    with a gated ``pass`` (VLM6-A-05 / VLM6-B-07 / AUDIT-07).

    ``non_comparable`` is reserved for archival manifest-relabel (VLM6-F-03 /
    EVAL-13): ``compare`` rejects it; it is never an adoption-eligible pass
    (S2-09 / sr-007 — single status vocabulary).
    """

    PASS = "pass"
    FAIL = "fail"
    PASS_UNGATED = "pass_ungated"
    NOT_READY = "not_ready"
    NON_COMPARABLE = "non_comparable"


# Floor for faces.identification wrong-name rate over scored images.
# WHY 0.0: attaching a hallucinated human name to a photograph is the one
# failure mode worse than placeholder text. Zero tolerance — any wrong-name
# assertion on a scored image fails the scored verdict and the score CLI gate.
WRONG_NAME_RATE_FLOOR = 0.0

# S2-02 quality floors — named policy constants (sr-007), not magic numbers.
# RV1-04 / EVAL-04: threshold *bands*, not IEEE corners. Pre-fix floors of
# 0.0 / 1.0 let position_accuracy=0.0001 and fabricated_fact_rate=0.9999 pass.
#
# Named frame for 0.5 (VLM6-R2-G-06 / RV1-04): binary chance on a two-way claim.
# Position (L→R) and placement (spatial claim correct/incorrect) are binary once
# a claim is scored. accuracy ≤ 0.5 means at-or-below coin-flip — measured-and-bad
# for adoption, not a working model. Comparison is `<=` so the floor itself fails
# (chance is not a pass). This is *not* a 5% false-pass sizing and is *not* the
# worked example of "< 0.05" that motivated IEEE-corner rejection — that example
# only showed why a floor of 0.0 was vacuous; the chosen magnitude is chance.
#
# Joint blast radius with the CLI quality-floor hard exit (fx4 / RV1-01): when
# compared_images>0 or placement.claims>0 and accuracy ≤ 0.5, score stamps
# verdict=fail *and* the CLI exits non-zero. Floors are dormant when the slice
# is unmeasured (compared=0 / claims=0 / accuracy=None) — current S2A bake-off
# anchors in docs/tasks/vlm/bakeoff-results/ report position_accuracy=None and
# placement.claims=0, so the 0.5 floor does not fire on those artifacts.
# - fabricated_fact: fail when rate ≥ 0.5 — majority of traps firing is
#   measured-and-bad (ceiling was 1.0 = exact all-traps-fired only).
# Floor breach is FAIL (measured and bad), never not_ready (not measured).
POSITION_ACCURACY_FLOOR = 0.5  # fail when position_accuracy <= floor
PLACEMENT_ACCURACY_FLOOR = 0.5  # fail when placement.accuracy <= floor
FABRICATED_FACT_RATE_CEILING = 0.5  # fail when fabricated_fact_rate >= ceiling

# S2-05 sample-size floor: undersized corpora cannot certify adoption-shaped pass.
# not_ready (insufficient sample), not fail. Named constant (sr-007).
#
# Honesty (VLM6-R2-A-03 / RV1-03): n=5 is an *operational* minimum so sparse
# corpora cannot certify adoption-shaped pass — not a 5% false-pass bound under
# a realistic per-image clean probability. Arithmetic that must not be confused:
# - Null coin-flip all-correct: P(5 clean | p=0.5) = 0.5^5 = 0.03125. That is
#   "five fair coins all heads", not "this gate's false-pass rate".
# - Realistic high-quality null: P(5 clean | p_ok=0.95) = 0.95^5 ≈ 0.774 — far
#   above 0.05. For 0.95^n < 0.05 you need n ≈ 59 (Wilson / Golden-100 territory).
# Keep n=5 as the score-verdict floor (sr-001: do not lower it); sizing for a
# 5% false-pass under p_ok≈0.95 is a different harness (compare / Golden-100).
# Enforced inside score_vacuous_category_labels so score and compare cannot
# diverge (RV1-02).
SCORE_PASS_MIN_SCORED_IMAGES = 5


class ReportError(Exception):
    """The run record cannot be scored: wrong document kind, unknown schema, or a
    run-record item whose media_id is absent from the score-time manifest."""

    def __init__(self, message: str, *, invariant: str | None = None) -> None:
        super().__init__(message)
        self.invariant = invariant


class RosterEpoch(StrEnum):
    """Roster-spelling epoch. PRIV-1 respelt names; a Δ across epochs is not a Δ."""

    PRE_PRIV1 = "pre-priv1"
    POST_PRIV1 = "post-priv1"


DELTA_REFUSES_STRADDLED_STAMPS = "delta_refuses_straddled_stamps"

# Caption aggregates surfaced in an EVAL-01 Δ. Counts stay counts; rates stay rates.
_CAPTION_DELTA_KEYS = (
    "insertion_rate",
    "name_precision",
    "wrong_name_image_rate",
    "must_right_failed_images",
    "must_right_defined_images",
    "easy_wrong_defined_images",
    "policy_violations",
    "wrong_name_images",
    "mean_gated_score",
)


# PUBLIC provenance is fail-closed: only these keys may leave the render boundary
# (VLM6-R3-01 / VLM6-R4-07). Deny-lists leak on schema growth; an allow-list drops
# unknown keys (tenant_id, images_dir, weave_bench_source, base_url, cache_dir,
# operator_note, run_record_path, …) by default.
# Nested ``model`` is path-redacted separately so absolute GGUF paths collapse.
# Caption *and* face PUBLIC paths share this set (VLM6-R2-A-02 / rg-015) — do not
# fork a face-only allow-list; add face-safe protocol keys here with a comment.
_PUBLIC_PROVENANCE_ALLOW_FIELDS: frozenset[str] = frozenset(
    {
        "head_sha",
        "manifest_sha256",
        "score_manifest_sha256",
        "manifest_matches_fetch",
        "roster_epoch",
        "started_at",
        "eval_mode",
        "model_versions",
        "model",
        "prompt_variant",
        "two_pass",
        "dual_length",
        "face_gate",
        # Face-bakeoff protocol aggregates (no operator paths / free-text).
        "zero_box_corpus",
        "total_gt_boxes",
        "canon_version",
        "protocol_id",
        "k_folds",
        "tau_fit_status",
        "sampling_frames",
        # RF-15: operator-facing sample-size caveat (not a gate change).
        "low_sample_warning",
        "quality_floor_caveat",
    }
)

# Closed enum for face tau_fit_status (RB-06 fail-closed on allow-listed free text).
_TAU_FIT_STATUS_PUBLIC_VALUES: frozenset[str] = frozenset(
    {"fitted", "mid_grid_unfitted", "error"}
)

# Minimum length for path-basename stems considered as identity scrub targets
# (RF-13: short stems like "al" / "img" over-scrub unrelated free text).
_FACE_PATH_STEM_SCRUB_MIN_LEN = 8

# Absolute / home-path shapes in free text (RB-03) — not key-name gated.
_OPERATOR_PATH_IN_TEXT_RE = re.compile(
    r"(?:"
    r"/(?:home|Users|var|tmp|opt|private|ops|root|usr|etc|data|mnt)(?:/[\w.\-@+]*)*"
    r"|file://[^\s\"'`]+"
    r"|[A-Za-z]:\\[^\s\"'`]+"
    r")"
)

# PUBLIC per-image is fail-closed allow-list (VLM6-A-01 / rg-015). Name-bearing
# detail lists (inserted_identities, missing_identities, must_right_failures,
# hallucinated_names, wrong_name_hits, …) and any future name-bearing key are
# excluded by default — deny-lists leak on schema growth.
#
# Free-text keys admitted here are NOT a redaction boundary by themselves (S2-03):
# every admitted free-text value is scrubbed via ``_public_free_text_value`` before
# emission. Adding a free-text key without scrubbing is a contract bug.
_PUBLIC_PER_IMAGE_ALLOW_FIELDS: frozenset[str] = frozenset(
    {
        "path",
        "media_id",
        "gated_score",
        "policy_violation",
        "fkre",
        "repetition_ratio",
        "tag_coverage",
        "first_sentence_gist_ok",
        "meta_framing_hits",
        "context_duplication_ratio",
        "sentence_count",
        "name_front_loaded",
        "cache_hit",
        "short_error",
        "placement",
        "hallucination",
        "long",
    }
)
_PUBLIC_PER_IMAGE_FREE_TEXT_FIELDS: frozenset[str] = frozenset({"path", "short_error"})
# Failures previously passed whole records with no allow-list (S2-03 leak).
_PUBLIC_FAILURE_ALLOW_FIELDS: frozenset[str] = frozenset({"media_id", "path", "error"})
_PUBLIC_FAILURE_FREE_TEXT_FIELDS: frozenset[str] = frozenset({"path", "error"})
# Model weights may keep basename; media/operator paths must not (S2-04).
_PUBLIC_MODEL_PATH_SUFFIXES: tuple[str, ...] = (
    ".gguf",
    ".bin",
    ".safetensors",
    ".pt",
    ".onnx",
    ".ckpt",
)
_PUBLIC_PER_IMAGE_LONG_ALLOW_FIELDS: frozenset[str] = frozenset(
    {
        "gated_score",
        "policy_violation",
        "meta_framing_hits",
        "context_duplication_ratio",
        "sentence_count",
        "word_count",
        "name_front_loaded",
    }
)
# Nested placement/hallucination fact lists embed identity names in free text;
# keep only scalar observables for PUBLIC (rg-015 boundary adapter).
_PUBLIC_PER_IMAGE_PLACEMENT_ALLOW_FIELDS: frozenset[str] = frozenset(
    {
        "accuracy",
        "claims",
    }
)
_PUBLIC_PER_IMAGE_HALLUCINATION_ALLOW_FIELDS: frozenset[str] = frozenset(
    {
        "fabricated",
        "trap_count",
        "coverage",
        "count_advisory",
    }
)


def _entry_index(manifest_entries: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(e["media_id"]): e for e in manifest_entries}


def _entry_is_publishable(entry: dict[str, Any] | None) -> bool:
    """Fail-closed publishability via manifest.Provenance.is_publishable (VLM-6 S1).

    Missing entry, missing provenance, or unparseable provenance => not publishable.
    Never infer publishable=True from absence.
    """
    if entry is None:
        return False
    raw = entry.get("provenance")
    if not isinstance(raw, dict):
        return False
    try:
        return Provenance.model_validate(raw).is_publishable
    except ValidationError:
        return False


def _refused_identification_metric(invariant: str) -> dict[str, Any]:
    """Caption-path identification block when boxed GT is missing (EVAL-03)."""
    return {
        "refused": True,
        "invariant": invariant,
        "precision": None,
        "recall": None,
        "macro_precision": None,
        "macro_recall": None,
        "per_identity": {},
        "true_rejections": None,
        "excluded_images": None,
        "wrong_names": None,
        "ignored_wrong_names": None,
    }


def _entry_recognition_enabled(entry: Mapping[str, Any]) -> bool:
    """Match identification_pr: policy-disabled rows are not live claims."""
    policy = entry.get("policy") or {}
    if isinstance(policy, Mapping):
        return bool(policy.get("recognition_enabled", True))
    return bool(getattr(policy, "recognition_enabled", True))


def _scored_identification_entries(
    run_record: Mapping[str, Any],
    manifest_entries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Entries that would enter identification scoring (matched, non-error)."""
    by_id = _entry_index(list(manifest_entries))
    out: list[dict[str, Any]] = []
    for item in run_record.get("items") or []:
        if item.get("error"):
            continue
        entry = by_id.get(int(item["media_id"]))
        if entry is None:
            continue
        out.append(entry)
    return out


def _identification_metric_entries(
    entries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Population identification_pr actually scores (recognition enabled)."""
    return [entry for entry in entries if _entry_recognition_enabled(entry)]


def _filter_for_public_audience(
    run_record: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Legacy pre-score filter retained for callers/tests that still need it.

    Prefer score-then-redact via ``_redact_caption_report_for_public`` (VLM6-R3-03):
    shrinking ``manifest_entries`` here silently drops closed-roster names and
    Must-Right denominators from the PUBLIC artifact.
    """
    entries = _entry_index(manifest_entries)
    kept_items: list[dict[str, Any]] = []
    for item in run_record["items"]:
        media_id = int(item["media_id"])
        if _entry_is_publishable(entries.get(media_id)):
            kept_items.append(item)
    filtered_record = {**run_record, "items": kept_items}
    filtered_entries = [e for e in manifest_entries if _entry_is_publishable(e)]
    withheld = len(run_record["items"]) - len(kept_items)
    return filtered_record, filtered_entries, withheld


def identity_names(identities: object) -> list[str]:
    """Turn stored ``identities`` into an ordered list of name strings.

    Pure data normalizer owned by the scoring module so report does not import
    ``cli`` at call time (VLM6-RH-07 — entrypoints depend on libraries, not the
    reverse). Greenfield: only dict rows with a non-empty ``name`` are accepted.

    This is the ONLY definition. ``cli`` and ``describe_baseline`` re-export it
    rather than carrying copies: the first RH-07 fix broke the cycle by cloning
    the body into both modules, which left the contract tests importing the
    ``cli`` clone while scoring ran the ``report`` one — a regression in the copy
    that scoring uses could not go red (sr-007, TEST-15).
    """
    if not isinstance(identities, list):
        raise TypeError(f"identities must be a list of dict rows, got {type(identities).__name__}")
    names: list[str] = []
    for index, entry in enumerate(identities):
        if not isinstance(entry, dict):
            raise TypeError(
                f"identities[{index}] must be a dict identity row; got "
                f"{type(entry).__name__} — greenfield rejects bare-string identity lists"
            )
        name = entry.get("name")
        if not name:
            raise ValueError(f"identities[{index}] has empty/missing 'name' (keys present: {sorted(entry)!r})")
        names.append(str(name))
    return names


def _publishable_media_ids(manifest_entries: list[dict[str, Any]]) -> set[int]:
    return {int(e["media_id"]) for e in manifest_entries if _entry_is_publishable(e)}


def _public_provenance(provenance: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed allow-list projection for PUBLIC provenance (VLM6-R3-01 / R4-07)."""
    known_sampling_frames = frozenset(FACE_BAKEOFF_SAMPLING_FRAMES.values())
    out: dict[str, Any] = {}
    for key in _PUBLIC_PROVENANCE_ALLOW_FIELDS:
        if key not in provenance:
            continue
        value = provenance[key]
        if key == "model" and isinstance(value, dict):
            # model_ids may carry absolute GGUF paths — collapse to basenames.
            model_out: dict[str, Any] = {}
            for mk, mv in value.items():
                if mk in ("model_ids", "adapters", "model_versions") and isinstance(mv, list):
                    model_out[mk] = [_public_safe_path(str(x)) if isinstance(x, str) else x for x in mv]
                elif isinstance(mv, str):
                    model_out[mk] = _public_safe_path(mv)
                else:
                    model_out[mk] = mv
            out[key] = model_out
        elif key == "tau_fit_status":
            # RB-06: closed enum only — hostile free text must not ride the allow-list.
            if isinstance(value, str) and value in _TAU_FIT_STATUS_PUBLIC_VALUES:
                out[key] = value
            elif value is not None:
                out[key] = "<redacted>"
        elif key == "sampling_frames" and isinstance(value, Mapping):
            # RB-06: only known protocol frame strings pass; anything else is opaque.
            frames_out: dict[str, Any] = {}
            for fk, fv in value.items():
                if isinstance(fv, str) and fv in known_sampling_frames:
                    frames_out[str(fk)] = fv
                elif isinstance(fv, str):
                    frames_out[str(fk)] = "<redacted>"
                else:
                    frames_out[str(fk)] = fv
            out[key] = frames_out
        else:
            out[key] = value
    return out


def _is_absolute_path_string(text: str) -> bool:
    """True when *text* is itself an absolute filesystem / file:// path."""
    if not text:
        return False
    if text.startswith("file://"):
        return True
    if text.startswith("/"):
        return True
    return len(text) > 2 and text[1] == ":" and text[2] in "\\/"


def _string_contains_operator_path(text: str) -> bool:
    """True when free text embeds an operator absolute path (RB-03)."""
    if not text:
        return False
    if _is_absolute_path_string(text.strip()):
        return True
    return _OPERATOR_PATH_IN_TEXT_RE.search(text) is not None


def _normalize_face_boxes_for_order(face_boxes: Sequence[Any] | None) -> list[Any]:
    """Normalize blank/non-numeric ``y`` to None before labeled_order (RA-04).

    Source ``labeled_order`` now coerces blank/non-numeric y itself; this consumer
    boundary normaliser remains as defense-in-depth for report path stability.
    """
    if not face_boxes:
        return []
    out: list[Any] = []
    for box in face_boxes:
        if not isinstance(box, Mapping):
            out.append(box)
            continue
        if "y" not in box:
            out.append(box)
            continue
        y = box.get("y")
        if y is None:
            out.append(box)
            continue
        try:
            float(y)  # noqa: B018 — validate only
            out.append(box)
        except (TypeError, ValueError):
            normalized = dict(box)
            normalized["y"] = None
            out.append(normalized)
    return out


def _collect_identity_names_for_public_scrub(
    scored: Mapping[str, Any],
    manifest_entries: Sequence[Mapping[str, Any]],
    run_record: Mapping[str, Any],
) -> list[str]:
    """All known identity names (publishable + private) for free-text scrubbing."""
    names: set[str] = set()
    for entry in manifest_entries:
        for key in ("present_identities", "must_right", "easy_wrong"):
            for name in entry.get(key) or []:
                if name:
                    names.add(str(name))
        for box in entry.get("face_boxes") or []:
            # Shared namedness predicate (RA-02 / wE4 residual) — not raw truthiness.
            box_name = named_box_name(box)
            if box_name is not None:
                names.add(box_name)
    for item in run_record.get("items") or []:
        for ident in item.get("identities") or []:
            if not isinstance(ident, Mapping):
                continue
            ident_name = named_box_name(ident)
            if ident_name is not None:
                names.add(ident_name)
    faces = scored.get("faces") if isinstance(scored.get("faces"), Mapping) else {}
    identification = faces.get("identification") if isinstance(faces.get("identification"), Mapping) else {}
    for name in identification.get("per_identity") or {}:
        names.add(str(name))
    for pair in list(identification.get("wrong_names") or []) + list(identification.get("ignored_wrong_names") or []):
        if isinstance(pair, list | tuple):
            for cell in pair:
                if isinstance(cell, str) and cell and "/" not in cell and "." not in cell.rsplit("/", 1)[-1]:
                    # Skip path-like cells; keep bare name strings.
                    if not any(cell.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
                        names.add(cell)
    title = (scored.get("quality") or {}).get("title") if isinstance(scored.get("quality"), Mapping) else None
    if isinstance(title, Mapping):
        for name in title.get("hallucinated_names") or []:
            if name:
                names.add(str(name))
    return sorted((n for n in names if n), key=len, reverse=True)


def _identity_name_match_patterns(name: str) -> list[re.Pattern[str]]:
    """Build case/separator-folded matchers for one roster name (RV4-05).

    Matches the literal (NFKC, case-insensitive), hyphen/underscore/space
    variants between tokens, and the fully compacted slug (``JaneDoePrivate``).
    """
    folded = unicodedata.normalize("NFKC", name).strip()
    if not folded:
        return []
    patterns: list[re.Pattern[str]] = [
        re.compile(re.escape(folded), re.IGNORECASE),
    ]
    tokens = [t for t in re.split(r"[\s_\-]+", folded) if t]
    if len(tokens) >= 2:
        sep = r"[\s_\-]*".join(re.escape(t) for t in tokens)
        patterns.append(re.compile(sep, re.IGNORECASE))
        patterns.append(re.compile("".join(re.escape(t) for t in tokens), re.IGNORECASE))
    return patterns


def _identity_quality_match_patterns(name: str) -> list[re.Pattern[str]]:
    """Per-token fallback matchers for quality metrics, which must ignore roster spelling."""
    folded = unicodedata.normalize("NFKC", name).strip()
    if not folded:
        return []
    return [
        re.compile(rf"(?<!\w){re.escape(token)}(?!\w)", re.IGNORECASE)
        for token in {t for t in re.findall(r"[A-Za-z']+", folded) if t}
    ]


def _scrub_identity_names(text: str, names: Sequence[str]) -> str:
    """Scrub roster names from free text (RV4-05 / S2-03).

    NFKC + case-insensitive; also hits hyphen/underscore/slug folds so
    ``jane-doe-private`` / ``JaneDoePrivate`` cannot evade a spaced roster name.
    """
    if not text:
        return text
    out = text
    # Longest first so multi-token names win over substrings.
    for name in sorted((n for n in names if n), key=len, reverse=True):
        for pat in _identity_name_match_patterns(str(name)):
            out = pat.sub("[redacted]", out)
    return out


def _scrub_identity_quality_names(text: str, names: Sequence[str]) -> str:
    """Scrub full roster names and their tokens from quality-only computations."""
    if not text:
        return text
    out = text
    changed = False
    for name in sorted((n for n in names if n), key=len, reverse=True):
        for pat in _identity_name_match_patterns(str(name)):
            out, replacements = pat.subn("[redacted]", out)
            changed = changed or replacements > 0
        for pat in _identity_quality_match_patterns(str(name)):
            out, replacements = pat.subn("[redacted]", out)
            changed = changed or replacements > 0
    return re.sub(r"\s+", " ", out).strip() if changed else text


def _quality_objects_without_identity_names(
    objects: Sequence[str] | None,
    names: Sequence[str],
) -> list[str] | None:
    """Drop identity-bearing tags so tag coverage tracks scene content, not roster spelling."""
    if not objects:
        return None
    scrubbed = [
        str(obj)
        for obj in objects
        if _scrub_identity_quality_names(str(obj), names) == str(obj)
    ]
    return scrubbed or None


def _caption_scores_without_identity_spelling(
    caption: str,
    *,
    scores: CaptionScores,
    names: Sequence[str],
    score_kwargs: Mapping[str, Any],
) -> CaptionScores:
    """Preserve identity-sensitive gates but compute quality-only fields on scrubbed text/tags."""
    quality_kwargs = dict(score_kwargs)
    quality_kwargs["objects"] = _quality_objects_without_identity_names(
        quality_kwargs.get("objects"), names
    )
    quality_scores = score_caption(_scrub_identity_quality_names(caption, names), **quality_kwargs)
    return replace(
        scores,
        fkre=quality_scores.fkre,
        repetition_ratio=quality_scores.repetition_ratio,
        tag_coverage=quality_scores.tag_coverage,
    )


def _public_list_path(
    path: str,
    names: Sequence[str] = (),
    *,
    media_id: object | None = None,
    path_to_media: Mapping[str, int] | None = None,
) -> str:
    """Opaque path for nested PUBLIC path lists (excluded_images, …) (RV4-01).

    Same rule as per-image paths: prefer ``media_id:N``; otherwise never emit a
    relative operator key. Absolute → ``<absolute>``. The space-bearing-basename
    heuristic is deleted — it was a symptom patch, not a privacy boundary.
    """
    text = str(path) if path is not None else ""
    # Idempotent: already-redacted tokens from a prior pass must pass through.
    if text.startswith("media_id:") or text in ("<path>", "<absolute>", "<error>", "<redacted>", ""):
        return text
    mid = media_id
    if mid is None and path_to_media is not None and text in path_to_media:
        mid = path_to_media[text]
    if mid is not None and str(mid) != "":
        return f"media_id:{mid}"
    safe = _public_safe_path(text)
    if safe == "":
        return safe
    if safe == "<absolute>":
        return safe
    # Relative keys without media_id: fail-closed opaque (never verbatim).
    # names retained in signature for call-site compatibility; scrub not needed
    # once the path is fully opaque.
    _ = names
    return "<path>"


def _public_free_text_value(
    key: str,
    value: object,
    *,
    media_id: object | None = None,
    names: Sequence[str] = (),
    path_to_media: Mapping[str, int] | None = None,
) -> str:
    """Scrub free-text admitted to the PUBLIC boundary (S2-03 / S2-04 / RV4-05).

    Paths never emit operator basenames: prefer an opaque ``media_id:N`` token.
    Absolute paths without media_id collapse to ``<absolute>`` (not basename).
    Other free-text is name-scrubbed and never passes raw operator prose.
    Default-deny: unclassified free-text keys are opaque even without a roster hit.
    """
    text = "" if value is None else str(value)
    if key == "path":
        if media_id is not None and str(media_id) != "":
            return f"media_id:{media_id}"
        return _public_list_path(text, names, path_to_media=path_to_media) if text else text
    if not text:
        return text
    scrubbed = _scrub_identity_names(text, names)
    if scrubbed != text:
        return "<redacted>"
    # Shape: free-text error strings are not a redaction boundary even without
    # a known roster hit — emit an opaque token (S2-03).
    if key in ("short_error", "error"):
        return "<error>"
    # RV4-05 default-deny: allow-listed string fields not typed as metric/bool
    # never pass through raw operator prose.
    return "<redacted>"


def _public_per_image_row(
    row: Mapping[str, Any],
    *,
    names: Sequence[str] = (),
    path_to_media: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Build a PUBLIC per-image record from an explicit allow-list (VLM6-A-01).

    Fail-closed (rg-015): unknown keys — including future name-bearing fields —
    are dropped. Nested ``long`` / ``placement`` / ``hallucination`` are themselves
    allow-listed so fact-string lists cannot carry roster names. Free-text keys
    on the allow-list are scrubbed (S2-03); paths never keep identifying basenames
    (S2-04). String values default-deny unless typed metric/bool (RV4-05).
    """
    out: dict[str, Any] = {}
    media_id = row.get("media_id")
    for key in _PUBLIC_PER_IMAGE_ALLOW_FIELDS:
        if key not in row:
            continue
        value = row[key]
        if key == "long" and isinstance(value, Mapping):
            out[key] = {k: value[k] for k in _PUBLIC_PER_IMAGE_LONG_ALLOW_FIELDS if k in value}
        elif key == "placement" and isinstance(value, Mapping):
            out[key] = {k: value[k] for k in _PUBLIC_PER_IMAGE_PLACEMENT_ALLOW_FIELDS if k in value}
        elif key == "hallucination" and isinstance(value, Mapping):
            out[key] = {k: value[k] for k in _PUBLIC_PER_IMAGE_HALLUCINATION_ALLOW_FIELDS if k in value}
        elif key in _PUBLIC_PER_IMAGE_FREE_TEXT_FIELDS or isinstance(value, str):
            # RV4-05: any allow-listed string is free text (default-deny).
            out[key] = _public_free_text_value(
                key, value, media_id=media_id, names=names, path_to_media=path_to_media
            )
        else:
            out[key] = value
    return out


def _public_failure_row(
    fail: Mapping[str, Any],
    *,
    names: Sequence[str] = (),
    path_to_media: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Fail-closed allow-list + free-text scrub for PUBLIC failures (S2-03)."""
    out: dict[str, Any] = {}
    media_id = fail.get("media_id")
    for key in _PUBLIC_FAILURE_ALLOW_FIELDS:
        if key not in fail:
            continue
        value = fail[key]
        if key in _PUBLIC_FAILURE_FREE_TEXT_FIELDS or isinstance(value, str):
            out[key] = _public_free_text_value(
                key, value, media_id=media_id, names=names, path_to_media=path_to_media
            )
        else:
            out[key] = value
    return out


def _redact_caption_report_for_public(
    scored: dict[str, Any],
    *,
    run_record: Mapping[str, Any],
    manifest_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Post-score PUBLIC redaction for the caption/face report path (VLM6-R3-*).

    Score the full corpus first (roster + rubric denominators intact), then:
    - allow-list provenance
    - strip identity-bearing detail lists that can name private people
    - drop non-publishable per_image rows from the rendered surface
    - split withheld (non-publishable) vs unknown_media (absent from manifest)
    Aggregate rates/denominators stay from the full-corpus score (parity with LOCAL).
    """
    redacted = copy.deepcopy(scored)
    entries = _entry_index(manifest_entries)
    publishable_ids = _publishable_media_ids(manifest_entries)

    # VLM6-LC-INT-01: publishability is conferred by being a SUBJECT of a
    # publishable image (present_identities / must_right) and revoked by being a
    # subject of any non-publishable one. ``easy_wrong`` is the decoy field — it
    # names a person who must NOT appear in that image's caption, and is routinely
    # populated with a private individual precisely because they are off-limits.
    # Treating a decoy as publishable published the private roster name under
    # ``per_identity`` with full tp/fp/precision/recall. Fail-closed both ways:
    # a decoy never confers publishability, and never revokes it either.
    def _subject_names(entry: Mapping[str, Any]) -> list[str]:
        return [str(n) for n in (list(entry.get("present_identities") or []) + list(entry.get("must_right") or []))]

    publishable_subjects: set[str] = set()
    private_subjects: set[str] = set()
    for e in manifest_entries:
        target = publishable_subjects if int(e["media_id"]) in publishable_ids else private_subjects
        target.update(_subject_names(e))
    publishable_names = publishable_subjects - private_subjects

    items = list(run_record.get("items") or [])
    total_items = len(items)
    unknown_media_items = 0
    withheld_items = 0
    for item in items:
        media_id = int(item["media_id"])
        if media_id not in entries:
            unknown_media_items += 1
        elif media_id not in publishable_ids:
            withheld_items += 1
    withheld_manifest_entries = sum(1 for e in manifest_entries if int(e["media_id"]) not in publishable_ids)

    # Provenance: allow-list only (unknown keys dropped, not deny-listed).
    redacted["provenance"] = _public_provenance(redacted.get("provenance") or {})

    scrub_names = _collect_identity_names_for_public_scrub(scored, manifest_entries, run_record)
    publishable_paths = {str(e["path"]) for e in manifest_entries if int(e["media_id"]) in publishable_ids}
    # RV4-01: map relative corpus keys → media_id so path lists emit media_id:N.
    path_to_media: dict[str, int] = {}
    for e in manifest_entries:
        path_to_media[str(e["path"])] = int(e["media_id"])
    for item in items:
        p = item.get("path")
        if isinstance(p, str) and p:
            path_to_media.setdefault(p, int(item["media_id"]))
    for row in redacted.get("per_image") or []:
        if isinstance(row, Mapping) and row.get("path") is not None and row.get("media_id") is not None:
            path_to_media.setdefault(str(row["path"]), int(row["media_id"]))

    def _keep_publishable_paths(paths: list[Any]) -> list[Any]:
        kept: list[Any] = []
        for p in paths:
            if isinstance(p, str) and p in publishable_paths or not isinstance(p, str):
                kept.append(p)
        return kept

    def _public_path_list(paths: list[Any]) -> list[Any]:
        # RV4-01: path lists use media_id:N (or <path>) — never relative keys.
        out: list[Any] = []
        for p in _keep_publishable_paths(paths):
            if isinstance(p, str):
                out.append(_public_list_path(p, scrub_names, path_to_media=path_to_media))
            else:
                out.append(p)
        return out

    faces = redacted.get("faces") or {}
    identification = faces.get("identification") or {}
    # Identity-name surfaces: empty detail lists, keep aggregate tp/fp/fn.
    identification["wrong_names"] = []
    identification["ignored_wrong_names"] = []
    per_identity = identification.get("per_identity") or {}
    identification["per_identity"] = {name: stats for name, stats in per_identity.items() if name in publishable_names}
    # Path lists can name local-only media — keep publishable paths only, then scrub.
    identification["excluded_images"] = _public_path_list(list(identification.get("excluded_images") or []))
    positional = identification.get("positional") or {}
    if positional:
        positional["excluded_images"] = _public_path_list(list(positional.get("excluded_images") or []))
        identification["positional"] = positional
    faces["identification"] = identification
    ordering = faces.get("identity_ordering") or {}
    if ordering:
        ordering["degraded_paths"] = _public_path_list(list(ordering.get("degraded_paths") or []))
        # VLM6-R2-G-01 / A-02: GT-side y-missing path list — same PUBLIC scrub
        # as degraded_paths (operator filesystem paths must not leak).
        ordering["labeled_y_missing_paths"] = _public_path_list(
            list(ordering.get("labeled_y_missing_paths") or [])
        )
        faces["identity_ordering"] = ordering
    redacted["faces"] = faces

    # Per-image: only publishable rows; rebuild from allow-list so identity
    # name fields and future name-bearing keys cannot leak by default (VLM6-A-01).
    # Free-text keys on the allow-list are scrubbed (S2-03 / S2-04).
    kept_rows: list[dict[str, Any]] = []
    for row in redacted.get("per_image") or []:
        media_id = int(row.get("media_id", -1))
        if media_id not in publishable_ids:
            continue
        if not isinstance(row, Mapping):
            continue
        kept_rows.append(
            _public_per_image_row(row, names=scrub_names, path_to_media=path_to_media)
        )
    redacted["per_image"] = kept_rows

    # Quality title block may list hallucinated roster names — clear for PUBLIC.
    quality = redacted.get("quality") or {}
    title_q = quality.get("title")
    if isinstance(title_q, dict):
        title_q["hallucinated_names"] = []
        quality["title"] = title_q
        redacted["quality"] = quality

    # Failures: allow-list + free-text scrub (S2-03). Keep unknown-media rows
    # (corpus integrity) and publishable timeouts; drop non-publishable detail.
    kept_failures: list[dict[str, Any]] = []
    for fail in redacted.get("failures") or []:
        if not isinstance(fail, Mapping):
            continue
        media_id = int(fail.get("media_id", -1))
        if media_id not in entries or media_id in publishable_ids:
            kept_failures.append(
                _public_failure_row(fail, names=scrub_names, path_to_media=path_to_media)
            )
    redacted["failures"] = kept_failures

    # Strata excluded_images are free-text path counts under difficulty/domain.
    strata = redacted.get("strata")
    if isinstance(strata, Mapping):
        for bucket_key in ("by_difficulty", "by_domain"):
            bucket = strata.get(bucket_key)
            if not isinstance(bucket, Mapping):
                continue
            for _label, block in bucket.items():
                if not isinstance(block, Mapping):
                    continue
                pos = block.get("positional")
                if isinstance(pos, Mapping) and isinstance(pos.get("excluded_images"), list):
                    pos["excluded_images"] = _public_path_list(list(pos.get("excluded_images") or []))

    redacted["redaction"] = {
        "audience": Audience.PUBLIC.value,
        "mode": "post_score_redact_caption_report",
        "withheld_items": withheld_items,
        "unknown_media_items": unknown_media_items,
        "withheld_manifest_entries": withheld_manifest_entries,
        "total_items": total_items,
        "total_manifest_entries": len(manifest_entries),
        "note": (
            "Aggregates scored on the full corpus (roster/rubric intact); "
            "identity-bearing detail lists and non-publishable per_image rows "
            "stripped. unknown_media_items are corpus-integrity failures, not privacy."
        ),
    }
    return _redact_public_paths(redacted, names=scrub_names, path_to_media=path_to_media)


def _public_safe_path(path: str) -> str:
    """Render-boundary path redaction for PUBLIC artifacts.

    Absolute filesystem paths (POSIX or Windows drive) never emit operator layout
    *or* identifying basenames (S2-04): operators put subject names in filenames.
    Model-weight basenames (``.gguf`` / ``.onnx`` / …) are kept for legibility.
    Relative corpus keys (``celebs01/…``, ``mock_images/…``) are left intact —
    per-image/failure free-text paths still go through ``_public_free_text_value``.
    """
    text = str(path)
    if not text:
        return text
    absolute = text.startswith("/") or (len(text) > 2 and text[1] == ":" and text[2] in "\\/")
    if absolute:
        base = text.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        lower = base.lower()
        if any(lower.endswith(suffix) for suffix in _PUBLIC_MODEL_PATH_SUFFIXES):
            return base
        # S2-04: basename is exactly where subject names live — do not emit it.
        return "<absolute>"
    return text


def _parse_spatial_facts(raw: Any) -> list[SpatialFact]:
    """Parse entry ``spatial_facts``; skip unparseable rows fail-open per item."""
    if not isinstance(raw, list):
        return []
    facts: list[SpatialFact] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            facts.append(SpatialFact.model_validate(item))
        except ValidationError:
            continue
    return facts


def _parse_reference_facts(raw: Any) -> list[ReferenceFact]:
    """Parse entry ``reference_facts``; skip unparseable rows fail-open per item."""
    if not isinstance(raw, list):
        return []
    facts: list[ReferenceFact] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            facts.append(ReferenceFact.model_validate(item))
        except ValidationError:
            continue
    return facts


def _redact_public_paths(
    obj: Any,
    *,
    names: Sequence[str] = (),
    path_to_media: Mapping[str, int] | None = None,
) -> Any:
    """Rewrite path strings nested in a scored report (render boundary).

    Absolute paths collapse without identifying basenames (S2-04). Nested path
    lists emit ``media_id:N`` or ``<path>`` — never relative operator keys
    (RV4-01).
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key in ("path",) and isinstance(value, str):
                # media_id:N tokens from free-text scrub must pass through.
                if value.startswith("media_id:") or value in ("<path>", "<absolute>", "<error>", "<redacted>"):
                    out[key] = value
                else:
                    out[key] = _public_list_path(value, names, path_to_media=path_to_media)
            elif key in ("excluded_images", "degraded_paths", "labeled_y_missing_paths") and isinstance(
                value, list
            ):
                out[key] = [
                    (
                        _public_list_path(v, names, path_to_media=path_to_media)
                        if isinstance(v, str)
                        else _redact_public_paths(v, names=names, path_to_media=path_to_media)
                    )
                    for v in value
                ]
            elif key in ("wrong_names", "ignored_wrong_names") and isinstance(value, list):
                rewritten: list[Any] = []
                for pair in value:
                    if isinstance(pair, list | tuple) and pair and isinstance(pair[0], str):
                        rewritten.append(
                            [
                                _public_list_path(str(pair[0]), names, path_to_media=path_to_media),
                                *list(pair[1:]),
                            ]
                        )
                    else:
                        rewritten.append(
                            _redact_public_paths(pair, names=names, path_to_media=path_to_media)
                        )
                out[key] = rewritten
            else:
                out[key] = _redact_public_paths(value, names=names, path_to_media=path_to_media)
        return out
    if isinstance(obj, list):
        return [_redact_public_paths(v, names=names, path_to_media=path_to_media) for v in obj]
    return obj


def _pr_dict(precision: float | None, recall: float | None) -> dict[str, float | None]:
    return {"precision": precision, "recall": recall}


def _validate_record_kind(run_record: dict[str, Any]) -> None:
    """Reject a report file (or foreign doc) passed where a run record is expected (HARM-06, S3-04)."""
    kind = run_record.get("kind")
    if kind is not None and kind != DocKind.RUN_RECORD.value:
        raise ReportError(
            f"expected a '{DocKind.RUN_RECORD.value}' document but got kind={kind!r}; "
            "did you pass a report file to score?"
        )
    schema = run_record.get("schema")
    if schema is not None and schema != SCHEMA:
        raise ReportError(f"unknown run-record schema {schema!r}; expected {SCHEMA!r}")
    if "items" not in run_record:
        raise ReportError("run record has no 'items' key — is this a report file passed as a run record?")
    if "provenance" not in run_record:
        raise ReportError("run record has no 'provenance' block")
    items = run_record["items"]
    if not isinstance(items, list):
        raise ReportError(f"run record 'items' must be a list, got {type(items).__name__}")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ReportError(f"run record items[{index}] must be a dict, got {type(item).__name__}")
        identities = item.get("identities", [])
        _validate_identities_element_types(identities, context=f"items[{index}].identities")


def _validate_identities_element_types(identities: Any, *, context: str) -> None:
    """Require identities to be a list of dict rows (A-10) — never bare strings.

    List-ness alone is not enough: a list of the wrong element type used to pass
    validation and only fail later inside scoring, far from the cause.
    """
    if not isinstance(identities, list):
        raise ReportError(f"{context} must be a list, got {type(identities).__name__}")
    for index, entry in enumerate(identities):
        if not isinstance(entry, dict):
            raise ReportError(
                f"{context}[{index}] must be a dict identity row "
                f"(keys include 'name'); got {type(entry).__name__} — "
                "greenfield rejects bare-string identity lists"
            )
        if "name" not in entry:
            raise ReportError(f"{context}[{index}] is missing required key 'name' (keys present: {sorted(entry)!r})")


def _model_provenance(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Adapter/model that actually produced the captions (HARM-01).

    Surfaced so a report is never mistaken for a caption-model baseline when it
    actually scored a model-free 'seeded' stub run — every artifact stamped with
    the adapter/model version (scope Q5).
    """
    adapters, model_ids, model_versions = set(), set(), set()
    for item in items:
        describe = item.get("describe") or {}
        if describe.get("adapter"):
            adapters.add(str(describe["adapter"]))
        if describe.get("model_id"):
            model_ids.add(str(describe["model_id"]))
        if describe.get("model_version") is not None:
            model_versions.add(str(describe["model_version"]))
    return {
        "adapters": sorted(adapters),
        "model_ids": sorted(model_ids),
        "model_versions": sorted(model_versions),
    }


def _context_text(entry: dict[str, Any]) -> str:
    """Deterministic flattening of the entry's context_pack for duplication checks."""
    pack = entry.get("context_pack") or {}
    parts = [str(v) for _, v in sorted(pack.items()) if isinstance(v, str) and v.strip()]
    return "\n".join(parts)


def _corpus_roster(manifest_entries: list[dict[str, Any]], manifest_roster: list[str] | None = None) -> list[str]:
    """Closed roster = the manifest's declared roster (ALTQ-1-REV-A-01/B-07)
    unioned with every identity the entries reference — a roster member never
    named in any rubric must still trip the hallucination gate."""
    roster: set[str] = set(manifest_roster or [])
    for entry in manifest_entries:
        roster.update(entry.get("present_identities", []))
        roster.update(entry.get("must_right", []))
        roster.update(entry.get("easy_wrong", []))
    return sorted(roster)


def _ablation_gate(scores: CaptionScores) -> float | None:
    """name_ablation gate: names were stripped from context at fetch, so ANY
    asserted name is a leak (the model guessed an identity — BreakingNews
    ablation as a mechanical never-guess test). Insertion fractions are
    meaningless in this mode; the gate is binary. Leaks are checked BEFORE the
    eligibility exit (ALTQ-1-REV-A-04): a wrong name on a recognition-disabled
    image zeroes here exactly as it does in standard mode."""
    if scores.inserted_identities or scores.wrong_name_hits or scores.hallucinated_names:
        return 0.0
    if not scores.insertion_eligible:
        return None
    return 1.0


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile on ascending pre-sorted values — deterministic, no interpolation."""
    rank = max(math.ceil(q * len(sorted_values)), 1)
    return sorted_values[rank - 1]


def _latency_summary(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """ALTQ-1 Slice 3: per-image wall-clock + model-call aggregates from run-record timing.

    Wall-clock per image = sum of ``describe.passes[*].latency_s`` when the item
    carries timed passes (multi-call pipelines), else the walker's single
    ``latency_s`` item field. Model calls per image = ``len(passes)`` or 1.
    Items with an error, no timing data, or a cache hit (``describe.cached``)
    are excluded from the percentile sample and counted beside ``images_timed``
    so coordinated omission is visible (VLM6-R4-04 / PERF-03). Emits p99 + max
    and a small-n caveat when nearest-rank p95 is tail-blind (VLM6-R4-09).
    Returns ``None`` when nothing is timed so untimed fixtures keep shape.
    """
    wall_clock: list[float] = []
    calls: list[int] = []
    cache_hits_excluded = 0
    error_items_excluded = 0
    timed_out_images = 0

    def _item_has_timing(item: dict[str, Any], describe: Mapping[str, Any]) -> bool:
        passes = describe.get("passes")
        if isinstance(passes, list) and passes:
            return any(isinstance(p, dict) and isinstance(p.get("latency_s"), int | float) for p in passes)
        return isinstance(item.get("latency_s"), int | float)

    for item in items:
        if item.get("error"):
            # Only count errors that would have contributed a timing sample.
            if _item_has_timing(item, item.get("describe") or {}):
                error_items_excluded += 1
                err = str(item.get("error") or "").lower()
                if "timeout" in err or "timed out" in err:
                    timed_out_images += 1
            else:
                # Untimed error items still counted when any live timings exist
                # so the timeout tail is visible beside images_timed (R4-04).
                err = str(item.get("error") or "").lower()
                if "timeout" in err or "timed out" in err:
                    error_items_excluded += 1
                    timed_out_images += 1
            continue
        describe = item.get("describe") or {}
        # Cache hits are not live inference timings (VLM6-R4-04).
        if bool(describe.get("cached", False)):
            if _item_has_timing(item, describe):
                cache_hits_excluded += 1
            continue
        passes = describe.get("passes")
        if isinstance(passes, list) and passes:
            latencies = [
                p["latency_s"] for p in passes if isinstance(p, dict) and isinstance(p.get("latency_s"), int | float)
            ]
            if not latencies:
                continue
            wall_clock.append(round(sum(latencies), 3))
            calls.append(len(passes))
        else:
            latency = item.get("latency_s")
            if not isinstance(latency, int | float):
                continue
            wall_clock.append(round(float(latency), 3))
            calls.append(1)
    if not wall_clock:
        # Additive schema: pre-Slice-3 / untimed fixtures keep no latency key.
        # Only surface a zeroed block when cache hits were the sole timed samples
        # (warm-cache re-score must not silently omit the pollution — VLM6-R4-04).
        if not cache_hits_excluded:
            return None
        return {
            "images_timed": 0,
            "wall_clock_s": {"p50": None, "p95": None, "p99": None, "max": None},
            "model_calls": {"per_image_mean": None, "total": 0},
            "cache_hits_excluded": cache_hits_excluded,
            "error_items_excluded": error_items_excluded,
            "timed_out_images": timed_out_images,
            "percentile_caveat": "no_live_timings",
        }
    ordered = sorted(wall_clock)
    n = len(ordered)
    result: dict[str, Any] = {
        "images_timed": n,
        "wall_clock_s": {
            "p50": round(_percentile(ordered, 0.5), 3),
            "p95": round(_percentile(ordered, 0.95), 3),
            "p99": round(_percentile(ordered, 0.99), 3),
            "max": round(ordered[-1], 3),
        },
        "model_calls": {
            "per_image_mean": round(sum(calls) / len(calls), 4),
            "total": sum(calls),
        },
        "cache_hits_excluded": cache_hits_excluded,
        "error_items_excluded": error_items_excluded,
        "timed_out_images": timed_out_images,
    }
    # Nearest-rank p95 needs n>=20 for the worst observation to be able to move it.
    if n < 20:
        result["percentile_caveat"] = f"n={n}_below_p95_rank_threshold"
    return result


def _total_wrong_name_count(ident: Mapping[str, Any]) -> int:
    """All observed wrong-name pairs, including ignore-list-triaged ones (F1-5).

    Presentation keeps ``wrong_names`` vs ``ignored_wrong_names`` split; the
    hard gate must not shrink when an operator file moves pairs into ignored.
    """
    live = ident.get("wrong_names") or []
    ignored = ident.get("ignored_wrong_names") or []
    return len(live) + len(ignored)


def _wrong_name_images(ident: Mapping[str, Any]) -> set[str]:
    """Unique image paths that asserted at least one wrong name (live + ignored)."""
    images: set[str] = set()
    for pair in list(ident.get("wrong_names") or []) + list(ident.get("ignored_wrong_names") or []):
        if isinstance(pair, list | tuple) and pair:
            images.add(str(pair[0]))
    return images


def face_wrong_name_rate(scored: Mapping[str, Any]) -> float:
    """Per-image wrong-name rate = unique wrong-name images / counts.scored.

    VLM6-S2A-B-09: the numerator is images (not (image,name) assertion pairs), so
    a multi-name image contributes 1 and the rate is bounded by [0, 1].
    Denominator is scored images; empty scored set → 0.0. Ignore-list pairs still
    count (F1-5 / OBS-04).
    """
    scored_n = int(scored["counts"]["scored"])
    if scored_n <= 0:
        return 0.0
    return len(_wrong_name_images(scored["faces"]["identification"])) / scored_n


def fabricated_fact_is_vacuous(hall: Mapping[str, Any] | None) -> bool:
    """True when fabricated-fact rate is non-observable (S2-01 / S2-06 / rg-005).

    Shared by ``build_score_verdict`` and ``compare``: zero trap denominator OR
    either rate field is None is vacuous. A stamped numeric ``0.0`` with
    ``images_with_traps=0`` is still vacuous — the clean-zero lie this wave
    removed. Prefer this single predicate over parallel copies of the rule.
    """
    if not isinstance(hall, Mapping):
        return True
    return (
        int(hall.get("images_with_traps") or 0) == 0
        or hall.get("fabricated_fact_rate") is None
        or hall.get("fabricated_fact_rate_trapped") is None
    )


def _score_nested_number(doc: Mapping[str, Any], path: tuple[str, ...]) -> float | None:
    cur: Any = doc
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            return None
        cur = cur[key]
    if isinstance(cur, bool) or not isinstance(cur, (int, float)):
        return None
    return float(cur)


def score_vacuous_category_labels(
    doc: Mapping[str, Any],
    *,
    include_verdict_fields: bool = True,
) -> list[str]:
    """Shared vacuity axis labels for score + compare (S2-01 / S2-06 / EVAL-23).

    Returns stable machine labels (no role prefix). ``compare`` prefixes with
    ``baseline:`` / ``candidate:``. Key absence and zero-denominator regimes are
    both non-observable. ``include_verdict_fields=False`` when building the
    verdict block itself (``verdict.wrong_name_rate`` is not yet on the doc).

    RV1-02: sample-size (``SCORE_PASS_MIN_SCORED_IMAGES``) lives here so score
    and compare consult the same predicate and cannot diverge.
    """
    labels: list[str] = []
    counts = doc.get("counts") if isinstance(doc.get("counts"), Mapping) else {}
    scored_n = int(counts.get("scored") or 0)
    if scored_n > 0 and scored_n < SCORE_PASS_MIN_SCORED_IMAGES:
        labels.append("sample_size")
    place = doc.get("placement") if isinstance(doc.get("placement"), Mapping) else {}
    if place.get("accuracy") is None or int(place.get("claims") or 0) == 0:
        labels.append("placement")
    faces = doc.get("faces") if isinstance(doc.get("faces"), Mapping) else {}
    ident = faces.get("identification") if isinstance(faces.get("identification"), Mapping) else {}
    pos = ident.get("positional") if isinstance(ident.get("positional"), Mapping) else None
    if (
        not isinstance(pos, Mapping)
        or pos.get("position_accuracy") is None
        or int(pos.get("compared_images") or 0) == 0
        or pos.get("evaluable") is False
        or pos.get("status") == POSITIONAL_EVAL_NOT_EVALUABLE
    ):
        labels.append("positional_identification")
    ordering = faces.get("identity_ordering") if isinstance(faces.get("identity_ordering"), Mapping) else None
    if not isinstance(ordering, Mapping) or int(ordering.get("positional_images") or 0) == 0:
        labels.append("identity_ordering")
    hall = doc.get("hallucination") if isinstance(doc.get("hallucination"), Mapping) else {}
    if fabricated_fact_is_vacuous(hall):
        labels.append("fabricated_fact")
    for path, label in (
        (("faces", "detection", "precision"), "face_detection.precision"),
        (("faces", "detection", "recall"), "face_detection.recall"),
        (("faces", "identification", "precision"), "face_identification.precision"),
        (("faces", "identification", "recall"), "face_identification.recall"),
        (("caption", "insertion_rate"), "insertion_rate"),
        (("caption", "mean_gated_score"), "mean_gated_score"),
        (("caption", "must_right_failed_images"), "must_right_failed_images"),
    ):
        if _score_nested_number(doc, path) is None:
            labels.append(label)
    if include_verdict_fields and _score_nested_number(doc, ("verdict", "wrong_name_rate")) is None:
        labels.append("wrong_name_rate")
    return labels


def build_score_vacuity_reasons(scored: Mapping[str, Any], *, scored_n: int) -> list[str]:
    """Detailed category-vacuity reasons for the score verdict (AUDIT-07).

    Uses the shared predicates in ``score_vacuous_category_labels`` /
    ``fabricated_fact_is_vacuous`` so score and compare cannot disagree on which
    axes are non-observable (S2-01 / S2-06 / rg-005). Sample-size is owned by
    the shared predicate (RV1-02); this helper only formats the operator reason.
    """
    vacuity_reasons: list[str] = []
    if scored_n <= 0:
        return vacuity_reasons
    labels = set(score_vacuous_category_labels(scored, include_verdict_fields=False))
    if "sample_size" in labels:
        vacuity_reasons.append(
            f"sample-size: scored={scored_n} < min={SCORE_PASS_MIN_SCORED_IMAGES} "
            f"(undersized corpus cannot certify adoption-shaped pass; EVAL-04 / S2-05)"
        )
    faces = scored.get("faces") if isinstance(scored.get("faces"), Mapping) else {}
    ident = faces.get("identification") if isinstance(faces.get("identification"), Mapping) else {}
    placement = scored.get("placement") if isinstance(scored.get("placement"), Mapping) else {}
    if "positional_identification" in labels:
        positional = ident.get("positional") if isinstance(ident.get("positional"), Mapping) else {}
        compared_images = int(positional.get("compared_images") or 0)
        pos_evaluable = positional.get("evaluable")
        pos_status = positional.get("status")
        ordering = faces.get("identity_ordering") if isinstance(faces.get("identity_ordering"), Mapping) else {}
        # S2-07: report exclusions via order_unknown_excluded / excluded_images,
        # not the overloaded degraded_images counter.
        excluded_raw = positional.get("excluded_images") or []
        excluded_n = len(excluded_raw) if isinstance(excluded_raw, list) else int(excluded_raw or 0)
        order_unknown = int(ordering.get("order_unknown_excluded") or excluded_n)
        vacuity_reasons.append(
            "category-vacuity: positional — claim unit=image with face_boxes "
            f"L→R order; compared_images={compared_images} "
            f"status={pos_status!s} evaluable={pos_evaluable!s} "
            f"order_unknown_excluded={order_unknown} excluded_images={excluded_n} "
            f"(π=0 on face_boxes; AUDIT-07)"
        )
    if "placement" in labels:
        place_claims = int(placement.get("claims") or 0)
        place_acc = placement.get("accuracy")
        abstained = int(placement.get("abstained") or 0)
        images_scored = int(placement.get("images_scored") or 0)
        vacuity_reasons.append(
            "category-vacuity: placement — claim unit=asserted spatial_fact; "
            f"claims={place_claims} accuracy={place_acc!s} abstained={abstained} "
            f"images_scored={images_scored} (π=0 on spatial_facts; AUDIT-07)"
        )
    if "fabricated_fact" in labels:
        hall = scored.get("hallucination") if isinstance(scored.get("hallucination"), Mapping) else {}
        traps = int(hall.get("images_with_traps") or 0)
        fab_rate = hall.get("fabricated_fact_rate")
        vacuity_reasons.append(
            "category-vacuity: fabricated_fact — claim unit=image with "
            f"reference_facts trap; fabricated_fact_rate={fab_rate!s} "
            f"images_with_traps={traps} (not measurable; AUDIT-07 / S2-01)"
        )
    if "identity_ordering" in labels:
        ordering = faces.get("identity_ordering") if isinstance(faces.get("identity_ordering"), Mapping) else {}
        vacuity_reasons.append(
            "category-vacuity: identity_ordering — "
            f"positional_images={int(ordering.get('positional_images') or 0)} "
            f"(order metric non-observable; AUDIT-07 / S2-06)"
        )
    for label in (
        "face_detection.precision",
        "face_detection.recall",
        "face_identification.precision",
        "face_identification.recall",
        "insertion_rate",
        "mean_gated_score",
        "must_right_failed_images",
    ):
        if label in labels:
            vacuity_reasons.append(f"category-vacuity: {label} (None — category not observed; S2-06)")
    return vacuity_reasons


def build_score_quality_floor_reasons(scored: Mapping[str, Any], *, scored_n: int) -> list[str]:
    """Quality-floor breaches on critical scored slices (S2-02 / EVAL-04).

    Floor breach is FAIL (measured and bad), never not_ready. Thresholds are the
    named constants ``POSITION_ACCURACY_FLOOR``, ``PLACEMENT_ACCURACY_FLOOR``,
    ``FABRICATED_FACT_RATE_CEILING`` — conservative degenerate-extreme policy.
    """
    reasons: list[str] = []
    if scored_n <= 0:
        return reasons
    faces = scored.get("faces") if isinstance(scored.get("faces"), Mapping) else {}
    ident = faces.get("identification") if isinstance(faces.get("identification"), Mapping) else {}
    positional = ident.get("positional") if isinstance(ident.get("positional"), Mapping) else {}
    compared = int(positional.get("compared_images") or 0)
    pos_acc = positional.get("position_accuracy")
    if compared > 0 and pos_acc is not None and float(pos_acc) <= POSITION_ACCURACY_FLOOR:
        reasons.append(
            f"quality-floor: position_accuracy={pos_acc} <= floor={POSITION_ACCURACY_FLOOR} "
            f"(critical scored slice total failure; EVAL-04 / S2-02)"
        )
    placement = scored.get("placement") if isinstance(scored.get("placement"), Mapping) else {}
    place_claims = int(placement.get("claims") or 0)
    place_acc = placement.get("accuracy")
    if place_claims > 0 and place_acc is not None and float(place_acc) <= PLACEMENT_ACCURACY_FLOOR:
        reasons.append(
            f"quality-floor: placement.accuracy={place_acc} <= floor={PLACEMENT_ACCURACY_FLOOR} "
            f"(critical scored slice total failure; EVAL-04 / S2-02)"
        )
    hall = scored.get("hallucination") if isinstance(scored.get("hallucination"), Mapping) else {}
    traps = int(hall.get("images_with_traps") or 0)
    fab_rate = hall.get("fabricated_fact_rate")
    if traps > 0 and fab_rate is not None and float(fab_rate) >= FABRICATED_FACT_RATE_CEILING:
        reasons.append(
            f"quality-floor: fabricated_fact_rate={fab_rate} >= ceiling={FABRICATED_FACT_RATE_CEILING} "
            f"(every trap fired; EVAL-04 / S2-02)"
        )
    return reasons


def build_score_verdict(
    scored: Mapping[str, Any],
    *,
    rubric_gate: str = "enforce",
) -> dict[str, Any]:
    """Build the machine-readable scored verdict block (VLM-6 S2A / F1d-1).

    Every condition that forces a non-zero ``score`` exit is folded into
    ``reasons`` here so the persisted artifact cannot report ``pass`` while the
    process exits 1 (OBS-04). ``insertion_rate``, ``mean_gated_score``, and
    ``must_right_failed_images`` remain reported for operators. Schema-hard-key
    failures are applied by the CLI before serialisation when report fields are
    missing (cannot be known inside a well-formed score_run_record result).

    ``rubric_gate=skip`` bypasses only the must-right failures reason; a clean
    skip run persists ``pass_ungated`` so it is never readable as a gated pass.

    Category vacuity (VLM6-A-05 / VLM6-B-07 / S2-06): critical scored slices with
    claim-unit sampling π=0 yield ``not_ready`` (never ``pass``). Quality-floor
    breaches on measurable critical slices yield ``fail`` (S2-02). Readiness is
    the weakest category (EVAL-23); AUDIT-07 requires naming the frame.
    """
    reasons: list[str] = []
    counts = scored.get("counts") or {}
    # F1d-4 / VLM-6-S2A-P-01: corpus-integrity counts live in scored["corpus"],
    # not counts (counts is the pinned {total, scored, failed} contract shape).
    corpus = scored.get("corpus") or {}
    caption = scored.get("caption") or {}
    faces = scored.get("faces") or {}
    ident = faces.get("identification") or {}

    failed = int(counts.get("failed") or 0)
    if failed > 0:
        reasons.append(f"failed-items: {failed} item(s) not scored")

    media_id_missing = int(corpus.get("media_id_missing") or 0)
    media_id_extra = int(corpus.get("media_id_extra") or 0)
    if media_id_missing or media_id_extra:
        reasons.append(f"truncation: media-id multiset differs (missing={media_id_missing}, extra={media_id_extra})")

    fetch_manifest_sha = (scored.get("provenance") or {}).get("manifest_sha256")
    if not fetch_manifest_sha:
        reasons.append("manifest-mismatch: run-record provenance missing fetch-time manifest_sha256")

    must_right_defined = int(caption.get("must_right_defined_images") or 0)
    easy_wrong_defined = int(caption.get("easy_wrong_defined_images") or 0)
    if must_right_defined == 0:
        reasons.append("empty-rubric: must_right is vacuous corpus-wide")
    if easy_wrong_defined == 0:
        reasons.append("empty-rubric: easy_wrong is vacuous corpus-wide")

    must_right_failed = int(caption.get("must_right_failed_images") or 0)
    # enforce only — skip is an explicit operator exemption (F1b-2 / F1-12).
    if rubric_gate != "skip" and must_right_failed > 0:
        reasons.append(f"must-right failures: {must_right_failed} image(s) failed Must-Right")

    # Vacuity only when images were scored but none entered identification
    # (recognition_enabled false). All-failed runs are the failed-items class.
    # VLM6-DELTA-03 (report-side): a structurally refused identification block
    # (boxed GT missing / roster_only mode) also serialises evaluated_images=0,
    # indistinguishable from a genuinely evaluated-but-zero corpus. Refusal is
    # reported separately (faces.identification.refused / category-vacuity);
    # this hard-fail reason must not fire for the refused case or it
    # permanently contaminates every verdict computed against an unboxed
    # corpus (e.g. the shipped scene/tests/seed/golden.json, README-documented
    # as roster_only with 34/37 unboxed claims) with an unrelated FAIL reason
    # (cli.py's parallel gate carries the identical exclusion — see
    # _cmd_score's SCORE_GATE_PREFIX_WRONG_NAME_FLOOR_VACUITY check).
    scored_n = int(counts.get("scored") or 0)
    identification_evaluated = int(ident.get("evaluated_images") or 0)
    if scored_n > 0 and not ident.get("refused") and identification_evaluated == 0:
        reasons.append("wrong-name floor vacuity: evaluated_images=0")

    # F1-7 / TEST-15: never compare a rounded rate. When the floor is 0.0 the
    # only non-vacuous signal is the wrong-name *count* — one wrong name among
    # ≥20001 images serialises as round(rate, 4) == 0.0 and 0.0 > 0.0 is false,
    # so a rate-only gate cannot go red. Display still rounds; the gate does not.
    rate = face_wrong_name_rate(scored)
    wrong_n = _total_wrong_name_count(ident)
    wrong_image_n = len(_wrong_name_images(ident))
    ignored_n = len(ident.get("ignored_wrong_names") or [])
    if WRONG_NAME_RATE_FLOOR == 0.0:
        floor_breach = wrong_n > 0
    else:
        floor_breach = rate > WRONG_NAME_RATE_FLOOR
    if floor_breach:
        reasons.append(
            # ``wrong_names`` is the count token the F1-7 rounding gate asserts on —
            # it is the only reason field that stays non-zero when round(rate, 4)
            # collapses to 0.0 at corpus scale. VLM6-S2A-B-09 added the image /
            # assertion split alongside it; it must not replace it (VLM6-LC-INT-02).
            f"wrong_name_rate={rate:.4f} exceeds floor={WRONG_NAME_RATE_FLOOR} "
            f"(wrong_names={wrong_n}, wrong_name_images={wrong_image_n}, "
            f"assertions={wrong_n}, ignored={ignored_n}, scored={scored_n})"
        )

    # S2-02: quality floors on critical slices (measured and bad → fail reasons).
    reasons.extend(build_score_quality_floor_reasons(scored, scored_n=scored_n))

    # Shared vacuity set with compare (S2-01 / S2-06 / EVAL-23 / AUDIT-07).
    vacuity_reasons = build_score_vacuity_reasons(scored, scored_n=scored_n)

    # Hard failures win; otherwise vacuity yields not_ready (not adoption pass).
    if reasons:
        verdict_value = ScoreVerdict.FAIL.value
        all_reasons = reasons + vacuity_reasons
    elif vacuity_reasons:
        verdict_value = ScoreVerdict.NOT_READY.value
        all_reasons = vacuity_reasons
    elif rubric_gate == "skip":
        verdict_value = ScoreVerdict.PASS_UNGATED.value
        all_reasons = []
    else:
        verdict_value = ScoreVerdict.PASS.value
        all_reasons = []
    return {
        "verdict": verdict_value,
        "reasons": all_reasons,
        # Display-only rounding — comparisons above use count / unrounded rate.
        # Rate is unique wrong-name images / scored (VLM6-S2A-B-09), not assertions.
        "wrong_name_rate": round(rate, 4),
        "wrong_name_rate_floor": WRONG_NAME_RATE_FLOOR,
        "wrong_name_images": wrong_image_n,
        "wrong_name_assertions": wrong_n,
        "insertion_rate": caption.get("insertion_rate"),
        "mean_gated_score": caption.get("mean_gated_score"),
        "must_right_failed_images": caption.get("must_right_failed_images"),
        # Operator-declared mode for the CLI must-right failures gate (F1b-2).
        "rubric_gate": rubric_gate,
    }


def _resolve_score_annotation_mode(
    annotation_mode: AnnotationMode | str | None,
    manifest_entries: Sequence[Mapping[str, Any]],
) -> AnnotationMode | None:
    """Resolve detection contract once from the data.

    Every scored entry must carry a stamp and those stamps must agree
    (mixed stamps fail loud). An explicit argument is compared against the
    stamp after that check — it may only *narrow* (most-restrictive-wins).
    Explicit ``exhaustive`` never overrides a ``roster_only`` stamp.
    Omission is not exhaustive.

    Zero entries **refuses** (``detection_refuses_empty_entries``), it is
    not scored as exhaustive. ``missing`` is only assigned inside the
    per-entry loop; an empty list never enters that loop, so returning
    ``explicit`` would fail-open an exhaustive request through the empty
    lattice cell (S2R3-01). Caption scoring maps this invariant onto a
    refused detection block — PUBLIC audience filtering can legitimately
    produce an empty entry list after withholding, and that path must
    still emit a report. Face scoring raises; it already fail-closes on
    any non-exhaustive resolve. Not a hard load error: an empty filtered
    public slice is a valid (vacuous) score, not a corrupt document.

    Per-entry lattice is raw-mapping-only by design (S2R3-10).
    ``GoldenEntry`` forbids ``annotation_mode`` (``extra="forbid"``, no
    field). Typed ``GoldenManifest`` is document-homogeneous: flatteners
    stamp the parent mode onto dumped entries. Mixed / per-entry stamps
    exist only on raw mappings passed to this resolver.
    """
    explicit = parse_annotation_mode(annotation_mode)
    if len(manifest_entries) == 0:
        raise ManifestError(
            "score entries are empty; zero entries cannot witness a "
            "detection contract (refusing explicit exhaustive fail-open)",
            invariant=ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES,
        )
    stamped: set[AnnotationMode] = set()
    missing = False
    for entry in manifest_entries:
        raw = entry.get("annotation_mode") if isinstance(entry, Mapping) else None
        parsed = parse_annotation_mode(raw)
        if parsed is None:
            missing = True
        else:
            stamped.add(parsed)
    # Mixed is strictly more dangerous than missing (S2R3-09): a document
    # that is both missing a stamp and mixed across the others must not
    # collapse to the missing-stamp refusal. Report both; mixed wins.
    if len(stamped) > 1:
        missing_note = "; also missing stamp on one or more entries" if missing else ""
        raise ReportError(
            f"mixed annotation_mode on score entries: "
            f"{sorted(member.value for member in stamped)}{missing_note}; "
            "refusing to guess which detection contract applies",
            invariant=ScoreInvariant.DETECTION_REFUSES_MIXED_ANNOTATION_MODE,
        )
    if missing:
        return None
    if not stamped:
        return explicit
    data = next(iter(stamped))
    if explicit is None:
        return data
    if _mode_restrictiveness(explicit) > _mode_restrictiveness(data):
        return explicit
    return data


def score_run_record(
    run_record: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
    ignore_list: dict[str, Any] | None = None,
    *,
    score_manifest_sha256: str | None = None,
    manifest_roster: list[str] | None = None,
    rubric_gate: str = "enforce",
    annotation_mode: AnnotationMode | str | None = None,
) -> dict[str, Any]:
    """Pure scoring: run record + manifest labels -> metrics dict.

    Detection P/R is computed only when the resolved ``annotation_mode`` is
    ``AnnotationMode.EXHAUSTIVE``. Mode is resolved from per-entry stamps
    (every scored entry must declare one; they must agree). An explicit
    argument may only narrow the stamp — it cannot widen ``roster_only``
    to exhaustive. ``roster_only``, a missing stamp, and an unrecognised
    token refuse; they never silently score unlabeled non-roster faces as
    false positives. Identification and caption metrics still run.
    Face-bakeoff scoring (``score_face_run_record``) raises instead.
    """
    # identity_names lives in this module (VLM6-RH-07) — no lazy cli import.
    _validate_record_kind(run_record)
    eval_mode = str(run_record["provenance"].get("eval_mode", "standard"))
    if eval_mode not in EVAL_MODES:
        raise ReportError(f"unknown eval_mode {eval_mode!r} in run-record provenance; expected one of {EVAL_MODES}")
    entries = _entry_index(manifest_entries)
    roster = _corpus_roster(manifest_entries, manifest_roster)
    caption_scores: list[CaptionScores] = []
    long_scores: list[CaptionScores] = []
    placement_scores: list[PlacementScores] = []
    hallucination_scores: list[Any] = []
    per_image: list[dict[str, Any]] = []
    detections: list[ImageDetection] = []
    identifications: list[ImageIdentities] = []
    positional_items: list[ImageIdentities] = []
    # VLM6-R2-G-01: GT-side y-missing disclosure (not predicted DEGRADED stamp).
    labeled_y_missing_images = 0
    labeled_y_missing_paths: list[str] = []
    identification_entries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    distractor_injected = 0
    distractor_taken = 0
    # ALTQ-1 v3 three-surface title axis (additive: all-zero when no record item
    # carries alt_text_title, and then nothing is surfaced in the report).
    titles_present = 0
    title_band_violations = 0
    title_hallucinated_images = 0
    title_hallucinated_names: set[str] = set()

    for item in run_record["items"]:
        media_id = int(item["media_id"])
        entry = entries.get(media_id)
        if entry is None:
            # Score-time manifest differs from fetch-time (e.g. an image was
            # pruned from the corpus). Record it, don't crash with a bare
            # KeyError (S3-04).
            failures.append(
                {
                    "path": str(item.get("path", f"media_id:{media_id}")),
                    "media_id": media_id,
                    "error": f"media_id {media_id} not in score-time manifest",
                }
            )
            continue
        path = str(entry["path"])
        if item.get("error"):
            failures.append({"path": path, "media_id": media_id, "error": str(item["error"])})
            continue
        recognition_enabled = bool(entry["policy"]["recognition_enabled"])
        describe = item.get("describe") or {}
        objects = list((describe.get("visual_facts") or {}).get("objects", []))
        # name_ablation runs cannot be held to Must-Right: the names were
        # withheld from the model, so requiring them would fail every image.
        # The per-item ablation stamp is REQUIRED (ALTQ-1-REV-A-03/B-03,
        # [GRPH-14]): an item without ``ablated_names`` was never transformed,
        # so charging its names as "leaks" would fabricate a model failure.
        must_right = list(entry["must_right"])
        if eval_mode == "name_ablation":
            must_right = []
            if "ablated_names" not in describe:
                failures.append(
                    {
                        "path": path,
                        "media_id": media_id,
                        "error": "name_ablation run-record item carries no ablated_names stamp — "
                        "context was not transformed at fetch time; refusing to score it as a leak check",
                    }
                )
                continue
        # A taken distractor must gate even when the fetch-time manifest drifted
        # from the score-time one (ALTQ-1-REV-A-02/B-04): trust the per-item
        # stamp over list membership.
        injected = describe.get("injected_distractor") if eval_mode == "context_distractor" else None
        easy_wrong = list(entry["easy_wrong"])
        if isinstance(injected, str) and injected and injected not in easy_wrong:
            easy_wrong.append(injected)
        score_kwargs: dict[str, Any] = {
            "present_identities": list(entry["present_identities"]),
            "must_right": must_right,
            "easy_wrong": easy_wrong,
            "recognition_enabled": recognition_enabled,
            "objects": objects or None,
            "roster": roster,
            "context_text": _context_text(entry) or None,
        }
        # ALTQ-1 Slice 2 degrade path: a ``short_error`` stamp means compression
        # to the short surface failed at fetch time — the long surface is kept
        # and scored, the short is marked failed instead of being charged to the
        # model as an empty caption. Absent the stamp (every pre-Slice-2 record)
        # the path below is byte-identical to the old behaviour.
        short_error = describe.get("short_error")
        scores: CaptionScores | None = None
        gated: float | None = None
        caption_text = ""
        if short_error is None:
            caption_text = str(describe.get("alt_text_draft", ""))
            scores = score_caption(caption_text, **score_kwargs)
            scores = _caption_scores_without_identity_spelling(
                caption_text,
                scores=scores,
                names=roster,
                score_kwargs=score_kwargs,
            )
            caption_scores.append(scores)
            gated = _ablation_gate(scores) if eval_mode == "name_ablation" else scores.gated_score

        long_text = describe.get("alt_text_long")
        long_s = score_caption(str(long_text), **score_kwargs) if isinstance(long_text, str) and long_text else None
        if long_s is not None:
            long_s = _caption_scores_without_identity_spelling(
                str(long_text),
                scores=long_s,
                names=roster,
                score_kwargs=score_kwargs,
            )
        if long_s is not None:
            long_scores.append(long_s)

        # VLM6-R4-02 / VLM6-R2-02: placement + fabricated-fact hallucination are
        # scored against manifest facts and MUST surface on the report (not drop).
        spatial_facts = _parse_spatial_facts(entry.get("spatial_facts"))
        reference_facts = _parse_reference_facts(entry.get("reference_facts"))
        place_s = score_placement(caption_text, spatial_facts=spatial_facts) if short_error is None else None
        if place_s is not None:
            placement_scores.append(place_s)
        face_count = int(entry["face_count"])
        hall_s = (
            score_hallucination(caption_text, reference_facts=reference_facts, face_count=face_count)
            if short_error is None
            else None
        )
        if hall_s is not None:
            hallucination_scores.append(hall_s)

        # ALTQ-1 v3: titles run through the SAME closed-roster name traps as
        # captions (score_caption) — a roster name the entry's context does not
        # account for appearing in a title is a hallucination, exactly as it
        # would be in the alt text. No new rubric axes: word band + name traps.
        title = describe.get("alt_text_title")
        if isinstance(title, str) and title.strip():
            titles_present += 1
            title_s = score_caption(title, **score_kwargs)
            if not (TITLE_WORD_BAND[0] <= title_s.word_count <= TITLE_WORD_BAND[1]):
                title_band_violations += 1
            title_bad_names = [*title_s.wrong_name_hits, *title_s.hallucinated_names]
            if title_bad_names:
                title_hallucinated_images += 1
                title_hallucinated_names.update(title_bad_names)

        taken: bool | None = None
        if isinstance(injected, str) and injected:
            distractor_injected += 1
            taken = (scores is not None and injected in scores.wrong_name_hits) or (
                long_s is not None and injected in long_s.wrong_name_hits
            )
            distractor_taken += int(taken)
        # Ground-truth total faces (incl. non-roster strangers), not just named
        # roster identities — otherwise every stranger face is a detection FP and
        # true_rejections is unreachable (S3-01, HARM-04). Required, not defaulted:
        # a missing face_count must fail loud, never silently re-create the bug.
        n_labeled = len(entry["present_identities"])
        if face_count < n_labeled:
            raise ReportError(
                f"{path} media_id={media_id}: face_count={face_count} < "
                f"len(present_identities)={n_labeled} "
                "(present_identities_fit_face_count)"
            )
        stranger_faces = face_count - n_labeled
        detections.append(
            ImageDetection(
                image=path,
                pred_faces=int(item.get("face_count", 0)),
                labeled_faces=face_count,
            )
        )
        # item["identities"] are positional dict rows from _extract_identities
        # ({name,bbox,unpositioned,...}). Set-based identification uses the name
        # multiset (order-blind). Positional L→R MUST use centre-x ordering
        # (VLM6-B-03 / EVAL-13) — corner-x and centre-x disagree when face widths
        # differ; identity_names alone cannot recover that.
        # Labeled order for the positional metric must NOT use present_identities
        # (alphabetical / XMP write order). Derive L→R from face_boxes centre x;
        # when face_boxes are missing, exclude from positional scoring (FL30A-GATE-01).
        # VLM6-R2-04: never feed alphabetical present_identities as labeled when
        # order is unknown — that was a dead/no-op path (excluded anyway) that
        # invited accidental re-enablement of alphabetical scoring.
        identities_raw = item.get("identities") or []
        try:
            predicted_names = identity_names(identities_raw)
        except (TypeError, ValueError) as exc:
            raise ReportError(str(exc)) from exc
        # Absolute-pixel wire bboxes need image size for normalized centre
        # (A-08). When capture size is missing, unit dims keep the same
        # within-image centre-x order without inventing a spatial scale.
        image_w = item.get("image_width")
        image_h = item.get("image_height")
        order_w = float(image_w) if image_w is not None else 1.0
        order_h = float(image_h) if image_h is not None else 1.0
        pos_predicted = predicted_names_for_positional(
            identities_raw, image_width=order_w, image_height=order_h
        )
        # Fallback only when rows are unusable (identities is None).
        if pos_predicted is None:
            pos_predicted = predicted_names
        present = list(entry["present_identities"])
        # VLM6-R2-G-01: prefer labeled_order so report can surface order_degraded
        # (y-missing per-box fallback). labeled_left_to_right is .names only.
        # RA-04: normalize blank/non-numeric y at this boundary (face_metrics raises).
        order_result = labeled_order(_normalize_face_boxes_for_order(entry.get("face_boxes") or []))
        ordered_labeled = order_result.names
        # RA-01: order_degraded L→R is not full spatial GT — exclude from positional
        # scoring (invented alpha order on missing-y must not yield position_accuracy).
        # Disclosure stays on labeled_y_missing_* (S2-07: do not overload degraded_*).
        if order_result.order_degraded:
            labeled_y_missing_images += 1
            labeled_y_missing_paths.append(path)
            labeled_order_known = False
        else:
            labeled_order_known = ordered_labeled is not None
        # VLM6-R4-06: predicted order is only spatial when the fetch stamp says so.
        # ``degraded`` means unpositioned rows were appended alphabetically — exclude
        # from positional scoring so the L→R swap metric is not contaminated.
        ordering_stamp = item.get("identity_ordering")
        predicted_order_known = ordering_stamp != IdentityOrdering.DEGRADED
        order_known = labeled_order_known and predicted_order_known
        # Set-based identification_pr still uses present_identities (order-blind).
        # Positional uses face-box L→R when both labeled and predicted order known.
        identifications.append(
            ImageIdentities(
                image=path,
                predicted=predicted_names,
                labeled=present,
                recognition_enabled=recognition_enabled,
                stranger_faces=stranger_faces,
            )
        )
        positional_items.append(
            ImageIdentities(
                image=path,
                # Centre-ordered + leftmost-wins names for the positional metric
                # (VLM6-B-03). predicted_rows lets positional_identification
                # re-apply the same rule if callers pass raw list order.
                predicted=pos_predicted,
                # When order is known, feed spatial L→R — never sort predicted.
                # When unknown, labeled=[] + labeled_order_known=False (exclude).
                labeled=list(ordered_labeled) if order_known else [],
                recognition_enabled=recognition_enabled,
                stranger_faces=stranger_faces,
                labeled_order_known=order_known,
                predicted_rows=list(identities_raw) if order_known else None,
                image_width=order_w if order_known else None,
                image_height=order_h if order_known else None,
            )
        )
        identification_entries.append(entry)
        row: dict[str, Any] = {
            "path": path,
            "media_id": media_id,
            "gated_score": gated,
            "must_right_failures": scores.must_right_failures if scores is not None else None,
            "policy_violation": scores.policy_violation if scores is not None else None,
            "wrong_name_hits": scores.wrong_name_hits if scores is not None else None,
            "hallucinated_names": scores.hallucinated_names if scores is not None else None,
            "inserted_identities": scores.inserted_identities if scores is not None else None,
            "missing_identities": scores.missing_identities if scores is not None else None,
            "fkre": round(scores.fkre, 2) if scores is not None else None,
            "repetition_ratio": round(scores.repetition_ratio, 4) if scores is not None else None,
            "tag_coverage": scores.tag_coverage if scores is not None else None,
            "first_sentence_gist_ok": scores.first_sentence_gist_ok if scores is not None else None,
            "meta_framing_hits": scores.meta_framing_hits if scores is not None else None,
            "context_duplication_ratio": (
                None
                if scores is None or scores.context_duplication_ratio is None
                else round(scores.context_duplication_ratio, 4)
            ),
            "sentence_count": scores.sentence_count if scores is not None else None,
            "name_front_loaded": scores.name_front_loaded if scores is not None else None,
            "cache_hit": bool(describe.get("cached", False)),  # contract field is 'cached' (HARM-02)
        }
        if place_s is not None:
            row["placement"] = {
                "accuracy": place_s.accuracy,
                "claims": place_s.claims,
                "correct": list(place_s.correct),
                "wrong": [[fact, evidence] for fact, evidence in place_s.wrong],
                "abstained": list(place_s.abstained),
            }
        if hall_s is not None:
            row["hallucination"] = {
                "fabricated": hall_s.fabricated,
                "fabricated_facts": [
                    {"kind": f.kind.value, "text": f.text, "matched_phrase": f.matched_phrase}
                    for f in hall_s.fabricated_facts
                ],
                "covered_facts": list(hall_s.covered_facts),
                "missing_facts": list(hall_s.missing_facts),
                "trap_count": hall_s.trap_count,
                "coverage": hall_s.coverage,
                "count_advisory": hall_s.count_advisory,
            }
        if short_error is not None:
            row["short_error"] = str(short_error)
        if long_s is not None:
            row["long"] = {
                "gated_score": _ablation_gate(long_s) if eval_mode == "name_ablation" else long_s.gated_score,
                "must_right_failures": long_s.must_right_failures,
                "wrong_name_hits": long_s.wrong_name_hits,
                "hallucinated_names": long_s.hallucinated_names,
                "inserted_identities": long_s.inserted_identities,
                "missing_identities": long_s.missing_identities,
                "meta_framing_hits": long_s.meta_framing_hits,
                "context_duplication_ratio": (
                    None if long_s.context_duplication_ratio is None else round(long_s.context_duplication_ratio, 4)
                ),
                "sentence_count": long_s.sentence_count,
                "word_count": long_s.word_count,
                "name_front_loaded": long_s.name_front_loaded,
            }
        if taken is not None:
            row["injected_distractor"] = injected
            row["distractor_taken"] = taken
        per_image.append(row)

    try:
        mode = _resolve_score_annotation_mode(annotation_mode, manifest_entries)
    except ManifestError as exc:
        if not _invariant_is(
            exc.invariant,
            ScoreInvariant.DETECTION_UNRECOGNISED_ANNOTATION_MODE,
            ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES,
        ):
            raise
        det = None
        detection_invariant = exc.invariant
    else:
        if mode is AnnotationMode.EXHAUSTIVE:
            try:
                require_exhaustive_box_coverage(manifest_entries)
            except ManifestError as exc:
                if not _invariant_is(
                    exc.invariant, DETECTION_UNCOVERED_FACE_COUNT_INVARIANT
                ):
                    raise
                det = None
                detection_invariant = exc.invariant
            else:
                if not detections:
                    det = None
                    detection_invariant = DETECTION_EMPTY_OBSERVATIONS_INVARIANT
                else:
                    det = detection_pr(detections, annotation_mode=mode)
                    detection_invariant = None
        elif mode is AnnotationMode.ROSTER_ONLY:
            det = None
            detection_invariant = ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
        else:
            det = None
            detection_invariant = ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE

    # Order-sensitive binding score (A-02): set-based identification_pr cannot
    # distinguish a correct left-to-right interleave from a swap of the same names.
    # Uses positional_items (face_boxes L→R labeled order), not alphabetical
    # present_identities (FL30A-GATE-01). Independent of the boxed-GT refusal
    # below — its own evaluable/status/vacuity_signal covers missing face_boxes.
    positional = positional_identification(positional_items)

    if not identification_entries:
        ident = None
        identification_invariant = IDENTIFICATION_EMPTY_OBSERVATIONS_INVARIANT
    else:
        try:
            require_boxed_identification_gt(
                _identification_metric_entries(identification_entries)
            )
        except ManifestError as exc:
            if not _invariant_is(exc.invariant, IDENTIFICATION_UNBOXED_INVARIANT):
                raise
            ident = None
            identification_invariant = exc.invariant
        else:
            ident = identification_pr(identifications)
            identification_invariant = None

    if ident is None:
        live_wrong: list[list[str]] = []
        ignored_wrong: list[list[str]] = []
        identification_evaluated = 0
    else:
        # Presentation split only: ignore-list moves pairs into ignored_wrong_names
        # for operator triage visibility. The wrong-name floor rate still counts
        # live + ignored (F1-5); a side file must not zero a hard gate.
        ignored_pairs = {tuple(p) for p in (ignore_list or {}).get("wrong_names", [])}
        live_wrong = [list(p) for p in ident.wrong_names if tuple(p) not in ignored_pairs]
        ignored_wrong = [list(p) for p in ident.wrong_names if tuple(p) in ignored_pairs]
        # Images that actually entered identification_pr counting (recognition_enabled).
        # Zero ⇒ wrong-name floor is vacuous regardless of asserted names (F1-5 / EVAL-19).
        identification_evaluated = len(identifications) - len(ident.excluded_images)

    # Surface fetch-time ordering degradation (A-07): missing/malformed bboxes
    # must not silently reinstate alphabetical name order without a number.
    ordering_positional = 0
    ordering_degraded = 0
    degraded_paths: list[str] = []
    for item in run_record["items"]:
        if item.get("error"):
            continue
        source = item.get("identity_ordering")
        path = str(item.get("path", item.get("media_id", "?")))
        # Exhaustive (sr-007, VLM6-RH-06): an unrecognized stamp used to take
        # neither branch, leaving both counters 0 — the A-07 loud surface failing
        # silently. ``None`` stays legal: it means the fetch never stamped.
        if source is None:
            continue
        if source == IdentityOrdering.DEGRADED:
            ordering_degraded += 1
            degraded_paths.append(path)
        elif source == IdentityOrdering.POSITIONAL:
            ordering_positional += 1
        else:
            raise ReportError(
                f"unknown identity_ordering {source!r} on {path}; "
                f"expected one of {[m.value for m in IdentityOrdering]} or absent"
            )

    fetch_provenance = dict(run_record["provenance"])
    provenance = {
        **fetch_provenance,
        # Manifest actually scored against — the fetch-time manifest_sha256 above
        # can differ if golden labels changed after the run (HARM-03).
        "score_manifest_sha256": score_manifest_sha256,
        "manifest_matches_fetch": (
            None if score_manifest_sha256 is None else score_manifest_sha256 == fetch_provenance.get("manifest_sha256")
        ),
        "model": _model_provenance(run_record["items"]),
        # RF-15: surface sample-size / chance-floor caveats in operator-facing
        # provenance (constants unchanged — disclosure only, not an sr-001 loosen).
        "quality_floor_caveat": (
            f"position_accuracy/placement floors are binary-chance "
            f"({POSITION_ACCURACY_FLOOR}); accuracy at the floor fails the gate"
        ),
    }
    scored_n_for_sample = len(per_image)
    if scored_n_for_sample < SCORE_PASS_MIN_SCORED_IMAGES:
        provenance["low_sample_warning"] = (
            f"scored={scored_n_for_sample} < SCORE_PASS_MIN_SCORED_IMAGES="
            f"{SCORE_PASS_MIN_SCORED_IMAGES}; green gates on small n are not "
            f"population evidence (AUDIT-07 / EVAL-03)"
        )

    # Vacuity is per-rubric, not OR'd: emptying only must_right while easy_wrong
    # remains must still trip the empty-rubric gate (VLM-6 S2A F1-1 / r08116b50).
    # F1-8 / EVAL-19: count only among successfully scored run-record items, not
    # the full score-time manifest. Un-rubriced scored items + omitted rubriced
    # manifest entries used to keep the counter non-zero while the measured set
    # had a vacuous rubric (empty-rubric then passed on a corpus it never scored).
    scored_entries = [entries[int(row["media_id"])] for row in per_image if int(row["media_id"]) in entries]
    must_right_defined_images = sum(1 for e in scored_entries if e.get("must_right"))
    easy_wrong_defined_images = sum(1 for e in scored_entries if e.get("easy_wrong"))

    # Media-id multiset coverage: fetch --limit N yields a partial run-record whose
    # provenance still stamps the full-corpus fetch sha. counts.total alone is
    # self-referential (scored=N/N) and never compared to the manifest (F1-2).
    manifest_media_ids = Counter(int(e["media_id"]) for e in manifest_entries)
    record_media_ids = Counter(int(item["media_id"]) for item in run_record["items"])
    media_id_missing = int(sum((manifest_media_ids - record_media_ids).values()))
    media_id_extra = int(sum((record_media_ids - manifest_media_ids).values()))

    def _quality_block(scores: list[CaptionScores], band: tuple[int, int]) -> dict[str, Any]:
        duplication = [s.context_duplication_ratio for s in scores if s.context_duplication_ratio is not None]
        front = [s.name_front_loaded for s in scores if s.name_front_loaded is not None]
        fkre_vals = [s.fkre for s in scores]
        rep_vals = [s.repetition_ratio for s in scores]
        tag_vals = [s.tag_coverage for s in scores if s.tag_coverage is not None]
        gist_vals = [s.first_sentence_gist_ok for s in scores if s.first_sentence_gist_ok is not None]
        return {
            "meta_framing_images": sum(1 for s in scores if s.meta_framing_hits),
            "mean_context_duplication": (round(sum(duplication) / len(duplication), 4) if duplication else None),
            "name_front_loaded_rate": (round(sum(front) / len(front), 4) if front else None),
            "sentence_band": list(band),
            "sentence_band_ok_rate": (
                round(sum(1 for s in scores if band[0] <= s.sentence_count <= band[1]) / len(scores), 4)
                if scores
                else None
            ),
            # Surface axes previously computed only on per_image then dropped
            # from the report aggregates (dead-path group).
            "mean_fkre": (round(sum(fkre_vals) / len(fkre_vals), 2) if fkre_vals else None),
            "mean_repetition_ratio": (round(sum(rep_vals) / len(rep_vals), 4) if rep_vals else None),
            "mean_tag_coverage": (round(sum(tag_vals) / len(tag_vals), 4) if tag_vals else None),
            "first_sentence_gist_ok_rate": (
                round(sum(1 for g in gist_vals if g) / len(gist_vals), 4) if gist_vals else None
            ),
        }

    # Use caption_metrics.aggregate_gated_scores so N/A rows (gated_score=None)
    # are excluded from the mean and the exclusion count is surfaced (la1 wiring).
    if eval_mode == "name_ablation":
        ablation_gates = [_ablation_gate(s) for s in caption_scores]
        gated_agg_values = [g for g in ablation_gates if g is not None]
        gated_mean = round(sum(gated_agg_values) / len(gated_agg_values), 4) if gated_agg_values else None
        gated_scored_n = len(gated_agg_values)
        gated_excluded_n = len(caption_scores) - gated_scored_n
    else:
        gated_agg = aggregate_gated_scores(caption_scores)
        gated_mean = None if gated_agg.mean is None else round(gated_agg.mean, 4)
        gated_scored_n = gated_agg.scored
        gated_excluded_n = gated_agg.excluded

    # Hallucination headline (VLM6-R2-02) + placement (VLM6-R4-02).
    by_kind = fabrication_by_kind(hallucination_scores)
    hall_block = {
        "fabricated_fact_rate": fabricated_fact_rate(hallucination_scores, over="all"),
        "fabricated_fact_rate_trapped": fabricated_fact_rate(hallucination_scores, over="trapped"),
        "images_with_traps": sum(1 for s in hallucination_scores if s.trap_count),
        "images_caught": sum(1 for s in hallucination_scores if s.fabricated),
        "trap_instances": sum(s.trap_count for s in hallucination_scores),
        "fabricated_instances": sum(len(s.fabricated_facts) for s in hallucination_scores),
        "by_kind": {k.value: v for k, v in sorted(by_kind.items(), key=lambda kv: kv[0].value)},
        "mean_coverage": (
            round(sum(coverage_vals) / len(coverage_vals), 4)
            if (coverage_vals := [s.coverage for s in hallucination_scores if s.coverage is not None])
            else None
        ),
        "count_advisory_images": sum(1 for s in hallucination_scores if s.count_advisory),
    }
    place_block = {
        "accuracy": placement_accuracy(placement_scores),
        "claims": sum(s.claims for s in placement_scores),
        "correct": sum(len(s.correct) for s in placement_scores),
        "wrong": sum(len(s.wrong) for s in placement_scores),
        "abstained": sum(len(s.abstained) for s in placement_scores),
        "images_scored": len(placement_scores),
    }

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": DocKind.REPORT.value,
        "eval_mode": eval_mode,
        "provenance": provenance,
        # counts is a pinned contract shape {total, scored, failed} (additive-schema
        # proof in test_eval_harness_pipeline). Corpus-integrity multiset fields
        # live in "corpus" so they cannot break that contract (F1d-4 / VLM-6-S2A-P-01).
        "counts": {
            "total": len(run_record["items"]),
            "scored": len(per_image),
            "failed": len(failures),
        },
        "corpus": {
            "manifest_entries": len(manifest_entries),
            "media_id_missing": media_id_missing,
            "media_id_extra": media_id_extra,
        },
        "caption": {
            "insertion_rate": insertion_rate(caption_scores),
            "name_precision": name_precision(caption_scores),
            "wrong_name_image_rate": wrong_name_image_rate(caption_scores),
            "must_right_failed_images": sum(1 for s in caption_scores if not s.must_right_pass),
            "must_right_defined_images": must_right_defined_images,  # 0 => Must-Right gate vacuous
            "easy_wrong_defined_images": easy_wrong_defined_images,  # 0 => Easy-Wrong trap vacuous
            "policy_violations": sum(1 for s in caption_scores if s.policy_violation),
            "wrong_name_images": sum(1 for s in caption_scores if s.named_wrong_person),
            "mean_gated_score": gated_mean,
            "gated_score_scored": gated_scored_n,
            "gated_score_excluded": gated_excluded_n,
        },
        "hallucination": hall_block,
        "placement": place_block,
        "quality": _quality_block(caption_scores, SHORT_SENTENCE_BAND),
        "faces": {
            "detection": (
                {
                    "refused": True,
                    "invariant": detection_invariant,
                    "precision": None,
                    "recall": None,
                    "tp": None,
                    "fp": None,
                    "fn": None,
                }
                if det is None
                else {
                    **_pr_dict(det.precision, det.recall),
                    "tp": det.true_positives,
                    "fp": det.false_positives,
                    "fn": det.false_negatives,
                }
            ),
            # A-02 / VLM6-B-10: "positional" is always computed — it has its own
            # evaluable/status/vacuity_signal/sampling_frame vacuity contract and
            # is independent of the boxed-GT refusal that can null out set-based
            # identification below (EVAL-23: consumers must not treat
            # position_accuracy is None alone as a soft skip).
            "identification": (
                {
                    **_refused_identification_metric(identification_invariant),
                    "evaluated_images": None,
                    "positional": {
                        "position_accuracy": positional.position_accuracy,
                        "position_hits": positional.position_hits,
                        "position_total": positional.position_total,
                        "exact_order_rate": positional.exact_order_rate,
                        "exact_order_images": positional.exact_order_images,
                        "compared_images": positional.compared_images,
                        "swap_images": positional.swap_images,
                        "excluded_images": list(positional.excluded_images),
                        "evaluable": positional.evaluable,
                        "status": positional.status,
                        "vacuity_signal": positional.vacuity_signal,
                        "sampling_frame": positional.sampling_frame,
                    },
                }
                if ident is None
                else {
                    **_pr_dict(ident.precision, ident.recall),
                    "macro_precision": ident.macro_precision,
                    "macro_recall": ident.macro_recall,
                    "per_identity": {
                        name: {
                            **_pr_dict(pr.precision, pr.recall),
                            "tp": pr.true_positives,
                            "fp": pr.false_positives,
                            "fn": pr.false_negatives,
                        }
                        for name, pr in ident.per_identity.items()
                    },
                    "true_rejections": ident.true_rejections,
                    "excluded_images": ident.excluded_images,
                    # recognition_enabled scored images; 0 ⇒ wrong-name floor vacuous (F1-5).
                    "evaluated_images": identification_evaluated,
                    "wrong_names": live_wrong,
                    "ignored_wrong_names": ignored_wrong,
                    "positional": {
                        "position_accuracy": positional.position_accuracy,
                        "position_hits": positional.position_hits,
                        "position_total": positional.position_total,
                        "exact_order_rate": positional.exact_order_rate,
                        "exact_order_images": positional.exact_order_images,
                        "compared_images": positional.compared_images,
                        "swap_images": positional.swap_images,
                        # Legacy entries without face_boxes: order unknown (FL30A-GATE-01).
                        "excluded_images": list(positional.excluded_images),
                        "evaluable": positional.evaluable,
                        "status": positional.status,
                        "vacuity_signal": positional.vacuity_signal,
                        "sampling_frame": positional.sampling_frame,
                    },
                }
            ),
            # A-07 / VLM6-R2-04 / S2-07: degraded_images means identity_ordering
            # stamp was DEGRADED — not positional exclusions. Vacuity of
            # face_boxes-absent images is ``order_unknown_excluded`` (own counter;
            # rg-015: do not invent contract metadata by overloading degraded).
            # VLM6-R2-G-01: labeled_y_missing_* is GT-side order_degraded (missing
            # y on named face_boxes) — a different condition from degraded_images.
            "identity_ordering": {
                "positional_images": ordering_positional,
                "degraded_images": ordering_degraded,
                "degraded_paths": list(degraded_paths),
                "order_unknown_excluded": len(positional.excluded_images),
                "labeled_y_missing_images": labeled_y_missing_images,
                "labeled_y_missing_paths": list(labeled_y_missing_paths),
            },
        },
        "per_image": per_image,
        "failures": failures,
    }
    # VLM6-R4-05: per-stratum caption/placement/positional floors (EVAL-04).
    result["strata"] = _stratum_blocks(
        per_image=per_image,
        entries=entries,
        positional_items=positional_items,
        caption_scores=caption_scores,
        placement_scores=placement_scores,
    )
    # VLM-6 S2A: machine-readable scored verdict (pass/fail + reasons). Built
    # after the face/caption blocks so rate derives from live wrong_names.
    # rubric_gate is operator-declared CLI mode (enforce|skip), not derived
    # from scores — recorded so skipped harness-shakedown runs stay self-describing.
    result["verdict"] = build_score_verdict(result, rubric_gate=rubric_gate)

    # ALTQ-1 Slice 2: surfaced only when a short compression actually failed so
    # pre-Slice-2 records keep their exact report shape (additive schema).
    short_failed_images = sum(1 for r in per_image if "short_error" in r)
    if short_failed_images:
        result["caption"]["short_failed_images"] = short_failed_images

    # ALTQ-1 v3: surfaced only when at least one item carries alt_text_title so
    # every pre-v3 record keeps its exact report shape (additive schema).
    if titles_present:
        result["quality"]["title"] = {
            "title_present": titles_present,
            "word_band": list(TITLE_WORD_BAND),
            "word_band_violations": title_band_violations,
            "hallucinated_name_images": title_hallucinated_images,
            "hallucinated_names": sorted(title_hallucinated_names),
        }

    # ALTQ-1 Slice 3: additive latency axis — omitted entirely when the record
    # carries no timing data so untimed records keep their exact report shape.
    latency = _latency_summary(run_record["items"])
    if latency is not None:
        result["latency"] = latency

    if long_scores:
        long_gated = [
            g
            for s in long_scores
            if (g := (_ablation_gate(s) if eval_mode == "name_ablation" else s.gated_score)) is not None
        ]
        result["caption_long"] = {
            "images_with_long": len(long_scores),
            "insertion_rate": insertion_rate(long_scores),
            "name_precision": name_precision(long_scores),
            "wrong_name_image_rate": wrong_name_image_rate(long_scores),
            "wrong_name_images": sum(1 for s in long_scores if s.named_wrong_person),
            "mean_gated_score": (round(sum(long_gated) / len(long_gated), 4) if long_gated else None),
            "mean_word_count": round(sum(s.word_count for s in long_scores) / len(long_scores), 1),
            "quality": _quality_block(long_scores, LONG_SENTENCE_BAND),
        }

    if eval_mode == "context_distractor":
        result["distractor"] = {
            "injected_images": distractor_injected,
            "taken_images": distractor_taken,
            "resistance_rate": (round(1 - distractor_taken / distractor_injected, 4) if distractor_injected else None),
        }
    if eval_mode == "name_ablation":
        # Derive from the gate itself so a leaked-but-recognition-disabled row
        # counts (ALTQ-1-REV-A-04): _ablation_gate returns 0.0 for any leak,
        # None only for clean ineligible rows.
        gates = [_ablation_gate(s) for s in caption_scores]
        counted = [g for g in gates if g is not None]
        leaks = sum(1 for g in counted if g == 0.0)
        result["ablation"] = {
            "eligible_images": len(counted),
            "leak_images": leaks,
            "leak_free_rate": (round(1 - leaks / len(counted), 4) if counted else None),
        }

    return result


def _fmt_prov(value: object, *, default: str = "unknown") -> str:
    """Render provenance fields for markdown (S4-05 / HARM-04).

    JSON null must read as ``null``, not the Python identifier ``None``.
    Booleans render as JSON ``true``/``false``, not Python ``True``/``False``.

    Empty-string → default is intentionally live: producers may still emit ""
    for free-text provenance (base_url, manifest_sha256, started_at, face model
    fields) even if head_sha has been tightened to None. Do not delete this
    branch without a producer-invariant test that fails when any producer
    reintroduces "" (VLM6-R2-A-04).
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value == "":
        return default
    return str(value)


def _fmt(value: float | None) -> str:
    return "null" if value is None else f"{value:.3f}"


def _stratum_blocks(
    *,
    per_image: list[dict[str, Any]],
    entries: dict[int, dict[str, Any]],
    positional_items: list[ImageIdentities],
    caption_scores: list[CaptionScores],
    placement_scores: list[PlacementScores],
) -> dict[str, Any]:
    """Per-difficulty / per-domain aggregates for caption + placement + positional (VLM6-R4-05).

    Mirrors the face bake-off ``by_cohort`` shape: each stratum carries ``n`` and the
    headline rates so Simpson's paradox is visible at the caption gate.
    """
    # Map path → positional item for order-sensitive rates.
    pos_by_path = {item.image: item for item in positional_items}

    def _bucket_key(entry: dict[str, Any], field: str) -> str:
        raw = entry.get(field)
        if raw is None or raw == "":
            return "unspecified"
        return str(raw)

    def _build(field: str) -> dict[str, Any]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in per_image:
            media_id = int(row["media_id"])
            entry = entries.get(media_id)
            if entry is None:
                continue
            key = _bucket_key(entry, field)
            buckets.setdefault(key, []).append(row)
        out: dict[str, Any] = {}
        for key, rows in sorted(buckets.items()):
            gated = [r["gated_score"] for r in rows if r.get("gated_score") is not None]
            place_acc = [
                r["placement"]["accuracy"]
                for r in rows
                if isinstance(r.get("placement"), dict) and r["placement"].get("accuracy") is not None
            ]
            # Positional within stratum: re-score only items in this bucket.
            pos_items = [pos_by_path[r["path"]] for r in rows if r["path"] in pos_by_path]
            pos = positional_identification(pos_items) if pos_items else None
            wrong_name_images = sum(1 for r in rows if r.get("wrong_name_hits") or r.get("hallucinated_names"))
            out[key] = {
                "n": len(rows),
                "mean_gated_score": (round(sum(gated) / len(gated), 4) if gated else None),
                "wrong_name_images": wrong_name_images,
                "placement_accuracy": (round(sum(place_acc) / len(place_acc), 4) if place_acc else None),
                "positional": (
                    {
                        "compared_images": pos.compared_images,
                        "position_accuracy": pos.position_accuracy,
                        "exact_order_rate": pos.exact_order_rate,
                        "swap_images": pos.swap_images,
                        "excluded_images": len(pos.excluded_images),
                    }
                    if pos is not None
                    else None
                ),
            }
        return out

    # caption_scores / placement_scores kept in signature for call-site symmetry;
    # per_image already carries the rolled values we need.
    _ = caption_scores, placement_scores
    return {
        "by_difficulty": _build("difficulty"),
        "by_domain": _build("domain"),
    }


def _placement_vacuity_lines(place: dict[str, Any]) -> list[str]:
    """Disclose how little the placement number is standing on (VLM6-R4-03).

    ``score_placement`` only counts a fact when the caption contains a near-verbatim
    substring of an authored phrase or its token-swapped inversion; a paraphrase
    ("Bob in the middle, flanked by Alice and Carol" against a BETWEEN fact) is
    dropped from the denominator as "no claim", not scored wrong. So a ``None`` or
    near-1.0 accuracy is not evidence of correct placement — it can just mean the
    model phrased things its own way. Publishing the denominator alongside the
    number is the disclosure; a validated-judge scorer (EVAL-11) is Slice 2 work.
    """
    claims = int(place.get("claims") or 0)
    abstained = int(place.get("abstained") or 0)
    if claims == 0:
        return [
            "- ⚠️ **placement is VACUOUS**: 0 asserted claims — every spatial fact was "
            "abstained or the corpus defines no `spatial_facts`. The accuracy above is "
            "not evidence of placement correctness.",
        ]
    if abstained > claims:
        return [
            f"- ⚠️ placement accuracy is computed over a minority of facts: {claims} asserted "
            f"vs {abstained} abstained. Near-verbatim matching drops paraphrased placement "
            f"claims from the denominator rather than scoring them wrong.",
        ]
    return []


def _manifest_drift_line(prov: dict[str, Any]) -> str:
    """Provenance line for the score-time manifest, loud on drift (VLM6-R2-06).

    Drift is deliberately not a hard gate (``_manifest_sha`` hashes ``model_dump()``,
    so any label edit would permanently block re-scoring archived baselines — see
    the F1-3 note in ``cli._cmd_score``). But ``(matches fetch: False)`` buried in a
    provenance list read as an ordinary pass: a candidate scored against a different
    corpus revision than it was fetched under produced evidence that looked valid.
    Shared by the caption and face renderers so the face report cannot omit it.
    """
    matches = prov.get("manifest_matches_fetch")
    # RB-05: never interpolate raw Python None/True/False into published markdown.
    line = (
        f"- score manifest_sha256: `{_fmt_prov(prov.get('score_manifest_sha256'))}` "
        f"(matches fetch: {_fmt_prov(matches)})"
    )
    if matches is False:
        return (
            f"{line}\n"
            "- ⚠️ **MANIFEST DRIFT**: scored against a different corpus revision than the run "
            "was fetched under. Rubric/label edits since the fetch are inside these numbers; "
            "they are not comparable to a baseline scored on the fetch-time manifest."
        )
    return line


def _markdown(scored: dict[str, Any]) -> str:
    prov = scored["provenance"]
    model = prov.get("model", {})
    cap = scored["caption"]
    det = scored["faces"]["detection"]
    ident = scored["faces"]["identification"]
    adapters = ", ".join(model.get("adapters", [])) or "unknown"
    model_ids = ", ".join(model.get("model_ids", [])) or "unknown"
    lines = [
        "# Caption + Face Eval Report",
        "",
        f"- schema: `{scored['schema']}` kind: `{scored.get('kind', 'report')}`",
        f"- adapter(s): `{adapters}` model(s): `{model_ids}` version(s): "
        f"`{', '.join(model.get('model_versions', [])) or 'unknown'}`",
        f"- head_sha: `{_fmt_prov(prov.get('head_sha'))}`",
        f"- base_url: {_fmt_prov(prov.get('base_url'))}",
        f"- fetch manifest_sha256: `{_fmt_prov(prov.get('manifest_sha256'))}`",
        _manifest_drift_line(prov),
        f"- started_at: {_fmt_prov(prov.get('started_at'))}",
        f"- images: {scored['counts']['scored']}/{scored['counts']['total']} scored, "
        f"{scored['counts']['failed']} failed",
    ]
    # RF-15: low-sample / chance-floor caveats must be operator-visible, not
    # source-comment-only.
    if prov.get("low_sample_warning"):
        lines.append(f"- ⚠️ **low_sample_warning**: {_fmt_prov(prov.get('low_sample_warning'))}")
    if prov.get("quality_floor_caveat"):
        lines.append(f"- quality_floor_caveat: {_fmt_prov(prov.get('quality_floor_caveat'))}")
    verdict = scored.get("verdict") or {}
    if verdict:
        rate = verdict.get("wrong_name_rate")
        floor = verdict.get("wrong_name_rate_floor")
        lines.append(
            f"- verdict: **{verdict.get('verdict', 'unknown')}** "
            f"(wrong_name_rate={_fmt(rate) if isinstance(rate, int | float) else rate}, "
            f"floor={_fmt(floor) if isinstance(floor, int | float) else floor})"
        )
        # F1b-2: always surface rubric_gate so skip mode is never silent in MD.
        if verdict.get("rubric_gate") is not None:
            lines.append(f"- rubric_gate: `{verdict.get('rubric_gate')}`")
        for reason in verdict.get("reasons") or []:
            lines.append(f"- verdict reason: {reason}")
    # Honest redaction: public reports must state what they withheld (VLM-6 S1).
    redaction = scored.get("redaction")
    if redaction:
        unknown_n = redaction.get("unknown_media_items", 0)
        withheld_manifest = redaction.get("withheld_manifest_entries")
        redaction_bits = [
            f"withheld {redaction['withheld_items']} of {redaction['total_items']} items (local-only / non-publishable)"
        ]
        if unknown_n:
            redaction_bits.append(f"{unknown_n} unknown-media item(s) (corpus integrity, not privacy)")
        if withheld_manifest is not None:
            redaction_bits.append(
                f"withheld_manifest_entries={withheld_manifest}/{redaction.get('total_manifest_entries', '?')}"
            )
        lines.append(f"- redaction: audience=`{redaction['audience']}` — " + "; ".join(redaction_bits))
    estimand = scored.get("estimand")
    if estimand:
        lines.append(
            f"- estimand: population=`{estimand.get('population')}` — "
            f"annotation_mode and coverage resolved on `{estimand.get('resolved_on')}` "
            f"({estimand.get('n_items')} items / {estimand.get('n_entries')} entries); "
            "not the unfiltered corpus"
        )
    if "seeded" in model.get("adapters", []):
        lines.append(
            "- ⚠ produced by the model-free `seeded` stub adapter — harness-shakedown "
            "numbers, NOT a caption-model baseline."
        )
    if "bakeoff" in model.get("adapters", []):
        lines.append(
            "- ⚠ produced by the throwaway `bakeoff` transport (VLM-2B) — face detection/"
            "identification sections below are **vacuous by design** (stub `analyze`/"
            "`media_identities`); 0% is expected, NOT a recognition regression."
        )
    if prov.get("weave_bench"):
        source = prov.get("weave_bench_source") or {}
        lines.append(
            "- ⚠ weave-bench replay: pass-2 re-run text-only from recorded pass-1 facts "
            f"(source run: `{source.get('path', 'unknown')}` sha256 `{source.get('sha256', 'unknown')}`); "
            "no image was sent — NOT comparable to image-grounded runs."
        )
    if cap.get("must_right_defined_images", 0) == 0:
        lines.append("- ⚠ no Must-Right rubric entries in the corpus — the caption hard gate is vacuous.")
    if cap.get("easy_wrong_defined_images", 0) == 0:
        lines.append("- ⚠ no Easy-Wrong rubric entries in the corpus — the wrong-name trap is vacuous.")
    eval_mode = scored.get("eval_mode", "standard")
    if eval_mode != "standard":
        lines.append(
            f"- ⚠ eval_mode: **{eval_mode}** — context was transformed at fetch time; "
            "metrics are mode-specific, NOT comparable to standard runs."
        )
    # ALTQ-1 Slice 2 attribution: the prompt/pipeline config that produced the
    # captions (absent on pre-Slice-2 records — nothing rendered then).
    prompt_variant = prov.get("prompt_variant")
    if prompt_variant:
        pipeline_flags = [flag for flag in ("two_pass", "dual_length", "face_gate") if prov.get(flag)]
        lines.append(
            f"- prompt variant: `{prompt_variant}`"
            + (f" pipeline: {', '.join(pipeline_flags)}" if pipeline_flags else "")
        )
    if cap.get("short_failed_images"):
        lines.append(
            f"- ⚠ short-surface compression failed on {cap['short_failed_images']} image(s) — "
            "long surface kept and scored; short surface excluded from caption metrics."
        )
    latency = scored.get("latency")
    if latency:
        wall = latency["wall_clock_s"]
        calls = latency["model_calls"]
        excl_bits: list[str] = []
        if latency.get("cache_hits_excluded"):
            excl_bits.append(f"cache-hits excluded={latency['cache_hits_excluded']}")
        if latency.get("error_items_excluded"):
            excl_bits.append(f"errors excluded={latency['error_items_excluded']}")
        if latency.get("timed_out_images"):
            excl_bits.append(f"timed-out={latency['timed_out_images']}")
        excl_note = f", {', '.join(excl_bits)}" if excl_bits else ""
        p99 = wall.get("p99")
        wall_max = wall.get("max")
        tail = ""
        if p99 is not None or wall_max is not None:
            tail = f" p99 {p99}s max {wall_max}s"
        caveat = latency.get("percentile_caveat")
        caveat_note = f" ⚠ {caveat}" if caveat else ""
        lines.append(
            f"- latency: per-image wall-clock p50 {wall['p50']}s p95 {wall['p95']}s{tail} "
            f"({latency['images_timed']} timed{excl_note}) · model calls/image: {calls['per_image_mean']} "
            f"(total {calls['total']}){caveat_note}"
        )
    lines += [
        "",
        "## Caption metrics (deterministic tier)",
        "",
        f"- insertion rate: {_fmt(cap['insertion_rate'])}",
        f"- name precision: {_fmt(cap.get('name_precision'))} "
        f"(wrong-name images: {cap.get('wrong_name_images', 0)}, "
        f"rate: {_fmt(cap.get('wrong_name_image_rate'))})",
        f"- Must-Right failed images (hard gate): {cap['must_right_failed_images']} "
        f"(must_right-defined images: {cap['must_right_defined_images']}; "
        f"easy_wrong-defined images: {cap.get('easy_wrong_defined_images')})",
        f"- policy violations: {cap['policy_violations']}",
        f"- mean gated score: {_fmt(cap['mean_gated_score'])} "
        f"(scored={cap.get('gated_score_scored')}, excluded={cap.get('gated_score_excluded')})",
    ]
    hall = scored.get("hallucination") or {}
    if hall:
        by_kind = hall.get("by_kind") or {}
        kind_bits = ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())) or "none"
        lines += [
            f"- fabricated-fact rate: {_fmt(hall.get('fabricated_fact_rate'))} "
            f"(caught={hall.get('images_caught')}/{hall.get('images_with_traps')} trap images; "
            f"instances={hall.get('fabricated_instances')}/{hall.get('trap_instances')})",
            f"- fabricated by kind: {kind_bits}",
            f"- true-fact coverage: {_fmt(hall.get('mean_coverage'))}",
        ]
    place = scored.get("placement") or {}
    if place:
        lines += [
            f"- placement accuracy: {_fmt(place.get('accuracy'))} "
            f"(correct={place.get('correct')} wrong={place.get('wrong')} "
            f"claims={place.get('claims')} abstained={place.get('abstained')})",
        ]
        lines += _placement_vacuity_lines(place)
    strata = scored.get("strata") or {}
    if strata.get("by_difficulty") or strata.get("by_domain"):
        lines += ["", "### Strata (difficulty / domain)", ""]
        for axis, label in (("by_difficulty", "difficulty"), ("by_domain", "domain")):
            block = strata.get(axis) or {}
            for key, stats in block.items():
                pos = stats.get("positional") or {}
                lines.append(
                    f"- {label}={key}: n={stats.get('n')} "
                    f"mean_gated={_fmt(stats.get('mean_gated_score'))} "
                    f"wrong_name_images={stats.get('wrong_name_images')} "
                    f"placement={_fmt(stats.get('placement_accuracy'))} "
                    f"positional={_fmt(pos.get('position_accuracy'))} "
                    f"(compared={pos.get('compared_images')})"
                )

    def _quality_lines(quality: dict[str, Any]) -> list[str]:
        band = quality.get("sentence_band", [])
        return [
            f"- meta-framing images: {quality['meta_framing_images']}",
            f"- mean context duplication: {_fmt(quality['mean_context_duplication'])}",
            f"- name front-loaded rate: {_fmt(quality['name_front_loaded_rate'])}",
            f"- sentence band {band} ok rate: {_fmt(quality['sentence_band_ok_rate'])}",
            f"- mean FKRE: {_fmt(quality.get('mean_fkre'))}",
            f"- mean repetition ratio: {_fmt(quality.get('mean_repetition_ratio'))}",
            f"- mean tag coverage: {_fmt(quality.get('mean_tag_coverage'))}",
            f"- first-sentence gist ok rate: {_fmt(quality.get('first_sentence_gist_ok_rate'))}",
        ]

    lines += ["", "## Quality axes (short surface, report-only signals)", ""]
    lines += _quality_lines(scored["quality"])
    title_q = scored["quality"].get("title")
    if title_q:
        lines += [
            f"- titles present: {title_q['title_present']}",
            f"- title word band {title_q['word_band']} violations: {title_q['word_band_violations']}",
            f"- title hallucinated-name images: {title_q['hallucinated_name_images']}"
            + (f" ({', '.join(title_q['hallucinated_names'])})" if title_q["hallucinated_names"] else ""),
        ]
    if "caption_long" in scored:
        long_c = scored["caption_long"]
        lines += [
            "",
            "## Long surface (alt_text_long)",
            "",
            f"- images with long: {long_c['images_with_long']}",
            f"- insertion rate: {_fmt(long_c['insertion_rate'])} name precision: {_fmt(long_c['name_precision'])}",
            f"- wrong-name images: {long_c['wrong_name_images']}",
            f"- mean gated score: {_fmt(long_c['mean_gated_score'])}",
            f"- mean word count: {long_c['mean_word_count']}",
        ]
        lines += _quality_lines(long_c["quality"])
    if "distractor" in scored:
        d = scored["distractor"]
        lines += [
            "",
            "## Context-distractor resistance",
            "",
            f"- injected: {d['injected_images']} taken: {d['taken_images']} resistance: {_fmt(d['resistance_rate'])}",
        ]
    if "ablation" in scored:
        a = scored["ablation"]
        lines += [
            "",
            "## Name-ablation leak check",
            "",
            f"- eligible: {a['eligible_images']} leaks: {a['leak_images']} leak-free rate: {_fmt(a['leak_free_rate'])}",
        ]
    lines += [
        "",
        "## Face detection (identity-agnostic)",
        "",
        (
            f"- REFUSED ({det.get('invariant')}): {refusal_explanation(det.get('invariant'))}"
            if det.get("refused")
            else (
                f"- precision: {_fmt(det['precision'])} recall: {_fmt(det['recall'])} "
                f"(tp={det['tp']} fp={det['fp']} fn={det['fn']})"
            )
        ),
        "",
        "## Face identification (named assertions)",
        "",
    ]
    positional_block = ident.get("positional") or {}
    if positional_block:
        lines += [
            f"- positional accuracy (L→R order): {_fmt(positional_block.get('position_accuracy'))} "
            f"(hits={positional_block.get('position_hits')} / "
            f"{positional_block.get('position_total')}; "
            f"exact-order images={positional_block.get('exact_order_images')}/"
            f"{positional_block.get('compared_images')}; "
            f"swaps={positional_block.get('swap_images')}; "
            f"status={positional_block.get('status')}; "
            f"evaluable={positional_block.get('evaluable')})",
        ]
        # VLM6-B-10: surface vacuity loudly in MD (not only JSON).
        if positional_block.get("evaluable") is False or positional_block.get("vacuity_signal"):
            lines.append(
                f"- positional vacuity: {positional_block.get('vacuity_signal') or 'not_evaluable'} "
                f"(sampling_frame={positional_block.get('sampling_frame')})"
            )
    ordering = scored["faces"].get("identity_ordering") or {}
    if ordering.get("degraded_images"):
        lines += [
            f"- ⚠ identity ordering degraded on {ordering['degraded_images']} image(s) "
            f"(missing/malformed bbox → not pure L→R): "
            + ", ".join(f"`{p}`" for p in ordering.get("degraded_paths", [])),
        ]
    # VLM6-R2-G-01: GT-side y-missing is its own counter (not degraded_images).
    if ordering.get("labeled_y_missing_images"):
        lines += [
            f"- ⚠ labeled L→R y-missing (order_degraded) on "
            f"{ordering['labeled_y_missing_images']} image(s): "
            + ", ".join(f"`{p}`" for p in ordering.get("labeled_y_missing_paths", [])),
        ]
    # S2-07: exclusions are their own counter — do not overload degraded_images.
    if ordering.get("order_unknown_excluded"):
        lines += [
            f"- ⚠ identity order unknown (no face_boxes) on "
            f"{ordering['order_unknown_excluded']} image(s) — positional excluded",
        ]
    if ident.get("refused"):
        lines.append(
            f"- REFUSED ({ident.get('invariant')}): "
            f"{refusal_explanation(ident.get('invariant'))}"
        )
    else:
        lines += [
            f"- micro precision: {_fmt(ident['precision'])} recall: {_fmt(ident['recall'])}",
            f"- macro precision: {_fmt(ident['macro_precision'])} recall: {_fmt(ident['macro_recall'])}",
            f"- true rejections (strangers): {ident['true_rejections']}",
            "",
            "### Wrong-name errors (top product risk — every instance listed)",
            "",
        ]
        if ident["wrong_names"]:
            lines += [f"- `{image}` → asserted **{name}**" for image, name in ident["wrong_names"]]
        else:
            lines.append("- none")
        lines.append(f"- ignored (triaged): {len(ident['ignored_wrong_names'])}")
        lines += ["", "### Per-identity (macro components)", ""]
        for name, pr in ident["per_identity"].items():
            lines.append(
                f"- {name}: precision={_fmt(pr['precision'])} recall={_fmt(pr['recall'])} "
                f"(tp={pr['tp']} fp={pr['fp']} fn={pr['fn']})"
            )
    lines += _baseline_delta_lines(
        scored.get("baseline_delta") if isinstance(scored.get("baseline_delta"), Mapping) else None
    )
    lines += ["", "## Per-item failures", ""]
    if scored["failures"]:
        lines += [f"- `{f['path']}` (media_id={f['media_id']}): {f['error']}" for f in scored["failures"]]
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _stamp_value(raw: object) -> str:
    """Render a stamp for refusal messages, including a named missing value."""
    if raw is None:
        return "missing"
    text = str(raw).strip()
    return text if text else "missing"


def _paired_gated_delta(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    """Paired mean Δ on per-image gated_score, with a 95% interval.

    n=20 held-out is underpowered. If the interval includes 0, the headline is
    that we cannot tell the candidate from the zero-rule — not a quiet omit.
    """
    cand_by_id = {
        int(row["media_id"]): row.get("gated_score")
        for row in candidate.get("per_image") or []
        if isinstance(row, Mapping) and row.get("media_id") is not None
    }
    base_by_id = {
        int(row["media_id"]): row.get("gated_score")
        for row in baseline.get("per_image") or []
        if isinstance(row, Mapping) and row.get("media_id") is not None
    }
    diffs: list[float] = []
    for media_id in sorted(set(cand_by_id) & set(base_by_id)):
        cand_val, base_val = cand_by_id[media_id], base_by_id[media_id]
        if cand_val is None or base_val is None:
            continue
        diffs.append(float(cand_val) - float(base_val))
    n = len(diffs)
    if n == 0:
        return {
            "n_paired": 0,
            "mean_delta": None,
            "ci95": None,
            "undistinguished": True,
            "headline": "we cannot tell yet: no paired gated_score rows",
        }
    mean = sum(diffs) / n
    if n < 2:
        return {
            "n_paired": n,
            "mean_delta": round(mean, 4),
            "ci95": None,
            "undistinguished": True,
            "headline": f"we cannot tell yet at n={n}",
        }
    variance = sum((delta - mean) ** 2 for delta in diffs) / (n - 1)
    se = math.sqrt(variance / n)
    half = 1.96 * se
    lo, hi = mean - half, mean + half
    undistinguished = lo <= 0 <= hi
    if undistinguished:
        headline = (
            f"we cannot tell yet at n={n}: 95% CI for Δ mean_gated_score "
            f"[{lo:.4f}, {hi:.4f}] includes 0"
        )
    else:
        headline = (
            f"Δ mean_gated_score={mean:.4f} 95% CI [{lo:.4f}, {hi:.4f}] excludes 0 "
            f"(n={n}; still not a global claim on this imbalanced held-out set)"
        )
    return {
        "n_paired": n,
        "mean_delta": round(mean, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "undistinguished": undistinguished,
        "headline": headline,
    }


def compare_scored_runs(
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    """EVAL-01 Δ between two already-scored reports, or an explicit refusal.

    Refuses when the runs disagree on score-time corpus identity
    (``score_manifest_sha256``) or roster-spelling epoch (``roster_epoch``).
    Missing stamps are named and refused — never treated as matching. A
    refused comparison never includes a computed ``metrics`` block.
    """
    cand_prov = candidate.get("provenance") if isinstance(candidate.get("provenance"), Mapping) else {}
    base_prov = baseline.get("provenance") if isinstance(baseline.get("provenance"), Mapping) else {}
    cand_sha = cand_prov.get("score_manifest_sha256")
    base_sha = base_prov.get("score_manifest_sha256")
    cand_epoch = cand_prov.get("roster_epoch")
    base_epoch = base_prov.get("roster_epoch")
    mismatches: list[str] = []
    if _stamp_value(cand_sha) != _stamp_value(base_sha) or cand_sha is None or base_sha is None:
        mismatches.append(
            f"score_manifest_sha256 candidate={_stamp_value(cand_sha)!r} "
            f"baseline={_stamp_value(base_sha)!r}"
        )
    if _stamp_value(cand_epoch) != _stamp_value(base_epoch) or cand_epoch is None or base_epoch is None:
        mismatches.append(
            f"roster_epoch candidate={_stamp_value(cand_epoch)!r} "
            f"baseline={_stamp_value(base_epoch)!r}"
        )
    if mismatches:
        reason = "refusing Δ across straddled stamps: " + "; ".join(mismatches)
        return {
            "refused": True,
            "invariant": DELTA_REFUSES_STRADDLED_STAMPS,
            "reason": reason,
            "metrics": None,
            "power": None,
        }
    cand_caption = candidate.get("caption") if isinstance(candidate.get("caption"), Mapping) else {}
    base_caption = baseline.get("caption") if isinstance(baseline.get("caption"), Mapping) else {}
    metrics: dict[str, Any] = {}
    for key in _CAPTION_DELTA_KEYS:
        cand_val = cand_caption.get(key)
        base_val = base_caption.get(key)
        delta: float | None
        if cand_val is None or base_val is None:
            delta = None
        else:
            delta = float(cand_val) - float(base_val)
        metrics[key] = {
            "baseline": base_val,
            "candidate": cand_val,
            "delta": None if delta is None else round(delta, 4),
        }
    power = _paired_gated_delta(candidate, baseline)
    return {
        "refused": False,
        "invariant": None,
        "reason": None,
        "metrics": metrics,
        "power": power,
    }


def _baseline_delta_lines(delta: Mapping[str, Any] | None) -> list[str]:
    """Markdown for the EVAL-01 Δ block. Refusal occupies the number's place.

    Absent comparison: emit nothing so existing reports stay byte-stable.
    """
    if not delta:
        return []
    lines = ["", "## Δ vs zero-rule baseline", ""]
    if delta.get("refused"):
        invariant = delta.get("invariant") or DELTA_REFUSES_STRADDLED_STAMPS
        reason = delta.get("reason") or "refusing Δ across straddled stamps"
        return lines + [f"- REFUSED ({invariant}): {reason}", ""]
    power = delta.get("power") if isinstance(delta.get("power"), Mapping) else {}
    headline = power.get("headline")
    if headline:
        lines.append(f"- **HEADLINE: {headline}**")
    n_paired = power.get("n_paired")
    if n_paired is not None:
        lines.append(
            f"- paired gated_score n={n_paired} "
            "(held-out corpus is imbalanced; not a global/adoption claim)"
        )
    metrics = delta.get("metrics") if isinstance(delta.get("metrics"), Mapping) else {}
    for key in _CAPTION_DELTA_KEYS:
        row = metrics.get(key)
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"- {key}: candidate={_fmt(row.get('candidate'))} "
            f"baseline={_fmt(row.get('baseline'))} "
            f"Δ={_fmt(row.get('delta'))}"
        )
    lines.append("")
    return lines


def build_reports(
    run_record: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
    ignore_list: dict[str, Any] | None = None,
    *,
    score_manifest_sha256: str | None = None,
    manifest_roster: list[str] | None = None,
    annotation_mode: AnnotationMode | str | None = None,
    audience: Audience = Audience.LOCAL,
    rubric_gate: str = "enforce",
    baseline_run_record: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return (json_report, markdown_report) — deterministic for identical inputs.

    ``audience=LOCAL`` (default) scores the full corpus — byte-identical to the
    pre-audience contract. ``audience=PUBLIC`` uses the same full-corpus score
    (roster/rubric denominators intact — VLM6-R3-03) then post-score redacts
    identity-bearing detail, non-publishable per_image rows, and provenance
    via a fail-closed allow-list (VLM6-R3-01/02). Signature unchanged for the
    concurrent cli lane.

    A filtered artifact is a different estimand (S2R5-03): PUBLIC declares its
    scored population in ``estimand`` rather than silently reusing an
    unfiltered refusal or dropping the evidence that would have refused a
    metric. Because this path scores the full corpus *before* redacting
    (VLM6-R3-03), ``estimand.resolved_on`` is ``"full_corpus"`` — not
    ``"publishable_items"`` — even for ``audience=PUBLIC``.

    ``rubric_gate`` is the operator-declared Must-Right exit-gate mode
    (``enforce``|``skip``); stamped into ``verdict.rubric_gate`` (F1b-2 / F1-12).
    """
    # VLM6-R3-04: validate at every trust boundary before audience branching.
    _validate_record_kind(run_record)
    scored = score_run_record(
        run_record,
        manifest_entries,
        ignore_list=ignore_list,
        score_manifest_sha256=score_manifest_sha256,
        manifest_roster=manifest_roster,
        rubric_gate=rubric_gate,
        annotation_mode=annotation_mode,
    )
    if baseline_run_record is not None:
        _validate_record_kind(baseline_run_record)
        baseline_scored = score_run_record(
            baseline_run_record,
            manifest_entries,
            ignore_list=ignore_list,
            score_manifest_sha256=score_manifest_sha256,
            manifest_roster=manifest_roster,
            rubric_gate=rubric_gate,
            annotation_mode=annotation_mode,
        )
        scored["baseline_delta"] = compare_scored_runs(scored, baseline_scored)
        scored["baseline"] = {
            "caption": baseline_scored.get("caption"),
            "counts": baseline_scored.get("counts"),
        }
    if audience is Audience.PUBLIC:
        scored = _redact_caption_report_for_public(
            scored,
            run_record=run_record,
            manifest_entries=manifest_entries,
        )
        redaction = scored.get("redaction") or {}
        scored["estimand"] = {
            "audience": Audience.PUBLIC.value,
            "population": "publishable_items",
            "n_items": redaction.get("total_items"),
            "n_entries": redaction.get("total_manifest_entries"),
            "withheld_items": redaction.get("withheld_items"),
            "total_items": redaction.get("total_items"),
            "resolved_on": "full_corpus",
        }
    return json.dumps(scored, indent=2, sort_keys=True, ensure_ascii=False) + "\n", _markdown(scored)


# ---------------------------------------------------------------------------
# FIR-5 S5 — face bake-off scorer (§G) + post-score public redaction
# ---------------------------------------------------------------------------
#
# Heuristics (docs/workbay/rules/engineering-heuristics.md + ml-systems — cite ids):
# EVAL-01/03/04, FAIR-01/03, PROV-01/02, COST-04/15, CAL-02, RLSE-02/03, TEST-06/15.
#
# Two-stage publishability (PROV-01): score the FULL unfiltered corpus, then
# redact via ``redact_face_report_for_public`` — NEVER reuse Audience.PUBLIC /
# ``_filter_for_public_audience`` (that zeros the unknown-rejection gate).

# Floor units (§Headline / floor policy). Under-floor → DIRECTIONAL only (SC4).
# Error targets are Wilson 95% half-widths at p̂=0.5 (scope sizing table).
HEADLINE_ID_RECALL_ELIGIBLE_FLOOR = 100
HEADLINE_ID_ERROR_TARGET = "Wilson_95_halfwidth_le_10pct_at_p0.5 (n≈96–100 → ±9.8%)"
DIRECTIONAL_LABEL = "UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion"
GATING_LABEL = "gating_candidate"  # only when floor met; FIR-6 operator decides
WILSON_Z = 1.96
DIVERGENCE_ABS_FLOOR = 0.20


def wilson_half_width(p: float, n: int, *, z: float = WILSON_Z) -> float:
    """Wilson score-interval half-width at measured proportion ``p`` with sample ``n``."""
    if n <= 0:
        return 1.0
    p = max(0.0, min(1.0, float(p)))
    z2 = z * z
    denom = 1.0 + z2 / n
    rad = (z / denom) * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    return float(rad)


def synthetic_real_divergence(
    a_s: float | None,
    a_r: float | None,
    *,
    n_real: int,
    real_floor: int = ELIGIBLE_PAIR_FLOOR,
    abs_floor: float = DIVERGENCE_ABS_FLOOR,
) -> dict[str, Any]:
    """Operational synthetic↔real divergence rule (scope amendment).

    Auto-demote synthetic only when ``d = |a_s − a_r|`` exceeds
    ``max(Wilson half-width at a_r, abs_floor)``. If real n < floor, real is
    qualitative only — no auto-demote. Always prints d + threshold.
    """
    if a_s is None or a_r is None:
        return {
            "d": None,
            "threshold": None,
            "wilson_half_width": None,
            "auto_demote": False,
            "reason": "missing_accuracy",
            "n_real": int(n_real),
            "real_floor": int(real_floor),
        }
    d = abs(float(a_s) - float(a_r))
    if n_real < real_floor:
        return {
            "d": round(d, 6),
            "threshold": None,
            "wilson_half_width": None,
            "auto_demote": False,
            "reason": "real_n_below_floor_qualitative_only",
            "n_real": int(n_real),
            "real_floor": int(real_floor),
        }
    half = wilson_half_width(float(a_r), int(n_real))
    threshold = max(half, float(abs_floor))
    return {
        "d": round(d, 6),
        "threshold": round(threshold, 6),
        "wilson_half_width": round(half, 6),
        "auto_demote": bool(d > threshold),
        "reason": "d_exceeds_threshold" if d > threshold else "within_threshold",
        "n_real": int(n_real),
        "real_floor": int(real_floor),
    }


def _refused_face_identification_block(invariant: str) -> dict[str, Any]:
    """Identification slice that cannot be computed honestly (EVAL-03)."""
    return {
        "refused": True,
        "invariant": invariant,
        "precision": None,
        "recall": None,
        "tp": None,
        "fp": None,
        "fn": None,
        "n_named_probes": None,
        "n_recall_eligible": None,
        "wrong_names": None,
        "detection_recall_coupling_flag": None,
        "sampling_frame": None,
        "precision_numerator": None,
        "precision_denominator": None,
        "recall_numerator": None,
        "recall_denominator": None,
        "missed_gt": None,
        "unmatched_detections": None,
        **_slice_status(meets_floor=False, reasons=[invariant]),
    }


def _refused_unknown_rejection_block(invariant: str) -> dict[str, Any]:
    """Unknown-rejection must not credit probes dropped for lack of boxes."""
    return {
        "refused": True,
        "invariant": invariant,
        "rate": None,
        "correct_rejects": None,
        "false_accepts": None,
        "n": None,
        "n_floor": UNKNOWN_REJECTION_N_FLOOR,
        "error_target": UNKNOWN_REJECTION_ERROR_TARGET,
        "sampling_frame": None,
        "rate_numerator": None,
        "rate_denominator": None,
        **_slice_status(meets_floor=False, reasons=[invariant]),
    }


def _face_pr_dict(pr: Any) -> dict[str, Any]:
    # FIR5RR-12: FaceLevelIdPr is the only accepted shape — direct field access
    # (a getattr default here would silently fabricate audit fields on a
    # foreign object instead of failing loud).
    return {
        "precision": pr.precision,
        "recall": pr.recall,
        "tp": pr.true_positives,
        "fp": pr.false_positives,
        "fn": pr.false_negatives,
        "n_named_probes": pr.n_named_probes,
        "n_recall_eligible": pr.n_recall_eligible,
        "wrong_names": [list(w) for w in pr.wrong_names],
        "detection_recall_coupling_flag": pr.detection_recall_coupling_flag,
        "sampling_frame": pr.sampling_frame,
        "precision_numerator": pr.precision_numerator,
        "precision_denominator": pr.precision_denominator,
        "recall_numerator": pr.recall_numerator,
        "recall_denominator": pr.recall_denominator,
        "missed_gt": pr.missed_gt,
        "unmatched_detections": pr.unmatched_detections,
    }


def _tau_by_identity_from_decisions(decisions: Sequence[Any]) -> dict[str, float]:
    """Identity → held-out fold tau_k map from pooled decisions (FIR5CR-02).

    Subject-disjoint folds (CAL-07) pin every face of an identity to exactly
    one fold, so all of an identity's decisions must carry the SAME tau_k.
    Disagreement means the fold split regressed (an identity straddles folds)
    — raise instead of silently keeping the last-seen value.
    """
    out: dict[str, float] = {}
    for d in decisions:
        if d.true_name is None:
            continue
        tau_k = float(d.tau_k)
        prev = out.get(d.true_name)
        if prev is not None and prev != tau_k:
            raise ReportError(
                f"fold-split regression (FIR5CR-02): identity {d.true_name!r} "
                f"has disagreeing held-out tau_k values ({prev} vs {tau_k}) — "
                "subject-disjoint folds must pin an identity to one fold"
            )
        out[d.true_name] = tau_k
    return out


def _association_counts_for_media(
    assignment: Any,
    media_ids: set[int],
    *,
    gt_by_media: Mapping[int, Sequence[Any]],
    probe_media_ids: set[int],
) -> tuple[int, int, list[str]]:
    """Headline-scoped miss / unmatched-detection counts (FIR5RR-06).

    - ``missed_gt`` counts only unmatched GT boxes with a non-empty name
      (``gt_box_name`` — HARM-06): the headline frame is NAMED probes, so an
      unmatched stranger/empty-name box must not inflate the miss count.
    - ``unmatched_detections`` counts only on media that contributed at least
      one headline probe (``probe_media_ids``) — detections on images whose
      probes never entered the frame are not this frame's false detections.
    - Media absent from ``association_by_media`` (e.g. an error item that
      never reached assignment) contribute their manifest NAMED labeled-face
      counts as misses, with an explicit provenance note — never a silent
      ``continue``.
    - An out-of-range ``unmatched_gt`` index (``gi >= len(boxes)``: GT box /
      manifest drift) is counted conservatively as a miss with an explicit
      provenance note — never a silent skip (FIR5CR-05; same fail-visible
      posture as the absent-media branch above).
    """
    missed = 0
    unmatched = 0
    notes: list[str] = []
    by_media = assignment.association_by_media or {}
    for mid in sorted(media_ids):
        boxes = list(gt_by_media.get(mid, ()))
        assoc = by_media.get(mid)
        if assoc is None:
            named = sum(1 for b in boxes if gt_box_name(b) is not None)
            if named:
                missed += named
                notes.append(
                    f"media_id {mid} absent from association (error/missing "
                    f"run-record item): counted {named} manifest named "
                    f"face(s) as missed_gt"
                )
            continue
        for gi in assoc.unmatched_gt:
            if gi >= len(boxes):
                # FIR5CR-05: index/manifest drift — the box cannot be
                # inspected, so count it conservatively as a miss and leave a
                # provenance note (never a silent skip).
                missed += 1
                notes.append(
                    f"media_id {mid}: unmatched_gt index {gi} out of range "
                    f"for {len(boxes)} manifest GT box(es); counted "
                    "conservatively as missed_gt (association/manifest drift)"
                )
            elif gt_box_name(boxes[gi]) is not None:
                missed += 1
        if mid in probe_media_ids:
            unmatched += len(assoc.unmatched_detections)
    return missed, unmatched, notes


def _slice_status(*, meets_floor: bool, reasons: Sequence[str] | None = None) -> dict[str, Any]:
    if meets_floor:
        return {
            "status": GATING_LABEL,
            "directional": False,
            "label": GATING_LABEL,
            "reasons": [],
        }
    reason_list = list(reasons) if reasons else ["under_floor"]
    return {
        "status": DIRECTIONAL_LABEL,
        "directional": True,
        "label": DIRECTIONAL_LABEL,
        "reasons": sorted(reason_list),
    }


def _annotation_mode_of(manifest: Any) -> AnnotationMode | None:
    """Read annotation_mode from a GoldenManifest or mapping; never invent one.

    Mapping content wins over a dict-subclass attribute (S2R4-12). Attribute
    first inverted most-restrictive-wins when the key said roster_only.
    """
    if isinstance(manifest, Mapping) and "annotation_mode" in manifest:
        return parse_annotation_mode(manifest.get("annotation_mode"))
    raw = getattr(manifest, "annotation_mode", None)
    return parse_annotation_mode(raw)


def _stamp_typed_document_mode(entries: list[dict[str, Any]], mode_value: str) -> None:
    """Stamp the loaded document mode onto GoldenEntry dumps.

    ``GoldenEntry`` has no ``annotation_mode`` field (S2R3-10). The
    document-level field on a typed ``GoldenManifest`` *is* the loaded
    contract (ADR-015). CLI ``_face_score_once`` passes that object
    straight into ``build_face_reports``; without this stamp every
    score-face run would refuse. This is a flatten, not a fill: raw
    mappings never enter this helper (S2R3-02).
    """
    for entry in entries:
        if entry.get("annotation_mode") is None:
            entry["annotation_mode"] = mode_value


def _entries_as_dicts(manifest: Any) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    """Normalize GoldenManifest | mapping | entry-list into plain dicts.

    Typed ``GoldenEntry`` cannot carry a per-entry stamp (S2R3-10): the
    field does not exist and ``extra="forbid"``. On a typed manifest this
    therefore stamps the *document* mode onto every dumped entry. A raw
    mapping's parent ``annotation_mode`` is a caller assertion, not
    per-entry evidence — it is not copied downward (S2R3-02). The
    per-entry lattice (mixed / disagreeing stamps) is raw-mapping-only.
    """
    mode = _annotation_mode_of(manifest)
    mode_value = None if mode is None else mode.value
    if hasattr(manifest, "entries") and hasattr(manifest, "roster"):
        entries = [e.model_dump() if hasattr(e, "model_dump") else dict(e) for e in manifest.entries]
        roster_cohorts = dict(getattr(manifest, "roster_cohorts", {}) or {})
        roster = list(getattr(manifest, "roster", []) or [])
        if mode_value is not None:
            _stamp_typed_document_mode(entries, mode_value)
        return entries, roster_cohorts, roster
    if isinstance(manifest, Mapping):
        raw_entries = list(manifest.get("entries") or [])
        entries = [e.model_dump() if hasattr(e, "model_dump") else dict(e) for e in raw_entries]
        return entries, dict(manifest.get("roster_cohorts") or {}), list(manifest.get("roster") or [])
    # bare entry list
    entries = [e.model_dump() if hasattr(e, "model_dump") else dict(e) for e in manifest]
    return entries, {}, []


def _build_single_subject_cohort_by_media(entries: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    """celebs01 single-subject image-level cohort only; multi-face EXCLUDED (S3d)."""
    out: dict[int, str] = {}
    for entry in entries:
        cohort = entry.get("demographic_cohort")
        if not cohort:
            continue
        prov = entry.get("provenance") or {}
        source = prov.get("source") if isinstance(prov, Mapping) else getattr(prov, "source", None)
        if source != ProvenanceSource.CELEB.value and source != ProvenanceSource.CELEB:
            continue
        boxes = list(entry.get("face_boxes") or [])
        named: set[str] = set()
        for b in boxes:
            # Shared face_metrics predicate (strip + drop Cf; empty → anonymous).
            name = named_box_name(b)
            if name is not None:
                named.add(name)
        # multi-face / multi-identity media EXCLUDED from image-level fallback
        if len(named) != 1:
            continue
        if len(boxes) > 1 or int(entry.get("face_count") or 0) > 1:
            continue
        out[int(entry["media_id"])] = str(cohort)
    return out


def _is_celebs01(entry: Mapping[str, Any] | None) -> bool:
    if entry is None:
        return False
    prov = entry.get("provenance") or {}
    source = prov.get("source") if isinstance(prov, Mapping) else None
    return source == ProvenanceSource.CELEB.value or source == "celeb"


def _gt_by_media(entries: Sequence[Mapping[str, Any]]) -> dict[int, list[Any]]:
    out: dict[int, list[Any]] = {}
    for e in entries:
        boxes = e.get("face_boxes") or []
        out[int(e["media_id"])] = list(boxes)
    return out


def _total_gt_boxes(entries: Sequence[Mapping[str, Any]]) -> int:
    return sum(len(e.get("face_boxes") or []) for e in entries)


def _sort_nested_lists(obj: Any) -> Any:
    """Canonicalize for bit-identical serialization (§G) WITHOUT corrupting rows.

    Sorts each *collection of rows* by a stable key so build-order variance is
    absorbed, but treats list/tuple elements — fixed-schema rows like
    ``wrong_names`` ``[media_id, box_index, true, pred]`` or a ``tau_k`` per-fold
    threshold vector — as ATOMIC: their internal element order is positionally
    meaningful and must never be reordered. Only dict elements are recursed into
    (to canonicalize their own list-valued fields).
    """
    if isinstance(obj, dict):
        return {k: _sort_nested_lists(v) for k, v in obj.items()}
    if isinstance(obj, list):
        # Recurse into dict elements only; leave list/scalar rows atomic.
        items = [_sort_nested_lists(v) if isinstance(v, dict) else v for v in obj]
        try:
            return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, default=str))
        except TypeError:
            return items
    if isinstance(obj, tuple):
        return _sort_nested_lists(list(obj))
    return obj


# FIR5RR-08: the build-face-report path scores UN-OCCLUDED probes only —
# occlusion twins travel exclusively via occlusion_pairs_by_tag. A run-record
# item carrying any of these markers would smuggle a twin into the headline
# frame (the contract filter_headline_probes fail-closes on), so scoring
# rejects the record outright.
_OCCLUSION_ITEM_MARKER_KEYS: tuple[str, ...] = (
    "occluded",
    "occlusion",
    "occlusion_kind",
    "twin",
    "twin_of",
)


def _assert_no_occlusion_marked_items(items: Sequence[Mapping[str, Any]]) -> None:
    for item in items:
        marked = [k for k in _OCCLUSION_ITEM_MARKER_KEYS if k in item]
        if marked:
            raise ReportError(
                f"run-record item media_id={item.get('media_id')} carries occlusion "
                f"marker(s) {marked}: occlusion twins must never enter the headline "
                "run record (EVAL-16); pass them via occlusion_pairs_by_tag instead"
            )


def _validate_face_record_kind(face_run_record: dict[str, Any]) -> None:
    kind = face_run_record.get("kind")
    if kind is not None and kind != DocKind.FACE_RUN_RECORD.value:
        raise ReportError(
            f"expected a '{DocKind.FACE_RUN_RECORD.value}' document but got kind={kind!r}; "
            "did you pass a caption run-record or report to score-face?"
        )
    schema = face_run_record.get("schema")
    if schema is not None and schema != SCHEMA:
        raise ReportError(f"unknown face run-record schema {schema!r}; expected {SCHEMA!r}")
    if "items" not in face_run_record:
        raise ReportError("face run record has no 'items' key")
    if "provenance" not in face_run_record:
        raise ReportError("face run record has no 'provenance' block")


def _detection_from_assignment(assignment: Any) -> dict[str, Any]:
    """Identity-agnostic detection P/R over **all** GT boxes (HARM-01 / EVAL-16).

    Detection asks "was a box found at all?" — named and anonymous GT share one
    population. ``assignment.missed_gt`` is named-only (identification FN fold-in);
    stranger misses live on ``missed_stranger_gt``. FN = both. Identification is
    the metric that legitimately excludes anonymous GT.

    Geometry-incomplete GT (null/invalid centre-y) are **not** detector FNs
    (wG2). They are stamped on ``AssignmentResult.geometry_incomplete_gt`` /
    ``association_incomplete_media`` and published here so a freeze can pin them
    (wH1 / rg-015). Invariant: ``tp + fn + geometry_incomplete_gt`` equals the
    number of GT boxes that entered association (pairs + unmatched complete GT +
    geometry-incomplete). Do not invent these counters at the report boundary —
    read the assignment stamp (rg-015).

    VLM6-R2-C-02: publish ``sampling_frame`` (string, same shape as floor-gated
    slices) so operators can tell the population behind precision/recall.
    """
    tp = sum(len(a.pairs) for a in assignment.association_by_media.values())
    fp = int(assignment.false_detections)
    # Detection FN = named misses + stranger misses (complete GT only).
    # Geometry-incomplete boxes are excluded upstream and must not re-enter FN.
    fn = int(assignment.missed_gt) + int(getattr(assignment, "missed_stranger_gt", 0) or 0)
    # Stamp fields: real AssignmentResult counters — never re-count at boundary.
    geometry_incomplete_gt = int(getattr(assignment, "geometry_incomplete_gt", 0) or 0)
    association_incomplete_media = int(
        getattr(assignment, "association_incomplete_media", 0) or 0
    )
    association_complete = geometry_incomplete_gt == 0
    precision = (tp / (tp + fp)) if (tp + fp) else 0.0
    # Recall denominator is complete-GT population only (tp+fn); incomplete
    # boxes are outside detection P/R and disclosed via geometry_incomplete_*.
    recall = (tp / (tp + fn)) if (tp + fn) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        # wG2 residual / wH1: publish association-completeness so freeze pins it.
        # Denominator for geometry_incomplete_gt: n_gt that entered association
        # (= tp + fn + geometry_incomplete_gt). Media counter is out of scored
        # images (counts.scored). association_complete is corpus-level completeness.
        "geometry_incomplete_gt": geometry_incomplete_gt,
        "association_incomplete_media": association_incomplete_media,
        "association_complete": association_complete,
        "sampling_frame": FACE_BAKEOFF_SAMPLING_FRAMES["detection"],
    }


def _clustering_dict(metrics: Any) -> dict[str, Any]:
    status = _slice_status(
        meets_floor=not metrics.directional,
        reasons=list(metrics.directional_reasons),
    )
    return {
        "d_cut": metrics.d_cut,
        "n_faces": metrics.n_faces,
        "n_clusters": metrics.n_clusters,
        "purity": metrics.purity,
        "false_merge": metrics.false_merge,
        "false_split": metrics.false_split,
        "p_same": metrics.p_same,
        "p_diff": metrics.p_diff,
        "m_co_clustered": metrics.m_co_clustered,
        "labels": list(metrics.labels),
        **status,
    }


# Occlusion slice-tag vocabulary (SC3 subset) for real-occlusion pair extraction.
_OCCLUSION_TAG_VALUES: tuple[str, ...] = (
    SliceTag.MASKED.value,
    SliceTag.SUNGLASSES.value,
    SliceTag.OCCLUSION_OTHER.value,
)


def build_real_occlusion_pairs(
    face_run_record: dict[str, Any],
    manifest: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Real-occlusion pair inputs from occlusion-TAGGED manifest entries (FIR5GL-01).

    For every scoreable run-record item whose manifest entry carries an
    occlusion SliceTag (masked/sunglasses/occlusion_other), each NAMED GT box
    becomes one pair input per occlusion tag on the entry: §C-associate the
    item's detections to the entry's GT boxes, take the matched detection's
    embedding, or ``embedding=None`` when the named box went undetected on the
    real occluded photo (a detect miss inside the eligible frame, EMB-03).
    Tags are image-level strata, so an entry tagged with two occlusion tags
    contributes its faces to both strata — consistent with per-tag slicing.
    """
    entries, _roster_cohorts, _roster = _entries_as_dicts(manifest)
    entry_by_id = _entry_index(entries)
    out: dict[str, list[dict[str, Any]]] = {}
    for item in face_run_record.get("items") or []:
        if item.get("error"):
            continue
        entry = entry_by_id.get(int(item["media_id"]))
        if entry is None:
            continue
        occ_tags = [t for t in (str(tag) for tag in (entry.get("tags") or [])) if t in _OCCLUSION_TAG_VALUES]
        if not occ_tags:
            continue
        boxes = list(entry.get("face_boxes") or [])
        # Shared namedness predicate — whitespace/format-only never enter pairs.
        named: list[tuple[int, Any, str]] = []
        for i, box in enumerate(boxes):
            name = named_box_name(box)
            if name is not None:
                named.append((i, box, name))
        if not named:
            continue
        faces = list(item.get("faces") or [])
        assoc = associate_detections(
            [f["bbox_px"] for f in faces],
            boxes,
            list(item.get("image_size") or [1, 1]),
        )
        emb_by_gt = {p.gt_index: [float(v) for v in faces[p.det_index]["embedding"]] for p in assoc.pairs}
        for gt_index, _box, name in named:
            for tag in occ_tags:
                out.setdefault(tag, []).append(
                    {
                        "media_id": int(item["media_id"]),
                        "box_index": gt_index,
                        "true_name": name,
                        "kind": tag,
                        "embedding": emb_by_gt.get(gt_index),
                    }
                )
    return out


def occlusion_inputs_from_record(
    face_run_record: dict[str, Any],
    manifest: Any,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """Extract (synthetic, real) occlusion pair inputs for build_face_reports.

    Synthetic twins ride the run record's document-level
    ``occlusion_twin_pairs_by_tag`` (written by the face-bakeoff twin pass —
    never items, EVAL-16); real pairs derive from occlusion-tagged manifest
    entries. One shared entry point so score-face and the cross-process
    determinism re-score can never diverge on occlusion inputs.
    """
    synth = {
        str(tag): [dict(p) for p in pairs]
        for tag, pairs in (face_run_record.get("occlusion_twin_pairs_by_tag") or {}).items()
    }
    return synth, build_real_occlusion_pairs(face_run_record, manifest)


def _identity_ordering_block_for_face(
    scoreable: Sequence[Mapping[str, Any]],
    entry_by_id: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """GT + predicted ordering disclosure for the face bakeoff report (VLM6-R2-G-01).

    Field names and semantics match caption ``faces.identity_ordering`` exactly
    so one freeze surface pins one quantity (wG1 / wF4 residual):

    - ``labeled_y_missing_images`` / ``labeled_y_missing_paths`` — GT-side
      ``labeled_order.order_degraded`` (named box missing ``y``). Source is
      manifest ``face_boxes`` via ``labeled_order``; never re-counted at the
      boundary from a convenience walk of raw boxes alone (rg-015).
    - ``degraded_images`` / ``degraded_paths`` / ``positional_images`` —
      predicted ``identity_ordering`` stamp on the run-record item (caption
      fetch stamps these; face walk items usually omit the stamp → honest 0).
    - ``order_unknown_excluded`` — scored images excluded from positional L→R
      (no usable labeled order, predicted DEGRADED stamp, or recognition off).

    Denominator for image-level counts is ``counts.scored`` (same scoreable set
    this block walks — EVAL-03). Paths are manifest entry paths when present.
    """
    labeled_y_missing_images = 0
    labeled_y_missing_paths: list[str] = []
    order_unknown_excluded = 0
    ordering_positional = 0
    ordering_degraded = 0
    degraded_paths: list[str] = []

    for item in scoreable:
        media_id = int(item["media_id"])
        entry = entry_by_id.get(media_id) or {}
        path = str(entry.get("path") or item.get("path") or f"media_id:{media_id}")
        policy = entry.get("policy") if isinstance(entry.get("policy"), Mapping) else {}
        recognition_enabled = bool((policy or {}).get("recognition_enabled", True))

        # Same GT aggregation as score_run_record (caption path) — one quantity.
        order_result = labeled_order(_normalize_face_boxes_for_order(entry.get("face_boxes") or []))
        if order_result.order_degraded:
            labeled_y_missing_images += 1
            labeled_y_missing_paths.append(path)
            labeled_order_known = False
        else:
            labeled_order_known = order_result.names is not None

        ordering_stamp = item.get("identity_ordering")
        # Caption semantics: absent stamp is legal (not counted); unknown stamp
        # is a hard error (VLM6-RH-06). None ≠ DEGRADED → predicted_order_known.
        if ordering_stamp is None:
            predicted_order_known = True
        elif ordering_stamp == IdentityOrdering.DEGRADED:
            ordering_degraded += 1
            degraded_paths.append(path)
            predicted_order_known = False
        elif ordering_stamp == IdentityOrdering.POSITIONAL:
            ordering_positional += 1
            predicted_order_known = True
        else:
            raise ReportError(
                f"unknown identity_ordering {ordering_stamp!r} on {path}; "
                f"expected one of {[m.value for m in IdentityOrdering]} or absent"
            )

        if not recognition_enabled or not labeled_order_known or not predicted_order_known:
            order_unknown_excluded += 1

    return {
        "positional_images": ordering_positional,
        "degraded_images": ordering_degraded,
        "degraded_paths": list(degraded_paths),
        "order_unknown_excluded": order_unknown_excluded,
        "labeled_y_missing_images": labeled_y_missing_images,
        "labeled_y_missing_paths": list(labeled_y_missing_paths),
    }


def score_face_run_record(
    face_run_record: dict[str, Any],
    manifest: Any,
    *,
    score_manifest_sha256: str | None = None,
    occlusion_pairs_by_tag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    real_occlusion_pairs_by_tag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    walk_stability_by_tag: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pure §C–§G face scorer over the FULL UNFILTERED corpus (FIR-5 S5).

    Never applies ``Audience.PUBLIC`` / ``_filter_for_public_audience`` — strangers
    from LOCALWP/OPERATOR are required for the unknown-rejection gating slice.
    Published artifacts go through ``redact_face_report_for_public`` *after* scoring.

    Floor policy (SC4): every under-floor slice is DIRECTIONAL; the gate-proposal
    section EXCLUDES every DIRECTIONAL slice. No code path emits a gating verdict
    for an under-floor slice. 0-box corpus → all DIRECTIONAL.
    """
    _validate_face_record_kind(face_run_record)
    entries, roster_cohorts, _roster = _entries_as_dicts(manifest)
    parent = _annotation_mode_of(manifest)
    mode = _resolve_score_annotation_mode(parent, entries)
    if mode is not AnnotationMode.EXHAUSTIVE:
        # Parent roster_only may only *narrow* (fail closed). It must not
        # mint exhaustive, but it still names the more specific refusal
        # when raw-mapping entries carry no stamp of their own (S2R3-02).
        if mode is AnnotationMode.ROSTER_ONLY or parent is AnnotationMode.ROSTER_ONLY:
            raise ManifestError(
                "score_face_run_record refuses roster_only manifests; unlabeled "
                "non-roster faces would be scored as false positives",
                invariant=ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY,
            )
        raise ManifestError(
            "score_face_run_record requires annotation_mode=exhaustive; "
            "omission is not exhaustive",
            invariant=ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE,
        )
    require_exhaustive_box_coverage(entries)
    entry_by_id = _entry_index(entries)
    gt_by_media = _gt_by_media(entries)
    total_boxes = _total_gt_boxes(entries)
    zero_box_corpus = total_boxes == 0

    items = list(face_run_record.get("items") or [])
    _assert_no_occlusion_marked_items(items)  # FIR5RR-08 / EVAL-16
    # Keep error items out of assignment but count them as failures.
    scoreable: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in items:
        media_id = int(item["media_id"])
        entry = entry_by_id.get(media_id)
        if entry is None:
            failures.append(
                {
                    "path": str(item.get("path", f"media_id:{media_id}")),
                    "media_id": media_id,
                    "error": f"media_id {media_id} not in score-time manifest",
                }
            )
            continue
        if item.get("error"):
            failures.append(
                {
                    "path": str(entry.get("path", item.get("path", ""))),
                    "media_id": media_id,
                    "error": str(item["error"]),
                }
            )
            continue
        scoreable.append(item)

    # VLM6-R2-G-01 / wG1: publish ordering disclosure on the face freeze surface.
    # Caption score_run_record already publishes the same block under
    # faces.identity_ordering; face bakeoff previously never called labeled_order
    # and the freeze could not pin labeled_y_missing_* (wF4 residual).
    identity_ordering = _identity_ordering_block_for_face(scoreable, entry_by_id)

    assignment = score_face_assignment(scoreable, gt_by_media)
    detection = _detection_from_assignment(assignment)

    try:
        require_boxed_identification_gt(
            [entry_by_id[int(item["media_id"])] for item in scoreable]
        )
    except ManifestError as exc:
        if not _invariant_is(exc.invariant, IDENTIFICATION_UNBOXED_INVARIANT):
            raise
        identification_invariant = exc.invariant
    else:
        identification_invariant = None

    # Full-corpus identification + unknown-rejection (includes private strangers).
    # Unboxed identity claims cannot be scored as named probes OR as stranger
    # rejects — both would silently drop the claim from the ID denominator
    # and recycle it as unknown-rejection credit (S2R4-01).
    # FIR5RR-07: mid-grid-unfitted τ can never back a gating number — every
    # τ-dependent slice is forced DIRECTIONAL with an explicit reason.
    tau_unfitted = assignment.tau_fit_status != "fitted"
    tau_unfitted_reason = f"tau_fit_status={assignment.tau_fit_status}"

    celebs01_ids = {mid for mid, e in entry_by_id.items() if _is_celebs01(e)}
    headline_assoc_notes: list[str] = []
    if identification_invariant is None:
        id_pr = face_identification_pr(
            assignment.decisions,
            missed_gt=assignment.missed_gt,
            unmatched_detections=assignment.false_detections,
            sampling_frame=FACE_BAKEOFF_SAMPLING_FRAMES["full_corpus_identification"],
        )
        unknown = face_unknown_rejection(
            assignment.decisions,
            missed_stranger_gt=assignment.missed_stranger_gt,
        )

        # Headline = celebs01 named probes only (provenance.source == CELEB).
        # Coupling counts are headline-scoped (not full-corpus) so the honesty
        # flag matches the published rate's sampling frame (FIR5V11-05 / REF-27).
        headline_decisions = [
            d
            for d in assignment.decisions
            if d.media_id in celebs01_ids and d.true_name is not None
        ]
        headline_missed_gt, headline_unmatched, headline_assoc_notes = (
            _association_counts_for_media(
                assignment,
                celebs01_ids,
                gt_by_media=gt_by_media,
                probe_media_ids={d.media_id for d in headline_decisions},
            )
        )
        headline_id = face_identification_pr(
            headline_decisions,
            missed_gt=headline_missed_gt,
            unmatched_detections=headline_unmatched,
            sampling_frame=FACE_BAKEOFF_SAMPLING_FRAMES["headline_identification"],
        )

        headline_reasons: list[str] = []
        if zero_box_corpus:
            headline_reasons.append("zero_box_corpus")
        elif headline_id.n_recall_eligible < HEADLINE_ID_RECALL_ELIGIBLE_FLOOR:
            headline_reasons.append(
                f"n_recall_eligible={headline_id.n_recall_eligible}<{HEADLINE_ID_RECALL_ELIGIBLE_FLOOR}"
            )
        if tau_unfitted:
            headline_reasons.append(tau_unfitted_reason)
        headline_floor_met = (
            not zero_box_corpus
            and not tau_unfitted
            and headline_id.n_recall_eligible >= HEADLINE_ID_RECALL_ELIGIBLE_FLOOR
        )
        headline_status = _slice_status(
            meets_floor=headline_floor_met,
            reasons=headline_reasons,
        )

        unknown_reasons: list[str] = []
        if zero_box_corpus:
            unknown_reasons.append("zero_box_corpus")
        elif not unknown.meets_floor:
            unknown_reasons.append(f"n={unknown.n}<{UNKNOWN_REJECTION_N_FLOOR}")
        if tau_unfitted:
            unknown_reasons.append(tau_unfitted_reason)
        unknown_floor_met = not zero_box_corpus and not tau_unfitted and unknown.meets_floor
        unknown_status = _slice_status(
            meets_floor=unknown_floor_met,
            reasons=unknown_reasons,
        )
    else:
        id_pr = None
        unknown = None
        headline_id = None
        headline_status = None
        unknown_status = None

    # Clustering on named matched faces only (strangers excluded).
    named_matched = [m for m in assignment.matched if m.true_name is not None]
    # Stable order for determinism
    named_matched_sorted = sorted(
        named_matched,
        key=lambda m: (m.true_name or "", m.media_id, m.box_index, m.det_index),
    )
    if named_matched_sorted:
        emb = [list(m.embedding) for m in named_matched_sorted]
        labels = [str(m.true_name) for m in named_matched_sorted]
        _sweep, cluster_headline = clustering_sweep(
            emb,
            labels,
            tau_grid=TAU_GRID,
            tau_op=assignment.tau_op,
            pair_floor=CLUSTER_PAIR_FLOOR,
        )
        cluster_block = _clustering_dict(cluster_headline)
        if zero_box_corpus:
            cluster_block.update(_slice_status(meets_floor=False, reasons=["zero_box_corpus"]))
    else:
        cluster_block = {
            "d_cut": round(1.0 - float(assignment.tau_op), 4),
            "n_faces": 0,
            "n_clusters": 0,
            "purity": 0.0,
            "false_merge": 0.0,
            "false_split": 0.0,
            "p_same": 0,
            "p_diff": 0,
            "m_co_clustered": 0,
            "labels": [],
            **_slice_status(
                meets_floor=False,
                reasons=["zero_box_corpus"] if zero_box_corpus else ["empty", "p_same<20", "p_diff<20", "m==0"],
            ),
        }
    if tau_unfitted:
        # FIR5RR-07: clustering's headline d_cut derives from τ_op — unfitted τ
        # demotes it regardless of pair floors.
        cluster_block.update(
            _slice_status(
                meets_floor=False,
                reasons=[*cluster_block.get("reasons", []), tau_unfitted_reason],
            )
        )

    # Demographic Fair-SA (always DIRECTIONAL — no floor). Identification
    # refusal also refuses the per-cohort ID rollup — it is the same estimand.
    if identification_invariant is None:
        single_subject = _build_single_subject_cohort_by_media(entries)
        demo = demographic_rollup(
            assignment.decisions,
            roster_cohorts,
            single_subject_cohort_by_media=single_subject,
            # FIR5RR-05: per-cohort miss fields stay None (not attributed); the
            # coupling flag is inherited from the full-corpus identification frame.
            parent_detection_coupling=id_pr.detection_recall_coupling_flag,
        )
        demo_block = {
            "section_header": demo.section_header,
            "directional": True,
            "directional_reasons": list(demo.directional_reasons),
            "status": DIRECTIONAL_LABEL,
            "label": DIRECTIONAL_LABEL,
            "by_cohort": {
                cohort: _face_pr_dict(pr) for cohort, pr in sorted(demo.by_cohort.items())
            },
        }
    else:
        demo_block = {
            "refused": True,
            "invariant": identification_invariant,
            "section_header": "demographic Fair-SA (DIRECTIONAL)",
            "directional": True,
            "directional_reasons": [identification_invariant],
            "status": DIRECTIONAL_LABEL,
            "label": DIRECTIONAL_LABEL,
            "by_cohort": {},
        }

    # Occlusion slices (synthetic + real divergence).
    # FIR5RR-01 (CAL-07/EVAL-07): each twin is scored at its source identity's
    # held-out fold tau_k — never at tau_op, whose median includes the twin's
    # own identity's fold. Subject-disjoint folds pin every face of an identity
    # to one fold, so the identity→tau_k map is well-defined. FIR5CR-01: the
    # pooled-tau fallback is an explicit opt-in restricted to matched named
    # identities provably absent from the pooled decisions (they contributed
    # no held-out probe to any fold fit; the fallback is still not guaranteed
    # entity-disjoint if the identity entered fit galleries).
    tau_by_identity = _tau_by_identity_from_decisions(assignment.decisions)
    tau_fallback_identities = frozenset(
        {f.true_name for f in assignment.matched if f.true_name is not None} - set(tau_by_identity)
    )
    occlusion_out: dict[str, Any] = {}
    occlusion_pairs_by_tag = occlusion_pairs_by_tag or {}
    real_occlusion_pairs_by_tag = real_occlusion_pairs_by_tag or {}
    walk_stability_by_tag = walk_stability_by_tag or {}
    for tag in sorted(
        set(occlusion_pairs_by_tag) | set(real_occlusion_pairs_by_tag) | {"masked", "sunglasses", "occlusion_other"}
    ):
        synth_inputs = list(occlusion_pairs_by_tag.get(tag) or [])
        real_inputs = list(real_occlusion_pairs_by_tag.get(tag) or [])
        ws = walk_stability_by_tag.get(tag) or {}
        walk_asserted = bool(ws.get("asserted", False))
        walk_delta = ws.get("delta")
        # Optional independent re-run pair for stability
        if "accuracy_a" in ws and "accuracy_b" in ws:
            met, delta = assert_walk_stability(
                ws.get("accuracy_a"),
                ws.get("accuracy_b"),
                n_eligible_a=int(ws.get("n_eligible_a", 0)),
                n_eligible_b=int(ws.get("n_eligible_b", 0)),
            )
            walk_asserted = met
            walk_delta = delta

        if synth_inputs:
            synth_acc = score_occlusion_accuracy(
                synth_inputs,
                assignment.matched,
                tau=assignment.tau_op,
                tau_by_identity=tau_by_identity,
                allow_tau_fallback_for=tau_fallback_identities,
                walk_stability_asserted=walk_asserted,
                walk_stability_delta=walk_delta,
            )
        else:
            synth_acc = score_occlusion_accuracy(
                [],
                assignment.matched,
                tau=assignment.tau_op,
                tau_by_identity=tau_by_identity,
                allow_tau_fallback_for=tau_fallback_identities,
                walk_stability_asserted=False,
                walk_stability_delta=None,
            )

        if real_inputs:
            real_acc = score_occlusion_accuracy(
                real_inputs,
                assignment.matched,
                tau=assignment.tau_op,
                tau_by_identity=tau_by_identity,
                allow_tau_fallback_for=tau_fallback_identities,
                walk_stability_asserted=True,  # real tags have no walk twin
                walk_stability_delta=0.0,
            )
        else:
            real_acc = None

        divergence = synthetic_real_divergence(
            synth_acc.accuracy,
            real_acc.accuracy if real_acc is not None else None,
            n_real=real_acc.n_eligible if real_acc is not None else 0,
        )
        # Auto-demote synthetic when divergence fires.
        synth_directional = bool(synth_acc.directional) or zero_box_corpus or divergence["auto_demote"] or tau_unfitted
        synth_reasons = list(synth_acc.directional_reasons)
        if zero_box_corpus:
            synth_reasons.append("zero_box_corpus")
        if divergence["auto_demote"]:
            synth_reasons.append(f"synthetic_real_divergence d={divergence['d']}>threshold={divergence['threshold']}")
        if tau_unfitted:
            synth_reasons.append(tau_unfitted_reason)
        status = _slice_status(meets_floor=not synth_directional, reasons=synth_reasons)
        occlusion_out[tag] = {
            "synthetic": {
                "accuracy": synth_acc.accuracy,
                "n_eligible": synth_acc.n_eligible,
                "n_correct": synth_acc.n_correct,
                "n_re_detect_miss": synth_acc.n_re_detect_miss,
                "n_ineligible": synth_acc.n_ineligible,
                "walk_stability_asserted": synth_acc.walk_stability_asserted,
                "walk_stability_delta": synth_acc.walk_stability_delta,
                # FIR5RR-12: direct dataclass field access — no getattr defaults.
                "sampling_frame": synth_acc.sampling_frame,
                "rate_numerator": synth_acc.rate_numerator,
                "rate_denominator": synth_acc.rate_denominator,
                "n_floor": ELIGIBLE_PAIR_FLOOR,
                **status,
            },
            "real": (
                {
                    "accuracy": real_acc.accuracy,
                    "n_eligible": real_acc.n_eligible,
                    "n_correct": real_acc.n_correct,
                    # FIR5RR-12: direct dataclass field access — no getattr defaults.
                    "sampling_frame": real_acc.sampling_frame,
                    "rate_numerator": real_acc.rate_numerator,
                    "rate_denominator": real_acc.rate_denominator,
                    "directional": True,  # real n floors small — never gating alone here
                    "status": DIRECTIONAL_LABEL,
                }
                if real_acc is not None
                else None
            ),
            "divergence": divergence,
        }

    # Floor-gated rollup of every gating slice.
    if identification_invariant is None:
        headline_block = {
            **_face_pr_dict(headline_id),
            "n_floor": HEADLINE_ID_RECALL_ELIGIBLE_FLOOR,
            "floor_unit": "recall_eligible_celebs01",
            "error_target": HEADLINE_ID_ERROR_TARGET,
            # FIR5RR-06: celebs01 media that never reached association are
            # disclosed here (their manifest named faces were counted as misses).
            "association_provenance_notes": list(headline_assoc_notes),
            **headline_status,
        }
        unknown_block = {
            "rate": unknown.rate,
            "correct_rejects": unknown.correct_rejects,
            "false_accepts": unknown.false_accepts,
            "n": unknown.n,
            "n_floor": UNKNOWN_REJECTION_N_FLOOR,
            "error_target": UNKNOWN_REJECTION_ERROR_TARGET,
            "sampling_frame": unknown.sampling_frame,
            "rate_numerator": unknown.rate_numerator,
            "rate_denominator": unknown.rate_denominator,
            # HARM-09 / AUDIT-07: disclose the stranger-miss term folded into
            # rate_denominator (already required into face_unknown_rejection).
            "missed_stranger_gt": int(assignment.missed_stranger_gt),
            **unknown_status,
        }
        full_id_block = _face_pr_dict(id_pr)
        coupling_block = {
            "identification_recall": headline_id.recall,
            "detection_recall": detection["recall"],
            "detection_recall_coupling_flag": headline_id.detection_recall_coupling_flag,
            "missed_gt": headline_id.missed_gt,
            "unmatched_detections": headline_id.unmatched_detections,
            "sampling_frame": headline_id.sampling_frame,
            "flag": (
                "identification recall is computed only over faces this leg detected and "
                "§C-matched (enrolled); weak detection can inflate id-recall on the easy "
                "detected subset — report id-recall ALONGSIDE detection-recall"
            ),
        }
    else:
        headline_block = {
            **_refused_face_identification_block(identification_invariant),
            "n_floor": HEADLINE_ID_RECALL_ELIGIBLE_FLOOR,
            "floor_unit": "recall_eligible_celebs01",
            "error_target": HEADLINE_ID_ERROR_TARGET,
            "association_provenance_notes": list(headline_assoc_notes),
        }
        unknown_block = _refused_unknown_rejection_block(identification_invariant)
        full_id_block = _refused_face_identification_block(identification_invariant)
        coupling_block = {
            "refused": True,
            "invariant": identification_invariant,
            "identification_recall": None,
            "detection_recall": detection["recall"],
            "detection_recall_coupling_flag": None,
            "missed_gt": None,
            "unmatched_detections": None,
            "sampling_frame": None,
            "flag": (
                "identification recall is not computed from identity claims that "
                "carry no per-face box lineage"
            ),
        }
    slices: dict[str, Any] = {
        "headline_identification": headline_block,
        "unknown_rejection": unknown_block,
        "clustering": {
            **cluster_block,
            "sampling_frame": SAMPLING_FRAME_CLUSTERING,
        },
        "occlusion": occlusion_out,
        "demographic": demo_block,
        "full_corpus_identification": full_id_block,
    }

    # Gate-proposal: EXCLUDE every DIRECTIONAL slice (SC4). Never emit demoted verdict.
    proposed: dict[str, Any] = {}
    excluded: list[str] = []

    def _maybe_propose(name: str, block: Mapping[str, Any]) -> None:
        if block.get("directional", True):
            excluded.append(name)
        else:
            proposed[name] = {
                k: v
                for k, v in block.items()
                if k not in ("wrong_names", "labels")  # keep proposal compact; aggregates only
            }

    _maybe_propose("headline_identification", slices["headline_identification"])
    _maybe_propose("unknown_rejection", slices["unknown_rejection"])
    _maybe_propose("clustering", slices["clustering"])
    for tag, block in sorted(occlusion_out.items()):
        synth = block.get("synthetic") or {}
        _maybe_propose(f"occlusion.{tag}", synth)

    gate_proposal = {
        "role": "proposal_only",
        # RLSE-11: explicit release-surface label — never a ship/release artifact.
        "release_surface": GATE_PROPOSAL_RELEASE_SURFACE,
        "operator_authority": "FIR-6 human operator records gate/deferral; FIR-5 cannot self-promote",
        "proposed_slices": proposed,
        "excluded_directional": sorted(excluded),
        "identification_detection_coupling": coupling_block,
        "p95_scan_latency": "FIR-6-owned; not measured here.",
        "scope_amendments_for_operator_ack": [
            "p95 full-scan latency deferred to FIR-6 (not measured in FIR-5)",
            "A10 eval throughput deferred to named follow-up FIR-5a (NOT FIR-7 prod GPU)",
            "synthetic↔real divergence uses Wilson half-width rule (replaces scope >1/3)",
            "clustering local floor P_same≥20 ∧ P_diff≥20 and M==0 all-singletons guard",
        ],
        "perf_label": "detect+embed-only (COST-04/15); not full-scan p95",
        "protocol_disclosures": list(FACE_BAKEOFF_PROTOCOL_DISCLOSURES),
        "canon_version": FACE_BAKEOFF_CANON_VERSION,
        "protocol_id": FACE_BAKEOFF_PROTOCOL_ID,
    }

    decisions_json = [
        {
            "media_id": d.media_id,
            "path": d.path,
            "box_index": d.box_index,
            "det_index": d.det_index,
            "true_name": d.true_name,
            "decision": d.decision,
            "predicted_name": d.predicted_name,
            "s_max": d.s_max if d.s_max != float("-inf") else None,
            "name_star": d.name_star,
            "tau_k": d.tau_k,
            "fold": d.fold,
            "enrolled": d.enrolled,
            "excluded_single_face_recall": d.excluded_single_face_recall,
            # PROV-01: manifest-grounded publishability stamped at score time so the
            # post-score public redaction can key on Provenance.is_publishable
            # (fail-closed) instead of guessing from path spelling.
            "publishable": _entry_is_publishable(entry_by_id.get(int(d.media_id))),
        }
        for d in assignment.decisions
    ]

    fetch_provenance = dict(face_run_record.get("provenance") or {})
    model_ids = sorted({str(i.get("model_id")) for i in items if i.get("model_id")})
    emb_dims = sorted({int(i["embedding_dim"]) for i in items if i.get("embedding_dim") is not None})
    provenance = {
        **fetch_provenance,
        "score_manifest_sha256": score_manifest_sha256,
        "manifest_matches_fetch": (
            None if score_manifest_sha256 is None else score_manifest_sha256 == fetch_provenance.get("manifest_sha256")
        ),
        "model": {
            "model_ids": model_ids,
            "embedding_dims": emb_dims,
            "leg": fetch_provenance.get("leg"),
        },
        "zero_box_corpus": zero_box_corpus,
        "total_gt_boxes": total_boxes,
        # AUDIT-01/02 (FIR5RR-04/07): K-fold + tau-fit provenance mirrored here
        # so redacted/public artifacts keep the protocol facts.
        "k_folds": {
            "requested": assignment.requested_k,
            "effective": assignment.effective_k,
            "clamped": assignment.requested_k != assignment.effective_k,
        },
        "tau_fit_status": assignment.tau_fit_status,
        # REF-25..28: pin protocol/canon version + sampling-frame refs alongside SHAs.
        "canon_version": FACE_BAKEOFF_CANON_VERSION,
        "protocol_id": FACE_BAKEOFF_PROTOCOL_ID,
        "sampling_frames": dict(FACE_BAKEOFF_SAMPLING_FRAMES),
    }

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": DocKind.REPORT.value,
        "report_kind": "face_bakeoff",
        "provenance": provenance,
        "counts": {
            "total": len(items),
            "scored": len(scoreable),
            "failed": len(failures),
            "matched_faces": len(assignment.matched),
            "named_matched": len(named_matched_sorted),
            "stranger_matched": sum(1 for m in assignment.matched if m.true_name is None),
        },
        "tau": {
            "tau_k": list(assignment.tau_k),
            "tau_op": assignment.tau_op,
            # AUDIT-01/02 (FIR5RR-04): requested vs effective K, with an
            # explicit disclosure whenever the subject-count clamp fired.
            "requested_k": assignment.requested_k,
            "effective_k": assignment.effective_k,
            "k_clamp_disclosure": (
                None
                if assignment.requested_k == assignment.effective_k
                else (
                    f"requested_k={assignment.requested_k} clamped to "
                    f"effective_k={assignment.effective_k} by the subject count — "
                    f"tau_k/folds reflect effective_k, not the requested protocol K"
                )
            ),
            # FIR5RR-07: how tau_k were obtained; non-"fitted" forces every
            # tau-dependent slice DIRECTIONAL.
            "tau_fit_status": assignment.tau_fit_status,
            "note": "PROVISIONAL — not product defaults (FIR-6 owns calibration)",
        },
        "protocol_disclosures": list(FACE_BAKEOFF_PROTOCOL_DISCLOSURES),
        "detection": detection,
        # Top-level (no faces.* wrapper): face bakeoff report is already face-only.
        # Field names/semantics match caption faces.identity_ordering exactly (wG1).
        "identity_ordering": identity_ordering,
        "slices": slices,
        "gate_proposal": gate_proposal,
        "decisions": decisions_json,
        "failures": sorted(failures, key=lambda f: (f.get("media_id", -1), f.get("path", ""))),
    }
    return _sort_nested_lists(report)


def _face_publishable_identity_names(report: Mapping[str, Any]) -> set[str]:
    """True names of publishable named decisions — the only identities PUBLIC may name."""
    names: set[str] = set()
    for d in report.get("decisions") or []:
        if not isinstance(d, Mapping):
            continue
        if d.get("publishable") is True and isinstance(d.get("true_name"), str) and d["true_name"].strip():
            names.add(d["true_name"])
    return names


def _harvest_name_cells_from_wrong_names(node: Any, names: set[str]) -> None:
    """Recursively collect identity-like strings from wrong_names rows (RF-01)."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key in ("wrong_names", "ignored_wrong_names") and isinstance(value, list):
                for pair in value:
                    if not isinstance(pair, list | tuple):
                        continue
                    for cell in pair:
                        if not isinstance(cell, str) or not cell.strip():
                            continue
                        if "/" in cell or "\\" in cell:
                            continue
                        lower = cell.lower()
                        if any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
                            continue
                        # Skip pure ints encoded as strings / media tokens.
                        if cell.startswith("media_id:"):
                            continue
                        names.add(cell)
            else:
                _harvest_name_cells_from_wrong_names(value, names)
    elif isinstance(node, list):
        for item in node:
            _harvest_name_cells_from_wrong_names(item, names)


def _face_private_identity_names_for_public_scrub(report: Mapping[str, Any]) -> list[str]:
    """Private roster names from a face report for free-text scrub (VLM6-R2-A-02).

    Face PUBLIC redaction has no separate manifest at the call site — names are
    recovered from decision rows / wrong_names before those surfaces are stripped.

    Publishable *true_name* values are not scrub targets (they ship on kept
    decisions). Every other identity string — including private ``predicted_name``
    / ``name_star`` on a publishable probe (CDX-01 / RB-04) and wrong_names cells
    under any slice (RF-01 demographic copy) — is a scrub target.

    Path-basename stems are **not** harvested as scrub targets (RF-13): short
    stems over-scrub unrelated free text. Paths are handled by path redaction /
    absolute-path free-text collapse instead (RB-03).
    """
    publishable = _face_publishable_identity_names(report)
    names: set[str] = set()
    for d in report.get("decisions") or []:
        if not isinstance(d, Mapping):
            continue
        for key in ("true_name", "predicted_name", "name_star"):
            val = d.get(key)
            if not isinstance(val, str) or not val.strip():
                continue
            # Keep publishable subjects; scrub every other identity reference.
            if key == "true_name" and d.get("publishable") is True:
                continue
            if val in publishable:
                continue
            names.add(val)
    slices = report.get("slices") if isinstance(report.get("slices"), Mapping) else {}
    _harvest_name_cells_from_wrong_names(slices, names)
    # Drop any publishable true names that wrong_names harvest may have re-added.
    names -= publishable
    # RF-13: never add short path stems. (Previous harvest of basenames is gone.)
    _ = _FACE_PATH_STEM_SCRUB_MIN_LEN  # documented floor if stem harvest returns
    return sorted((n for n in names if n), key=len, reverse=True)


def _scrub_face_public_string(text: str, names: Sequence[str]) -> str:
    """Scrub one free-text leaf: identity hits + absolute-path shapes (RB-01/03)."""
    if not text:
        return text
    if text.startswith("media_id:") or text in (
        "<path>",
        "<absolute>",
        "<error>",
        "<redacted>",
    ):
        return text
    if _is_absolute_path_string(text):
        return "<absolute>"
    if _string_contains_operator_path(text):
        return "<redacted>"
    if names:
        scrubbed = _scrub_identity_names(text, names)
        if scrubbed != text:
            return "<redacted>"
    return text


def _scrub_face_public_free_text(
    obj: Any,
    names: Sequence[str],
    *,
    publishable_names: frozenset[str] | set[str] | None = None,
) -> Any:
    """Fail-closed free-text walk for face PUBLIC (VLM6-R2-A-02 / RF-02 / RB-01).

    Walks dicts *and* list elements (including bare ``str``). Absolute paths in
    any free-text leaf collapse (RB-03). Publishable decision ``true_name`` is
    retained; ``predicted_name`` / ``name_star`` are retained only when the
    referenced identity is itself a publishable subject (CDX-01 / RB-04).
    """
    pub = frozenset(publishable_names or ())
    _keep_name_keys = frozenset({"true_name", "predicted_name", "name_star"})

    def _walk(node: Any, *, parent_is_decision: bool = False) -> Any:
        if isinstance(node, dict):
            is_decision = parent_is_decision or (
                "publishable" in node and "true_name" in node and "media_id" in node
            )
            out: dict[str, Any] = {}
            for key, value in node.items():
                if is_decision and key in _keep_name_keys and isinstance(value, str):
                    if key == "true_name":
                        # Kept decisions are publishable+named; true_name ships.
                        out[key] = value
                    elif value in pub:
                        out[key] = value
                    else:
                        # Private gallery identity referenced from a publishable probe.
                        out[key] = "<redacted>"
                elif isinstance(value, str):
                    out[key] = _scrub_face_public_string(value, names)
                else:
                    out[key] = _walk(value, parent_is_decision=is_decision and key != "decisions")
            return out
        if isinstance(node, list):
            # RB-01 / RF-02: bare str elements must scrub (not fall through).
            return [
                (
                    _scrub_face_public_string(v, names)
                    if isinstance(v, str)
                    else _walk(v, parent_is_decision=parent_is_decision)
                )
                for v in node
            ]
        if isinstance(node, str):
            return _scrub_face_public_string(node, names)
        return node

    # Always walk: path collapse is load-bearing even when the scrub roster is empty.
    return _walk(obj)


def _clear_wrong_names_everywhere(node: Any) -> Any:
    """Fail-closed: clear wrong_names under every dict, not two known keys (RF-01)."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in ("wrong_names", "ignored_wrong_names"):
                out[key] = []
            else:
                out[key] = _clear_wrong_names_everywhere(value)
        return out
    if isinstance(node, list):
        return [_clear_wrong_names_everywhere(v) for v in node]
    return node


def redact_face_report_for_public(report: dict[str, Any]) -> dict[str, Any]:
    """POST-SCORE public redaction (PROV-01) — provenance-grounded, fail-CLOSED.

    Scoring keeps unpublishable strangers/persons in the aggregate rates (the
    unknown-rejection gate needs them). This function strips every per-face
    DETAIL row and identity-bearing list that could name or locate a
    non-publishable individual, while PRESERVING aggregate rates. Publishability
    is decided by the manifest-derived ``publishable`` flag stamped on each
    decision at score time (``_entry_is_publishable`` / Provenance.is_publishable)
    — NOT by path-string guessing, which fails open for a named private person
    whose path lacks the expected tokens. Fail-closed: a decision row without
    ``publishable is True`` is dropped; identity lists with no per-element
    publishability signal (clustering labels, wrong_names, failures) are stripped
    wholesale. Distinct from the pre-score ``_filter_for_public_audience`` /
    ``Audience.PUBLIC`` path.

    Shared PUBLIC boundary (VLM6-R2-A-02 / rg-015): after face-specific detail
    stripping, provenance goes through the same ``_public_provenance`` allow-list
    as the caption path, paths through ``_redact_public_paths``, and free text
    through ``_scrub_identity_names``. Do not fork a second allow-list here.
    """
    redacted = copy.deepcopy(report)

    # Collect private names + path→media map from the *pre-strip* report so
    # free-text scrub and media_id:N tokens still work after detail drop.
    publishable_names = _face_publishable_identity_names(report)
    scrub_names = _face_private_identity_names_for_public_scrub(report)
    path_to_media: dict[str, int] = {}
    for row in list(report.get("decisions") or []) + list(report.get("failures") or []):
        if not isinstance(row, Mapping):
            continue
        p = row.get("path")
        mid = row.get("media_id")
        if isinstance(p, str) and p and mid is not None:
            path_to_media.setdefault(p, int(mid))

    # (1) Per-decision detail: keep ONLY publishable AND named (celebs01) rows.
    #     Fail-closed — a missing or False publishable flag drops the row. A
    #     stranger (true_name None) is private detail even from a publishable
    #     source, so it is dropped too (its count stays in the aggregate rate).
    kept_decisions: list[dict[str, Any]] = []
    stripped = 0
    for d in redacted.get("decisions") or []:
        if d.get("publishable") is True and d.get("true_name") is not None:
            kept_decisions.append(d)
        else:
            stripped += 1
    redacted["decisions"] = kept_decisions

    slices = redacted.get("slices") or {}

    # (2) Clustering ``labels`` is the per-face cluster assignment (one integer id
    #     per matched face) — per-face detail with no per-element publishability
    #     signal ⇒ strip wholesale to keep the public artifact aggregate-only.
    #     Public keeps the aggregate clustering metrics (purity, false_merge/split,
    #     counts).
    clustering = slices.get("clustering")
    if isinstance(clustering, dict) and "labels" in clustering:
        clustering["labels"] = []

    # (3) wrong_names rows can name a private individual under *any* slice
    #     (headline, full_corpus, demographic.by_cohort.*, …). Fail-closed
    #     recursive clear — not a two-key enumeration (RF-01).
    if isinstance(slices, dict):
        redacted["slices"] = _clear_wrong_names_everywhere(slices)
        slices = redacted["slices"]

    # (4) Failure rows embed media paths and carry no publishability signal ⇒ drop
    #     wholesale (operator-triage detail only). Aggregate failed-count stays in
    #     ``counts``.
    redacted["failures"] = []

    # AUDIT-09/12: redaction strips decision rows but must retain denominators
    # for every published aggregate rate so n/N honesty survives public export.
    # RB-02: do NOT copy free-text sampling_frame into preserved_* — that
    # re-injects pre-scrub secrets after the free-text walk. Numeric denominators
    # only; sampling_frame remains (and is scrubbed) on the slice blocks themselves.
    preserved: dict[str, Any] = {}
    hl = slices.get("headline_identification") if isinstance(slices, Mapping) else None
    if isinstance(hl, dict):
        preserved["headline_identification"] = {
            "precision_numerator": hl.get("precision_numerator"),
            "precision_denominator": hl.get("precision_denominator"),
            "recall_numerator": hl.get("recall_numerator"),
            "recall_denominator": hl.get("recall_denominator"),
            "n_named_probes": hl.get("n_named_probes"),
            "n_recall_eligible": hl.get("n_recall_eligible"),
        }
    unk = slices.get("unknown_rejection") if isinstance(slices, Mapping) else None
    if isinstance(unk, dict):
        preserved["unknown_rejection"] = {
            "rate_numerator": unk.get("rate_numerator", unk.get("correct_rejects")),
            "rate_denominator": unk.get("rate_denominator", unk.get("n")),
            "n": unk.get("n"),
        }
    full = slices.get("full_corpus_identification") if isinstance(slices, Mapping) else None
    if isinstance(full, dict):
        preserved["full_corpus_identification"] = {
            "precision_numerator": full.get("precision_numerator"),
            "precision_denominator": full.get("precision_denominator"),
            "recall_numerator": full.get("recall_numerator"),
            "recall_denominator": full.get("recall_denominator"),
            "n_named_probes": full.get("n_named_probes"),
            "n_recall_eligible": full.get("n_recall_eligible"),
        }
    occ = slices.get("occlusion") if isinstance(slices, Mapping) else None
    if isinstance(occ, dict):
        occ_pres: dict[str, Any] = {}
        for tag, block in occ.items():
            if not isinstance(block, dict):
                continue
            synth = block.get("synthetic") or {}
            if isinstance(synth, dict):
                occ_pres[str(tag)] = {
                    "rate_numerator": synth.get("rate_numerator", synth.get("n_correct")),
                    "rate_denominator": synth.get("rate_denominator", synth.get("n_eligible")),
                    "n_eligible": synth.get("n_eligible"),
                }
        if occ_pres:
            preserved["occlusion"] = occ_pres

    # (5) Shared PUBLIC boundary — same helpers as caption (rg-015). Allow-list
    #     drops base_url / cache_dir / operator_note / run_record_path / …;
    #     path redaction collapses absolute paths; identity scrub hits free text
    #     including list[str] leaves (RB-01) and non-path absolute paths (RB-03).
    redacted["provenance"] = _public_provenance(redacted.get("provenance") or {})
    redacted = _redact_public_paths(redacted, names=scrub_names, path_to_media=path_to_media)
    redacted = _scrub_face_public_free_text(
        redacted, scrub_names, publishable_names=publishable_names
    )

    redacted["redaction"] = {
        "audience": "public",
        "mode": "post_score_redact_face_report_for_public",
        "grounded_on": "manifest.Provenance.is_publishable (stamped per decision at score time)",
        "stripped_decision_rows": stripped,
        "preserved_aggregate_denominators": preserved,
        "note": (
            "Aggregate rates (incl. unknown-rejection) preserved from full-corpus "
            "score with denominators retained under preserved_aggregate_denominators; "
            "every non-publishable per-face detail row + identity list "
            "(clustering labels, wrong_names under all slices, failures) stripped; "
            "provenance allow-list + path redaction + identity scrub shared with "
            "caption PUBLIC (_public_provenance / _redact_public_paths / "
            "_scrub_face_public_free_text). Fail-closed structural walk (not key "
            "enumeration). Distinct from pre-score _filter_for_public_audience / "
            "Audience.PUBLIC."
        ),
    }
    # RB-02: scrub the redaction envelope itself so a future free-text field
    # cannot bypass the walk by being stamped after scrub.
    redacted["redaction"] = _scrub_face_public_free_text(
        redacted["redaction"], scrub_names, publishable_names=publishable_names
    )
    # Do NOT drop unknown_rejection aggregates — they must stay.
    return _sort_nested_lists(redacted)


def _fmt_rate_n_over_n(rate: Any, num: Any, den: Any) -> str:
    """Format a published rate with explicit n/N (AUDIT-13). RB-05: no raw None."""
    return f"{_fmt(rate)} ({_fmt_prov(num)}/{_fmt_prov(den)})"


# Contract token on provenance.corpus_traps[].affects (VLM6-R2-C-02 / EVAL-03).
# Renderers filter on this field — never on kind strings or media ids (rg-009).
CORPUS_TRAP_AFFECTS_DETECTION_FN = "detection_fn"


def _corpus_traps_with_affect(traps: object, affect: str) -> list[Mapping[str, Any]]:
    """Return trap entries whose machine-readable ``affects`` list includes ``affect``."""
    if not isinstance(traps, list):
        return []
    matched: list[Mapping[str, Any]] = []
    for trap in traps:
        if not isinstance(trap, Mapping):
            continue
        affects = trap.get("affects")
        if isinstance(affects, (list, tuple, set)) and affect in affects:
            matched.append(trap)
    return matched


def _fixture_local_detection_caveat_line(
    *,
    traps: object,
    fn: object,
    scored_images: object,
) -> str | None:
    """EVAL-03 / VLM6-R2-C-02 / VLM6-PANEL6L-rvE-01: disclose fixture-local
    detection FN traps.

    Filters solely on ``affects`` containing ``detection_fn``. Absent that tag,
    emit nothing so a real population corpus cannot grow a phantom caveat.

    ``N`` counts matching trap *media*, never trap-attributed FN: a trap image
    with several GT faces contributes several FN (freeze media 10 contributes 2).
    When every matching trap declares its own ``fn_count`` (VLM6-PANEL6L-rvE-01
    — a per-trap figure, never a corpus-total denominator, so it cannot go
    stale as traps are added/removed), the sentence states the derived
    trap_fn share; otherwise it falls back to declaring the share undisclosed
    rather than inventing one (rg-015).
    """
    traps_fn = _corpus_traps_with_affect(traps, CORPUS_TRAP_AFFECTS_DETECTION_FN)
    if not traps_fn:
        return None
    ordered = sorted(
        traps_fn,
        key=lambda t: (int(t.get("media_id") or 0), str(t.get("path") or "")),
    )
    media_bits = ", ".join(f"{t.get('media_id')} `{t.get('path')}`" for t in ordered)
    n = len(ordered)
    fn_counts = [t.get("fn_count") for t in ordered]
    if all(isinstance(c, int) for c in fn_counts):
        trap_fn = sum(fn_counts)
        share_clause = f"trap_fn={trap_fn} of fn={_fmt_prov(fn)} is attributable to them"
    else:
        share_clause = (
            "the FN share attributable to them is not derivable from this table "
            "(a trap image with several GT faces misses several)"
        )
    return (
        "- ⚠ fixture-local detection frame — recall is NOT a population estimate: "
        f"fn={_fmt_prov(fn)} includes misses from {n} deliberate trap media "
        f"({media_bits}) added so the pre-HARM-01 named-only FN formula goes red; "
        f"{share_clause}. This corpus is a "
        f"synthetic determinism anchor "
        f"({_fmt_prov(scored_images)} images), not a sampled population."
    )


def _markdown_face(scored: dict[str, Any]) -> str:
    prov = scored.get("provenance") or {}
    model = prov.get("model") or {}
    gp = scored.get("gate_proposal") or {}
    slices = scored.get("slices") or {}
    det = scored.get("detection") or {}
    counts = scored.get("counts") or {}
    lines = [
        "# Face Bake-off Eval Report",
        "",
        f"- schema: `{scored.get('schema')}` kind: `{scored.get('kind')}` report_kind: `{scored.get('report_kind')}`",
        f"- model_ids: `{', '.join(model.get('model_ids') or []) or 'unknown'}` "
        f"embedding_dims: `{_fmt_prov(model.get('embedding_dims'))}` leg: `{_fmt_prov(model.get('leg'))}`",
        f"- head_sha: `{_fmt_prov(prov.get('head_sha'))}`",
        f"- fetch manifest_sha256: `{_fmt_prov(prov.get('manifest_sha256'))}`",
        _manifest_drift_line(prov),
        f"- started_at: {_fmt_prov(prov.get('started_at'))}",
        f"- canon_version: `{_fmt_prov(prov.get('canon_version'), default=FACE_BAKEOFF_CANON_VERSION)}` "
        f"protocol_id: `{_fmt_prov(prov.get('protocol_id'), default=FACE_BAKEOFF_PROTOCOL_ID)}`",
        f"- zero_box_corpus: {_fmt_prov(prov.get('zero_box_corpus'))} "
        f"total_gt_boxes: {_fmt_prov(prov.get('total_gt_boxes'))}",
        f"- images: {_fmt_prov(counts.get('scored'))}/{_fmt_prov(counts.get('total'))} scored, "
        f"{_fmt_prov(counts.get('failed'))} failed; matched_faces={_fmt_prov(counts.get('matched_faces'))}",
    ]
    if prov.get("low_sample_warning"):
        lines.append(f"- ⚠️ **low_sample_warning**: {_fmt_prov(prov.get('low_sample_warning'))}")
    if prov.get("quality_floor_caveat"):
        lines.append(f"- quality_floor_caveat: {_fmt_prov(prov.get('quality_floor_caveat'))}")
    lines += [
        "",
        "## Detection",
        "",
        f"- precision: {_fmt(det.get('precision'))} recall: {_fmt(det.get('recall'))} "
        f"(tp={_fmt_prov(det.get('tp'))} fp={_fmt_prov(det.get('fp'))} fn={_fmt_prov(det.get('fn'))} "
        f"geometry_incomplete_gt={_fmt_prov(det.get('geometry_incomplete_gt'))} "
        f"association_incomplete_media={_fmt_prov(det.get('association_incomplete_media'))} "
        f"association_complete={_fmt_prov(det.get('association_complete'))}) "
        f"frame=`{_fmt_prov(det.get('sampling_frame'), default='')}`",
    ]
    # wH1 / EVAL-03: disclose geometry-incomplete exclusion so operators can
    # reconcile tp+fn against n_gt (identity: tp+fn+geometry_incomplete_gt = n_gt).
    if det.get("geometry_incomplete_gt"):
        lines.append(
            f"- ⚠ geometry-incomplete GT excluded from detection FN: "
            f"geometry_incomplete_gt={_fmt_prov(det.get('geometry_incomplete_gt'))} "
            f"(of n_gt=tp+fn+incomplete="
            f"{_fmt_prov((det.get('tp') or 0) + (det.get('fn') or 0) + (det.get('geometry_incomplete_gt') or 0))}; "
            f"association_incomplete_media="
            f"{_fmt_prov(det.get('association_incomplete_media'))}; "
            f"association_complete={_fmt_prov(det.get('association_complete'))})"
        )
    # VLM6-R2-C-02 / EVAL-03: fixture-local detection frame. Filter on
    # corpus_traps[].affects only — never kind / media id (rg-009).
    caveat = _fixture_local_detection_caveat_line(
        traps=prov.get("corpus_traps"),
        fn=det.get("fn"),
        scored_images=counts.get("scored"),
    )
    if caveat:
        lines.append(caveat)
    # VLM6-R2-G-01 / wG1: GT-side y-missing + predicted stamp disclosure (same
    # field names as caption faces.identity_ordering). Denominator = counts.scored.
    ordering = scored.get("identity_ordering") if isinstance(scored.get("identity_ordering"), Mapping) else {}
    if ordering:
        lines += [
            "",
            "## Identity ordering",
            "",
            f"- positional_images={_fmt_prov(ordering.get('positional_images'))} "
            f"degraded_images={_fmt_prov(ordering.get('degraded_images'))} "
            f"order_unknown_excluded={_fmt_prov(ordering.get('order_unknown_excluded'))} "
            f"labeled_y_missing_images={_fmt_prov(ordering.get('labeled_y_missing_images'))} "
            f"(denominator: scored_images={_fmt_prov(counts.get('scored'))})",
        ]
        if ordering.get("degraded_images"):
            lines.append(
                f"- ⚠ predicted identity ordering degraded on {ordering['degraded_images']} image(s): "
                + ", ".join(f"`{p}`" for p in ordering.get("degraded_paths") or [])
            )
        if ordering.get("labeled_y_missing_images"):
            lines.append(
                f"- ⚠ labeled L→R y-missing (order_degraded) on "
                f"{ordering['labeled_y_missing_images']} image(s): "
                + ", ".join(f"`{p}`" for p in ordering.get("labeled_y_missing_paths") or [])
            )
        if ordering.get("order_unknown_excluded"):
            lines.append(
                f"- ⚠ identity order unknown / positional-excluded on "
                f"{ordering['order_unknown_excluded']} image(s)"
            )
    lines += [
        "",
        "## Floor-gated slices",
        "",
    ]
    hl = slices.get("headline_identification") or {}
    if hl.get("refused"):
        lines.append(
            f"- **headline_identification**: REFUSED ({hl.get('invariant')}): "
            f"{refusal_explanation(hl.get('invariant'))}"
        )
    else:
        lines.append(
            f"- **headline_identification**: status=`{_fmt_prov(hl.get('status', hl.get('label', '?')))}` "
            f"directional={_fmt_prov(hl.get('directional'))} "
            f"precision={_fmt_rate_n_over_n(hl.get('precision'), hl.get('precision_numerator'), hl.get('precision_denominator'))} "
            f"recall={_fmt_rate_n_over_n(hl.get('recall'), hl.get('recall_numerator'), hl.get('recall_denominator'))} "
            f"n_recall_eligible={_fmt_prov(hl.get('n_recall_eligible'))}/{_fmt_prov(hl.get('n_floor'))} "
            f"frame=`{_fmt_prov(hl.get('sampling_frame'), default='')}`"
        )
    unk = slices.get("unknown_rejection") or {}
    if unk.get("refused"):
        lines.append(
            f"- **unknown_rejection**: REFUSED ({unk.get('invariant')}): "
            "unknown-rejection is not scored from identity claims that carry "
            "no per-face box lineage"
        )
    else:
        lines.append(
            f"- **unknown_rejection**: status=`{_fmt_prov(unk.get('status', unk.get('label', '?')))}` "
            f"directional={_fmt_prov(unk.get('directional'))} "
            f"rate={_fmt_rate_n_over_n(unk.get('rate'), unk.get('rate_numerator', unk.get('correct_rejects')), unk.get('rate_denominator', unk.get('n')))} "
            f"n={_fmt_prov(unk.get('n'))}/{_fmt_prov(unk.get('n_floor'))} "
            f"missed_stranger_gt={_fmt_prov(unk.get('missed_stranger_gt'))} "
            f"frame=`{_fmt_prov(unk.get('sampling_frame'), default='')}`"
        )
    cl = slices.get("clustering") or {}
    lines.append(
        f"- **clustering**: status=`{_fmt_prov(cl.get('status', cl.get('label', '?')))}` "
        f"directional={_fmt_prov(cl.get('directional'))} "
        f"purity={_fmt(cl.get('purity'))} "
        f"false_merge={_fmt(cl.get('false_merge'))} false_split={_fmt(cl.get('false_split'))} "
        f"P_same={_fmt_prov(cl.get('p_same'))} P_diff={_fmt_prov(cl.get('p_diff'))} "
        f"M={_fmt_prov(cl.get('m_co_clustered'))} "
        f"frame=`{_fmt_prov(cl.get('sampling_frame'), default='')}`"
    )
    occ = slices.get("occlusion") or {}
    if occ:
        lines += ["", "### Occlusion recovery", ""]
        for tag in sorted(occ):
            block = occ[tag] or {}
            synth = block.get("synthetic") or {}
            lines.append(
                f"- **occlusion.{tag}**: status=`{synth.get('status', synth.get('label', '?'))}` "
                f"directional={_fmt_prov(synth.get('directional'))} "
                f"accuracy={_fmt_rate_n_over_n(synth.get('accuracy'), synth.get('rate_numerator', synth.get('n_correct')), synth.get('rate_denominator', synth.get('n_eligible')))} "
                f"n_eligible={_fmt_prov(synth.get('n_eligible'))}/"
                f"{_fmt_prov(synth.get('n_floor'), default=str(ELIGIBLE_PAIR_FLOOR))}"
            )
    lines += ["", "## Gate proposal (excludes DIRECTIONAL)", ""]
    lines.append(f"- role: {_fmt_prov(gp.get('role'))}")
    lines.append(
        f"- release_surface: `{_fmt_prov(gp.get('release_surface'), default=GATE_PROPOSAL_RELEASE_SURFACE)}`"
    )
    lines.append(
        f"- canon_version: `{_fmt_prov(gp.get('canon_version'), default=FACE_BAKEOFF_CANON_VERSION)}`"
    )
    lines.append(f"- proposed_slices: {sorted((gp.get('proposed_slices') or {}).keys())}")
    lines.append(f"- excluded_directional: {_fmt_prov(gp.get('excluded_directional'))}")
    couple = gp.get("identification_detection_coupling") or {}
    lines.append(
        f"- id-recall: {_fmt(couple.get('identification_recall'))} "
        f"alongside detection-recall: {_fmt(couple.get('detection_recall'))} "
        f"(coupling_flag={_fmt_prov(couple.get('detection_recall_coupling_flag'))}, "
        f"missed_gt={_fmt_prov(couple.get('missed_gt'))}, "
        f"unmatched_det={_fmt_prov(couple.get('unmatched_detections'))}) "
        f"— {_fmt_prov(couple.get('flag'), default='')}"
    )
    lines.append(f"- p95 scan latency: {_fmt_prov(gp.get('p95_scan_latency'))}")
    lines.append("- scope amendments (operator ack required):")
    for a in gp.get("scope_amendments_for_operator_ack") or []:
        lines.append(f"  - {_fmt_prov(a)}")
    if scored.get("redaction"):
        r = scored["redaction"]
        lines += [
            "",
            "## Redaction",
            "",
            f"- audience=`{r.get('audience')}` mode=`{r.get('mode')}` "
            f"stripped_decision_rows={r.get('stripped_decision_rows')}",
            f"- preserved_aggregate_denominators keys: "
            f"{sorted((r.get('preserved_aggregate_denominators') or {}).keys())}",
        ]
    lines += ["", "## Failures", ""]
    if scored.get("failures"):
        lines += [f"- `{f.get('path')}` (media_id={f.get('media_id')}): {f.get('error')}" for f in scored["failures"]]
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def build_face_reports(
    face_run_record: dict[str, Any],
    manifest: Any,
    *,
    score_manifest_sha256: str | None = None,
    occlusion_pairs_by_tag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    real_occlusion_pairs_by_tag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    walk_stability_by_tag: Mapping[str, Mapping[str, Any]] | None = None,
    public: bool = False,
) -> tuple[str, str]:
    """Return (json_report, markdown_report) for a face run-record.

    Always scores the full corpus. When ``public=True``, applies
    ``redact_face_report_for_public`` post-score (never pre-score filter).
    """
    scored = score_face_run_record(
        face_run_record,
        manifest,
        score_manifest_sha256=score_manifest_sha256,
        occlusion_pairs_by_tag=occlusion_pairs_by_tag,
        real_occlusion_pairs_by_tag=real_occlusion_pairs_by_tag,
        walk_stability_by_tag=walk_stability_by_tag,
    )
    if public:
        scored = redact_face_report_for_public(scored)
    return (
        json.dumps(scored, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        _markdown_face(scored),
    )
