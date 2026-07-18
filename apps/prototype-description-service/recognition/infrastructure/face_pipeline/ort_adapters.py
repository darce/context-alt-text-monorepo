"""ONNX Runtime CPU YuNet detector + SFace embedder (FIR-3 S3).

Production path with semantics pinned to OpenCV reference (S2):
- YuNet post-process ports OpenCV ``FaceDetectorYNImpl::postProcess``
  (strides 8/16/32, score = sqrt(cls·obj) with upper-only clamp, bbox/kps
  decode, FaceDetectorYN NMS).
- SFace preprocessing matches ``FaceRecognizerSFImpl::feature``:
  ``blobFromImage(crop, 1, Size(112,112), Scalar(0,0,0), swapRB=true)``
  i.e. BGR→RGB, scale=1.0, mean=0, NCHW float32 — verified empirically
  (cosine 1.0 vs OpenCV feature on golden crop).

Shared validation + embed batch live in ``_common`` (cv2/onnxruntime-free).
Alignment is owned by ``FivePointAligner`` (separate module); this module does
not reimplement alignment.

Parity is validated for real-signal scores (production threshold 0.9). OpenCV
FaceDetectorYN is itself instance-nondeterministic at the noise floor
(tiny/degenerate inputs); do not treat empty-image double-runs as a parity
oracle.

Heuristics: rg-015 (manifest dim, no invented contracts), AGT-06 (fail closed),
rg-013-style purity (onnxruntime/numpy + face_pipeline siblings only; no cv2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Sequence

import numpy as np
import onnxruntime as ort

from recognition.infrastructure.face_pipeline._common import (
    DEFAULT_INPUT_SIZE,
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_TOP_K,
    SFACE_EMBEDDING_DIM,
    FacePipelineInputError,
    RawDetection,
    ZeroNormEmbeddingError,
    _ensure_bgr_u8,
    embed_batch,
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
    """CPU-only InferenceSession with pinned single-thread + reduced log noise.

    Thread counts fixed to 1 for reproducible parity/determinism builds (BR-05).
    """
    opts = ort.SessionOptions()
    opts.log_severity_level = 3  # ERROR
    opts.inter_op_num_threads = 1
    opts.intra_op_num_threads = 1
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
    """Decode one YuNet FPN level into pre-NMS detections (vectorized numpy).

    Score: ``sqrt(min(cls,1) * min(obj,1))`` — OpenCV FaceDetectorYN upper-only
    ``MIN(x, 1.f)`` (no lower clamp; BR-06). Bbox: center/size prior decode with
    exp on w/h; landmarks offset by grid cell. Survivors only are decoded after
    a score mask (no per-anchor Python loop; BR-03 / REF-05 behavior-preserving).
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

    # OpenCV FaceDetectorYN: upper-only MIN(x, 1.f) — no lower clamp (BR-06).
    cls_c = np.minimum(cls_v, 1.0)
    obj_c = np.minimum(obj_v, 1.0)
    # Negative product → NaN score → fails threshold (document in modelless tests).
    with np.errstate(invalid="ignore"):
        scores = np.sqrt(cls_c * obj_c)
    keep = np.flatnonzero(scores >= score_threshold)
    if keep.size == 0:
        return []

    rs = keep // cols
    cs = keep % cols
    bb = bbox_v[keep]
    kp = kps_v[keep]
    sc = scores[keep]

    cs_f = cs.astype(np.float32)
    rs_f = rs.astype(np.float32)
    cx = (cs_f + bb[:, 0]) * stride
    cy = (rs_f + bb[:, 1]) * stride
    w = np.exp(bb[:, 2]) * float(stride)
    h = np.exp(bb[:, 3]) * float(stride)
    x1 = cx - w * 0.5
    y1 = cy - h * 0.5

    lm = kp.reshape(-1, 5, 2).astype(np.float32, copy=True)
    lm[:, :, 0] = (lm[:, :, 0] + cs_f[:, None]) * float(stride)
    lm[:, :, 1] = (lm[:, :, 1] + rs_f[:, None]) * float(stride)

    out: list[RawDetection] = []
    for i in range(int(keep.size)):
        out.append(
            RawDetection(
                bbox=np.array(
                    [float(x1[i]), float(y1[i]), float(w[i]), float(h[i])],
                    dtype=np.float32,
                ),
                landmarks=lm[i],
                score=float(sc[i]),
            )
        )
    return out


def _box_iou_xywh_int(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """IoU of integer xywh boxes (OpenCV Rect2i / FaceDetectorYN NMS convention)."""
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
    """Greedy NMS with FaceDetectorYN postProcess semantics (int xywh IoU, score >= thr).

    Not pure ``cv2.dnn.NMSBoxes`` float-IoU / strict-``>`` score-gate parity —
    matches the int-cast path FaceDetectorYN uses (BR-04). Float boxes are
    retained on keep. When ≤1 candidate survives the score gate, NMS is a no-op.
    """
    if not detections:
        return []

    # Score gate again (FaceDetectorYN NMS also filters by score_threshold).
    candidates = [d for d in detections if d.score >= score_threshold]
    if len(candidates) <= 1:
        return candidates

    # Sort by score descending.
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

    ``initial_input_size`` is accepted for kwargs parity with
    ``OpenCVYuNetDetector`` (BR-07). ORT sets input size per image via padding;
    the value is not used to configure a native detector.
    """

    def __init__(
        self,
        *,
        model_name: str = "yunet",
        models_dir: Path | None = None,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        nms_threshold: float = DEFAULT_NMS_THRESHOLD,
        top_k: int = DEFAULT_TOP_K,
        initial_input_size: tuple[int, int] = DEFAULT_INPUT_SIZE,
    ) -> None:
        model_path = load_verified_model(model_name, models_dir=models_dir)
        self._model_name = model_name
        self._model_path = model_path
        self._score_threshold = float(score_threshold)
        self._nms_threshold = float(nms_threshold)
        self._top_k = int(top_k)
        # Accepted for DI/factory kwargs parity; per-image pad resets size (BR-07).
        self._initial_input_size = (int(initial_input_size[0]), int(initial_input_size[1]))
        self._session = _ort_session(model_path)
        self._input_name = self._session.get_inputs()[0].name
        # Cache output names once (BR-03) — do not re-fetch inside detect loop.
        self._output_names: tuple[str, ...] = tuple(o.name for o in self._session.get_outputs())
        out_names = set(self._output_names)
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
            outputs = {name: arr for name, arr in zip(self._output_names, raw_outs)}
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
    Validation/normalization lives in ``_common.embed_batch`` (shared with OpenCV).
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
        return embed_batch(
            crops,
            feature_fn=self._feature,
            embedding_dim=self.embedding_dim,
        )


__all__ = [
    "OrtSFaceEmbedder",
    "OrtYuNetDetector",
    "decode_yunet_level",
    "decode_yunet_outputs",
    "nms_yunet",
]
