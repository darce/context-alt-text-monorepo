#!/usr/bin/env python3
"""Build the v3 eval corpus manifest from the pseudonym-labelled image tree.

The image tree is the single authority for what exists, what it hashes to, and who
the primary subject is. Everything else (curated identity boxes, detector geometry,
captions, slice tags) is enrichment joined onto that spine by path, and is recorded
with the source it came from so the two never blur together again.

Replaces build_manifest.py, whose inputs (the fir-5 .task-state curation files) no
longer exist and whose output disagreed with corpus646 on sha space, face_count
semantics, box source, and provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_VERSION = 3

# The sha256 spine is the DOWNSCALED eval cache, not benchmarks/images/corpus646/originals.
# Its old home (the deleted vlm-6 worktree) is gone and there is deliberately no default:
# pointing this at the originals would silently rebase `sha256_space` (CARD-07).
_DOWNSCALED = os.environ.get("ACX_CORPUS_DOWNSCALED_ROOT")
IMAGES_ROOT = Path(_DOWNSCALED) if _DOWNSCALED else None
MANIFEST_DIR = Path(__file__).resolve().parents[1] / "manifests"
CORPUS646 = MANIFEST_DIR / "corpus646-interleave-manifest-20260716.json"
GOLDEN150 = MANIFEST_DIR / "golden150-draft-20260723.json"
DETECTIONS = MANIFEST_DIR / "detections-yunet-t030.json"

# Derived slice tags, and ONLY those that earned it against the 150 hand-tagged images
# (see calibrate_slice_tags.py). `profile` clears the AUC floor at 0.782 via eye-line
# foreshortening; every other tag scores 0.59-0.68, i.e. chance. Notably the occlusion
# trio cannot be recovered even with full detector coverage — consistent with strata.py
# classing occlusion as an operator domain, and with FIR-5 choosing to *generate*
# occlusion synthetically rather than hunt for it.
#
# 0.67 precision means this SHORTLISTS, it does not label. Derived tags are kept in a
# separate field from the operator's so a benchmark can never silently treat a guess as
# ground truth.
DERIVED_TAG_RULES = {
    "profile": {
        "signal": "eye_span_ratio",
        "max": 0.75,
        "auc": 0.782,
        "precision": 0.67,
        "recall": 0.61,
        "calibrated_on": "150 hand-tagged images",
    },
}
OUT = MANIFEST_DIR / "corpus-manifest-v3.json"

BUCKETS = ("personal", "celebs")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}

# Per-bucket provenance. Personal imagery is operator-collected under signed consent
# held off-repo; celebrity imagery is third-party editorial material used as fixtures
# and is NOT consented — the two must never share a licence token.
PROVENANCE = {
    "personal": {
        "source": "localwp",
        "license": "consented",
        "consent": "on_file",
        "consent_register": "operator-held, off-repo",
        "subject_naming": "pseudonym",
    },
    "celebs": {
        "source": "public_figure",
        "license": "editorial_fixture",
        "consent": "not_applicable",
        "consent_register": None,
        "subject_naming": "real_name",
    },
}

SLICE_TAGS = ("masked", "sunglasses", "occlusion_other", "profile", "low_res", "blur")


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def parse_filename(stem: str) -> tuple[str, int | None]:
    """`maggie_hunter_551` -> ('maggie_hunter', 551). Trailing digits are the media id."""
    m = re.match(r"^(?P<slug>.+?)_(?P<mid>\d+)$", stem)
    if not m:
        return norm(stem), None
    return norm(m.group("slug")), int(m.group("mid"))


def read_dimensions(paths: list[Path]) -> dict[Path, tuple[int, int] | None]:
    """Read dimensions with optional Pillow (install Pillow and needed codecs)."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Building requires Pillow; install Pillow with the needed image codecs") from exc
    out = {}
    for path in paths:
        with Image.open(path) as image:
            out[path] = image.size
    return out


def display_name(slug: str, roster: dict[str, str]) -> str:
    if slug in roster:
        return roster[slug]
    return " ".join(part.capitalize() for part in slug.split("_"))


def derived_tags(faces: list[dict]) -> list[str]:
    """Shortlist tags from detector geometry on the largest face.

    Largest face only: an image-level pose tag describes the subject, not a bystander
    who happens to be turned away in the background.
    """
    if not faces:
        return []
    primary = faces[0]
    tags = []
    for tag, rule in DERIVED_TAG_RULES.items():
        value = primary.get(rule["signal"])
        if value is not None and value <= rule["max"]:
            tags.append(tag)
    return tags


def build(*, corpus_path: Path = CORPUS646, golden_path: Path = GOLDEN150,
          detections_path: Path = DETECTIONS, images_root: Path | None = IMAGES_ROOT) -> dict:
    corpus = json.loads(corpus_path.read_text())
    golden = json.loads(golden_path.read_text())
    detection = json.loads(detections_path.read_text())

    # Exact spelling of every identity name anyone has already committed to.
    roster: dict[str, str] = {}
    for name in corpus.get("roster", []) + golden.get("roster", []):
        roster.setdefault(norm(name), name)
    for entry in corpus["entries"]:
        for name in entry.get("present_identities") or []:
            roster.setdefault(norm(name), name)

    # Join on media_id, not path. The operator re-labels filenames in place, so a path
    # join silently loses every enrichment row the moment a subject is renamed.
    curated = {e["media_id"]: e for e in corpus["entries"]}
    drafted = {e["media_id"]: e for e in golden["entries"]}
    detected = {e["media_id"]: e for e in detection["entries"]}

    if images_root is None or not all((images_root / b).is_dir() for b in BUCKETS):
        raise ValueError(
            f"downscaled image cache not found (ACX_CORPUS_DOWNSCALED_ROOT={images_root}); "
            f"it must contain {'/'.join(BUCKETS)} subdirs. Regenerate it with the eval "
            "harness downscale step, or use --verify-only against an existing manifest."
        )
    files: list[tuple[str, Path]] = []
    for bucket in BUCKETS:
        for path in sorted((images_root / bucket).iterdir()):
            if path.name.startswith(".") or path.suffix.lower() not in IMAGE_EXTS:
                continue
            files.append((f"{bucket}/{path.name}", path))

    dims = read_dimensions([p for _, p in files])

    by_sha: dict[str, list[str]] = defaultdict(list)
    entries: list[dict] = []

    for rel, abspath in files:
        bucket, filename = rel.split("/", 1)
        stem = filename.rsplit(".", 1)[0]
        slug, media_id = parse_filename(stem)
        blob = abspath.read_bytes()
        sha = hashlib.sha256(blob).hexdigest()
        by_sha[sha].append(rel)

        cur = curated.get(media_id) or {}
        det = drafted.get(media_id) or {}
        yunet_faces = (detected.get(media_id) or {}).get("faces") or []

        is_unlabeled = slug == "unlabeled"
        primary = None if is_unlabeled else display_name(slug, roster)

        named_boxes = [dict(b) for b in (cur.get("face_boxes") or [])]
        for box in named_boxes:
            box.setdefault("source", "workbench")
        # Detector geometry is now one pass over all 646 with pinned weights and one
        # threshold, replacing the draft's 150-image subset. Uniform provenance is the
        # whole point: the previous manifest mixed two detectors' boxes in one field.
        detected_boxes = [dict(f) for f in yunet_faces]

        named_identities: list[str] = []
        for name in cur.get("present_identities") or []:
            if name not in named_identities:
                named_identities.append(name)
        if primary and primary not in named_identities:
            named_identities.insert(0, primary)

        flags: list[str] = []
        if media_id not in curated:
            flags.append("absent_from_curated_manifest")
        elif cur["path"] != rel:
            flags.append("curated_path_stale")
        if not is_unlabeled and not (cur.get("present_identities") or []):
            flags.append("identity_from_filename_only")
        if is_unlabeled and (cur.get("present_identities") or []):
            flags.append("unlabeled_but_named")
        # The draft's boxes carried detector-assigned names; the YuNet pass is pure
        # geometry, so the name-conflict check still reads the draft.
        det_names = {norm(b["name"]) for b in (det.get("face_boxes") or []) if b.get("name")}
        if primary and det_names and norm(primary) not in det_names:
            flags.append("detector_label_conflicts_with_slug")
        if not named_boxes and not detected_boxes:
            flags.append("no_faces")
        if media_id is None:
            flags.append("no_media_id")

        width, height = dims.get(abspath) or (None, None)

        entries.append(
            {
                "media_id": media_id,
                "path": rel,
                "bucket": bucket,
                "slug": slug,
                "sha256": sha,
                "sha256_source": cur.get("sha256"),
                "bytes": len(blob),
                "width": width,
                "height": height,
                "primary_identity": primary,
                "named_identities": named_identities,
                "named_boxes": named_boxes,
                "detected_boxes": detected_boxes,
                "named_face_count": len(named_boxes),
                "detected_face_count": len(detected_boxes) if media_id in detected else None,
                "caption": {
                    "base": det.get("base_caption") or "",
                    "context_pack": det.get("context_pack") or {},
                    "source": "vlm-cpu-fullrun" if media_id in drafted else None,
                },
                "slice_tags": [t for t in (det.get("tags") or []) if t in SLICE_TAGS],
                "slice_tags_known": media_id in drafted,
                "slice_tags_derived": derived_tags(yunet_faces),
                "slice_tags_source": "operator_hand" if media_id in drafted else None,
                "policy": cur.get("policy") or {"recognition_enabled": True},
                "provenance": dict(PROVENANCE[bucket]),
                "flags": flags,
            }
        )

    duplicate_groups = [sorted(v) for v in by_sha.values() if len(v) > 1]
    dup_paths = {p for grp in duplicate_groups for p in grp}
    for entry in entries:
        if entry["path"] in dup_paths:
            group = next(g for g in duplicate_groups if entry["path"] in g)
            entry["flags"].append("duplicate_content")
            entry["duplicate_of"] = [p for p in group if p != entry["path"]]

    identities: dict[str, dict] = {}
    for entry in entries:
        if entry["primary_identity"]:
            rec = identities.setdefault(
                entry["slug"],
                {
                    "slug": entry["slug"],
                    "name": entry["primary_identity"],
                    "bucket": entry["bucket"],
                    "naming": PROVENANCE[entry["bucket"]]["subject_naming"],
                    "primary_of": [],
                    "appears_in": [],
                },
            )
            rec["primary_of"].append(entry["path"])
        for name in entry["named_identities"]:
            slug = norm(name)
            rec = identities.setdefault(
                slug,
                {
                    "slug": slug,
                    "name": name,
                    "bucket": entry["bucket"],
                    "naming": PROVENANCE[entry["bucket"]]["subject_naming"],
                    "primary_of": [],
                    "appears_in": [],
                },
            )
            rec["appears_in"].append(entry["path"])
    for rec in identities.values():
        rec["primary_count"] = len(rec["primary_of"])
        rec["appearance_count"] = len(rec["appears_in"])
        if rec["primary_count"] == 0:
            rec["secondary_only"] = True

    on_disk = {e["media_id"] for e in entries}
    dropped = [
        {
            "path": e["path"],
            "media_id": e["media_id"],
            "present_identities": e.get("present_identities"),
            "reason": "file absent from image tree after operator re-label",
        }
        for e in corpus["entries"]
        if e["media_id"] not in on_disk
    ]

    sha_rebased = sum(
        1 for e in entries if e["sha256_source"] and e["sha256_source"] != e["sha256"]
    )

    return {
        "manifest_version": MANIFEST_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "images_root": str(images_root),
        "sha256_space": "downscaled",
        "sha256_source_space": "original",
        "naming_convention": "<subject_slug>_<media_id>.<ext>; unlabeled_<media_id> when no subject is assigned",
        "sources": {
            "spine": "image tree (existence, sha256, dimensions, primary identity)",
            "named_boxes": f"{corpus_path.name} (operator workbench clusters)",
            "detected_boxes": f"{detections_path.name} (YuNet geometry + landmarks, all 646)",
            "captions": f"{golden_path.name} (150-entry subset)",
            "slice_tags": f"{golden_path.name} (operator hand tags, 150-entry subset)",
            "slice_tags_derived": f"{detections_path.name} via calibrated rules (shortlist, all 646)",
        },
        "detector": detection["detector"],
        "derived_tag_rules": DERIVED_TAG_RULES,
        "derived_tag_caveat": (
            "slice_tags_derived is a SHORTLIST at ~0.67 precision, not ground truth. Only"
            " `profile` cleared calibration against the 150 hand-tagged images; blur, low_res,"
            " masked, sunglasses and occlusion_other scored at chance and remain hand-only."
            " Never merge derived tags into slice_tags."
        ),
        "consent": {
            "personal": "signed consent on file with the operator, held off-repo; subjects are"
            " named by pseudonym throughout",
            "celebs": "third-party editorial fixtures; not consented, not consent-equivalent",
        },
        "counts": {
            "entries": len(entries),
            "personal": sum(1 for e in entries if e["bucket"] == "personal"),
            "celebs": sum(1 for e in entries if e["bucket"] == "celebs"),
            "unlabeled": sum(1 for e in entries if e["primary_identity"] is None),
            "identities": len(identities),
            "identities_secondary_only": sum(
                1 for r in identities.values() if r.get("secondary_only")
            ),
            "with_captions": sum(1 for e in entries if e["caption"]["base"]),
            "with_slice_tags_known": sum(1 for e in entries if e["slice_tags_known"]),
            "with_detected_faces": sum(1 for e in entries if e["detected_boxes"]),
            "detected_faces_total": sum(len(e["detected_boxes"]) for e in entries),
            "with_derived_tags": sum(1 for e in entries if e["slice_tags_derived"]),
            "derived_tags": dict(
                Counter(t for e in entries for t in e["slice_tags_derived"]).most_common()
            ),
            "sha256_rebased_from_original": sha_rebased,
            "duplicate_content_groups": len(duplicate_groups),
            "dropped_from_source": len(dropped),
            "flags": dict(Counter(f for e in entries for f in e["flags"]).most_common()),
        },
        "duplicate_groups": duplicate_groups,
        "dropped_from_source": dropped,
        "identities": sorted(identities.values(), key=lambda r: r["slug"]),
        "entries": sorted(entries, key=lambda e: (e["bucket"], e["media_id"] or 0)),
    }


def verify(manifest: dict, *, images_root: Path | None = None) -> list[str]:
    """Invariants that must hold for the manifest to be usable as an eval anchor."""
    problems: list[str] = []
    root = images_root if images_root is not None else Path(manifest["images_root"])
    entries = manifest["entries"]

    # A derived tag is a ~0.67-precision guess. If it ever leaks into slice_tags the
    # benchmark would report guessed strata as operator ground truth.
    leaked = [
        e["path"] for e in entries
        if not e["slice_tags_known"] and e["slice_tags"]
    ]
    if leaked:
        problems.append(f"{len(leaked)} entries carry slice_tags without operator labels: {leaked[:5]}")
    only_calibrated = set(manifest["derived_tag_rules"])
    stray = {t for e in entries for t in e["slice_tags_derived"]} - only_calibrated
    if stray:
        problems.append(f"uncalibrated tags present in slice_tags_derived: {sorted(stray)}")

    if len({e["path"] for e in entries}) != len(entries):
        problems.append("duplicate paths in entries")

    missing = [e["path"] for e in entries if not (root / e["path"]).exists()]
    if missing:
        problems.append(f"{len(missing)} entries point at absent files: {missing[:5]}")

    sample = entries[:: max(1, len(entries) // 40)]
    bad_sha = [
        e["path"]
        for e in sample
        if (root / e["path"]).exists()
        and hashlib.sha256((root / e["path"]).read_bytes()).hexdigest() != e["sha256"]
    ]
    if bad_sha:
        problems.append(f"sha256 mismatch on re-read: {bad_sha}")

    mids = [e["media_id"] for e in entries if e["media_id"] is not None]
    if len(set(mids)) != len(mids):
        dupes = [m for m, n in Counter(mids).items() if n > 1]
        problems.append(f"media_id is not unique: {dupes[:10]}")

    for e in entries:
        if e["named_face_count"] != len(e["named_boxes"]):
            problems.append(f"named_face_count desync at {e['path']}")
            break
        if e["detected_face_count"] is not None and e["detected_face_count"] != len(
            e["detected_boxes"]
        ):
            problems.append(f"detected_face_count desync at {e['path']}")
            break

    licences = {e["bucket"]: set() for e in entries}
    for e in entries:
        licences[e["bucket"]].add(e["provenance"]["license"])
    if licences.get("celebs", set()) & {"consented"}:
        problems.append("celebrity fixture carries a consent licence")
    for bucket, seen in licences.items():
        if len(seen) > 1:
            problems.append(f"bucket {bucket} has mixed licences: {seen}")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True,
                    help="New output path, or existing manifest to check with --verify-only")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--corpus", type=Path, default=CORPUS646)
    ap.add_argument("--golden", type=Path, default=GOLDEN150)
    ap.add_argument("--detections", type=Path, default=DETECTIONS)
    ap.add_argument("--images-root", type=Path, default=IMAGES_ROOT,
                    help="Downscaled cache (default: ACX_CORPUS_DOWNSCALED_ROOT)")
    args = ap.parse_args()

    try:
        if not args.verify_only and os.path.lexists(args.out):
            raise FileExistsError(f"Destination exists: {args.out}; choose a new output")
        if args.verify_only:
            manifest = json.loads(args.out.read_text())
        else:
            manifest = build(corpus_path=args.corpus, golden_path=args.golden,
                             detections_path=args.detections, images_root=args.images_root)
        problems = verify(manifest, images_root=args.images_root)
        if problems:
            for problem in problems:
                print(f"FAILED INVARIANT: {problem}", file=sys.stderr)
            return 1
        if not args.verify_only:
            # Serialize before exclusive creation; competing writers cannot clobber evidence.
            payload = json.dumps(manifest, indent=1, ensure_ascii=False, allow_nan=False)
            try:
                with args.out.open("x", encoding="utf-8") as stream:
                    stream.write(payload)
            except FileExistsError:
                raise FileExistsError(f"Destination exists: {args.out}; choose a new output")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    counts = manifest["counts"]
    print(f"{args.out}  ({args.out.stat().st_size:,} bytes)")
    for key, value in counts.items():
        if key != "flags":
            print(f"  {key:32s} {value}")
    print("  flags:")
    for flag, n in counts["flags"].items():
        print(f"    {flag:34s} {n}")
    if problems:
        print("\nFAILED INVARIANTS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nall invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
