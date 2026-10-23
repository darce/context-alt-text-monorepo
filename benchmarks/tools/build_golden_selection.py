#!/usr/bin/env python3
"""Rebuild golden150 as a *selection over* corpus-manifest-v3, not a second manifest.

The old golden150-draft carried its own copy of every field and drifted from the corpus
manifest on sha space, face_count semantics, box source and provenance. A selection
records only which media it picks and why; every attribute is read back through the
corpus manifest, so the two cannot disagree.

Selection is deterministic: ties break on sha256, never on wall-clock or PRNG state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_DIR = Path(__file__).resolve().parents[1] / "manifests"
CORPUS = MANIFEST_DIR / "corpus-manifest-v3.json"

SIZE = 150
LOW_RES_MIN_SIDE = 480  # ~20th percentile of the corpus

QUOTAS = {
    "recognition_core": 100,  # personal, identity has >=2 corpus images -> gallery/probe possible
    "multi_face": 20,  # >=2 named subjects -> tests left-to-right name binding
    "distractor": 20,  # unlabeled / no detectable subject -> measures false-positive naming
    "celeb": 10,  # separate licence track, never mixed into the consented personal metric
}
MAX_PER_IDENTITY = 3  # one 50-image subject would otherwise own a third of the set

# Strata the corpus can support today. The YuNet pass added detector geometry over all
# 646, which made `profile` derivable corpus-wide (AUC 0.782). The occlusion trio stayed
# at chance even with full detector coverage, so it remains known for the hand-tagged
# 150 only and still cannot drive selection over 643.
DERIVABLE_STRATA = ("bucket", "named_face_count", "identity_support", "low_res", "profile")
UNDERIVABLE_STRATA = ("occlusion_other", "sunglasses", "masked", "blur")


def hardness(entry: dict) -> tuple:
    """Prefer known-hard media. Deterministic; sha256 breaks ties.

    Operator hand tags outrank derived ones: a derived `profile` is a ~0.67-precision
    shortlist, so it should break a tie between otherwise-equal media, never outweigh a
    stratum a human actually confirmed.
    """
    hand = set(entry["slice_tags"])
    derived = set(entry["slice_tags_derived"])
    return (
        -len(hand & set(UNDERIVABLE_STRATA)),
        -len(hand & set(DERIVABLE_STRATA)),
        -len(derived),
        -1 if min(entry["width"], entry["height"]) <= LOW_RES_MIN_SIDE else 0,
        entry["sha256"],
    )


def build(corpus: dict, corpus_path: Path = CORPUS, *, corpus_bytes: bytes | None = None) -> dict:
    entries = {e["path"]: e for e in corpus["entries"]}

    excluded: dict[str, list[str]] = defaultdict(list)
    for group in corpus["duplicate_groups"]:
        for path in sorted(group, key=lambda p: entries[p]["media_id"] or 0)[1:]:
            excluded["duplicate_content"].append(path)
    # Identity-ambiguous media cannot be scored either way round: whichever label the
    # metric trusts, the other one makes the result meaningless.
    for entry in corpus["entries"]:
        for flag in ("detector_label_conflicts_with_slug", "unlabeled_but_named"):
            if flag in entry["flags"]:
                excluded[flag].append(entry["path"])

    dropped = {p for paths in excluded.values() for p in paths}
    eligible = [e for e in corpus["entries"] if e["path"] not in dropped]

    corpus_support = Counter(e["slug"] for e in corpus["entries"] if e["primary_identity"])

    pools: dict[str, list[dict]] = {
        "celeb": [e for e in eligible if e["bucket"] == "celebs"],
        "distractor": [
            e for e in eligible if e["bucket"] == "personal" and e["primary_identity"] is None
        ],
        "multi_face": [
            e for e in eligible if e["bucket"] == "personal" and e["named_face_count"] >= 2
        ],
        "recognition_core": [
            e
            for e in eligible
            if e["bucket"] == "personal"
            and e["primary_identity"] is not None
            and e["named_face_count"] < 2
            and corpus_support[e["slug"]] >= 2
        ],
    }

    picked: dict[str, list[dict]] = {}
    taken: set[str] = set()
    per_identity: Counter = Counter()

    # Order matters: the scarcest quotas claim their media before the deep pools do.
    for stratum in ("celeb", "multi_face", "distractor", "recognition_core"):
        quota = QUOTAS[stratum]
        chosen: list[dict] = []
        for entry in sorted(pools[stratum], key=hardness):
            if len(chosen) >= quota or entry["path"] in taken:
                continue
            slug = entry["slug"]
            if slug != "unlabeled":
                # Leave one corpus image per personal identity unselected so it can be
                # enrolled as gallery. Consuming every image makes the identity unscoreable.
                cap = MAX_PER_IDENTITY
                if entry["bucket"] == "personal":
                    cap = min(cap, corpus_support[slug] - 1)
                if per_identity[slug] >= cap:
                    continue
            chosen.append(entry)
            taken.add(entry["path"])
            if slug != "unlabeled":
                per_identity[slug] += 1
        picked[stratum] = chosen

    selected = [e for stratum in QUOTAS for e in picked[stratum]]

    # Gallery lives outside the probe set: an identity enrolled from an image it is then
    # scored on measures nothing. Only identities with a spare corpus image are enrollable.
    gallery: dict[str, str] = {}
    probe_only: list[str] = []
    for slug in sorted({e["slug"] for e in selected if e["primary_identity"]}):
        spare = sorted(
            (
                e
                for e in corpus["entries"]
                if e["slug"] == slug and e["path"] not in taken and e["path"] not in dropped
            ),
            key=lambda e: (-min(e["width"], e["height"]), e["sha256"]),
        )
        if spare:
            gallery[slug] = spare[0]["path"]
        else:
            probe_only.append(slug)
    # Celebrity identities are mostly single-image; their gallery is external by design.
    celeb_probe_only = [
        s for s in probe_only
        if any(e["slug"] == s and e["bucket"] == "celebs" for e in selected)
    ]

    realized = {
        "by_stratum": {k: len(v) for k, v in picked.items()},
        "by_bucket": dict(Counter(e["bucket"] for e in selected)),
        "named_face_count": dict(sorted(Counter(e["named_face_count"] for e in selected).items())),
        "low_res": sum(1 for e in selected if min(e["width"], e["height"]) <= LOW_RES_MIN_SIDE),
        "identities": len({e["slug"] for e in selected if e["primary_identity"]}),
        "identities_enrollable": len(gallery),
        "named_probes": sum(len(e["named_identities"]) for e in selected),
        "slice_tags_known": sum(1 for e in selected if e["slice_tags_known"]),
        "slice_tags": dict(Counter(t for e in selected for t in e["slice_tags"])),
        "slice_tags_derived": dict(Counter(t for e in selected for t in e["slice_tags_derived"])),
        "detected_faces_total": sum(e["detected_face_count"] or 0 for e in selected),
        "with_detected_faces": sum(1 for e in selected if e["detected_boxes"]),
    }

    return {
        "selection_version": 1,
        "name": "golden150",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_manifest": corpus_path.name,
        "corpus_manifest_sha256": hashlib.sha256(corpus_path.read_bytes() if corpus_bytes is None else corpus_bytes).hexdigest(),
        "size": len(selected),
        "sampling_frame": {
            "corpus_entries": len(corpus["entries"]),
            "eligible": len(eligible),
            "excluded": {k: sorted(v) for k, v in excluded.items()},
            "quotas": QUOTAS,
            "max_per_identity": MAX_PER_IDENTITY,
            "low_res_min_side": LOW_RES_MIN_SIDE,
            "tie_break": "sha256",
            "ordering": "hardness: known hard tags desc, low-res first, sha256",
        },
        "strata_derivable": list(DERIVABLE_STRATA),
        "coverage_gaps": [
            f"Occlusion strata ({', '.join(UNDERIVABLE_STRATA)}) are known for only"
            f" {sum(1 for e in corpus['entries'] if e['slice_tags_known'])} of"
            f" {len(corpus['entries'])} corpus images, all hand-tagged. A full-corpus detector"
            " pass did NOT close this: calibrated against those 150 labels, every occlusion"
            " signal scored at chance (AUC 0.59-0.68), so no threshold can extend them."
            " Natural-occlusion coverage needs either operator tagging or synthetic"
            " generation (synthetic_occlusion.py), not more detection.",
            "`profile` IS derived corpus-wide (AUC 0.782) but at ~0.67 precision it is a"
            " shortlist: roughly a third of derived profile media are not profile. Selection"
            " uses it for ordering only, and slice_tags_derived is never merged into"
            " slice_tags. The operator should confirm pose on the 150 selected images.",
            "Identity labels descend from operator cluster merges, so they are ground truth"
            " for naming but must not be reused to score the clustering that produced them.",
        ],
        "realized": realized,
        "gallery": gallery,
        "probe_only_identities": probe_only,
        "probe_only_celebs_external_gallery": celeb_probe_only,
        "selection": [
            {
                "stratum": stratum,
                "media_id": e["media_id"],
                "path": e["path"],
                "sha256": e["sha256"],
                "slug": e["slug"],
                "named_identities": e["named_identities"],
                "slice_tags": e["slice_tags"],
                "slice_tags_derived": e["slice_tags_derived"],
                "slice_tags_source": e["slice_tags_source"],
                "detected_face_count": e["detected_face_count"],
            }
            for stratum in QUOTAS
            for e in picked[stratum]
        ],
    }


def verify(sel: dict, corpus: dict, corpus_bytes: bytes) -> list[str]:
    # Rows only point into the corpus, so agreeing IDs and sha256 cannot catch a corpus
    # edited underneath (hand tags, say). The byte pin can. Hash the bytes `corpus` was
    # parsed from, never a second read, and judge nothing else against an unpinned corpus.
    if "corpus_manifest_sha256" not in sel:
        return ["selection has no corpus_manifest_sha256 pin"]
    if sel["corpus_manifest_sha256"] != hashlib.sha256(corpus_bytes).hexdigest():
        return ["corpus bytes do not match the selection's corpus_manifest_sha256 pin"]

    problems: list[str] = []
    entries = {e["path"]: e for e in corpus["entries"]}
    paths = [row["path"] for row in sel["selection"]]

    if len(set(paths)) != len(paths):
        problems.append("selection contains the same media twice")
    if sel["size"] != SIZE:
        problems.append(f"selection size {sel['size']} != {SIZE}")

    for row in sel["selection"]:
        if row["path"] not in entries:
            problems.append(f"selected media not in corpus: {row['path']}")
            break
        if entries[row["path"]]["sha256"] != row["sha256"]:
            problems.append(f"sha256 disagrees with corpus at {row['path']}")
            break

    dropped = {p for v in sel["sampling_frame"]["excluded"].values() for p in v}
    if dropped & set(paths):
        problems.append("an excluded medium was selected anyway")

    overlap = set(sel["gallery"].values()) & set(paths)
    if overlap:
        problems.append(f"gallery image is also a probe: {sorted(overlap)[:5]}")

    over = [s for s, n in Counter(r["slug"] for r in sel["selection"]).items()
            if s != "unlabeled" and n > sel["sampling_frame"]["max_per_identity"]]
    if over:
        problems.append(f"per-identity cap exceeded: {over}")

    unscoreable = [
        s for s in sel["probe_only_identities"]
        if s not in sel["probe_only_celebs_external_gallery"]
    ]
    if unscoreable:
        problems.append(
            f"{len(unscoreable)} personal identities have no gallery image left: {unscoreable[:5]}"
        )

    if any(entries[p]["bucket"] == "celebs" for p in paths
           if entries[p]["provenance"]["license"] == "consented"):
        problems.append("a celebrity fixture is carrying a consent licence")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--out", type=Path, required=True,
                    help="new output path, or selection to read with --verify-only")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    try:
        # lexists semantics include dangling symlinks; exclusive creation below
        # also closes the race with other writers creating this destination.
        if not args.verify_only and (args.out.exists() or args.out.is_symlink()):
            raise FileExistsError(f"{args.out} exists; choose a new output path")
        corpus_bytes = args.corpus.read_bytes()
        corpus = json.loads(corpus_bytes)
        if args.verify_only:
            sel = json.loads(args.out.read_bytes())
        else:
            sel = build(corpus, args.corpus, corpus_bytes=corpus_bytes)
        problems = verify(sel, corpus, corpus_bytes)
        if problems:
            print("FAILED INVARIANTS: " + "; ".join(problems), file=sys.stderr)
            return 1
        if not args.verify_only:
            # Complete serialization before reserving the output name. Mode x
            # refuses files, directories and symlinks without replacing evidence.
            payload = json.dumps(sel, indent=1, ensure_ascii=False)
            try:
                with args.out.open("x", encoding="utf-8") as output:
                    output.write(payload)
            except FileExistsError:
                raise FileExistsError(f"{args.out} exists; choose a new output path") from None
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"{args.out}  ({args.out.stat().st_size:,} bytes)")
    print(f"  eligible {sel['sampling_frame']['eligible']} / {sel['sampling_frame']['corpus_entries']}"
          f"   excluded { {k: len(v) for k, v in sel['sampling_frame']['excluded'].items()} }")
    for key, value in sel["realized"].items():
        print(f"  {key:24s} {value}")
    print("\nall invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
