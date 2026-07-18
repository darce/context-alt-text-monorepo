"""FIR-3 postmerge pure contracts (FIR3-BR-02/03/04/05) — modelless, no real models.

cv2/onnxruntime-free coverage for:
- YuNet score clamp [0,1] on both cls and obj (decode path lives in ort_adapters)
- SFace BGR→RGB NCHW preprocess helper
- shared ``embed_batch`` gates (injected feature_fn)
- fail-closed consumption of manifest normalization/metric (not decorative)

Heuristics: EMB-01/03/05, PROV-01/04, TEST-06/08, REF-19, TEST-01, rg-015.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from recognition.infrastructure.face_pipeline._common import (
    SFACE_CROP_SIZE,
    SFACE_EMBEDDING_DIM,
    FacePipelineInputError,
    ZeroNormEmbeddingError,
    embed_batch,
    resolve_sface_embedding_dim,
)
from recognition.infrastructure.face_pipeline.ort_adapters import (
    _bgr_to_sface_blob,
    decode_yunet_level,
)
from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST

# ---------------------------------------------------------------------------
# FIR3-BR-02 — lower+upper clamp of cls/obj to [0,1] before sqrt
# ---------------------------------------------------------------------------


def test_decode_both_negative_cls_obj_no_false_detection() -> None:
    """cls<0 and obj<0 must not yield a positive product / false detection.

    Current upper-only ``np.minimum(x, 1)`` keeps negatives, so
    (-0.5)*(-0.5)=0.25 → score=0.5. Contract: clamp both into [0,1] first so
    the score is 0 and the anchor is dropped even at a permissive threshold.
    """
    stride = 16
    pad_w = pad_h = 16
    cls = np.array([-0.5], dtype=np.float32)
    obj = np.array([-0.5], dtype=np.float32)
    bbox = np.zeros((1, 4), dtype=np.float32)
    kps = np.zeros((1, 10), dtype=np.float32)
    dets = decode_yunet_level(
        cls,
        obj,
        bbox,
        kps,
        stride=stride,
        pad_w=pad_w,
        pad_h=pad_h,
        score_threshold=0.01,
    )
    assert dets == [], (
        f"expected no detection for both-negative cls/obj; got scores={[d.score for d in dets]} "
        "(upper-only clamp produces sqrt(0.25)=0.5 false hit — clamp to [0,1] required)"
    )


def test_decode_mixed_sign_logits_no_detection_at_permissive_threshold() -> None:
    """Negative cls with positive obj must not pass a positive score gate."""
    stride = 16
    pad_w = pad_h = 16
    cls = np.array([-0.5], dtype=np.float32)
    obj = np.array([1.0], dtype=np.float32)
    bbox = np.zeros((1, 4), dtype=np.float32)
    kps = np.zeros((1, 10), dtype=np.float32)
    dets = decode_yunet_level(
        cls,
        obj,
        bbox,
        kps,
        stride=stride,
        pad_w=pad_w,
        pad_h=pad_h,
        score_threshold=0.01,
    )
    assert dets == []


def test_decode_clamps_above_one_still_unit_score() -> None:
    """Upper bound of the [0,1] clamp still caps scores at 1.0."""
    stride = 32
    pad_w = pad_h = 32
    cls = np.array([2.0], dtype=np.float32)
    obj = np.array([2.0], dtype=np.float32)
    bbox = np.zeros((1, 4), dtype=np.float32)
    kps = np.zeros((1, 10), dtype=np.float32)
    dets = decode_yunet_level(
        cls,
        obj,
        bbox,
        kps,
        stride=stride,
        pad_w=pad_w,
        pad_h=pad_h,
        score_threshold=0.5,
    )
    assert len(dets) == 1
    assert dets[0].score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# FIR3-BR-03 — pure SFace preprocess (no model fixture)
# ---------------------------------------------------------------------------


def test_bgr_to_sface_blob_channel_distinct_rgb_nchw_scale1() -> None:
    """Channel-distinct uint8 BGR → RGB NCHW float32, scale=1.0, mean=0, contiguous."""
    crop = np.zeros((SFACE_CROP_SIZE, SFACE_CROP_SIZE, 3), dtype=np.uint8)
    crop[..., 0] = 10  # B
    crop[..., 1] = 40  # G
    crop[..., 2] = 70  # R

    blob = _bgr_to_sface_blob(crop)

    assert blob.shape == (1, 3, SFACE_CROP_SIZE, SFACE_CROP_SIZE)
    assert blob.dtype == np.float32
    assert blob.flags["C_CONTIGUOUS"]
    # RGB order after swapRB: ch0=R, ch1=G, ch2=B
    assert float(blob[0, 0, 0, 0]) == 70.0
    assert float(blob[0, 1, 0, 0]) == 40.0
    assert float(blob[0, 2, 0, 0]) == 10.0
    # scale exactly 1.0 (raw 0–255 float), no mean shift
    assert float(blob[0, 0].mean()) == 70.0
    assert float(blob[0, 1].mean()) == 40.0
    assert float(blob[0, 2].mean()) == 10.0
    assert float(blob.max()) == 70.0
    assert float(blob.min()) == 10.0
    # not /255
    assert float(blob.max()) > 1.5


# ---------------------------------------------------------------------------
# FIR3-BR-04 — direct embed_batch characterization (injected feature_fn)
# ---------------------------------------------------------------------------


def _unit_feature(crop: np.ndarray) -> np.ndarray:
    """Deterministic non-zero feature from crop sum (dim = SFACE_EMBEDDING_DIM)."""
    seed = float(np.mean(crop)) + 1.0
    vec = np.arange(SFACE_EMBEDDING_DIM, dtype=np.float32) + seed
    return vec


def test_embed_batch_empty_shape() -> None:
    out = embed_batch([], feature_fn=_unit_feature, embedding_dim=SFACE_EMBEDDING_DIM)
    assert out.shape == (0, SFACE_EMBEDDING_DIM)
    assert out.dtype == np.float32


def test_embed_batch_112_gate() -> None:
    bad = np.zeros((64, 64, 3), dtype=np.uint8)
    with pytest.raises(FacePipelineInputError, match="expected shape"):
        embed_batch([bad], feature_fn=_unit_feature, embedding_dim=SFACE_EMBEDDING_DIM)


def test_embed_batch_embedding_dim_gate() -> None:
    crop = np.full((SFACE_CROP_SIZE, SFACE_CROP_SIZE, 3), 32, dtype=np.uint8)

    def _wrong_dim(_crop: np.ndarray) -> np.ndarray:
        return np.ones((SFACE_EMBEDDING_DIM + 1,), dtype=np.float32)

    with pytest.raises(FacePipelineInputError, match="embedding dim"):
        embed_batch([crop], feature_fn=_wrong_dim, embedding_dim=SFACE_EMBEDDING_DIM)


def test_embed_batch_zero_norm_raises() -> None:
    crop = np.full((SFACE_CROP_SIZE, SFACE_CROP_SIZE, 3), 32, dtype=np.uint8)

    def _zero(_crop: np.ndarray) -> np.ndarray:
        return np.zeros((SFACE_EMBEDDING_DIM,), dtype=np.float32)

    with pytest.raises(ZeroNormEmbeddingError, match="zero"):
        embed_batch([crop], feature_fn=_zero, embedding_dim=SFACE_EMBEDDING_DIM)


def test_embed_batch_nonfinite_norm_raises() -> None:
    crop = np.full((SFACE_CROP_SIZE, SFACE_CROP_SIZE, 3), 32, dtype=np.uint8)

    def _nan(_crop: np.ndarray) -> np.ndarray:
        return np.full((SFACE_EMBEDDING_DIM,), np.nan, dtype=np.float32)

    with pytest.raises(ZeroNormEmbeddingError, match="non-finite|zero"):
        embed_batch([crop], feature_fn=_nan, embedding_dim=SFACE_EMBEDDING_DIM)


def test_embed_batch_float01_trap() -> None:
    trap = np.full((SFACE_CROP_SIZE, SFACE_CROP_SIZE, 3), 0.5, dtype=np.float32)
    with pytest.raises(FacePipelineInputError, match=r"\[0,1\]-float"):
        embed_batch([trap], feature_fn=_unit_feature, embedding_dim=SFACE_EMBEDDING_DIM)


def test_embed_batch_l2_output_and_injected_feature_fn() -> None:
    crop = np.full((SFACE_CROP_SIZE, SFACE_CROP_SIZE, 3), 64, dtype=np.uint8)
    seen: list[tuple[int, ...]] = []

    def _feature(c: np.ndarray) -> np.ndarray:
        seen.append(tuple(c.shape))
        return _unit_feature(c)

    out = embed_batch([crop, crop], feature_fn=_feature, embedding_dim=SFACE_EMBEDDING_DIM)
    assert out.shape == (2, SFACE_EMBEDDING_DIM)
    assert len(seen) == 2
    for row in out:
        assert float(np.linalg.norm(row)) == pytest.approx(1.0, abs=1e-5)
    np.testing.assert_allclose(out[0], out[1], atol=1e-6)


# ---------------------------------------------------------------------------
# FIR3-BR-05 — manifest normalization/metric fail-closed (not decorative)
# ---------------------------------------------------------------------------


def test_resolve_sface_rejects_unsupported_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shared embedding contract path must reject unsupported normalization before embed.

    Dim-only resolvers that ignore ``normalization`` fail this assertion (RED until
    the resolver consumes the field fail-closed).
    """
    sface = MODEL_MANIFEST["sface"]
    monkeypatch.setitem(
        MODEL_MANIFEST,
        "sface",
        replace(sface, normalization="none"),
    )
    with pytest.raises(ValueError, match=r"normalization|unsupported|l2"):
        resolve_sface_embedding_dim()


def test_resolve_sface_rejects_unsupported_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shared embedding contract path must reject unsupported metric before embed."""
    sface = MODEL_MANIFEST["sface"]
    monkeypatch.setitem(
        MODEL_MANIFEST,
        "sface",
        replace(sface, metric="euclidean"),
    )
    with pytest.raises(ValueError, match=r"metric|unsupported|cosine"):
        resolve_sface_embedding_dim()


def test_resolve_sface_still_accepts_canonical_contract() -> None:
    """Canonical l2/cosine/128 contract remains resolvable."""
    assert MODEL_MANIFEST["sface"].normalization == "l2"
    assert MODEL_MANIFEST["sface"].metric == "cosine"
    assert resolve_sface_embedding_dim() == 128
    assert resolve_sface_embedding_dim() == SFACE_EMBEDDING_DIM
