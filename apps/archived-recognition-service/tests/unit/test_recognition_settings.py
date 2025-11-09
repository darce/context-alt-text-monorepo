import os

import pytest

from recognition_core.config import get_settings, reload_settings


def test_recognition_settings_defaults(monkeypatch):
    monkeypatch.delenv("RECOG_INSIGHTFACE__DET_THRESH", raising=False)
    reload_settings()
    settings = get_settings()

    assert settings.insightface.det_thresh == pytest.approx(0.3)
    assert settings.recognition.max_faces_per_image == 999
    assert settings.recognition.max_candidates == 999


def test_recognition_settings_env_override(monkeypatch):
    monkeypatch.setenv("RECOG_INSIGHTFACE__DET_THRESH", "0.42")
    try:
        reload_settings()
        settings = get_settings()
        assert settings.insightface.det_thresh == pytest.approx(0.42)
    finally:
        monkeypatch.delenv("RECOG_INSIGHTFACE__DET_THRESH", raising=False)
        reload_settings()
