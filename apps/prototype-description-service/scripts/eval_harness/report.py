"""Score a run record and build JSON + markdown reports (regression-harness pattern).

Split Phase: the fetch phase writes a run record (raw remote responses +
provenance); this module is the pure score phase — re-runnable offline,
bit-identical for unchanged inputs. The JSON artifact is an additive extension
of the E19-1 benchmark schema (``metrics``/``faces`` sections).

The ignore-list (a JSON file persisted next to the reports) suppresses triaged
wrong-name false positives across runs without deleting them: ignored entries
move to ``ignored_wrong_names`` so the report stays honest about what was
triaged away.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from .caption_metrics import (
    LONG_SENTENCE_BAND,
    SHORT_SENTENCE_BAND,
    CaptionScores,
    insertion_rate,
    name_precision,
    score_caption,
    wrong_name_image_rate,
)
from .face_assignment import (
    FOLD_MEDIA_CORESIDENCY_DISCLOSURE,
    TAU_GRID,
    associate_detections,
    score_face_assignment,
)
from .face_metrics import (
    CLUSTER_PAIR_FLOOR,
    SAMPLING_FRAME_CLUSTERING,
    SAMPLING_FRAME_FACE_ID,
    SAMPLING_FRAME_UNKNOWN_REJECTION,
    UNKNOWN_REJECTION_ERROR_TARGET,
    UNKNOWN_REJECTION_N_FLOOR,
    ImageDetection,
    ImageIdentities,
    clustering_sweep,
    demographic_rollup,
    detection_pr,
    face_identification_pr,
    face_unknown_rejection,
    identification_pr,
)
from .manifest import (
    AnnotationMode,
    ManifestError,
    Provenance,
    ProvenanceSource,
    SliceTag,
    parse_annotation_mode,
)
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

DETECTION_REFUSED_EXPLANATION = (
    "detection P/R is not computed unless annotation_mode is exhaustive"
)

# Bake-off protocol posture disclosed on every scored face artifact (FIR5RC-07).
# Measured protocol changes (weighted prototypes, ambiguity margin, matched
# non-mate impostors) are FIR-6 S4/S5-owned; FIR-5 owns honest disclosure.
FACE_BAKEOFF_PROTOCOL_DISCLOSURES: tuple[str, ...] = (
    "mean_prototype is an unweighted raw mean — one blurred face moves the "
    "identity centroid (EMB-02); weighted/medoid prototypes are FIR-6-owned",
    "open-set accept is raw cosine vs τ with no ambiguity/margin penalty "
    "(EMB-09); product ternary accept|suggest|reject is FIR-6-owned",
    "impostors are pooled zero-effort strangers rather than matched non-mates "
    "(CAL-04 posture declared in FIR-6 plan)",
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


class ReportError(Exception):
    """The run record cannot be scored: wrong document kind, unknown schema, or a
    run-record item whose media_id is absent from the score-time manifest."""


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


def _filter_for_public_audience(
    run_record: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Keep only publishable items/entries before scoring. Returns withheld count."""
    entries = _entry_index(manifest_entries)
    kept_items: list[dict[str, Any]] = []
    for item in run_record["items"]:
        media_id = int(item["media_id"])
        if _entry_is_publishable(entries.get(media_id)):
            kept_items.append(item)
    filtered_record = {**run_record, "items": kept_items}
    # Rubric / lookup surface: only publishable entries so public metrics stay scoped.
    filtered_entries = [e for e in manifest_entries if _entry_is_publishable(e)]
    withheld = len(run_record["items"]) - len(kept_items)
    return filtered_record, filtered_entries, withheld


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
    Items with an error or no timing data are skipped. Returns ``None`` when
    nothing is timed so untimed (pre-Slice-3 fixture) records keep their exact
    report shape (additive schema). Pure and deterministic; NO cost math here —
    $/1k images stays a memo-time formula (plan §Slice 3)."""
    wall_clock: list[float] = []
    calls: list[int] = []
    for item in items:
        if item.get("error"):
            continue
        describe = item.get("describe") or {}
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
        return None
    ordered = sorted(wall_clock)
    return {
        "images_timed": len(wall_clock),
        "wall_clock_s": {
            "p50": round(_percentile(ordered, 0.5), 3),
            "p95": round(_percentile(ordered, 0.95), 3),
        },
        "model_calls": {
            "per_image_mean": round(sum(calls) / len(calls), 4),
            "total": sum(calls),
        },
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
    """
    explicit = parse_annotation_mode(annotation_mode)
    if len(manifest_entries) == 0:
        raise ManifestError(
            "score entries are empty; zero entries cannot witness a "
            "detection contract (refusing explicit exhaustive fail-open)",
            invariant="detection_refuses_empty_entries",
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
    if missing:
        return None
    if len(stamped) > 1:
        raise ReportError(
            f"mixed annotation_mode on score entries: "
            f"{sorted(member.value for member in stamped)}; "
            "refusing to guess which detection contract applies"
        )
    if not stamped:
        return explicit
    data = next(iter(stamped))
    if explicit is None:
        return data
    if _MODE_RESTRICTIVENESS[explicit] > _MODE_RESTRICTIVENESS[data]:
        return explicit
    return data


def score_run_record(
    run_record: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
    ignore_list: dict[str, Any] | None = None,
    *,
    score_manifest_sha256: str | None = None,
    manifest_roster: list[str] | None = None,
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
    _validate_record_kind(run_record)
    eval_mode = str(run_record["provenance"].get("eval_mode", "standard"))
    if eval_mode not in EVAL_MODES:
        raise ReportError(f"unknown eval_mode {eval_mode!r} in run-record provenance; expected one of {EVAL_MODES}")
    entries = _entry_index(manifest_entries)
    roster = _corpus_roster(manifest_entries, manifest_roster)
    caption_scores: list[CaptionScores] = []
    long_scores: list[CaptionScores] = []
    gated_values: list[float] = []
    per_image: list[dict[str, Any]] = []
    detections: list[ImageDetection] = []
    identifications: list[ImageIdentities] = []
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
        if short_error is None:
            caption = str(describe.get("alt_text_draft", ""))
            scores = score_caption(caption, **score_kwargs)
            caption_scores.append(scores)
            gated = _ablation_gate(scores) if eval_mode == "name_ablation" else scores.gated_score
            if gated is not None:
                gated_values.append(gated)

        long_text = describe.get("alt_text_long")
        long_s = score_caption(str(long_text), **score_kwargs) if isinstance(long_text, str) and long_text else None
        if long_s is not None:
            long_scores.append(long_s)

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
        face_count = int(entry["face_count"])
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
        identifications.append(
            ImageIdentities(
                image=path,
                predicted=list(item.get("identities", [])),
                labeled=list(entry["present_identities"]),
                recognition_enabled=recognition_enabled,
                stranger_faces=stranger_faces,
            )
        )
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
        if exc.invariant not in {
            "detection_unrecognised_annotation_mode",
            "detection_refuses_empty_entries",
        }:
            raise
        det = None
        detection_invariant = exc.invariant
    else:
        if mode is AnnotationMode.EXHAUSTIVE:
            det = detection_pr(detections, annotation_mode=mode)
            detection_invariant = None
        elif mode is AnnotationMode.ROSTER_ONLY:
            det = None
            detection_invariant = "detection_refuses_roster_only"
        else:
            det = None
            detection_invariant = "detection_requires_annotation_mode"
    ident = identification_pr(identifications)

    ignored_pairs = {tuple(p) for p in (ignore_list or {}).get("wrong_names", [])}
    live_wrong = [list(p) for p in ident.wrong_names if tuple(p) not in ignored_pairs]
    ignored_wrong = [list(p) for p in ident.wrong_names if tuple(p) in ignored_pairs]

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
    }

    rubric_images = sum(1 for e in manifest_entries if e.get("must_right") or e.get("easy_wrong"))

    def _quality_block(scores: list[CaptionScores], band: tuple[int, int]) -> dict[str, Any]:
        duplication = [s.context_duplication_ratio for s in scores if s.context_duplication_ratio is not None]
        front = [s.name_front_loaded for s in scores if s.name_front_loaded is not None]
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
        }

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": DocKind.REPORT.value,
        "eval_mode": eval_mode,
        "provenance": provenance,
        "counts": {
            "total": len(run_record["items"]),
            "scored": len(per_image),
            "failed": len(failures),
        },
        "caption": {
            "insertion_rate": insertion_rate(caption_scores),
            "name_precision": name_precision(caption_scores),
            "wrong_name_image_rate": wrong_name_image_rate(caption_scores),
            "must_right_failed_images": sum(1 for s in caption_scores if not s.must_right_pass),
            "must_right_defined_images": rubric_images,  # 0 => hard gate vacuous (S1-02)
            "policy_violations": sum(1 for s in caption_scores if s.policy_violation),
            "wrong_name_images": sum(1 for s in caption_scores if s.named_wrong_person),
            "mean_gated_score": (round(sum(gated_values) / len(gated_values), 4) if gated_values else None),
        },
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
            "identification": {
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
                "wrong_names": live_wrong,
                "ignored_wrong_names": ignored_wrong,
            },
        },
        "per_image": per_image,
        "failures": failures,
    }

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


def _fmt(value: float | None) -> str:
    return "null" if value is None else f"{value:.3f}"


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
        f"- head_sha: `{prov.get('head_sha', 'unknown')}`",
        f"- base_url: {prov.get('base_url', 'unknown')}",
        f"- fetch manifest_sha256: `{prov.get('manifest_sha256', 'unknown')}`",
        f"- score manifest_sha256: `{prov.get('score_manifest_sha256', 'unknown')}` "
        f"(matches fetch: {prov.get('manifest_matches_fetch')})",
        f"- started_at: {prov.get('started_at', 'unknown')}",
        f"- images: {scored['counts']['scored']}/{scored['counts']['total']} scored, "
        f"{scored['counts']['failed']} failed",
    ]
    # Honest redaction: public reports must state what they withheld (VLM-6 S1).
    redaction = scored.get("redaction")
    if redaction:
        lines.append(
            f"- redaction: audience=`{redaction['audience']}` — "
            f"withheld {redaction['withheld_items']} of {redaction['total_items']} items "
            "(local-only / non-publishable)"
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
    if cap["must_right_defined_images"] == 0:
        lines.append("- ⚠ no Must-Right/Easy-Wrong rubric entries in the corpus — the caption hard gate is vacuous.")
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
        lines.append(
            f"- latency: per-image wall-clock p50 {wall['p50']}s p95 {wall['p95']}s "
            f"({latency['images_timed']} timed) · model calls/image: {calls['per_image_mean']} "
            f"(total {calls['total']})"
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
        f"(rubric-defined images: {cap['must_right_defined_images']})",
        f"- policy violations: {cap['policy_violations']}",
        f"- mean gated score: {_fmt(cap['mean_gated_score'])}",
    ]

    def _quality_lines(quality: dict[str, Any]) -> list[str]:
        band = quality.get("sentence_band", [])
        return [
            f"- meta-framing images: {quality['meta_framing_images']}",
            f"- mean context duplication: {_fmt(quality['mean_context_duplication'])}",
            f"- name front-loaded rate: {_fmt(quality['name_front_loaded_rate'])}",
            f"- sentence band {band} ok rate: {_fmt(quality['sentence_band_ok_rate'])}",
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
            f"- REFUSED ({det.get('invariant')}): {DETECTION_REFUSED_EXPLANATION}"
            if det.get("refused")
            else (
                f"- precision: {_fmt(det['precision'])} recall: {_fmt(det['recall'])} "
                f"(tp={det['tp']} fp={det['fp']} fn={det['fn']})"
            )
        ),
        "",
        "## Face identification (named assertions)",
        "",
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
    lines += ["", "## Per-item failures", ""]
    if scored["failures"]:
        lines += [f"- `{f['path']}` (media_id={f['media_id']}): {f['error']}" for f in scored["failures"]]
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def build_reports(
    run_record: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
    ignore_list: dict[str, Any] | None = None,
    *,
    score_manifest_sha256: str | None = None,
    manifest_roster: list[str] | None = None,
    annotation_mode: AnnotationMode | str | None = None,
    audience: Audience = Audience.LOCAL,
) -> tuple[str, str]:
    """Return (json_report, markdown_report) — deterministic for identical inputs.

    ``audience=LOCAL`` (default) scores the full corpus — byte-identical to the
    pre-audience contract. ``audience=PUBLIC`` filters to publishable items only
    (via ``Provenance.is_publishable``) and stamps a top-level ``redaction`` block
    so withheld local-only items are never silent.
    """
    score_record = run_record
    score_entries = manifest_entries
    redaction: dict[str, Any] | None = None
    if audience is Audience.PUBLIC:
        total_items = len(run_record["items"])
        score_record, score_entries, withheld = _filter_for_public_audience(run_record, manifest_entries)
        redaction = {
            "audience": Audience.PUBLIC.value,
            "withheld_items": withheld,
            "total_items": total_items,
        }
    scored = score_run_record(
        score_record,
        score_entries,
        ignore_list=ignore_list,
        score_manifest_sha256=score_manifest_sha256,
        manifest_roster=manifest_roster,
        annotation_mode=annotation_mode,
    )
    if redaction is not None:
        scored["redaction"] = redaction
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
HEADLINE_ID_ERROR_TARGET = (
    "Wilson_95_halfwidth_le_10pct_at_p0.5 (n≈96–100 → ±9.8%)"
)
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


def _gt_box_name(box: Any) -> str | None:
    if isinstance(box, Mapping):
        name = box.get("name")
    else:
        name = getattr(box, "name", None)
    return None if name is None else str(name)


def _association_counts_for_media(
    assignment: Any,
    media_ids: set[int],
    *,
    gt_by_media: Mapping[int, Sequence[Any]],
    probe_media_ids: set[int],
) -> tuple[int, int, list[str]]:
    """Headline-scoped miss / unmatched-detection counts (FIR5RR-06).

    - ``missed_gt`` counts only unmatched GT boxes with a non-None name: the
      headline frame is NAMED probes, so an unmatched stranger box must not
      inflate the miss count.
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
            named = sum(1 for b in boxes if _gt_box_name(b) is not None)
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
            elif _gt_box_name(boxes[gi]) is not None:
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
    """Read annotation_mode from a GoldenManifest or mapping; never invent one."""
    raw = getattr(manifest, "annotation_mode", None)
    if raw is None and isinstance(manifest, Mapping):
        raw = manifest.get("annotation_mode")
    return parse_annotation_mode(raw)


def _stamp_missing_annotation_mode(entries: list[dict[str, Any]], mode_value: str) -> None:
    """Fill omitted entry stamps from the document mode. Never overwrite.

    A blank or whitespace-only string is not omitted: it is an explicit
    empty token and is not inheritable (S2R3-02). Filling it would mint
    the parent mode onto an entry that never carried it and reopen
    exhaustive scoring on the face path. Leave the blank in place so the
    resolver treats it as missing (same as omitted-after-resolve) and
    refuses. Only a missing key or an explicit ``None`` is filled.
    Overwriting a real stamp would hide a conflict; leaving a disagreeing
    stamp lets the shared resolver apply most-restrictive-wins.
    """
    for entry in entries:
        if entry.get("annotation_mode") is None:
            entry["annotation_mode"] = mode_value


def _entries_as_dicts(manifest: Any) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    """Normalize GoldenManifest | mapping | entry-list into plain dicts."""
    mode = _annotation_mode_of(manifest)
    mode_value = None if mode is None else mode.value
    if hasattr(manifest, "entries") and hasattr(manifest, "roster"):
        entries = [e.model_dump() if hasattr(e, "model_dump") else dict(e) for e in manifest.entries]
        roster_cohorts = dict(getattr(manifest, "roster_cohorts", {}) or {})
        roster = list(getattr(manifest, "roster", []) or [])
        if mode_value is not None:
            _stamp_missing_annotation_mode(entries, mode_value)
        return entries, roster_cohorts, roster
    if isinstance(manifest, Mapping):
        raw_entries = list(manifest.get("entries") or [])
        entries = [e.model_dump() if hasattr(e, "model_dump") else dict(e) for e in raw_entries]
        if mode_value is not None:
            _stamp_missing_annotation_mode(entries, mode_value)
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
            name = b.get("name") if isinstance(b, Mapping) else getattr(b, "name", None)
            if name:
                named.add(str(name))
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
    tp = sum(len(a.pairs) for a in assignment.association_by_media.values())
    fp = int(assignment.false_detections)
    fn = int(assignment.missed_gt)
    precision = (tp / (tp + fp)) if (tp + fp) else 0.0
    recall = (tp / (tp + fn)) if (tp + fn) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "tp": tp,
        "fp": fp,
        "fn": fn,
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
        occ_tags = [
            t for t in (str(tag) for tag in (entry.get("tags") or [])) if t in _OCCLUSION_TAG_VALUES
        ]
        if not occ_tags:
            continue
        boxes = list(entry.get("face_boxes") or [])
        named = [
            (i, box)
            for i, box in enumerate(boxes)
            if (box.get("name") if isinstance(box, Mapping) else getattr(box, "name", None))
        ]
        if not named:
            continue
        faces = list(item.get("faces") or [])
        assoc = associate_detections(
            [f["bbox_px"] for f in faces],
            boxes,
            list(item.get("image_size") or [1, 1]),
        )
        emb_by_gt = {
            p.gt_index: [float(v) for v in faces[p.det_index]["embedding"]] for p in assoc.pairs
        }
        for gt_index, box in named:
            name = box.get("name") if isinstance(box, Mapping) else getattr(box, "name", None)
            for tag in occ_tags:
                out.setdefault(tag, []).append(
                    {
                        "media_id": int(item["media_id"]),
                        "box_index": gt_index,
                        "true_name": str(name),
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
    mode = _resolve_score_annotation_mode(_annotation_mode_of(manifest), entries)
    if mode is not AnnotationMode.EXHAUSTIVE:
        if mode is AnnotationMode.ROSTER_ONLY:
            raise ManifestError(
                "score_face_run_record refuses roster_only manifests; unlabeled "
                "non-roster faces would be scored as false positives",
                invariant="detection_refuses_roster_only",
            )
        raise ManifestError(
            "score_face_run_record requires annotation_mode=exhaustive; "
            "omission is not exhaustive",
            invariant="detection_requires_annotation_mode",
        )
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

    assignment = score_face_assignment(scoreable, gt_by_media)
    detection = _detection_from_assignment(assignment)

    # Full-corpus identification + unknown-rejection (includes private strangers).
    id_pr = face_identification_pr(
        assignment.decisions,
        missed_gt=assignment.missed_gt,
        unmatched_detections=assignment.false_detections,
        sampling_frame=FACE_BAKEOFF_SAMPLING_FRAMES["full_corpus_identification"],
    )
    unknown = face_unknown_rejection(assignment.decisions)

    # Headline = celebs01 named probes only (provenance.source == CELEB).
    # Coupling counts are headline-scoped (not full-corpus) so the honesty flag
    # matches the published rate's sampling frame (FIR5V11-05 / REF-27).
    celebs01_ids = {mid for mid, e in entry_by_id.items() if _is_celebs01(e)}
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

    # FIR5RR-07: mid-grid-unfitted τ can never back a gating number — every
    # τ-dependent slice is forced DIRECTIONAL with an explicit reason.
    tau_unfitted = assignment.tau_fit_status != "fitted"
    tau_unfitted_reason = f"tau_fit_status={assignment.tau_fit_status}"

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

    # Demographic Fair-SA (always DIRECTIONAL — no floor).
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
        {f.true_name for f in assignment.matched if f.true_name is not None}
        - set(tau_by_identity)
    )
    occlusion_out: dict[str, Any] = {}
    occlusion_pairs_by_tag = occlusion_pairs_by_tag or {}
    real_occlusion_pairs_by_tag = real_occlusion_pairs_by_tag or {}
    walk_stability_by_tag = walk_stability_by_tag or {}
    for tag in sorted(set(occlusion_pairs_by_tag) | set(real_occlusion_pairs_by_tag) | {"masked", "sunglasses", "occlusion_other"}):
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
        synth_directional = (
            bool(synth_acc.directional)
            or zero_box_corpus
            or divergence["auto_demote"]
            or tau_unfitted
        )
        synth_reasons = list(synth_acc.directional_reasons)
        if zero_box_corpus:
            synth_reasons.append("zero_box_corpus")
        if divergence["auto_demote"]:
            synth_reasons.append(
                f"synthetic_real_divergence d={divergence['d']}>threshold={divergence['threshold']}"
            )
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
    slices: dict[str, Any] = {
        "headline_identification": {
            **_face_pr_dict(headline_id),
            "n_floor": HEADLINE_ID_RECALL_ELIGIBLE_FLOOR,
            "floor_unit": "recall_eligible_celebs01",
            "error_target": HEADLINE_ID_ERROR_TARGET,
            # FIR5RR-06: celebs01 media that never reached association are
            # disclosed here (their manifest named faces were counted as misses).
            "association_provenance_notes": list(headline_assoc_notes),
            **headline_status,
        },
        "unknown_rejection": {
            "rate": unknown.rate,
            "correct_rejects": unknown.correct_rejects,
            "false_accepts": unknown.false_accepts,
            "n": unknown.n,
            "n_floor": UNKNOWN_REJECTION_N_FLOOR,
            "error_target": UNKNOWN_REJECTION_ERROR_TARGET,
            "sampling_frame": unknown.sampling_frame,
            "rate_numerator": unknown.rate_numerator,
            "rate_denominator": unknown.rate_denominator,
            **unknown_status,
        },
        "clustering": {
            **cluster_block,
            "sampling_frame": SAMPLING_FRAME_CLUSTERING,
        },
        "occlusion": occlusion_out,
        "demographic": demo_block,
        "full_corpus_identification": _face_pr_dict(id_pr),
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
        "identification_detection_coupling": {
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
        },
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
            None
            if score_manifest_sha256 is None
            else score_manifest_sha256 == fetch_provenance.get("manifest_sha256")
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
        "slices": slices,
        "gate_proposal": gate_proposal,
        "decisions": decisions_json,
        "failures": sorted(failures, key=lambda f: (f.get("media_id", -1), f.get("path", ""))),
    }
    return _sort_nested_lists(report)


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
    """
    redacted = copy.deepcopy(report)

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

    # (3) wrong_names rows [media_id, box_index, true, pred] can name a private
    #     individual and carry no publishability signal ⇒ drop the detail from
    #     BOTH identification slices (aggregate precision/recall already preserved
    #     in each block). Same for ignored_wrong_names.
    for key in ("headline_identification", "full_corpus_identification"):
        block = slices.get(key)
        if isinstance(block, dict):
            block["wrong_names"] = []
            block["ignored_wrong_names"] = []

    # (4) Failure rows embed media paths and carry no publishability signal ⇒ drop
    #     wholesale (operator-triage detail only). Aggregate failed-count stays in
    #     ``counts``.
    redacted["failures"] = []

    # AUDIT-09/12: redaction strips decision rows but must retain denominators
    # for every published aggregate rate so n/N honesty survives public export.
    preserved: dict[str, Any] = {}
    hl = slices.get("headline_identification")
    if isinstance(hl, dict):
        preserved["headline_identification"] = {
            "precision_numerator": hl.get("precision_numerator"),
            "precision_denominator": hl.get("precision_denominator"),
            "recall_numerator": hl.get("recall_numerator"),
            "recall_denominator": hl.get("recall_denominator"),
            "n_named_probes": hl.get("n_named_probes"),
            "n_recall_eligible": hl.get("n_recall_eligible"),
            "sampling_frame": hl.get("sampling_frame"),
        }
    unk = slices.get("unknown_rejection")
    if isinstance(unk, dict):
        preserved["unknown_rejection"] = {
            "rate_numerator": unk.get("rate_numerator", unk.get("correct_rejects")),
            "rate_denominator": unk.get("rate_denominator", unk.get("n")),
            "n": unk.get("n"),
            "sampling_frame": unk.get("sampling_frame"),
        }
    full = slices.get("full_corpus_identification")
    if isinstance(full, dict):
        preserved["full_corpus_identification"] = {
            "precision_numerator": full.get("precision_numerator"),
            "precision_denominator": full.get("precision_denominator"),
            "recall_numerator": full.get("recall_numerator"),
            "recall_denominator": full.get("recall_denominator"),
            "n_named_probes": full.get("n_named_probes"),
            "n_recall_eligible": full.get("n_recall_eligible"),
            "sampling_frame": full.get("sampling_frame"),
        }
    occ = slices.get("occlusion")
    if isinstance(occ, dict):
        occ_pres: dict[str, Any] = {}
        for tag, block in occ.items():
            if not isinstance(block, dict):
                continue
            synth = block.get("synthetic") or {}
            if isinstance(synth, dict):
                occ_pres[str(tag)] = {
                    "rate_numerator": synth.get("rate_numerator", synth.get("n_correct")),
                    "rate_denominator": synth.get(
                        "rate_denominator", synth.get("n_eligible")
                    ),
                    "n_eligible": synth.get("n_eligible"),
                    "sampling_frame": synth.get("sampling_frame"),
                }
        if occ_pres:
            preserved["occlusion"] = occ_pres

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
            "(clustering labels, wrong_names, failures) stripped. Fail-closed on "
            "missing provenance. Distinct from pre-score _filter_for_public_audience "
            "/ Audience.PUBLIC."
        ),
    }
    # Do NOT drop unknown_rejection aggregates — they must stay.
    return _sort_nested_lists(redacted)


def _fmt_rate_n_over_n(rate: Any, num: Any, den: Any) -> str:
    """Format a published rate with explicit n/N (AUDIT-13)."""
    return f"{_fmt(rate)} ({num}/{den})"


def _markdown_face(scored: dict[str, Any]) -> str:
    prov = scored.get("provenance") or {}
    model = prov.get("model") or {}
    gp = scored.get("gate_proposal") or {}
    slices = scored.get("slices") or {}
    det = scored.get("detection") or {}
    lines = [
        "# Face Bake-off Eval Report",
        "",
        f"- schema: `{scored.get('schema')}` kind: `{scored.get('kind')}` report_kind: `{scored.get('report_kind')}`",
        f"- model_ids: `{', '.join(model.get('model_ids') or []) or 'unknown'}` "
        f"embedding_dims: `{model.get('embedding_dims')}` leg: `{model.get('leg')}`",
        f"- head_sha: `{prov.get('head_sha', 'unknown')}`",
        f"- score manifest_sha256: `{prov.get('score_manifest_sha256', 'unknown')}`",
        f"- canon_version: `{prov.get('canon_version', FACE_BAKEOFF_CANON_VERSION)}` "
        f"protocol_id: `{prov.get('protocol_id', FACE_BAKEOFF_PROTOCOL_ID)}`",
        f"- zero_box_corpus: {prov.get('zero_box_corpus')} total_gt_boxes: {prov.get('total_gt_boxes')}",
        f"- images: {scored.get('counts', {}).get('scored')}/{scored.get('counts', {}).get('total')} scored, "
        f"{scored.get('counts', {}).get('failed')} failed; matched_faces={scored.get('counts', {}).get('matched_faces')}",
        "",
        "## Detection",
        "",
        f"- precision: {_fmt(det.get('precision'))} recall: {_fmt(det.get('recall'))} "
        f"(tp={det.get('tp')} fp={det.get('fp')} fn={det.get('fn')})",
        "",
        "## Floor-gated slices",
        "",
    ]
    hl = slices.get("headline_identification") or {}
    lines.append(
        f"- **headline_identification**: status=`{hl.get('status', hl.get('label', '?'))}` "
        f"directional={hl.get('directional')} "
        f"precision={_fmt_rate_n_over_n(hl.get('precision'), hl.get('precision_numerator'), hl.get('precision_denominator'))} "
        f"recall={_fmt_rate_n_over_n(hl.get('recall'), hl.get('recall_numerator'), hl.get('recall_denominator'))} "
        f"n_recall_eligible={hl.get('n_recall_eligible')}/{hl.get('n_floor')} "
        f"frame=`{hl.get('sampling_frame', '')}`"
    )
    unk = slices.get("unknown_rejection") or {}
    lines.append(
        f"- **unknown_rejection**: status=`{unk.get('status', unk.get('label', '?'))}` "
        f"directional={unk.get('directional')} "
        f"rate={_fmt_rate_n_over_n(unk.get('rate'), unk.get('rate_numerator', unk.get('correct_rejects')), unk.get('rate_denominator', unk.get('n')))} "
        f"n={unk.get('n')}/{unk.get('n_floor')} "
        f"frame=`{unk.get('sampling_frame', '')}`"
    )
    cl = slices.get("clustering") or {}
    lines.append(
        f"- **clustering**: status=`{cl.get('status', cl.get('label', '?'))}` "
        f"directional={cl.get('directional')} "
        f"purity={_fmt(cl.get('purity'))} "
        f"false_merge={_fmt(cl.get('false_merge'))} false_split={_fmt(cl.get('false_split'))} "
        f"P_same={cl.get('p_same')} P_diff={cl.get('p_diff')} M={cl.get('m_co_clustered')} "
        f"frame=`{cl.get('sampling_frame', '')}`"
    )
    occ = slices.get("occlusion") or {}
    if occ:
        lines += ["", "### Occlusion recovery", ""]
        for tag in sorted(occ):
            block = occ[tag] or {}
            synth = block.get("synthetic") or {}
            lines.append(
                f"- **occlusion.{tag}**: status=`{synth.get('status', synth.get('label', '?'))}` "
                f"directional={synth.get('directional')} "
                f"accuracy={_fmt_rate_n_over_n(synth.get('accuracy'), synth.get('rate_numerator', synth.get('n_correct')), synth.get('rate_denominator', synth.get('n_eligible')))} "
                f"n_eligible={synth.get('n_eligible')}/{synth.get('n_floor', ELIGIBLE_PAIR_FLOOR)}"
            )
    lines += ["", "## Gate proposal (excludes DIRECTIONAL)", ""]
    lines.append(f"- role: {gp.get('role')}")
    lines.append(f"- release_surface: `{gp.get('release_surface', GATE_PROPOSAL_RELEASE_SURFACE)}`")
    lines.append(f"- canon_version: `{gp.get('canon_version', FACE_BAKEOFF_CANON_VERSION)}`")
    lines.append(f"- proposed_slices: {sorted((gp.get('proposed_slices') or {}).keys())}")
    lines.append(f"- excluded_directional: {gp.get('excluded_directional')}")
    couple = gp.get("identification_detection_coupling") or {}
    lines.append(
        f"- id-recall: {_fmt(couple.get('identification_recall'))} "
        f"alongside detection-recall: {_fmt(couple.get('detection_recall'))} "
        f"(coupling_flag={couple.get('detection_recall_coupling_flag')}, "
        f"missed_gt={couple.get('missed_gt')}, unmatched_det={couple.get('unmatched_detections')}) "
        f"— {couple.get('flag', '')}"
    )
    lines.append(f"- p95 scan latency: {gp.get('p95_scan_latency')}")
    lines.append("- scope amendments (operator ack required):")
    for a in gp.get("scope_amendments_for_operator_ack") or []:
        lines.append(f"  - {a}")
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
