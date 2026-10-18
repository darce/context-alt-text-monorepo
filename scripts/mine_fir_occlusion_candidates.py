#!/usr/bin/env python3
"""Build a review shortlist from saved captions; never writes ground-truth labels.

Run from the repository root. Media-ID joins are provisional until image hashes
and coordinate transforms are verified. Keyword negatives are not clean faces.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


PATTERNS = {
    "sunglasses": r"\b(sunglasses|shades|dark glasses|tinted glasses|aviators?)\b",
    "masked": r"\b(mask(?:s|ed)?|respirator|n95|ffp2|face covering|bandana|scarf|veil)\b",
    "occlusion_other": r"\b(occlud\w*|obscur\w*|cover\w*|hidden|hiding|conceal\w*|balaclava|helmet|sleep mask|eye mask|face paint)\b",
    "head_context": r"\b(back of (?:the |their |her |his )?head|from behind|looking away|turned away|back to (?:the )?camera|profile)\b",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json_object(path: Path, key: str) -> dict:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f"Input not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Input is not valid JSON: {path} ({exc})")
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise SystemExit(f"Input {path} must be a JSON object with a '{key}' list")
    return payload


def unique_by_id(rows: list[dict]) -> dict[int, dict]:
    result = {int(row["media_id"]): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate media IDs: resolve before mining")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/manifests/corpus-manifest-v3r-20260814.json"))
    parser.add_argument("--run", type=Path, default=Path("docs/tasks/altq/bakeoff-results/run-altq-646-interleave-v3.json"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/reports/fir-occlusion-caption-mining-20260904.json"))
    args = parser.parse_args()
    manifest = load_json_object(args.manifest, "entries")
    run = load_json_object(args.run, "items")
    entries = unique_by_id(manifest["entries"])
    items = unique_by_id(run["items"])
    if set(entries) != set(items):
        raise ValueError("Run and manifest media-ID sets differ: adjudicate the join")
    match_sets = {key: set() for key in PATTERNS}
    queue, failed, uncaptioned, successful = [], [], [], []
    for mid, entry in sorted(entries.items()):
        item = items[mid]
        description = item.get("describe") or {}
        text = " ".join(str(description.get(key) or "") for key in ("alt_text_title", "alt_text_draft", "alt_text_long"))
        if item.get("error"):
            failed.append(mid)
        if not text.strip():
            uncaptioned.append(mid)
        usable = bool(text.strip()) and not item.get("error")
        if usable:
            successful.append(mid)
        hits = {key: sorted(set(m.group(0).lower() for m in re.finditer(pattern, text, re.I))) for key, pattern in PATTERNS.items()} if usable else {}
        hits = {key: values for key, values in hits.items() if values}
        for key in hits:
            match_sets[key].add(mid)
        if hits:
            queue.append({
                "media_id": mid, "manifest_path": entry["path"], "run_path": item.get("path"),
                "bucket": entry["bucket"], "source_image_sha256": entry.get("sha256_source"),
                "downscaled_image_sha256": entry.get("sha256"),
                "review_status": "unreviewed_caption_candidate", "join_status": "media_id_only_image_hash_unverified",
                "slice_tags_known": entry["slice_tags_known"], "existing_image_tags": entry["slice_tags"],
                "detected_face_count": entry.get("detected_face_count"),
                "matched_terms": hits, "caption": description.get("alt_text_long"),
                "model_id": description.get("model_id"), "model_version": description.get("model_version"),
                "face_id": None, "verified_occluder": None, "verified_hidden_regions": None,
            })
    personal = {mid for mid, e in entries.items() if e["bucket"] == "personal"}
    known = {mid for mid, e in entries.items() if e["slice_tags_known"]}
    stats = {}
    for key, mids in match_sets.items():
        tagged = {mid for mid, e in entries.items() if key in e["slice_tags"]}
        stats[key] = {
            "all_candidates": len(mids), "personal_candidates": len(mids & personal),
            "personal_previously_untriaged": len((mids & personal) - known),
            "hits_in_hand_tagged_images": len(mids & known), "existing_positive_image_tags": len(tagged),
            "existing_positive_tags_retrieved": len(mids & tagged),
            "existing_positive_tags_missed_media_ids": sorted(tagged - mids),
            "personal_previously_untriaged_media_ids": sorted((mids & personal) - known),
        }
    hit_ids = set().union(*match_sets.values())
    result = {
        "schema": "fir.caption-occlusion-shortlist.v1", "status": "candidate_mining_only_not_ground_truth",
        "inputs": {"manifest": str(args.manifest), "manifest_sha256": digest(args.manifest),
                   "run": str(args.run), "run_sha256": digest(args.run), "script_sha256": digest(Path(__file__)),
                   "run_provenance": run.get("provenance")},
        "join": {"media_id_overlap": len(entries), "pixel_identity_verified": False,
                 "manifest_images_root_exists": Path(manifest["images_root"]).exists()},
        "counts": {"images": len(entries), "successful_descriptions": len(successful), "failed_run_items": len(failed),
                   "personal_images": len(personal), "hand_tagged_images": len(known),
                   "image_tag_counts": dict(Counter(t for e in entries.values() for t in e["slice_tags"])),
                   "candidate_images_union": len(hit_ids)},
        "patterns": PATTERNS, "per_class": stats, "failed_run_media_ids": failed,
        "uncaptioned_media_ids": uncaptioned,
        "personal_keyword_negative_audit_frame": sorted(personal & set(successful) - hit_ids),
        "cautions": ["Counts are image-level retrieval, not face-level precision or recall.",
                     "Sample keyword negatives and failed captions independently; never infer clean from silence.",
                     "Existing image tags can name the wrong wearer or hidden region.",
                     "The saved run's provenance manifest digest is not a verified match to this manifest.",
                     "Seal grouped train/calibration/test allocation before selecting or labeling a claim corpus."],
        "candidates": queue,
    }
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise SystemExit(f"Could not write output {args.output}: {exc}")
    print(json.dumps({"output": str(args.output), "counts": result["counts"], "per_class": stats}, indent=2))


if __name__ == "__main__":
    main()
