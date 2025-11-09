"""Integration tests for the FastAPI lifespan/startup sequence."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest  # type: ignore[import]
from fastapi.testclient import TestClient  # type: ignore[import]

import app as recognition_app
from api.routes.main import set_scene_analysis_service
from recognition_core.config import reload_settings


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure settings cache is cleared between tests."""
    reload_settings()

    for var in [
        "CACHE_DIR",
        "LOCAL_CACHE_ROOT",
        "INSIGHTFACE_CACHE_DIR",
        "HF_HOME",
        "HF_HUB_CACHE",
        "TRANSFORMERS_CACHE",
    ]:
        monkeypatch.delenv(var, raising=False)


def test_lifespan_completes_and_sets_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("CACHE_DIR", str(cache_dir))

    fake_scene_service = SimpleNamespace(
        generate_caption=lambda *args, **kwargs: {"caption": "stub", "processing_info": {}},
        recognition_service=SimpleNamespace(
            recognize_faces=lambda *args, **kwargs: None,
            settings=SimpleNamespace(recognition=SimpleNamespace(default_threshold=0.5)),
        ),
    )

    def fake_initialize(app: Any) -> None:
        recognition_app.startup_manager = SimpleNamespace(
            current_phase=recognition_app.StartupPhase.COMPLETED,
            get_metrics=lambda: SimpleNamespace(total_time=None, adapter_creation_time=None),
        )
        recognition_app.scene_composer = object()
        recognition_app.scene_analysis_service = fake_scene_service
        set_scene_analysis_service(fake_scene_service)
        app.state.is_initializing = False
        app.state.initialization_complete = True

    monkeypatch.setattr(recognition_app, "initialize_application", fake_initialize)

    class DummyStartupManager:
        def __init__(self) -> None:
            self.current_phase = recognition_app.StartupPhase.COMPLETED

        def get_caption_pipeline(self) -> str:
            return "pipeline"

        def get_metrics(self):  # pragma: no cover - compatibility
            return SimpleNamespace(total_time=None, adapter_creation_time=None)

    monkeypatch.setattr(recognition_app, "get_startup_manager", lambda config: DummyStartupManager())

    class DummyStartupConfig:
        @classmethod
        def from_config(cls, cfg):
            return SimpleNamespace()

    monkeypatch.setattr(recognition_app, "StartupConfig", DummyStartupConfig)
    monkeypatch.setattr(recognition_app, "get_config", lambda: {"startup": {}})

    with TestClient(recognition_app.app) as client:
        assert recognition_app.app.state.initialization_complete is True
        assert recognition_app.app.state.img2text == "pipeline"
        response = client.get("/ready")
        assert response.status_code == 200

    # Lifespan shutdown clears globals
    assert recognition_app.scene_composer is None
    assert recognition_app.startup_manager is None

