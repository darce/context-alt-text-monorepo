#!/usr/bin/env python3
"""Test whether detector geometry can reproduce the operator's hand-drawn slice tags.

The corpus has pose/occlusion tags on 150 images only, all hand-applied. If a geometric
signal from the detection pass predicts those labels, it can be extended to the other
496 images; if it does not, the tag stays hand-only and the coverage gap stands.

This script decides nothing on its own. It reports discrimination (ROC AUC over the 150
labelled images) and the best achievable precision/recall, so a signal has to earn its
threshold instead of being handed one. A signal at AUC ~0.5 is noise, and saying so is
the useful result: it is direct evidence for the claim that occlusion is not detectable
offline, rather than an appeal to the harness's prior say-so.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

MANIFEST_DIR = Path(__file__).resolve().parents[1] / "manifests"
DETECTIONS = MANIFEST_DIR / "detections-yunet-v1.json"
GOLDEN_DRAFT = MANIFEST_DIR / "golden150-draft-20260723.json"
CORPUS = MANIFEST_DIR / "corpus-manifest-v3.json"


def check_output(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"{path} already exists; choose a new output")


def publish(path: Path, data: dict) -> None:
    # Serialize and reject non-finite values before creating any destination.
    payload = json.dumps(data, indent=1, ensure_ascii=False, allow_nan=False)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    except FileExistsError:
        raise FileExistsError(f"{path} already exists; choose a new output") from None

TAGS = ("profile", "blur", "low_res", "sunglasses", "masked", "occlusion_other")
# (signal, direction) — direction -1 means "low values indicate the tag".
SIGNALS = (
    ("interocular_ratio", -1),
    ("nose_offset", +1),
    ("blur_var", -1),
    ("face_min_side", -1),
    ("face_area_frac", -1),
    ("score", -1),
    ("yaw_eye", +1),
    ("yaw_mouth", +1),
    ("eye_span_ratio", -1),
    ("roll_deg", +1),
)
# Below this a signal is not distinguishable from chance on 150 images and must not be
# extended to the unlabelled 496.
AUC_FLOOR = 0.75


def auc(pos: Sequence[float], neg: Sequence[float]) -> float | None:
    """Mann-Whitney U / |pos||neg|. Ties count as half, as in the rank-sum definition."""
    if not pos or not neg:
        return None
    wins = sum(sum(1.0 if p > n else 0.5 if p == n else 0.0 for n in neg) for p in pos)
    return wins / (len(pos) * len(neg))


def best_threshold(pos: Sequence[float], neg: Sequence[float], direction: int) -> dict:
    """Sweep every observed value; return the cut with the best F1."""
    best = {"f1": 0.0, "threshold": None, "precision": 0.0, "recall": 0.0}
    for cut in sorted(set(pos) | set(neg)):
        tp = sum(1 for v in pos if (v >= cut if direction > 0 else v <= cut))
        fp = sum(1 for v in neg if (v >= cut if direction > 0 else v <= cut))
        fn = len(pos) - tp
        if tp == 0:
            continue
        precision, recall = tp / (tp + fp), tp / (tp + fn)
        f1 = 2 * precision * recall / (precision + recall)
        if f1 > best["f1"]:
            best = {"f1": f1, "threshold": cut, "precision": precision, "recall": recall}
    return best


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detections", type=Path, default=DETECTIONS)
    ap.add_argument("--golden", type=Path, default=GOLDEN_DRAFT)
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    check_output(args.out)
    detections = {row["media_id"]: row for row in json.loads(args.detections.read_text())["entries"]}
    golden = json.loads(args.golden.read_text())
    corpus = {e["media_id"]: e for e in json.loads(args.corpus.read_text())["entries"]}

    # Ground truth: the 150 that carry a `tags` key. An empty list is a real negative —
    # the operator looked and applied nothing — so absence is informative here.
    labelled: list[tuple[int, set[str], dict | None]] = []
    for entry in golden["entries"]:
        media_id = entry["media_id"]
        if "tags" not in entry or media_id not in detections:
            continue
        faces = detections[media_id]["faces"]
        labelled.append((media_id, set(entry["tags"]), faces[0] if faces else None))

    detected = [row for row in labelled if row[2] is not None]
    print(f"labelled images {len(labelled)} | with a detected face {len(detected)}"
          f" | detector found nothing {len(labelled) - len(detected)}\n")

    print(f"{'tag':<17}{'n_pos':>6}{'signal':>20}{'AUC':>8}{'thresh':>10}{'prec':>7}{'rec':>7}{'F1':>7}  verdict")
    print("-" * 100)
    shippable: dict[str, dict] = {}
    for tag in TAGS:
        rows = [(tags, face) for _, tags, face in detected]
        n_pos = sum(1 for tags, _ in rows if tag in tags)
        if n_pos == 0:
            continue
        ranked = []
        for signal, direction in SIGNALS:
            pos = [f[signal] * direction for tags, f in rows if tag in tags and f.get(signal) is not None]
            neg = [f[signal] * direction for tags, f in rows if tag not in tags and f.get(signal) is not None]
            area = auc(pos, neg)
            if area is None:
                continue
            ranked.append((area, signal, direction, pos, neg))
        ranked.sort(reverse=True, key=lambda r: r[0])
        area, signal, direction, pos, neg = ranked[0]
        cut = best_threshold(pos, neg, +1)
        verdict = "SHIP" if area >= AUC_FLOOR else "noise - hand-tag only"
        raw_cut = cut["threshold"] * direction if cut["threshold"] is not None else float("nan")
        print(f"{tag:<17}{n_pos:>6}{signal:>20}{area:>8.3f}{raw_cut:>10.3f}"
              f"{cut['precision']:>7.2f}{cut['recall']:>7.2f}{cut['f1']:>7.2f}  {verdict}")
        if area >= AUC_FLOOR:
            shippable[tag] = {"signal": signal, "direction": direction, "threshold": raw_cut,
                              "auc": round(area, 3), **{k: round(v, 3) for k, v in cut.items() if k != "threshold"}}

    # Detector recall against the operator's own identity boxes: a face the operator
    # named but YuNet misses is a hole in every geometry-derived tag downstream.
    named_but_undetected = [
        mid for mid, e in corpus.items()
        if e["named_boxes"] and not detections.get(mid, {}).get("faces")
    ]
    print(f"\nimages with an operator-named face that YuNet@0.9 does not detect: "
          f"{len(named_but_undetected)} / {sum(1 for e in corpus.values() if e['named_boxes'])}")
    print(f"shippable tags: {sorted(shippable) or 'none'}")
    publish(args.out, {"auc_floor": AUC_FLOOR, "labelled_images": len(detected),
                    "shippable": shippable,
                    "named_but_undetected": sorted(named_but_undetected)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
