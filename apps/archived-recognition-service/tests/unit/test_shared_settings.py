import os

import pytest

from shared.config.settings import (
    get_clustering_config,
    get_config,
    get_settings,
    reset_settings,
)


def test_shared_settings_defaults(monkeypatch):
    reset_settings()
    settings = get_settings()

    assert settings.caption_generator.type == "mock"
    assert settings.media_storage.config.upload_directory == "data/media"
    assert settings.runtime_optimizations.default_gpu.recommended_attention == "eager"

    config_dict = get_config()
    assert config_dict["caption"]["prompt_template"].startswith("Generate a factual")
    assert config_dict["adapters"]["object_detector"]["type"] == "yolo"
    assert config_dict["adapters"]["caption_generator"]["type"] == "mock"


def test_clustering_env_overrides(monkeypatch):
    reset_settings()
    monkeypatch.setenv("CLUSTER_THRESHOLD", "0.8")
    monkeypatch.setenv("CLUSTER_MIN_SAMPLES", "4")
    try:
        config = get_clustering_config()
        assert config["distance_threshold"] == pytest.approx(0.8)
        assert config["min_samples"] == 4
    finally:
        monkeypatch.delenv("CLUSTER_THRESHOLD", raising=False)
        monkeypatch.delenv("CLUSTER_MIN_SAMPLES", raising=False)
