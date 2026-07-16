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

import json
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
from .face_metrics import ImageDetection, ImageIdentities, detection_pr, identification_pr
from .manifest import Provenance
from .schema import SCHEMA, DocKind

EVAL_MODES = ("standard", "context_distractor", "name_ablation")


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


def score_run_record(
    run_record: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
    ignore_list: dict[str, Any] | None = None,
    *,
    score_manifest_sha256: str | None = None,
    manifest_roster: list[str] | None = None,
) -> dict[str, Any]:
    """Pure scoring: run record + manifest labels -> metrics dict."""
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
        scores = score_caption(caption, **score_kwargs)
        caption_scores.append(scores)
        gated = _ablation_gate(scores) if eval_mode == "name_ablation" else scores.gated_score
        if gated is not None:
            gated_values.append(gated)

        long_text = describe.get("alt_text_long")
        long_s = score_caption(str(long_text), **score_kwargs) if isinstance(long_text, str) and long_text else None
        if long_s is not None:
            long_scores.append(long_s)

        taken: bool | None = None
        if isinstance(injected, str) and injected:
            distractor_injected += 1
            taken = injected in scores.wrong_name_hits or (long_s is not None and injected in long_s.wrong_name_hits)
            distractor_taken += int(taken)
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
        row: dict[str, Any] = {
            "path": path,
            "media_id": media_id,
            "gated_score": gated,
            "must_right_failures": scores.must_right_failures,
            "policy_violation": scores.policy_violation,
            "wrong_name_hits": scores.wrong_name_hits,
            "hallucinated_names": scores.hallucinated_names,
            "inserted_identities": scores.inserted_identities,
            "missing_identities": scores.missing_identities,
            "fkre": round(scores.fkre, 2),
            "repetition_ratio": round(scores.repetition_ratio, 4),
            "tag_coverage": scores.tag_coverage,
            "first_sentence_gist_ok": scores.first_sentence_gist_ok,
            "meta_framing_hits": scores.meta_framing_hits,
            "context_duplication_ratio": (
                None if scores.context_duplication_ratio is None else round(scores.context_duplication_ratio, 4)
            ),
            "sentence_count": scores.sentence_count,
            "name_front_loaded": scores.name_front_loaded,
            "cache_hit": bool(describe.get("cached", False)),  # contract field is 'cached' (HARM-02)
        }
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
    if cap["must_right_defined_images"] == 0:
        lines.append("- ⚠ no Must-Right/Easy-Wrong rubric entries in the corpus — the caption hard gate is vacuous.")
    eval_mode = scored.get("eval_mode", "standard")
    if eval_mode != "standard":
        lines.append(
            f"- ⚠ eval_mode: **{eval_mode}** — context was transformed at fetch time; "
            "metrics are mode-specific, NOT comparable to standard runs."
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
    manifest_roster: list[str] | None = None,
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
    )
    if redaction is not None:
        scored["redaction"] = redaction
    return json.dumps(scored, indent=2, sort_keys=True, ensure_ascii=False) + "\n", _markdown(scored)
