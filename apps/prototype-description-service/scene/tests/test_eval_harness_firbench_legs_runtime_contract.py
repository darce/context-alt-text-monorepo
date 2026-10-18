"""S2 runtime regressions: actual producers with fake apps, no model weights."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.eval_harness import firbench_legs as legs
from scripts.eval_harness.firbench_contract import (
    Arm,
    CrossSpaceComparisonError,
    LegId,
    LegKind,
    RuntimeMismatchError,
    SearchStage,
)


def _leg(**kwargs):
    return legs.BuffaloLeg(weights_sha256="a" * 64, opencv_version="5.0.0", ort_version="1.28.0", **kwargs)


@pytest.fixture
def buffalo_producer(monkeypatch):
    """Execute the actual guarded producer, replacing only its weight-loading builder."""
    import scripts.eval_harness as package

    name = "scripts.eval_harness.buffalo_bench"
    spec = importlib.util.spec_from_file_location(name, Path(legs.__file__).with_name("buffalo_bench.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setenv("ACX_EVAL_BENCH", "1")
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(package, "buffalo_bench", module, raising=False)
    spec.loader.exec_module(module)
    apps = []

    def build():
        class FakeApp:
            def __init__(self):
                self.images = []

            def get(self, image):
                self.images.append(image)
                return [
                    SimpleNamespace(
                        bbox=np.array([1, 2, 11, 14]),
                        kps=np.arange(10).reshape(5, 2),
                        det_score=0.9,
                        embedding=np.ones(512),
                    )
                ]

        app = FakeApp()
        apps.append(app)
        return app

    monkeypatch.setattr(module, "_build_face_analysis", build)
    return module, apps


def test_default_buffalo_lazily_reuses_one_app_per_leg_with_actual_producer(buffalo_producer):
    _, apps = buffalo_producer
    first, second = _leg(), _leg()
    images = [np.full((16, 16, 3), value, dtype=np.uint8) for value in (0, 1, 2)]
    assert apps == [], "constructing a leg must not load weights"
    for image in images:
        (observation,) = first.observe(image)
        assert observation.stage == SearchStage.embedded
        assert observation.detection.bbox_px == (1.0, 2.0, 10.0, 12.0)
        assert observation.embedding.shape == (512,)
        assert np.linalg.norm(observation.embedding) == pytest.approx(1.0)
    assert len(apps) == 1, "the actual producer builds an app on every call unless supplied one"
    assert all(actual is expected for actual, expected in zip(apps[0].images, images, strict=True))
    second.observe(images[0])
    first.observe(images[1])
    assert len(apps) == 2, "apps must belong to individual legs, never a process-global singleton"
    assert apps[0].images[-1] is images[1]
    assert apps[1].images == [images[0]]


def test_default_buffalo_forwards_declared_dimension_to_producer(buffalo_producer):
    # The actual producer validates the 512D fake output before the adapter sees it.
    with pytest.raises(ValueError, match="buffalo embedding dim 512 != 128"):
        _leg(embedding_dim=128).observe(np.zeros((16, 16, 3), dtype=np.uint8))


def test_injected_process_stays_image_only_without_bench_import(monkeypatch):
    def forbidden_import(*args, **kwargs):
        raise AssertionError("injected process must not import buffalo_bench")

    import scripts.eval_harness as package

    monkeypatch.delattr(package, "buffalo_bench", raising=False)
    monkeypatch.setitem(sys.modules, "scripts.eval_harness.buffalo_bench", None)
    monkeypatch.setattr(legs, "_default_buffalo_process", forbidden_import)
    seen = []

    def process(image):
        seen.append(image)
        return [
            {"bbox_px": [1, 2, 3, 4], "landmarks_px": np.zeros((5, 2)), "det_score": 0.8},
            {
                "bbox_px": [5, 6, 7, 8],
                "landmarks_px": np.zeros((5, 2)),
                "det_score": 0.9,
                "embedding": np.ones(3),
            },
        ]

    leg = _leg(process=process, embedding_dim=3)
    for value in (0, 1):
        image = np.full((16, 16, 3), value, dtype=np.uint8)
        detected, embedded = leg.observe(image)
        assert detected.stage == SearchStage.detected
        assert detected.embedding is None
        assert embedded.stage == SearchStage.embedded
        np.testing.assert_array_equal(embedded.embedding, np.ones(3))
        assert seen[-1] is image
    assert len(seen) == 2


def test_fresh_import_and_leg_construction_are_lazy_and_default_observe_refuses_without_eval():
    script = textwrap.dedent(
        """
        import importlib.abc
        import sys
        from pathlib import Path

        class BlockBench(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == 'scripts.eval_harness.buffalo_bench' or fullname.split('.')[0] == 'insightface':
                    raise AssertionError('eager optional dependency import: ' + fullname)

        def no_weights(event, args):
            if event == 'open' and isinstance(args[0], (str, bytes)):
                path = str(args[0])
                if path.endswith(('.onnx', '.npz', '.pth', '.pt')):
                    raise AssertionError('unexpected weight read: ' + path)

        sys.addaudithook(no_weights)
        blocker = BlockBench()
        sys.meta_path.insert(0, blocker)
        import numpy as np
        from scripts.eval_harness.firbench_legs import BuffaloLeg
        leg = BuffaloLeg(weights_sha256='a'*64, opencv_version='5.0.0', ort_version='1.28.0')
        assert 'scripts.eval_harness.buffalo_bench' not in sys.modules
        sys.meta_path.remove(blocker)
        try:
            leg.observe(np.zeros((16, 16, 3), dtype=np.uint8))
        except RuntimeError as exc:
            assert type(exc).__name__ == 'BuffaloBenchGuardError'
            assert 'ACX_EVAL_BENCH=1 is required' in str(exc)
        else:
            raise AssertionError('default observe bypassed eval-only refusal')
        assert not any(name == 'insightface' or name.startswith('insightface.') for name in sys.modules)
        """
    )
    env = dict(os.environ)
    env.pop("ACX_EVAL_BENCH", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(legs.__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("kind", [LegKind.sface, LegKind.auraface])
@pytest.mark.parametrize("bumped", [{"opencv_version": "5.0.1"}, {"onnxruntime_version": "1.29.0"}])
@pytest.mark.parametrize("reverse", [False, True])
def test_runtime_mismatch_precedes_changed_actual_manifest_fingerprint(monkeypatch, kind, bumped, reverse):
    from recognition.infrastructure.embeddings import face_pipeline_adapter as adapter
    from recognition.infrastructure.face_pipeline import provenance

    base = provenance.NumericRuntimeFingerprint(
        opencv_version="5.0.0",
        opencv_major=5,
        onnxruntime_version="1.28.0",
        numpy_version="2.5.1",
        scipy_version="1.18.0",
        pillow_version="12.3.0",
        hdbscan_version="0.8.44",
        pgvector_version="0.5.0",
    )
    factory = getattr(adapter, f"{kind.value}_embedding_model_manifest")

    def leg_id(runtime):
        monkeypatch.setattr(provenance, "numeric_runtime_fingerprint", lambda: runtime)
        manifest = factory()
        leg = legs.build_face_pipeline_leg(
            kind,
            manifest=manifest,
            detector=object(),
            aligner=object(),
            embedder=SimpleNamespace(embedding_dim=manifest.dimensions),
            weights_sha256="a" * 64,
            preprocessing=None,
            opencv_version=runtime.opencv_version,
            ort_version=runtime.onnxruntime_version,
        )
        return leg.leg_id(Arm.native)

    a, b = leg_id(base), leg_id(replace(base, **bumped))
    assert a.space_fingerprint != b.space_fingerprint, "actual manifest names fold in runtime tokens"
    with pytest.raises(RuntimeMismatchError, match="OpenCV/ORT versions differ"):
        legs.compare_guard(b, a) if reverse else legs.compare_guard(a, b)


@pytest.mark.parametrize(
    ("kind", "opencv", "ort"),
    [(LegKind.sface, "5.0.0", "1.28.0"), (LegKind.auraface, "5.0.1", "1.29.0")],
)
def test_other_cross_space_comparisons_remain_refused(kind, opencv, ort):
    a = LegId(LegKind.sface, Arm.native, "a" * 64, "5.0.0", "1.28.0")
    b = LegId(kind, Arm.native, "b" * 64, opencv, ort)
    with pytest.raises(CrossSpaceComparisonError):
        legs.compare_guard(a, b)
    with pytest.raises(CrossSpaceComparisonError):
        legs.compare_guard(b, a)


def test_same_contract_comparison_still_succeeds():
    leg_id = _leg(process=lambda image: []).leg_id(Arm.native)
    legs.compare_guard(leg_id, leg_id)
