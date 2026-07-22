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

from .caption_metrics import CaptionScores, insertion_rate, score_caption
from .face_assignment import TAU_GRID, score_face_assignment
from .face_metrics import (
    CLUSTER_PAIR_FLOOR,
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
from .manifest import Provenance, ProvenanceSource
from .schema import SCHEMA, DocKind
from .synthetic_occlusion import (
    ELIGIBLE_PAIR_FLOOR,
    SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES,
    assert_walk_stability,
    score_occlusion_accuracy,
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
    *SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES,
)


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


def score_run_record(
    run_record: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
    ignore_list: dict[str, Any] | None = None,
    *,
    score_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Pure scoring: run record + manifest labels -> metrics dict."""
    _validate_record_kind(run_record)
    entries = _entry_index(manifest_entries)
    caption_scores: list[CaptionScores] = []
    per_image: list[dict[str, Any]] = []
    detections: list[ImageDetection] = []
    identifications: list[ImageIdentities] = []
    failures: list[dict[str, Any]] = []

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
        caption = str(describe.get("alt_text_draft", ""))
        objects = list((describe.get("visual_facts") or {}).get("objects", []))
        scores = score_caption(
            caption,
            present_identities=list(entry["present_identities"]),
            must_right=list(entry["must_right"]),
            easy_wrong=list(entry["easy_wrong"]),
            recognition_enabled=recognition_enabled,
            objects=objects or None,
        )
        caption_scores.append(scores)
        # Ground-truth total faces (incl. non-roster strangers), not just named
        # roster identities — otherwise every stranger face is a detection FP and
        # true_rejections is unreachable (S3-01, HARM-04). Required, not defaulted:
        # a missing face_count must fail loud, never silently re-create the bug.
        face_count = int(entry["face_count"])
        stranger_faces = max(face_count - len(entry["present_identities"]), 0)
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
        per_image.append(
            {
                "path": path,
                "media_id": media_id,
                "gated_score": scores.gated_score,
                "must_right_failures": scores.must_right_failures,
                "policy_violation": scores.policy_violation,
                "inserted_identities": scores.inserted_identities,
                "missing_identities": scores.missing_identities,
                "fkre": round(scores.fkre, 2),
                "repetition_ratio": round(scores.repetition_ratio, 4),
                "tag_coverage": scores.tag_coverage,
                "first_sentence_gist_ok": scores.first_sentence_gist_ok,
                "cache_hit": bool(describe.get("cached", False)),  # contract field is 'cached' (HARM-02)
            }
        )

    det = detection_pr(detections)
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

    return {
        "schema": SCHEMA,
        "kind": DocKind.REPORT.value,
        "provenance": provenance,
        "counts": {
            "total": len(run_record["items"]),
            "scored": len(per_image),
            "failed": len(failures),
        },
        "caption": {
            "insertion_rate": insertion_rate(caption_scores),
            "must_right_failed_images": sum(1 for s in caption_scores if not s.must_right_pass),
            "must_right_defined_images": rubric_images,  # 0 => hard gate vacuous (S1-02)
            "policy_violations": sum(1 for s in caption_scores if s.policy_violation),
            "mean_gated_score": (
                round(
                    sum(s.gated_score for s in caption_scores if s.gated_score is not None)
                    / len([s for s in caption_scores if s.gated_score is not None]),
                    4,
                )
                if any(s.gated_score is not None for s in caption_scores)
                else None
            ),
        },
        "faces": {
            "detection": {
                **_pr_dict(det.precision, det.recall),
                "tp": det.true_positives,
                "fp": det.false_positives,
                "fn": det.false_negatives,
            },
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
    if cap["must_right_defined_images"] == 0:
        lines.append("- ⚠ no Must-Right/Easy-Wrong rubric entries in the corpus — the caption hard gate is vacuous.")
    lines += [
        "",
        "## Caption metrics (deterministic tier)",
        "",
        f"- insertion rate: {_fmt(cap['insertion_rate'])}",
        f"- Must-Right failed images (hard gate): {cap['must_right_failed_images']} "
        f"(rubric-defined images: {cap['must_right_defined_images']})",
        f"- policy violations: {cap['policy_violations']}",
        f"- mean gated score: {_fmt(cap['mean_gated_score'])}",
        "",
        "## Face detection (identity-agnostic)",
        "",
        f"- precision: {_fmt(det['precision'])} recall: {_fmt(det['recall'])} "
        f"(tp={det['tp']} fp={det['fp']} fn={det['fn']})",
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
HEADLINE_ID_RECALL_ELIGIBLE_FLOOR = 100
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
    }


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


def _entries_as_dicts(manifest: Any) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    """Normalize GoldenManifest | mapping | entry-list into plain dicts."""
    if hasattr(manifest, "entries") and hasattr(manifest, "roster"):
        entries = [e.model_dump() if hasattr(e, "model_dump") else dict(e) for e in manifest.entries]
        roster_cohorts = dict(getattr(manifest, "roster_cohorts", {}) or {})
        roster = list(getattr(manifest, "roster", []) or [])
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
    entry_by_id = _entry_index(entries)
    gt_by_media = _gt_by_media(entries)
    total_boxes = _total_gt_boxes(entries)
    zero_box_corpus = total_boxes == 0

    items = list(face_run_record.get("items") or [])
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
    )
    unknown = face_unknown_rejection(assignment.decisions)

    # Headline = celebs01 named probes only (provenance.source == CELEB).
    celebs01_ids = {mid for mid, e in entry_by_id.items() if _is_celebs01(e)}
    headline_decisions = [
        d
        for d in assignment.decisions
        if d.media_id in celebs01_ids and d.true_name is not None
    ]
    headline_id = face_identification_pr(
        headline_decisions,
        missed_gt=assignment.missed_gt,
        unmatched_detections=assignment.false_detections,
    )
    headline_floor_met = (
        not zero_box_corpus and headline_id.n_recall_eligible >= HEADLINE_ID_RECALL_ELIGIBLE_FLOOR
    )
    headline_status = _slice_status(
        meets_floor=headline_floor_met,
        reasons=(
            ["zero_box_corpus"]
            if zero_box_corpus
            else [f"n_recall_eligible={headline_id.n_recall_eligible}<{HEADLINE_ID_RECALL_ELIGIBLE_FLOOR}"]
        ),
    )

    unknown_floor_met = not zero_box_corpus and unknown.meets_floor
    unknown_status = _slice_status(
        meets_floor=unknown_floor_met,
        reasons=(
            ["zero_box_corpus"]
            if zero_box_corpus
            else [f"n={unknown.n}<{UNKNOWN_REJECTION_N_FLOOR}"]
        ),
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

    # Demographic Fair-SA (always DIRECTIONAL — no floor).
    single_subject = _build_single_subject_cohort_by_media(entries)
    demo = demographic_rollup(
        assignment.decisions,
        roster_cohorts,
        single_subject_cohort_by_media=single_subject,
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
                walk_stability_asserted=walk_asserted,
                walk_stability_delta=walk_delta,
            )
        else:
            synth_acc = score_occlusion_accuracy(
                [],
                assignment.matched,
                tau=assignment.tau_op,
                walk_stability_asserted=False,
                walk_stability_delta=None,
            )

        if real_inputs:
            real_acc = score_occlusion_accuracy(
                real_inputs,
                assignment.matched,
                tau=assignment.tau_op,
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
        synth_directional = bool(synth_acc.directional) or zero_box_corpus or divergence["auto_demote"]
        synth_reasons = list(synth_acc.directional_reasons)
        if zero_box_corpus:
            synth_reasons.append("zero_box_corpus")
        if divergence["auto_demote"]:
            synth_reasons.append(
                f"synthetic_real_divergence d={divergence['d']}>threshold={divergence['threshold']}"
            )
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
                **status,
            },
            "real": (
                {
                    "accuracy": real_acc.accuracy,
                    "n_eligible": real_acc.n_eligible,
                    "n_correct": real_acc.n_correct,
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
            **headline_status,
        },
        "unknown_rejection": {
            "rate": unknown.rate,
            "correct_rejects": unknown.correct_rejects,
            "false_accepts": unknown.false_accepts,
            "n": unknown.n,
            "n_floor": UNKNOWN_REJECTION_N_FLOOR,
            **unknown_status,
        },
        "clustering": cluster_block,
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
        "operator_authority": "FIR-6 human operator records gate/deferral; FIR-5 cannot self-promote",
        "proposed_slices": proposed,
        "excluded_directional": sorted(excluded),
        "identification_detection_coupling": {
            "identification_recall": headline_id.recall,
            "detection_recall": detection["recall"],
            "detection_recall_coupling_flag": headline_id.detection_recall_coupling_flag,
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

    redacted["redaction"] = {
        "audience": "public",
        "mode": "post_score_redact_face_report_for_public",
        "grounded_on": "manifest.Provenance.is_publishable (stamped per decision at score time)",
        "stripped_decision_rows": stripped,
        "note": (
            "Aggregate rates (incl. unknown-rejection) preserved from full-corpus "
            "score; every non-publishable per-face detail row + identity list "
            "(clustering labels, wrong_names, failures) stripped. Fail-closed on "
            "missing provenance. Distinct from pre-score _filter_for_public_audience "
            "/ Audience.PUBLIC."
        ),
    }
    # Do NOT drop unknown_rejection aggregates — they must stay.
    return _sort_nested_lists(redacted)


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
    for name in ("headline_identification", "unknown_rejection", "clustering"):
        block = slices.get(name) or {}
        lines.append(
            f"- **{name}**: status=`{block.get('status', block.get('label', '?'))}` "
            f"directional={block.get('directional')}"
        )
    lines += ["", "## Gate proposal (excludes DIRECTIONAL)", ""]
    lines.append(f"- role: {gp.get('role')}")
    lines.append(f"- proposed_slices: {sorted((gp.get('proposed_slices') or {}).keys())}")
    lines.append(f"- excluded_directional: {gp.get('excluded_directional')}")
    couple = gp.get("identification_detection_coupling") or {}
    lines.append(
        f"- id-recall: {_fmt(couple.get('identification_recall'))} "
        f"alongside detection-recall: {_fmt(couple.get('detection_recall'))} "
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
