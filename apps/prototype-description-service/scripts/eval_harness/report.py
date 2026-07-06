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
from typing import Any

from .caption_metrics import CaptionScores, insertion_rate, score_caption
from .face_metrics import ImageDetection, ImageIdentities, detection_pr, identification_pr

SCHEMA = "acx-eval/v1"


def _entry_index(manifest_entries: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(e["media_id"]): e for e in manifest_entries}


def _pr_dict(precision: float | None, recall: float | None) -> dict[str, float | None]:
    return {"precision": precision, "recall": recall}


def score_run_record(
    run_record: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
    ignore_list: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure scoring: run record + manifest labels -> metrics dict."""
    entries = _entry_index(manifest_entries)
    caption_scores: list[CaptionScores] = []
    per_image: list[dict[str, Any]] = []
    detections: list[ImageDetection] = []
    identifications: list[ImageIdentities] = []
    failures: list[dict[str, Any]] = []

    for item in run_record["items"]:
        entry = entries[int(item["media_id"])]
        path = str(entry["path"])
        if item.get("error"):
            failures.append({"path": path, "media_id": int(item["media_id"]), "error": str(item["error"])})
            continue
        recognition_enabled = bool(entry.get("policy", {}).get("recognition_enabled", True))
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
        labeled_faces = len(entry["present_identities"])
        detections.append(
            ImageDetection(
                image=path,
                pred_faces=int(item.get("face_count", 0)),
                labeled_faces=labeled_faces,
            )
        )
        identifications.append(
            ImageIdentities(
                image=path,
                predicted=list(item.get("identities", [])),
                labeled=list(entry["present_identities"]),
                recognition_enabled=recognition_enabled,
            )
        )
        per_image.append(
            {
                "path": path,
                "media_id": int(item["media_id"]),
                "gated_score": scores.gated_score,
                "must_right_failures": scores.must_right_failures,
                "policy_violation": scores.policy_violation,
                "inserted_identities": scores.inserted_identities,
                "missing_identities": scores.missing_identities,
                "fkre": round(scores.fkre, 2),
                "repetition_ratio": round(scores.repetition_ratio, 4),
                "tag_coverage": scores.tag_coverage,
                "first_sentence_gist_ok": scores.first_sentence_gist_ok,
                "cache_hit": bool(describe.get("cache_hit", False)),
            }
        )

    det = detection_pr(detections)
    ident = identification_pr(identifications)

    ignored_pairs = {tuple(p) for p in (ignore_list or {}).get("wrong_names", [])}
    live_wrong = [list(p) for p in ident.wrong_names if tuple(p) not in ignored_pairs]
    ignored_wrong = [list(p) for p in ident.wrong_names if tuple(p) in ignored_pairs]

    return {
        "schema": SCHEMA,
        "provenance": run_record["provenance"],
        "counts": {
            "total": len(run_record["items"]),
            "scored": len(per_image),
            "failed": len(failures),
        },
        "caption": {
            "insertion_rate": insertion_rate(caption_scores),
            "must_right_failed_images": sum(1 for s in caption_scores if not s.must_right_pass),
            "policy_violations": sum(1 for s in caption_scores if s.policy_violation),
            "mean_gated_score": (
                round(sum(s.gated_score for s in caption_scores) / len(caption_scores), 4) if caption_scores else None
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
    cap = scored["caption"]
    det = scored["faces"]["detection"]
    ident = scored["faces"]["identification"]
    lines = [
        "# Caption + Face Eval Report",
        "",
        f"- schema: `{scored['schema']}`",
        f"- head_sha: `{prov.get('head_sha', 'unknown')}`",
        f"- base_url: {prov.get('base_url', 'unknown')}",
        f"- manifest_sha256: `{prov.get('manifest_sha256', 'unknown')}`",
        f"- started_at: {prov.get('started_at', 'unknown')}",
        f"- images: {scored['counts']['scored']}/{scored['counts']['total']} scored, "
        f"{scored['counts']['failed']} failed",
        "",
        "## Caption metrics (deterministic tier)",
        "",
        f"- insertion rate: {_fmt(cap['insertion_rate'])}",
        f"- Must-Right failed images (hard gate): {cap['must_right_failed_images']}",
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
) -> tuple[str, str]:
    """Return (json_report, markdown_report) — deterministic for identical inputs."""
    scored = score_run_record(run_record, manifest_entries, ignore_list=ignore_list)
    return json.dumps(scored, indent=2, sort_keys=True, ensure_ascii=False) + "\n", _markdown(scored)
