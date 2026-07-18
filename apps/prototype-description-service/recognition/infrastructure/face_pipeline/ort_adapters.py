"""ONNX Runtime CPU YuNet detector + SFace embedder (FIR-3 S3).

Production path with semantics pinned to OpenCV reference (S2):
- YuNet post-process ports OpenCV ``FaceDetectorYNImpl::postProcess``
  (strides 8/16/32, cls×obj score, bbox/kps decode, NMSBoxes).
- SFace preprocessing matches ``FaceRecognizerSFImpl::feature``:
  ``blobFromImage(crop, 1, Size(112,112), Scalar(0,0,0), swapRB=true)``
  i.e. BGR→RGB, scale=1.0, mean=0, NCHW float32 — verified empirically
  (cosine 1.0 vs OpenCV feature on golden crop).

Shared validation helpers live in ``opencv_ref`` (REF-19: no duplication).
Alignment reuses ``FivePointAligner`` (no reimplementation).

Heuristics: rg-015 (manifest dim, no invented contracts), AGT-06 (fail closed),
rg-013-style purity (onnxruntime/numpy + face_pipeline siblings only).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Sequence

import numpy as np
import onnxruntime as ort

from recognition.infrastructure.face_pipeline.opencv_ref import (
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_TOP_K,
    SFACE_CROP_SIZE,
    SFACE_EMBEDDING_DIM,
    FacePipelineInputError,
    RawDetection,
    ZeroNormEmbeddingError,
    _ensure_bgr_u8,
)
from recognition.infrastructure.face_pipeline.provenance import load_verified_model

# OpenCV FaceDetectorYN pad divisor + FPN strides (face_detect.cpp).
_YUNET_DIVISOR: Final[int] = 32
_YUNET_STRIDES: Final[tuple[int, ...]] = (8, 16, 32)

# Output tensor name order matching OpenCV FaceDetectorYN forward list.
_YUNET_OUTPUT_NAMES: Final[tuple[str, ...]] = (
    "cls_8",
    "cls_16",
    "cls_32",
    "obj_8",
    "obj_16",
    "obj_32",
    "bbox_8",
    "bbox_16",
    "bbox_32",
    "kps_8",
    "kps_16",
    "kps_32",
)


def _ort_session(model_path: Path) -> ort.InferenceSession:
    """CPU-only InferenceSession with reduced log noise from initializer inputs."""
    opts = ort.SessionOptions()
    opts.log_severity_level = 3  # ERROR
    return ort.InferenceSession(
        str(model_path),
        sess_options=opts,
        providers=["CPUExecutionProvider"],
    )


def _pad_to_divisor(
    image: np.ndarray, *, divisor: int = _YUNET_DIVISOR
) -> tuple[np.ndarray, int, int]:
    """Pad BGR image bottom/right to multiple of ``divisor`` (OpenCV padWithDivisor)."""
    h, w = image.shape[:2]
    pad_w = ((w - 1) // divisor + 1) * divisor
    pad_h = ((h - 1) // divisor + 1) * divisor
    if pad_h == h and pad_w == w:
        return image, pad_w, pad_h
    pad = np.zeros((pad_h, pad_w, 3), dtype=np.uint8)
    pad[:h, :w] = image
    return pad, pad_w, pad_h


def _bgr_to_nchw_float(image_u8: np.ndarray) -> np.ndarray:
    """BGR uint8 HWC → float32 NCHW scale=1.0 (OpenCV blobFromImage defaults)."""
    return np.ascontiguousarray(
        image_u8.astype(np.float32).transpose(2, 0, 1)[None, ...]
    )


def _bgr_to_sface_blob(crop_u8: np.ndarray) -> np.ndarray:
    """BGR 112×112 → SFace ORT input: RGB float32 NCHW, scale=1, mean=0.

    Mirrors ``dnn::blobFromImage(img, 1, Size(112,112), Scalar(0,0,0), true, false)``
    (swapRB=true). Documented empirical match: cosine(ORT, OpenCV.feature) == 1.0
    on synthetic golden crop (max abs ~1e-6).
    """
    rgb = crop_u8[:, :, ::-1]
    return np.ascontiguousarray(rgb.astype(np.float32).transpose(2, 0, 1)[None, ...])


def decode_yunet_level(
    cls: np.ndarray,
    obj: np.ndarray,
    bbox: np.ndarray,
    kps: np.ndarray,
    *,
    stride: int,
    pad_w: int,
    pad_h: int,
    score_threshold: float,
) -> list[RawDetection]:
    """Decode one YuNet FPN level into pre-NMS detections (pure numpy).

    Score: ``sqrt(clamp(cls,0,1) * clamp(obj,0,1))`` (OpenCV FaceDetectorYN).
    Bbox: center/size prior decode with exp on w/h; landmarks offset by grid cell.
    """
    cols = int(pad_w // stride)
    rows = int(pad_h // stride)
    expected = rows * cols

    cls_v = np.asarray(cls, dtype=np.float32).reshape(-1)
    obj_v = np.asarray(obj, dtype=np.float32).reshape(-1)
    bbox_v = np.asarray(bbox, dtype=np.float32).reshape(-1, 4)
    kps_v = np.asarray(kps, dtype=np.float32).reshape(-1, 10)

    if cls_v.size != expected or obj_v.size != expected:
        raise FacePipelineInputError(
            f"YuNet level stride={stride}: expected {expected} anchors "
            f"(pad {pad_w}x{pad_h}), got cls={cls_v.size} obj={obj_v.size}"
        )
    if bbox_v.shape[0] != expected or kps_v.shape[0] != expected:
        raise FacePipelineInputError(
            f"YuNet level stride={stride}: bbox/kps anchor count mismatch "
            f"(bbox={bbox_v.shape[0]} kps={kps_v.shape[0]} expected={expected})"
        )

    out: list[RawDetection] = []
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            cls_score = float(np.clip(cls_v[idx], 0.0, 1.0))
            obj_score = float(np.clip(obj_v[idx], 0.0, 1.0))
            score = float(np.sqrt(cls_score * obj_score))
            if score < score_threshold:
                continue

            cx = (c + float(bbox_v[idx, 0])) * stride
            cy = (r + float(bbox_v[idx, 1])) * stride
            w = float(np.exp(bbox_v[idx, 2])) * stride
            h = float(np.exp(bbox_v[idx, 3])) * stride
            x1 = cx - w / 2.0
            y1 = cy - h / 2.0

            landmarks = np.empty((5, 2), dtype=np.float32)
            for n in range(5):
                landmarks[n, 0] = (float(kps_v[idx, 2 * n]) + c) * stride
                landmarks[n, 1] = (float(kps_v[idx, 2 * n + 1]) + r) * stride

            out.append(
                RawDetection(
                    bbox=np.array([x1, y1, w, h], dtype=np.float32),
                    landmarks=landmarks,
                    score=score,
                )
            )
    return out


def _box_iou_xywh_int(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """IoU of integer xywh boxes (OpenCV Rect2i / NMSBoxes convention)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter_w = max(0, ix2 - ix1)
    inter_h = max(0, iy2 - iy1)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


def nms_yunet(
    detections: list[RawDetection],
    *,
    score_threshold: float,
    nms_threshold: float,
    top_k: int,
) -> list[RawDetection]:
    """Greedy NMS matching OpenCV ``dnn::NMSBoxes`` on integer xywh boxes.

    OpenCV casts box coords to int before NMS; float boxes are retained on keep.
    When ≤1 candidate survives the score gate, NMS is a no-op (FaceDetectorYN).
    """
    if not detections:
        return []

    # Score gate again (NMSBoxes also filters by score_threshold).
    candidates = [d for d in detections if d.score >= score_threshold]
    if len(candidates) <= 1:
        return candidates

    # Sort by score descending (OpenCV NMSBoxes).
    order = sorted(range(len(candidates)), key=lambda i: candidates[i].score, reverse=True)
    if top_k > 0 and len(order) > top_k:
        order = order[:top_k]

    int_boxes = [
        (
            int(candidates[i].bbox[0]),
            int(candidates[i].bbox[1]),
            int(candidates[i].bbox[2]),
            int(candidates[i].bbox[3]),
        )
        for i in order
    ]

    keep_order_idx: list[int] = []
    suppressed = [False] * len(order)
    for i in range(len(order)):
        if suppressed[i]:
            continue
        keep_order_idx.append(i)
        for j in range(i + 1, len(order)):
            if suppressed[j]:
                continue
            if _box_iou_xywh_int(int_boxes[i], int_boxes[j]) > nms_threshold:
                suppressed[j] = True

    return [candidates[order[i]] for i in keep_order_idx]


def decode_yunet_outputs(
    outputs: dict[str, np.ndarray],
    *,
    pad_w: int,
    pad_h: int,
    score_threshold: float,
    nms_threshold: float,
    top_k: int,
) -> list[RawDetection]:
    """Full YuNet post-process: per-stride decode + NMS (pure, modelless-testable)."""
    missing = [n for n in _YUNET_OUTPUT_NAMES if n not in outputs]
    if missing:
        raise FacePipelineInputError(f"YuNet outputs missing keys: {missing}")

    pre_nms: list[RawDetection] = []
    for stride in _YUNET_STRIDES:
        pre_nms.extend(
            decode_yunet_level(
                outputs[f"cls_{stride}"],
                outputs[f"obj_{stride}"],
                outputs[f"bbox_{stride}"],
                outputs[f"kps_{stride}"],
                stride=stride,
                pad_w=pad_w,
                pad_h=pad_h,
                score_threshold=score_threshold,
            )
        )
    return nms_yunet(
        pre_nms,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
    )


class OrtYuNetDetector:
    """ORT CPU YuNet detector with OpenCV FaceDetectorYN post-process semantics.

    Batch API: ``detect(images) -> list[list[RawDetection]]``.
    Defaults match ``OpenCVYuNetDetector`` (score 0.9, nms 0.3, top_k 5000).
    """

    def __init__(
        self,
        *,
        model_name: str = "yunet",
        models_dir: Path | None = None,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        nms_threshold: float = DEFAULT_NMS_THRESHOLD,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        model_path = load_verified_model(model_name, models_dir=models_dir)
        self._model_name = model_name
        self._model_path = model_path
        self._score_threshold = float(score_threshold)
        self._nms_threshold = float(nms_threshold)
        self._top_k = int(top_k)
        self._session = _ort_session(model_path)
        self._input_name = self._session.get_inputs()[0].name
        out_names = {o.name for o in self._session.get_outputs()}
        missing = [n for n in _YUNET_OUTPUT_NAMES if n not in out_names]
        if missing:
            raise FacePipelineInputError(
                f"YuNet ONNX missing expected outputs {missing}; got {sorted(out_names)}"
            )

    @property
    def score_threshold(self) -> float:
        return self._score_threshold

    @property
    def nms_threshold(self) -> float:
        return self._nms_threshold

    @property
    def top_k(self) -> int:
        return self._top_k

    def detect(self, images: Sequence[np.ndarray]) -> list[list[RawDetection]]:
        """Detect faces in a batch of BGR images (same contract as OpenCV path)."""
        results: list[list[RawDetection]] = []
        for i, image in enumerate(images):
            img = _ensure_bgr_u8(image, label=f"images[{i}]")
            padded, pad_w, pad_h = _pad_to_divisor(img)
            blob = _bgr_to_nchw_float(padded)
            raw_outs = self._session.run(None, {self._input_name: blob})
            out_names = [o.name for o in self._session.get_outputs()]
            outputs = {name: arr for name, arr in zip(out_names, raw_outs)}
            faces = decode_yunet_outputs(
                outputs,
                pad_w=pad_w,
                pad_h=pad_h,
                score_threshold=self._score_threshold,
                nms_threshold=self._nms_threshold,
                top_k=self._top_k,
            )
            results.append(faces)
        return results


class OrtSFaceEmbedder:
    """ORT CPU SFace embedder with OpenCV FaceRecognizerSF preprocessing.

    Batch API: ``embed(crops) -> (N, dim)`` L2-normalized float32.
    Crops must be 112×112×3 BGR. Dim from manifest (rg-015). Zero-norm raises.
    """

    def __init__(
        self,
        *,
        model_name: str = "sface",
        models_dir: Path | None = None,
    ) -> None:
        model_path = load_verified_model(model_name, models_dir=models_dir)
        self._model_name = model_name
        self._model_path = model_path
        self._session = _ort_session(model_path)
        self._input_name = self._session.get_inputs()[0].name
        self.embedding_dim = SFACE_EMBEDDING_DIM

    def _feature(self, crop: np.ndarray) -> np.ndarray:
        """Raw model feature for one validated 112×112 BGR crop (hookable in tests)."""
        blob = _bgr_to_sface_blob(crop)
        out = self._session.run(None, {self._input_name: blob})[0]
        return np.asarray(out, dtype=np.float32).reshape(-1)

    def embed(self, crops: Sequence[np.ndarray]) -> np.ndarray:
        """Embed a batch of 112×112×3 BGR crops → L2-normalized (N, dim)."""
        if not crops:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)

        expected_shape = (SFACE_CROP_SIZE, SFACE_CROP_SIZE, 3)
        vectors: list[np.ndarray] = []
        for i, crop in enumerate(crops):
            img = _ensure_bgr_u8(crop, label=f"crops[{i}]")
            if img.shape != expected_shape:
                raise FacePipelineInputError(
                    f"crops[{i}]: expected shape {expected_shape} (SFace crop), "
                    f"got {img.shape}; align via FivePointAligner before embed"
                )
            raw = np.asarray(self._feature(img), dtype=np.float32).reshape(-1)
            if raw.size != self.embedding_dim:
                raise FacePipelineInputError(
                    f"crops[{i}]: expected embedding dim {self.embedding_dim}, got {raw.size}"
                )
            norm = float(np.linalg.norm(raw))
            if norm == 0.0 or not np.isfinite(norm):
                raise ZeroNormEmbeddingError(
                    f"crops[{i}]: SFace embedding has zero/non-finite L2 norm "
                    f"(norm={norm}); refusing silent zero-fill"
                )
            vectors.append(raw / norm)
        return np.stack(vectors, axis=0).astype(np.float32, copy=False)


__all__ = [
    "OrtSFaceEmbedder",
    "OrtYuNetDetector",
    "decode_yunet_level",
    "decode_yunet_outputs",
    "nms_yunet",
]
