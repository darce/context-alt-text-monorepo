#!/usr/bin/env python3
"""Run the pinned YuNet detector over every corpus image and record raw geometry.

This is *detection only* — bounding boxes, 5-point landmarks and detection scores.
No embedding, no clustering, no captioning. It runs on CPU in seconds and produces
the two things the corpus manifest is missing:

  1. `detected_boxes` for all 646 images (today only the 150 hand-drafted ones have
     detector geometry; the rest carry operator workbench boxes, which mark identity
     rather than every face).
  2. The frozen 5-point landmark cache that `synthetic_occlusion.py` needs to place
     occluders without ever calling a detector live.

Raw features only. This script does NOT decide slice tags: thresholds are chosen and
validated separately, against the 150 images an operator already hand-tagged, so a
derived tag has to earn its place by reproducing human labels.

Determinism: ORT CPU, pinned weights verified by sha256, entries emitted in media_id
order. Re-running produces byte-identical output modulo `built_at`.
"""

from __future__ import annotations

import argparse
import json
import os
import math
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "apps/prototype-description-service"
MANIFEST_DIR = REPO / "benchmarks/manifests"
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

# The aligner's canonical crop size. Blur variance is scale-sensitive, so every face is
# measured at one size or a big face outscores a small sharp one on pixel count alone.
BLUR_CROP_PX = 112


def read_bgr(path: Path) -> np.ndarray | None:
    """Read as BGR uint8. cv2 first; PIL covers the formats OpenCV was not built for."""
    import cv2
    import numpy as np

    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is not None:
        return img
    try:
        from PIL import Image

        with Image.open(path) as handle:
            rgb = np.asarray(handle.convert("RGB"))
        return rgb[:, :, ::-1].copy()
    except Exception:
        return None


def face_features(image: np.ndarray, bbox: np.ndarray, landmarks: np.ndarray) -> dict:
    """Geometry-derived signals for one face. Raw numbers; no thresholds applied here.

    Landmarks are YuNet order: right_eye, left_eye, nose_tip, right_mouth, left_mouth.
    "right" is the subject's right, so it sits on the LEFT of the image.
    """
    import cv2
    import numpy as np

    x, y, w, h = (float(v) for v in bbox)
    r_eye, l_eye, nose = landmarks[0], landmarks[1], landmarks[2]

    interocular = float(np.hypot(*(l_eye - r_eye)))
    # Yaw proxy 1: the nose leaves the eye midpoint as the head turns, normalized by
    # interocular distance so it is scale-free.
    eye_mid_x = float((r_eye[0] + l_eye[0]) / 2.0)
    nose_offset = abs(float(nose[0]) - eye_mid_x) / interocular if interocular > 1e-6 else None
    # Yaw proxy 2: at profile the two eyes converge in projection while the box stays
    # face-width, so the ratio collapses. Independent of proxy 1's landmark noise.
    interocular_ratio = interocular / w if w > 1e-6 else None

    crop = image[max(int(y), 0) : int(y + h), max(int(x), 0) : int(x + w)]
    blur_var = None
    if crop.size and crop.shape[0] >= 8 and crop.shape[1] >= 8:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (BLUR_CROP_PX, BLUR_CROP_PX), interpolation=cv2.INTER_AREA)
        blur_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    return {
        "bbox": [round(v, 2) for v in (x, y, w, h)],
        "landmarks": [[round(float(px), 2), round(float(py), 2)] for px, py in landmarks],
        "face_min_side": round(min(w, h), 2),
        "face_area_frac": round((w * h) / (image.shape[0] * image.shape[1]), 6),
        "interocular_ratio": round(interocular_ratio, 4) if interocular_ratio is not None else None,
        "nose_offset": round(nose_offset, 4) if nose_offset is not None else None,
        "blur_var": round(blur_var, 3) if blur_var is not None else None,
    }


def run(corpus: dict, limit: int | None, score_threshold: float,
        images_root: Path, corpus_path: Path = CORPUS) -> dict:
    sys.path.insert(0, str(SERVICE))
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector
    from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST
    detector = OrtYuNetDetector(score_threshold=score_threshold)
    entries = sorted(corpus["entries"], key=lambda e: e["media_id"])
    if limit:
        entries = entries[:limit]

    rows: list[dict] = []
    unreadable: list[str] = []
    started = time.monotonic()
    for i, entry in enumerate(entries, 1):
        path = images_root / entry["path"]
        image = read_bgr(path)
        if image is None:
            unreadable.append(entry["path"])
            continue
        detections = detector.detect([image])[0]
        # Largest face first: image-level tags describe the subject, not an incidental
        # bystander in the background.
        faces = sorted(
            (face_features(image, d.bbox, d.landmarks) | {"score": round(float(d.score), 4)} for d in detections),
            key=lambda f: -f["face_area_frac"],
        )
        rows.append(
            {
                "media_id": entry["media_id"],
                "path": entry["path"],
                "sha256": entry["sha256"],
                "width": image.shape[1],
                "height": image.shape[0],
                "faces": faces,
            }
        )
        if i % 100 == 0:
            print(f"  {i}/{len(entries)}  {time.monotonic() - started:.1f}s", file=sys.stderr)

    model = MODEL_MANIFEST["yunet"]
    return {
        "detection_version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_manifest": corpus_path.name,
        "detector": {
            "model_id": "yunet",
            "file_name": model.file_name,
            "weights_sha256": model.sha256,
            "score_threshold": detector.score_threshold,
            "nms_threshold": detector.nms_threshold,
            "top_k": detector.top_k,
            "runtime": "onnxruntime-cpu",
        },
        "blur_crop_px": BLUR_CROP_PX,
        "images": len(rows),
        "unreadable": unreadable,
        "entries": rows,
    }


def summarize(result: dict, out: Path) -> None:
    faces = [f for row in result["entries"] for f in row["faces"]]
    counts: dict[int, int] = {}
    for row in result["entries"]:
        counts[len(row["faces"])] = counts.get(len(row["faces"]), 0) + 1
    print(f"{out}  ({out.stat().st_size:,} bytes)  score_threshold {result['detector']['score_threshold']}")
    print(f"  images {result['images']} | unreadable {len(result['unreadable'])} | faces {len(faces)}")
    print(f"  faces_per_image {dict(sorted(counts.items()))}")
    if faces:
        for key in ("face_min_side", "interocular_ratio", "nose_offset", "blur_var", "score"):
            vals = sorted(v for f in faces if (v := f.get(key)) is not None)
            if vals:
                q = lambda p: vals[min(int(p * len(vals)), len(vals) - 1)]  # noqa: E731
                print(f"  {key:20s} p10 {q(0.10):>9.3f}  p50 {q(0.50):>9.3f}  p90 {q(0.90):>9.3f}")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--images-root", type=Path, default=os.environ.get("FIR_IMAGES_ROOT"))
    ap.add_argument("--limit", type=int, default=None)
    # The 0.9 default censors exactly the hard faces the slice tags are about: it misses
    # 80% of hand-tagged `masked` and 42% of `profile`, so calibrating on its output
    # measures only easy cases. Lower it to recover the population, then re-check.
    ap.add_argument("--score-threshold", type=float, default=0.9)
    args = ap.parse_args(argv)

    check_output(args.out)
    corpus = json.loads(args.corpus.read_text())
    if not isinstance(corpus["entries"], list):
        ap.error("corpus entries must be a list")
    for entry in corpus["entries"]:
        for key in ("media_id", "path", "sha256"):
            if key not in entry:
                ap.error(f"corpus entry missing {key}")
    if args.images_root is None or not args.images_root.is_dir():
        ap.error("provide an existing --images-root (or FIR_IMAGES_ROOT)")
    if not math.isfinite(args.score_threshold) or not 0 <= args.score_threshold <= 1:
        ap.error("--score-threshold must be finite and between 0 and 1")
    if args.limit is not None and args.limit <= 0:
        ap.error("--limit must be positive")
    result = run(corpus, args.limit, args.score_threshold, args.images_root, args.corpus)
    publish(args.out, result)
    summarize(result, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
