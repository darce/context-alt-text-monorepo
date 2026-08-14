#!/usr/bin/env python3
"""Regenerate FIR-3 S2 golden fixtures deterministically (seeded).

Run from apps/prototype-description-service:

    uv run python recognition/tests/fixtures/face_pipeline/generate_goldens.py

Writes small .npy/.json only — never .onnx. Requires verified SFace model on disk
for embedding goldens (``scripts/fetch_face_pipeline_models.py``).

Heuristics: TEST-06/TEST-08 (determinism), AGT-06 (name the skip).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

import cv2  # noqa: E402

from recognition.infrastructure.face_pipeline.aligner import (  # noqa: E402
    YUNET_LANDMARK_NAMES,
    FivePointAligner,
)
from recognition.infrastructure.face_pipeline.opencv_ref import (  # noqa: E402
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    OpenCVSFaceEmbedder,
    OpenCVYuNetDetector,
)
from recognition.infrastructure.face_pipeline.provenance import (  # noqa: E402
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
    load_verified_model,
    numeric_runtime_fingerprint,
)

FIXTURE_DIR = Path(__file__).resolve().parent
SEED = 20260715
EMBED_SEED = 20260716
GENERATOR_RELPATH = "recognition/tests/fixtures/face_pipeline/generate_goldens.py"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def toolchain_provenance() -> dict[str, str]:
    """Record which numeric-relevant runtimes produced the goldens (CVU-02V).

    Delegates to ``numeric_runtime_fingerprint`` so stamps cover OpenCV,
    onnxruntime, and numpy — the three packages that move embedding /
    clustering comparability on this upgrade. ``generator`` is the script path.
    """
    fp = numeric_runtime_fingerprint()
    return {
        "opencv_version": fp.opencv_version,
        "onnxruntime_version": fp.onnxruntime_version,
        "numpy_version": fp.numpy_version,
        "generator": GENERATOR_RELPATH,
    }


def synthetic_112_crop(seed: int = EMBED_SEED) -> np.ndarray:
    """Deterministic 112×112 BGR gradient+noise crop (no face required)."""
    rng = np.random.RandomState(seed)
    yy, xx = np.mgrid[0:112, 0:112]
    base = np.stack(
        [
            (xx * 2 + seed) % 256,
            (yy * 3 + seed // 2) % 256,
            ((xx + yy) + seed) % 256,
        ],
        axis=-1,
    ).astype(np.float32)
    noise = rng.randn(112, 112, 3).astype(np.float32) * 8.0
    return np.clip(base + noise, 0, 255).astype(np.uint8)


def aligner_source_image(seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic image + hand-specified 5 landmarks (YuNet order)."""
    rng = np.random.RandomState(seed)
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    for i in range(200):
        img[i, :, 0] = (i + seed) % 256
        img[:, i, 1] = (i * 2 + seed) % 256
        img[i, i, 2] = 255
    img = np.clip(img.astype(np.int16) + rng.randint(-3, 4, img.shape), 0, 255).astype(np.uint8)
    # YuNet order: right eye, left eye, nose, right mouth, left mouth
    landmarks = np.array(
        [
            [80.0, 80.0],
            [120.0, 80.0],
            [100.0, 100.0],
            [85.0, 130.0],
            [115.0, 130.0],
        ],
        dtype=np.float64,
    )
    return img, landmarks


def write_embedding_goldens(*, output_dir: Path | None = None) -> dict:
    out_dir = FIXTURE_DIR if output_dir is None else Path(output_dir)
    crop = synthetic_112_crop()
    crop_path = out_dir / "synthetic_112_crop.npy"
    np.save(crop_path, crop)

    embedder = OpenCVSFaceEmbedder()
    batch = embedder.embed([crop])
    emb = batch.vectors
    emb_path = out_dir / "synthetic_112_embedding.npy"
    np.save(emb_path, emb)

    # cosine_min: N=50 OpenCVSFaceEmbedder runs on this deterministic synthetic
    # 112×112 crop were bit-exact vs golden (vector maxabs=0; float64 unit-cosine
    # ≈ 1-1e-12). Floor 0.99999999 is 10× above a 1e-9 slack band so same-host
    # regen noise cannot greenwash a real embedder shift (CVUP1-LC-03).
    # Not the corpus OpenCV 4→5 upgrade self-similarity (min 0.999524 / median
    # 0.999933 over 83 faces — docs/tasks/fir/evidence/opencv-5-embedding-drift.md);
    # that protocol measures cross-version match-band drift, not golden noise floor.
    meta = {
        "kind": "embedding_golden",
        "seed": EMBED_SEED,
        "crop_sha256": _sha256_bytes(crop.tobytes()),
        "embedding_shape": list(emb.shape),
        "embedding_dim": int(emb.shape[1]),
        "l2_norm": float(np.linalg.norm(emb[0])),
        "pre_norm_magnitude": float(batch.norms[0]),
        "model": MODEL_MANIFEST["sface"].file_name,
        "model_sha256": MODEL_MANIFEST["sface"].sha256,
        "cosine_min": 0.99999999,
        **toolchain_provenance(),
    }
    (out_dir / "embedding_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return meta


def write_composed_aligner_embedder_goldens(*, output_dir: Path | None = None) -> dict:
    """Composed aligner→embedder golden (CVUP1-LC-03).

    The synthetic_112_embedding path feeds a pre-baked crop that never passes
    through cv2.warpAffine. This fixture starts from aligner_source_image +
    landmarks, runs FivePointAligner.align, then embeds — the only path that
    can catch aligner-driven embedding-space drift.
    """
    out_dir = FIXTURE_DIR if output_dir is None else Path(output_dir)
    img, landmarks = aligner_source_image()
    # Prefer committed source fixtures when present so regen stays consistent
    # with the aligner goldens already on disk.
    src_path = FIXTURE_DIR / "aligner_source_image.npy"
    lm_path = FIXTURE_DIR / "aligner_landmarks.npy"
    if src_path.is_file() and lm_path.is_file():
        img = np.load(src_path)
        landmarks = np.load(lm_path)

    crop = FivePointAligner().align(img, landmarks).crop
    batch = OpenCVSFaceEmbedder().embed([crop])
    emb = batch.vectors
    emb_path = out_dir / "aligner_composed_embedding.npy"
    np.save(emb_path, emb)

    meta = {
        "kind": "aligner_composed_embedding_golden",
        "description": (
            "Embedding of FivePointAligner.align(aligner_source_image, "
            "aligner_landmarks).crop — composed aligner→embedder path so "
            "warpAffine drift is visible at the embedding layer (CVUP1-LC-03)."
        ),
        "source_image": "aligner_source_image.npy",
        "source_landmarks": "aligner_landmarks.npy",
        "crop_sha256": _sha256_bytes(crop.tobytes()),
        "embedding_shape": list(emb.shape),
        "embedding_dim": int(emb.shape[1]),
        "l2_norm": float(np.linalg.norm(emb[0])),
        "pre_norm_magnitude": float(batch.norms[0]),
        "model": MODEL_MANIFEST["sface"].file_name,
        "model_sha256": MODEL_MANIFEST["sface"].sha256,
        # N=50 composed runs: bit-exact. Same floor as synthetic golden.
        "cosine_min": 0.99999999,
        **toolchain_provenance(),
    }
    (out_dir / "aligner_composed_embedding_meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return meta


def _face_box_from_landmarks(landmarks: np.ndarray, *, image_shape: tuple[int, ...]) -> np.ndarray:
    """Build FaceDetectorYN-style 15-vector for FaceRecognizerSF.alignCrop."""
    h, w = int(image_shape[0]), int(image_shape[1])
    box = np.zeros(15, dtype=np.float32)
    box[0:4] = (0.0, 0.0, float(w), float(h))
    box[4:14] = np.asarray(landmarks, dtype=np.float32).reshape(-1)
    box[14] = 1.0
    return box


def oracle_align_crop(img: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """OpenCV FaceRecognizerSF.alignCrop oracle crop (semantic source of truth)."""
    model_path = load_verified_model("sface")
    recognizer = cv2.FaceRecognizerSF.create(str(model_path), "")
    face_box = _face_box_from_landmarks(landmarks, image_shape=img.shape)
    return recognizer.alignCrop(img, face_box)


def write_aligner_goldens(*, output_dir: Path | None = None) -> dict:
    """Write aligner goldens from FaceRecognizerSF.alignCrop (not FivePointAligner).

    Breaks circularity (TEST-06 / BR-01): fixtures come from the OpenCV oracle;
    unit tests check FivePointAligner against those fixtures and vs alignCrop.
    """
    out_dir = FIXTURE_DIR if output_dir is None else Path(output_dir)
    img, landmarks = aligner_source_image()
    np.save(out_dir / "aligner_source_image.npy", img)
    np.save(out_dir / "aligner_landmarks.npy", landmarks)

    oracle_crop = oracle_align_crop(img, landmarks)
    portable = FivePointAligner().align(img, landmarks)
    # Same-host parity is currently bit-exact; fail golden regen if the port drifts.
    if not np.array_equal(portable.crop, oracle_crop):
        max_diff = int(np.max(np.abs(portable.crop.astype(np.int16) - oracle_crop.astype(np.int16))))
        raise RuntimeError(
            "FivePointAligner crop diverges from FaceRecognizerSF.alignCrop oracle "
            f"(max abs pixel diff={max_diff}); refuse to write circular goldens"
        )
    np.save(out_dir / "aligner_affine.npy", portable.affine)
    np.save(out_dir / "aligner_crop.npy", oracle_crop)
    crop_sha = _sha256_bytes(oracle_crop.tobytes())
    meta = {
        "kind": "aligner_golden",
        "seed": SEED,
        "landmark_order": list(YUNET_LANDMARK_NAMES),
        "crop_shape": list(oracle_crop.shape),
        "crop_sha256": crop_sha,
        "affine_shape": list(portable.affine.shape),
        "output_size": 112,
        "oracle": "cv2.FaceRecognizerSF.alignCrop",
        "oracle_model": MODEL_MANIFEST["sface"].file_name,
        **toolchain_provenance(),
    }
    (out_dir / "aligner_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return meta


def cartoon_drawn_feature_coords(
    *,
    size: int = 480,
    eye_sep: float = 0.095,
    mouth_y: float = 0.155,
) -> dict[str, tuple[float, float]]:
    """Pixel centers of procedural cartoon features (YuNet landmark name keys).

    Matches the drawing procedure in ``cartoon_face_image`` (eye blobs at
    ±eye_sep, nose at +0.02*size, mouth corners at ±0.08*size around mouth_y).
    """
    cx = size / 2.0
    cy = size / 2.0
    mouth_half = 0.08 * size
    return {
        "right_eye": (cx - eye_sep * size, cy - 0.08 * size),
        "left_eye": (cx + eye_sep * size, cy - 0.08 * size),
        "nose_tip": (cx, cy + 0.02 * size),
        "right_mouth_corner": (cx - mouth_half, cy + mouth_y * size),
        "left_mouth_corner": (cx + mouth_half, cy + mouth_y * size),
    }


def cartoon_face_image(
    *,
    size: int = 480,
    seed: int = 19,
    eye_sep: float = 0.095,
    mouth_y: float = 0.155,
    head_rx: float = 0.27,
    head_ry: float = 0.36,
    noise_scale: float = 3.0,
) -> np.ndarray:
    """Procedural high-contrast soft face (seeded; no real photo).

    Tuned so YuNet 2026may scores ≥ default score_threshold=0.9 on OpenCV 4.13.
    """
    rng = np.random.RandomState(seed)
    img = np.full((size, size, 3), 200, dtype=np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    head = np.exp(-(((xx - size / 2) / (head_rx * size)) ** 2 + ((yy - size / 2) / (head_ry * size)) ** 2))
    skin = np.array([150.0, 180.0, 220.0], dtype=np.float32)
    bg = np.array([200.0, 200.0, 200.0], dtype=np.float32)
    img = bg + head[..., None] * (skin - bg)
    for ex in (-eye_sep, eye_sep):
        eye = np.exp(
            -(
                ((xx - (size / 2 + ex * size)) / (0.04 * size)) ** 2
                + ((yy - (size / 2 - 0.08 * size)) / (0.025 * size)) ** 2
            )
        )
        img = img * (1.0 - 0.9 * eye[..., None])
    mouth = np.exp(
        -(((xx - size / 2) / (0.08 * size)) ** 2 + ((yy - (size / 2 + mouth_y * size)) / (0.03 * size)) ** 2)
    )
    img = img * (1.0 - 0.5 * mouth[..., None])
    nose = np.exp(-(((xx - size / 2) / (0.03 * size)) ** 2 + ((yy - (size / 2 + 0.02 * size)) / (0.06 * size)) ** 2))
    img = img + nose[..., None] * np.array([-20.0, -15.0, -10.0], dtype=np.float32)
    img = np.clip(img, 0, 255).astype(np.uint8)
    noise = rng.randn(size, size, 3).astype(np.float32) * noise_scale
    return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def write_detector_goldens(*, output_dir: Path | None = None) -> dict:
    """Record detector bbox/landmarks/score golden if YuNet detects the cartoon.

    If detection fails under default thresholds, write a typed skip note instead
    of a fake always-passing golden (TEST-06, AGT-06).
    """
    out_dir = FIXTURE_DIR if output_dir is None else Path(output_dir)
    procedure = {
        "size": 480,
        "seed": 19,
        "eye_sep": 0.095,
        "mouth_y": 0.155,
        "head_rx": 0.27,
        "head_ry": 0.36,
        "noise_scale": 3.0,
        "description": ("seeded gaussian soft face (skin disc + dark eyes + nose + mouth)"),
    }
    img = cartoon_face_image(
        **{
            k: procedure[k]
            for k in (
                "size",
                "seed",
                "eye_sep",
                "mouth_y",
                "head_rx",
                "head_ry",
                "noise_scale",
            )
        }
    )
    # Do not commit the full 480² RGB raster — rebuild from `procedure` in tests
    # (TEST-06 determinism; keep goldens small: .json only for detector).
    image_npy = out_dir / "detector_cartoon_image.npy"
    image_npy.unlink(missing_ok=True)

    det = OpenCVYuNetDetector(
        score_threshold=DEFAULT_SCORE_THRESHOLD,
        nms_threshold=DEFAULT_NMS_THRESHOLD,
    )
    detections = det.detect([img])[0]
    skip_path = out_dir / "detector_golden_skip.json"
    faces_path = out_dir / "detector_faces.json"

    if not detections or detections[0].score < DEFAULT_SCORE_THRESHOLD:
        note = {
            "kind": "detector_golden_skip",
            "status": "skipped_no_consented_image",
            "reason": (
                "Procedural cartoon face did not reach score>="
                f"{DEFAULT_SCORE_THRESHOLD} under default FaceDetectorYN "
                "thresholds. Detector-output goldens need an operator-supplied "
                "consented frontal face image. Plumbing tests remain covered."
            ),
            "default_score_threshold": DEFAULT_SCORE_THRESHOLD,
            "default_nms_threshold": DEFAULT_NMS_THRESHOLD,
            "model": MODEL_MANIFEST["yunet"].file_name,
            "procedure": procedure,
        }
        faces_path.unlink(missing_ok=True)
        skip_path.write_text(json.dumps(note, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return note

    d0 = detections[0]
    # Expected YuNet landmark → nearest drawn cartoon feature (order contract).
    drawn = cartoon_drawn_feature_coords(
        size=int(procedure["size"]),
        eye_sep=float(procedure["eye_sep"]),
        mouth_y=float(procedure["mouth_y"]),
    )
    expected_nearest = list(YUNET_LANDMARK_NAMES)
    payload = {
        "kind": "detector_golden",
        "status": "recorded",
        "score_threshold": DEFAULT_SCORE_THRESHOLD,
        "nms_threshold": DEFAULT_NMS_THRESHOLD,
        "image_shape": list(img.shape),
        "image_sha256": _sha256_bytes(img.tobytes()),
        "model": MODEL_MANIFEST["yunet"].file_name,
        "model_sha256": MODEL_MANIFEST["yunet"].sha256,
        # Version-drift budgets (CVUP1-LC-03). Regenerated only when procedure/runtime
        # changes; do not loosen without a fresh N-run noise-floor measurement.
        # Measurement 2026-07-29, OpenCV 5.0.0, N=50 identical cartoon inputs:
        #   max run-to-run | vs-golden abs: bbox=0, landmarks=0, score=0 (bit-exact).
        # Noise floor = 0. Tolerance = 10 × float32 ULP @ ~300 px
        #   ≈ 10*(300*2^-23) ≈ 3.6e-4 → 5e-4 px; score 10×ulp@1 ≈ 1e-5.
        "tolerances": {
            "bbox_px": 5e-4,
            "landmarks_px": 5e-4,
            "score": 1e-5,
            # Absolute distance to drawn feature center (YuNet offset on soft blob).
            "landmark_nearest_px": 50.0,
            "derivation": (
                "N=50 identical-input OpenCVYuNetDetector runs (OpenCV 5.0.0, 2026-07-29): "
                "max run-to-run and vs-golden abs were 0.0 for bbox_px, landmarks_px, and "
                "score (bit-exact). Noise floor = 0. Tolerance = 10 × float32 ULP at "
                "coordinate scale ~300 px ≈ 10*(300*2^-23) ≈ 3.6e-4, rounded to 5e-4 px "
                "for bbox/landmarks; score = 10 × float32 ULP at ~1.0 ≈ 1.2e-6, rounded "
                "to 1e-5. ~4000× tighter than the prior decorative 2.0 px / 0.02; a "
                "1.9 px landmark shift fails."
            ),
        },
        "procedure": procedure,
        "drawn_feature_coords": {k: [float(v[0]), float(v[1])] for k, v in drawn.items()},
        "expected_landmark_nearest_names": expected_nearest,
        "detection": {
            "bbox_xywh": d0.bbox.astype(float).tolist(),
            "landmarks_xy": d0.landmarks.astype(float).tolist(),
            "score": float(d0.score),
        },
        **toolchain_provenance(),
    }
    skip_path.unlink(missing_ok=True)
    faces_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for golden outputs (default: fixture dir next to this script).",
    )
    args = parser.parse_args(argv)
    output_dir = FIXTURE_DIR if args.output_dir is None else Path(args.output_dir)

    # Prove models load before writing goldens that depend on them.
    load_verified_model("sface")
    load_verified_model("yunet")
    output_dir.mkdir(parents=True, exist_ok=True)

    emb_meta = write_embedding_goldens(output_dir=output_dir)
    align_meta = write_aligner_goldens(output_dir=output_dir)
    composed_meta = write_composed_aligner_embedder_goldens(output_dir=output_dir)
    det_meta = write_detector_goldens(output_dir=output_dir)

    print("Wrote embedding goldens:", emb_meta["crop_sha256"][:12], "...")
    print("Wrote aligner goldens:", align_meta["crop_sha256"][:12], "...")
    print("Wrote composed aligner→embedder goldens:", composed_meta["crop_sha256"][:12], "...")
    print("Detector golden:", det_meta.get("status"), det_meta.get("kind"))
    print("models_dir:", DEFAULT_MODELS_DIR)
    print("output_dir:", output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
