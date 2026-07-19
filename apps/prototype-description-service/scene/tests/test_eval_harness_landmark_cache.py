"""FIR-5 S4: landmark_cache — pinned provenance, keying, no live detector at gen time.

TEST-04: injectable detector (no real YuNet weights required).
PROV-01: model_id + weights sha256 frozen in cache artifact.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest

from recognition.infrastructure.face_pipeline._common import RawDetection
from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST
from scripts.eval_harness.landmark_cache import (
    LANDMARK_CACHE_MODEL_ID,
    LANDMARK_CACHE_WEIGHTS_SHA256,
    CachedLandmark,
    LandmarkCache,
    LandmarkCacheProvenance,
    build_landmark_cache,
)
from scripts.eval_harness.synthetic_occlusion import (
    apply_occlusion,
    generate_twin_specs,
    render_twin,
)


class FakeDetector:
    """Injectable detector returning scripted RawDetections (no weights)."""

    def __init__(self, per_image: list[list[RawDetection]] | None = None) -> None:
        self.per_image = per_image or []
        self.calls: list[int] = []

    def detect(self, images: Sequence[np.ndarray]) -> list[list[RawDetection]]:
        self.calls.append(len(images))
        out: list[list[RawDetection]] = []
        for i, _img in enumerate(images):
            if i < len(self.per_image):
                out.append(self.per_image[i])
            else:
                out.append([])
        return out


class SpyDetector:
    """Records detect() calls; used to assert generation never invokes a live leg."""

    def __init__(self) -> None:
        self.detect_calls = 0

    def detect(self, images: Sequence[np.ndarray]) -> list[list[RawDetection]]:
        self.detect_calls += 1
        return [[] for _ in images]


def _raw(
    bbox: list[float],
    landmarks: list[list[float]],
    score: float = 0.95,
) -> RawDetection:
    return RawDetection(
        bbox=np.asarray(bbox, dtype=np.float32),
        landmarks=np.asarray(landmarks, dtype=np.float32),
        score=score,
    )


def _gt(x: float, y: float, w: float, h: float, name: str | None) -> dict:
    return {"x": x, "y": y, "w": w, "h": h, "name": name, "source": "iptc"}


def _frontal_landmarks(cx: float, cy: float, scale: float = 20.0) -> list[list[float]]:
    """YuNet order around centre (cx, cy)."""
    return [
        [cx - scale * 0.35, cy - scale * 0.15],  # right eye
        [cx + scale * 0.35, cy - scale * 0.15],  # left eye
        [cx, cy + scale * 0.05],  # nose
        [cx - scale * 0.30, cy + scale * 0.40],  # right mouth
        [cx + scale * 0.30, cy + scale * 0.40],  # left mouth
    ]


def test_pinned_model_id_and_sha256_in_cache_provenance():
    """PROV-01: cache provenance records model_id=yunet + MODEL_MANIFEST sha256."""
    assert LANDMARK_CACHE_MODEL_ID == "yunet"
    assert LANDMARK_CACHE_WEIGHTS_SHA256 == MODEL_MANIFEST["yunet"].sha256
    assert len(LANDMARK_CACHE_WEIGHTS_SHA256) == 64

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    # GT covers centre 50×50 in pixels → centre (0.5,0.5), size (0.5,0.5).
    gt = [_gt(0.5, 0.5, 0.5, 0.5, "Alice")]
    det = FakeDetector(
        [
            [
                _raw(
                    [25.0, 25.0, 50.0, 50.0],
                    _frontal_landmarks(50.0, 50.0),
                )
            ]
        ]
    )
    cache = build_landmark_cache(
        images_by_media={1: img},
        gt_by_media={1: gt},
        detector=det,
    )
    assert cache.provenance.model_id == "yunet"
    assert cache.provenance.weights_sha256 == MODEL_MANIFEST["yunet"].sha256
    assert cache.provenance.to_dict() == {
        "model_id": "yunet",
        "weights_sha256": MODEL_MANIFEST["yunet"].sha256,
    }


def test_cache_keyed_by_media_id_and_box_index():
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    # Two named GT boxes side by side on a 200×100 image.
    # Left: centre (0.25, 0.5), size 0.4×0.6 → px [10, 20, 80, 60]
    # Right: centre (0.75, 0.5), size 0.4×0.6 → px [110, 20, 80, 60]
    gt = [
        _gt(0.25, 0.5, 0.4, 0.6, "Alice"),
        _gt(0.75, 0.5, 0.4, 0.6, "Bob"),
    ]
    dets = [
        _raw([10.0, 20.0, 80.0, 60.0], _frontal_landmarks(50.0, 50.0, 15.0)),
        _raw([110.0, 20.0, 80.0, 60.0], _frontal_landmarks(150.0, 50.0, 15.0)),
    ]
    cache = build_landmark_cache(
        images_by_media={7: img},
        gt_by_media={7: gt},
        detector=FakeDetector([dets]),
    )
    assert len(cache.entries) == 2
    a = cache.get(7, 0)
    b = cache.get(7, 1)
    assert a is not None and a.name == "Alice" and a.box_index == 0
    assert b is not None and b.name == "Bob" and b.box_index == 1
    assert (7, 0) in cache.key_map()
    assert (7, 1) in cache.key_map()
    assert cache.get(7, 99) is None
    assert cache.get(99, 0) is None


def test_stranger_gt_not_cached():
    """Named roster faces only — stranger matches excluded from twin universe."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    gt = [_gt(0.5, 0.5, 0.5, 0.5, None)]
    det = FakeDetector(
        [[_raw([25.0, 25.0, 50.0, 50.0], _frontal_landmarks(50.0, 50.0))]]
    )
    cache = build_landmark_cache(
        images_by_media={1: img},
        gt_by_media={1: gt},
        detector=det,
    )
    assert cache.entries == ()
    assert cache.named_roster_entries() == ()


def test_cache_roundtrip_json(tmp_path):
    entry = CachedLandmark(
        media_id=3,
        box_index=1,
        name="Carol",
        landmarks_px=tuple((float(i), float(i + 1)) for i in range(5)),
        bbox_px=(1.0, 2.0, 3.0, 4.0),
        det_score=0.91,
    )
    cache = LandmarkCache(
        provenance=LandmarkCacheProvenance.pinned_yunet(),
        entries=(entry,),
    )
    path = tmp_path / "landmarks.json"
    cache.save(path)
    loaded = LandmarkCache.load(path)
    assert loaded.provenance.model_id == "yunet"
    assert loaded.provenance.weights_sha256 == MODEL_MANIFEST["yunet"].sha256
    assert loaded.get(3, 1) is not None
    assert loaded.get(3, 1).name == "Carol"


def test_no_live_detector_call_during_synthetic_generation():
    """Firewall: spy detector detect() must NOT run while occluders are generated."""
    img = np.full((120, 120, 3), 180, dtype=np.uint8)
    gt = [_gt(0.5, 0.5, 0.5, 0.5, "Alice")]
    lm = _frontal_landmarks(60.0, 60.0, 18.0)
    fake = FakeDetector([[_raw([30.0, 30.0, 60.0, 60.0], lm)]])
    cache = build_landmark_cache(
        images_by_media={1: img},
        gt_by_media={1: gt},
        detector=fake,
    )
    assert len(fake.calls) == 1  # offline pass only
    assert len(cache.entries) == 1

    spy = SpyDetector()
    # Generation path uses cache landmarks only — never spy.detect.
    specs = generate_twin_specs(cache, kinds=("masked",), seed=42)
    assert len(specs) == 1
    occluded = render_twin(img, specs[0])
    assert occluded.shape == img.shape
    # Direct apply also must not need a detector.
    _ = apply_occlusion(img, cache.entries[0].landmarks_px, "sunglasses", seed=7)
    assert spy.detect_calls == 0


def test_injectable_detector_used_when_provided():
    """TEST-04: passed detector is invoked; default path not required."""
    img = np.zeros((80, 80, 3), dtype=np.uint8)
    gt = [_gt(0.5, 0.5, 0.6, 0.6, "Dee")]
    det = FakeDetector(
        [[_raw([16.0, 16.0, 48.0, 48.0], _frontal_landmarks(40.0, 40.0, 12.0))]]
    )
    cache = build_landmark_cache(
        images_by_media={2: img},
        gt_by_media={2: gt},
        detector=det,
    )
    assert det.calls == [1]
    assert len(cache.entries) == 1
    assert cache.entries[0].name == "Dee"


def test_real_yunet_optional_skip_when_models_absent():
    """Mirror FIR-3 skipif: real weights absent must not fail the suite."""
    from recognition.tests.unit.face_pipeline_support import MODELS_PRESENT, MODELS_SKIP

    if not MODELS_PRESENT:
        pytest.skip(MODELS_SKIP)
    # Models present: construct real detector and run a trivial empty-GT pass.
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    det = OrtYuNetDetector()
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    cache = build_landmark_cache(
        images_by_media={1: img},
        gt_by_media={1: []},
        detector=det,
    )
    assert cache.provenance.model_id == "yunet"
    assert cache.entries == ()
