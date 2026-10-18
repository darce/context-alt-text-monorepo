from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

import pytest

from recognition import config
from recognition.application import health as health_mod
from shared.health import HealthStatus


@pytest.fixture(autouse=True)
def _reset_probe_cache() -> Any:
    health_mod.reset_face_pipeline_verify_cache_for_tests()
    yield
    health_mod.reset_face_pipeline_verify_cache_for_tests()


def _configure_insightface(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    models: dict[str, object],
    prepare_effect: Callable[[int], None] | None = None,
) -> dict[str, int]:
    calls = {"construct": 0, "prepare": 0}
    calls_lock = threading.Lock()
    settings = SimpleNamespace(
        insightface=SimpleNamespace(
            cache_dir=tmp_path / "models",
            model_name="buffalo_l",
            device="cpu",
            providers=["CPUExecutionProvider"],
            det_size=(512, 512),
            det_thresh=0.4,
        )
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    class FakeFaceAnalysis:
        def __init__(self, *, name: str, root: str, providers: list[str]) -> None:
            assert name == "buffalo_l"
            assert root == str(tmp_path)
            assert providers == ["CPUExecutionProvider"]
            with calls_lock:
                calls["construct"] += 1
            self.models = models

        def prepare(self, *, ctx_id: int, det_size: tuple[int, int], det_thresh: float) -> None:
            assert ctx_id == -1
            assert det_size == (512, 512)
            assert det_thresh == 0.4
            with calls_lock:
                calls["prepare"] += 1
                attempt = calls["prepare"]
            if prepare_effect is not None:
                prepare_effect(attempt)

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
    (bundle / "detector.onnx").write_bytes(b"detector model")
    return cache_dir, bundle


def test_sequential_probes_reuse_successful_insightface_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir, _ = _bundle(tmp_path)
    calls = _configure_insightface(
        monkeypatch,
        tmp_path=tmp_path,
        models={"detection": object(), "recognition": object()},
    )

    first = health_mod.check_model_cache(cache_dir)
    second = health_mod.check_model_cache(cache_dir)

    assert first.status is HealthStatus.OK
    assert second.status is HealthStatus.OK
    assert calls == {"construct": 1, "prepare": 1}


def test_concurrent_probes_construct_insightface_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir, _ = _bundle(tmp_path)
    prepare_started = threading.Event()
    release_prepare = threading.Event()

    def pause_prepare(_: int) -> None:
        prepare_started.set()
        assert release_prepare.wait(timeout=5)

    calls = _configure_insightface(
        monkeypatch,
        tmp_path=tmp_path,
        models={"detection": object(), "recognition": object()},
        prepare_effect=pause_prepare,
    )
    start = threading.Barrier(3)

    def probe() -> Any:
        start.wait(timeout=2)
        return health_mod.check_model_cache(cache_dir)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(probe) for _ in range(2)]
        start.wait(timeout=2)
        assert prepare_started.wait(timeout=2)
        time.sleep(0.05)
        release_prepare.set()
        results = [future.result(timeout=5) for future in futures]

    assert all(result.status is HealthStatus.OK for result in results)
    assert calls == {"construct": 1, "prepare": 1}


def test_failed_prepare_is_unhealthy_and_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir, _ = _bundle(tmp_path)

    def fail_first_prepare(attempt: int) -> None:
        if attempt == 1:
            raise RuntimeError("temporary prepare failure")

    calls = _configure_insightface(
        monkeypatch,
        tmp_path=tmp_path,
        models={"detection": object(), "recognition": object()},
        prepare_effect=fail_first_prepare,
    )

    first = health_mod.check_model_cache(cache_dir)
    second = health_mod.check_model_cache(cache_dir)

    assert first.status is HealthStatus.UNHEALTHY
    assert "temporary prepare failure" in first.detail
    assert second.status is HealthStatus.OK
    assert calls == {"construct": 2, "prepare": 2}


def test_touching_bundle_file_forces_insightface_reverification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir, bundle = _bundle(tmp_path)
    model_file = bundle / "detector.onnx"
    calls = _configure_insightface(
        monkeypatch,
        tmp_path=tmp_path,
        models={"detection": object(), "recognition": object()},
    )

    assert health_mod.check_model_cache(cache_dir).status is HealthStatus.OK
    before = model_file.stat()
    os.utime(model_file, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    assert model_file.stat().st_mtime_ns != before.st_mtime_ns

    result = health_mod.check_model_cache(cache_dir)

    assert result.status is HealthStatus.OK
    assert calls == {"construct": 2, "prepare": 2}


def test_removed_bundle_is_unhealthy_and_recreated_bundle_is_reverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir, bundle = _bundle(tmp_path)
    model_file = bundle / "detector.onnx"
    calls = _configure_insightface(
        monkeypatch,
        tmp_path=tmp_path,
        models={"detection": object(), "recognition": object()},
    )

    assert health_mod.check_model_cache(cache_dir).status is HealthStatus.OK
    model_file.unlink()
    missing = health_mod.check_model_cache(cache_dir)
    model_file.write_bytes(b"detector model")
    restored = health_mod.check_model_cache(cache_dir)

    assert missing.status is HealthStatus.UNHEALTHY
    assert "no_onnx_files" in missing.detail
    assert restored.status is HealthStatus.OK
    assert calls == {"construct": 2, "prepare": 2}
