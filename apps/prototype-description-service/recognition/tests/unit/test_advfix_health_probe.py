from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from recognition import config
from recognition.application import health as health_mod
from shared.health import HealthStatus


def _configure_insightface(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    models: dict[str, object],
    prepare_error: Exception | None = None,
) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    cache_root = tmp_path
    insightface_settings = SimpleNamespace(
        cache_dir=cache_root,
        device="cpu",
        providers=["CPUExecutionProvider"],
        det_size=(512, 512),
        det_thresh=0.4,
    )
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(insightface=insightface_settings),
    )

    class FakeFaceAnalysis:
        def __init__(self, *, name: str, root: str, providers: list[str]) -> None:
            calls["init"] = {"name": name, "root": root, "providers": providers}
            self.models = models

        def prepare(self, *, ctx_id: int, det_size: tuple[int, int], det_thresh: float) -> None:
            calls["prepare"] = {
                "ctx_id": ctx_id,
                "det_size": det_size,
                "det_thresh": det_thresh,
            }
            if prepare_error is not None:
                raise prepare_error

    insightface_module = ModuleType("insightface")
    app_module = ModuleType("insightface.app")
    app_module.FaceAnalysis = FakeFaceAnalysis  # type: ignore[attr-defined]
    insightface_module.app = app_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "insightface", insightface_module)
    monkeypatch.setitem(sys.modules, "insightface.app", app_module)
    return calls


def _bundle(tmp_path: Path) -> tuple[Path, Path]:
    cache_dir = tmp_path / "models"
    bundle = cache_dir / "buffalo_l"
    bundle.mkdir(parents=True)
    return cache_dir, bundle


def test_check_model_cache_rejects_broken_nonempty_onnx_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir, bundle = _bundle(tmp_path)
    (bundle / "broken.onnx").write_bytes(b"")
    calls = _configure_insightface(
        monkeypatch,
        tmp_path=tmp_path,
        models={"detection": object(), "recognition": object()},
        prepare_error=RuntimeError("invalid ONNX model"),
    )

    result = health_mod.check_model_cache(cache_dir)

    assert result.status is HealthStatus.UNHEALTHY
    assert "invalid ONNX model" in result.detail
    assert calls["prepare"] == {
        "ctx_id": -1,
        "det_size": (512, 512),
        "det_thresh": 0.4,
    }


def test_check_model_cache_requires_detector_and_recognition_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir, bundle = _bundle(tmp_path)
    (bundle / "detector.onnx").write_bytes(b"model")
    calls = _configure_insightface(
        monkeypatch,
        tmp_path=tmp_path,
        models={"detection": object()},
    )

    result = health_mod.check_model_cache(cache_dir)

    assert result.status is HealthStatus.UNHEALTHY
    assert "recognition" in result.detail
    assert calls["prepare"]


def test_check_model_cache_accepts_initialized_serving_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir, bundle = _bundle(tmp_path)
    (bundle / "detector.onnx").write_bytes(b"detector")
    calls = _configure_insightface(
        monkeypatch,
        tmp_path=tmp_path,
        models={"detection": object(), "recognition": object()},
    )

    result = health_mod.check_model_cache(cache_dir)

    assert result.status is HealthStatus.OK
    assert calls["init"] == {
        "name": "buffalo_l",
        "root": str(tmp_path),
        "providers": ["CPUExecutionProvider"],
    }
    assert calls["prepare"] == {
        "ctx_id": -1,
        "det_size": (512, 512),
        "det_thresh": 0.4,
    }
