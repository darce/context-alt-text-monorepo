"""FIR scale-retry contract: detector-level behaviour through the real runtime.

Proposed opt-in detector retry, knob ``RECOGNITION_FACE_DETECTION_RETRY_MAX_SIDE``
(default 0 = OFF). When enabled and the original max side is > S (S=640), one
extra YuNet pass runs on a 640-max-side resize; boxes and landmarks are projected
back to original pixels with separate sx/sy from the rounded resize; score and
threshold are unchanged; duplicates are suppressed by NMS IoU.

Model-free: the real ``_load_face_pipeline_runtime`` composition is built with
fake ORT sessions injected at the ``ort_adapters`` seam (same seam as
test_face_pipeline_pure_contracts.py). No ONNX weights, no native ORT.

Controls (knob off, no-op at <=640, score gate, NMS) pass on base. Causal RED
tests name the missing retry behaviour and must fail on assertions, never on
ImportError/AttributeError/fixture setup.

Heuristics: [TEST-15][RES-02]
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from db.settings import get_database_settings
from recognition.config import get_settings
from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
from recognition.infrastructure.face_pipeline import ort_adapters
from recognition.infrastructure.face_pipeline._common import RawDetection
from recognition.infrastructure.face_pipeline.model_space import ModelSpace
from recognition.tests.unit.face_pipeline_support import SFACE_EMBEDDING_DIM

KNOB = "RECOGNITION_FACE_DETECTION_RETRY_MAX_SIDE"
RETRY_MAX_SIDE = 640
YUNET_STRIDE = 8


@dataclass(frozen=True)
class Face:
    """One face the fake YuNet emits, in the coordinates of the image it receives."""

    x: float
    y: float
    w: float
    h: float
    score: float
    landmarks: tuple[tuple[float, float], ...]


class _Named:
    def __init__(self, name: str) -> None:
        self.name = name


def _encode_yunet(faces: list[Face], pad_h: int, pad_w: int) -> list[np.ndarray]:
    """Encode faces as YuNet head tensors that ``decode_yunet_outputs`` inverts exactly."""
    arrays: dict[str, np.ndarray] = {}
    for stride in ort_adapters._YUNET_STRIDES:
        rows, cols = pad_h // stride, pad_w // stride
        n = rows * cols
        cls = np.zeros(n, dtype=np.float32)
        obj = np.zeros(n, dtype=np.float32)
        bbox = np.zeros((n, 4), dtype=np.float32)
        kps = np.zeros((n, 10), dtype=np.float32)
        if stride == YUNET_STRIDE:
            for face in faces:
                cx, cy = face.x + face.w / 2.0, face.y + face.h / 2.0
                c, r = int(cx // stride), int(cy // stride)
                i = r * cols + c
                cls[i] = face.score * face.score  # sqrt(cls * obj) == score with obj == 1
                obj[i] = 1.0
                bbox[i] = (cx / stride - c, cy / stride - r, math.log(face.w / stride), math.log(face.h / stride))
                kps[i] = np.array([(x / stride - c, y / stride - r) for x, y in face.landmarks], dtype=np.float32).reshape(-1)
        arrays[f"cls_{stride}"] = cls
        arrays[f"obj_{stride}"] = obj
        arrays[f"bbox_{stride}"] = bbox
        arrays[f"kps_{stride}"] = kps
    return [arrays[name] for name in ort_adapters._YUNET_OUTPUT_NAMES]


class FakeYuNetSession:
    """Fake YuNet ORT session; ``visible(pad_h, pad_w)`` decides what the model 'sees'."""

    def __init__(self, visible: Callable[[int, int], list[Face]]) -> None:
        self._visible = visible
        self.input_shapes: list[tuple[int, ...]] = []

    def get_inputs(self) -> list[_Named]:
        return [_Named("input")]

    def get_outputs(self) -> list[_Named]:
        return [_Named(name) for name in ort_adapters._YUNET_OUTPUT_NAMES]

    def run(self, _outputs: object, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        blob = feeds["input"]
        self.input_shapes.append(tuple(int(v) for v in blob.shape))
        _, _, pad_h, pad_w = blob.shape
        return _encode_yunet(self._visible(int(pad_h), int(pad_w)), int(pad_h), int(pad_w))


class FakeSFaceSession:
    def get_inputs(self) -> list[_Named]:
        return [_Named("input")]

    def run(self, _outputs: object, _feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        return [np.ones((SFACE_EMBEDDING_DIM,), dtype=np.float32)]


def _clear_settings() -> None:
    get_settings.cache_clear()
    get_database_settings.cache_clear()


@pytest.fixture(autouse=True)
def _modelless_face_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", str(SFACE_EMBEDDING_DIM))
    monkeypatch.setenv("PGVECTOR_DIM", str(SFACE_EMBEDDING_DIM))
    monkeypatch.delenv(KNOB, raising=False)
    _clear_settings()

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("NATIVE_ORT_FORBIDDEN: modelless retry contract must use fake sessions", pytrace=False)

    monkeypatch.setattr(ort_adapters.ort, "InferenceSession", forbidden)
    monkeypatch.setattr(
        ort_adapters,
        "load_verified_model",
        lambda name, models_dir=None: tmp_path / f"{name}.onnx",
    )
    yield
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    _clear_settings()


def build_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    visible: Callable[[int, int], list[Face]],
    *,
    knob: int | None,
    score_threshold: float = 0.9,
    nms_threshold: float = 0.3,
) -> tuple[fpa.FacePipelineRuntime, FakeYuNetSession]:
    yunet = FakeYuNetSession(visible)
    sface = FakeSFaceSession()
    monkeypatch.setattr(
        ort_adapters,
        "_ort_session",
        lambda model_source: yunet if Path(model_source).name == "yunet.onnx" else sface,
    )
    if knob is None:
        monkeypatch.delenv(KNOB, raising=False)
    else:
        monkeypatch.setenv(KNOB, str(knob))
    _clear_settings()
    runtime = fpa._load_face_pipeline_runtime(
        space=ModelSpace.FACE_PIPELINE,
        models_dir=tmp_path,
        embedder_models_dir=tmp_path,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=5000,
    )
    return runtime, yunet


def bgr_image(width: int, height: int) -> np.ndarray:
    return np.full((height, width, 3), 96, dtype=np.uint8)


def scale_face(face: Face, sx: float, sy: float, *, score: float | None = None) -> Face:
    """Express an original-pixel face in the pixels of an image resized by (sx, sy)."""
    return Face(
        x=face.x * sx,
        y=face.y * sy,
        w=face.w * sx,
        h=face.h * sy,
        score=face.score if score is None else score,
        landmarks=tuple((x * sx, y * sy) for x, y in face.landmarks),
    )


SMALL_LANDMARKS = ((360.0, 290.0), (440.0, 290.0), (400.0, 340.0), (370.0, 390.0), (430.0, 390.0))
SMALL = Face(320.0, 240.0, 160.0, 200.0, 0.95, SMALL_LANDMARKS)
SMALL_BOX = np.array([320.0, 240.0, 160.0, 200.0], dtype=np.float32)

BIG_LANDMARKS = ((120.0, 130.0), (260.0, 130.0), (190.0, 190.0), (140.0, 260.0), (240.0, 260.0))
BIG_FULL = Face(100.0, 100.0, 300.0, 300.0, 0.97, BIG_LANDMARKS)


def _small_visible_only_at_640(sx: float, sy: float, score: float = 0.95) -> Callable[[int, int], list[Face]]:
    scaled = scale_face(SMALL, sx, sy, score=score)

    def visible(pad_h: int, pad_w: int) -> list[Face]:
        return [] if max(pad_h, pad_w) > RETRY_MAX_SIDE else [scaled]

    return visible


def _raw(x: float, y: float, w: float, h: float, score: float) -> RawDetection:
    return RawDetection(
        bbox=np.array([x, y, w, h], dtype=np.float32),
        landmarks=np.zeros((5, 2), dtype=np.float32),
        score=score,
    )


# ---------------------------------------------------------------------------
# Causal RED: the retry pass recovers a face invisible at full resolution.
# ---------------------------------------------------------------------------


def test_small_face_visible_only_at_640_is_recovered_and_projected_to_original_pixels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sx = sy = 0.5  # 1280x960 -> 640x480 (exact)
    image = bgr_image(1280, 960)
    runtime, yunet = build_runtime(monkeypatch, tmp_path, _small_visible_only_at_640(sx, sy), knob=RETRY_MAX_SIDE)

    faces = runtime.detector.detect([image])[0]

    assert len(faces) == 1, "retry pass must recover a face visible only at max side 640 (base returns none)"
    np.testing.assert_allclose(faces[0].bbox, SMALL_BOX, atol=1.0 / sx)
    np.testing.assert_allclose(faces[0].landmarks, np.asarray(SMALL_LANDMARKS), atol=1.0 / sx)
    assert faces[0].score == pytest.approx(0.95, abs=1e-5), "retry must not alter the detector score"
    assert yunet.input_shapes == [(1, 3, 960, 1280), (1, 3, 480, 640)], "exactly one extra scaled pass"


def test_non_integer_resize_projects_with_separate_sx_sy_from_rounded_sizes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 1000x777 -> round(777*0.64)=497 rows; sx != sy and both are non-integer.
    new_w, new_h = round(1000 * 0.64), round(777 * 0.64)
    sx, sy = new_w / 1000.0, new_h / 777.0
    truth = Face(300.0, 200.0, 120.0, 150.0, 0.95, ((330.0, 230.0), (390.0, 230.0), (360.0, 280.0), (335.0, 320.0), (385.0, 320.0)))
    scaled = scale_face(truth, sx, sy)

    def visible(pad_h: int, pad_w: int) -> list[Face]:
        return [] if max(pad_h, pad_w) > RETRY_MAX_SIDE else [scaled]

    image = bgr_image(1000, 777)
    runtime, yunet = build_runtime(monkeypatch, tmp_path, visible, knob=RETRY_MAX_SIDE)

    faces = runtime.detector.detect([image])[0]

    assert len(faces) == 1, "retry pass must recover the non-integer-scale face"
    box = np.array([300.0, 200.0, 120.0, 150.0], dtype=np.float32)
    tol = np.array([1.0 / sx, 1.0 / sy, 1.0 / sx, 1.0 / sy])
    assert len(faces[0].bbox) == len(box) == len(tol) == 4
    for actual, expected, bound in zip(faces[0].bbox, box, tol, strict=True):
        np.testing.assert_allclose(actual, expected, atol=bound)
    landmarks = np.asarray(truth.landmarks)
    landmark_tol = np.array([1.0 / sx, 1.0 / sy])
    assert faces[0].landmarks.shape == landmarks.shape == (5, 2)
    assert len(faces[0].landmarks) == len(landmarks) == 5
    for actual_point, expected_point in zip(faces[0].landmarks, landmarks, strict=True):
        assert len(actual_point) == len(expected_point) == len(landmark_tol) == 2
        for actual, expected, bound in zip(actual_point, expected_point, landmark_tol, strict=True):
            np.testing.assert_allclose(actual, expected, atol=bound)
    assert yunet.input_shapes[-1] == (1, 3, 512, 640), "retry pass input is the rounded 640-max-side resize, padded"


# ---------------------------------------------------------------------------
# Controls: must pass on base (knob off or no retry need).
# ---------------------------------------------------------------------------


def test_max_side_at_or_below_640_runs_one_pass_without_resize_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    truth = Face(100.0, 80.0, 120.0, 140.0, 0.95, ((120.0, 100.0), (200.0, 100.0), (160.0, 140.0), (130.0, 180.0), (190.0, 180.0)))
    runtime, yunet = build_runtime(monkeypatch, tmp_path, lambda _h, _w: [truth], knob=RETRY_MAX_SIDE)

    faces = runtime.detector.detect([bgr_image(640, 480)])[0]

    assert yunet.input_shapes == [(1, 3, 480, 640)]
    assert len(faces) == 1
    np.testing.assert_allclose(faces[0].bbox, [100.0, 80.0, 120.0, 140.0], atol=1e-3)


def test_knob_off_leaves_large_image_pass_one_unchanged_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    visible = _small_visible_only_at_640(0.5, 0.5)
    runtime, yunet = build_runtime(monkeypatch, tmp_path, visible, knob=None)

    faces = runtime.detector.detect([bgr_image(1280, 960)])[0]

    assert faces == []
    assert yunet.input_shapes == [(1, 3, 960, 1280)], "knob off must not add an inner pass"


def test_large_image_with_full_resolution_face_is_identical_with_knob_on_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scaled_big = scale_face(BIG_FULL, 0.5, 0.5)

    def visible(pad_h: int, pad_w: int) -> list[Face]:
        return [BIG_FULL] if max(pad_h, pad_w) > RETRY_MAX_SIDE else [scaled_big]

    image = bgr_image(1280, 960)
    base_runtime, _ = build_runtime(monkeypatch, tmp_path, visible, knob=None)
    base = base_runtime.detector.detect([image])[0]
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    on_runtime, on_yunet = build_runtime(monkeypatch, tmp_path, visible, knob=RETRY_MAX_SIDE)

    faces = on_runtime.detector.detect([image])[0]

    assert len(base) == len(faces) == 1
    np.testing.assert_array_equal(faces[0].bbox, base[0].bbox)
    np.testing.assert_array_equal(faces[0].landmarks, base[0].landmarks)
    assert faces[0].score == base[0].score
    assert len(on_yunet.input_shapes) <= 2, "at most one extra scaled pass"


@pytest.mark.parametrize("threshold", [0.85, 0.9])
def test_scaled_face_below_threshold_is_dropped_never_lowered_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, threshold: float
) -> None:
    visible = _small_visible_only_at_640(0.5, 0.5, score=threshold - 0.02)
    runtime, _ = build_runtime(monkeypatch, tmp_path, visible, knob=RETRY_MAX_SIDE, score_threshold=threshold)

    assert runtime.detector.detect([bgr_image(1280, 960)])[0] == []


@pytest.mark.parametrize("threshold", [0.85, 0.9])
def test_scaled_face_above_threshold_is_kept_with_unchanged_score(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, threshold: float
) -> None:
    score = threshold + 0.03
    visible = _small_visible_only_at_640(0.5, 0.5, score=score)
    runtime, _ = build_runtime(monkeypatch, tmp_path, visible, knob=RETRY_MAX_SIDE, score_threshold=threshold)

    faces = runtime.detector.detect([bgr_image(1280, 960)])[0]

    assert len(faces) == 1, f"retry must keep a scaled face scoring {score} at threshold {threshold}"
    assert faces[0].score == pytest.approx(score, abs=1e-5)


# ---------------------------------------------------------------------------
# Causal RED: partial miss on a non-empty first pass.
# ---------------------------------------------------------------------------


def test_partial_miss_recovers_small_face_and_keeps_pass_one_rows_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    small_scaled = scale_face(SMALL, 0.5, 0.5)
    big_scaled = scale_face(BIG_FULL, 0.5, 0.5)

    def visible(pad_h: int, pad_w: int) -> list[Face]:
        if max(pad_h, pad_w) > RETRY_MAX_SIDE:
            return [BIG_FULL]
        return [big_scaled, small_scaled]

    image = bgr_image(1280, 960)
    base_runtime, _ = build_runtime(monkeypatch, tmp_path, lambda _h, _w: [BIG_FULL], knob=None)
    base = base_runtime.detector.detect([image])[0]
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    runtime, _ = build_runtime(monkeypatch, tmp_path, visible, knob=RETRY_MAX_SIDE)

    faces = runtime.detector.detect([image])[0]

    assert len(faces) == 2, "partial miss must add the 640-only face after non-empty pass 1 (base returns 1)"
    np.testing.assert_array_equal(faces[0].bbox, base[0].bbox)
    np.testing.assert_array_equal(faces[0].landmarks, base[0].landmarks)
    assert faces[0].score == base[0].score
    np.testing.assert_allclose(faces[1].bbox, SMALL_BOX, atol=2.0)


# ---------------------------------------------------------------------------
# NMS non-regression (modelless): closes the direct coverage gap for nms_yunet.
# ---------------------------------------------------------------------------


def test_nms_suppresses_overlap_above_threshold_control() -> None:
    strong = _raw(0.0, 0.0, 100.0, 100.0, 0.95)
    overlap = _raw(10.0, 0.0, 100.0, 100.0, 0.93)  # IoU = 9000/11000 ~ 0.82 > 0.3

    kept = ort_adapters.nms_yunet([strong, overlap], score_threshold=0.9, nms_threshold=0.3, top_k=5000)

    assert len(kept) == 1
    assert kept[0] is strong


def test_nms_keeps_overlap_below_threshold_control() -> None:
    strong = _raw(0.0, 0.0, 100.0, 100.0, 0.95)
    apart = _raw(80.0, 0.0, 100.0, 100.0, 0.93)  # IoU = 2000/18000 ~ 0.11 <= 0.3

    kept = ort_adapters.nms_yunet([strong, apart], score_threshold=0.9, nms_threshold=0.3, top_k=5000)

    assert len(kept) == 2
    assert kept[0] is strong
    assert kept[1] is apart
