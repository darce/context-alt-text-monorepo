from __future__ import annotations

from textwrap import dedent

from recognition.config import settings as recognition_settings


def _reset_settings_cache():
    recognition_settings.get_settings.cache_clear()


def test_get_settings_reads_yaml_overrides(tmp_path, monkeypatch):
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(
        dedent(
            """
            identity_detection:
              default_threshold: 0.9
            clustering:
              similarity_threshold: 0.75
              max_reps_per_media: 5
              ward_sync_batch_limit: 50
              complete_link_min_floor: 0.70
              complete_link_avg_threshold: 0.80
            """
        ).strip()
    )
    monkeypatch.setattr(recognition_settings, "CONFIG_FILE", config_file)
    _reset_settings_cache()

    loaded = recognition_settings.get_settings()

    assert loaded.identity_detection.default_threshold == 0.9
    assert loaded.clustering.similarity_threshold == 0.75
    assert loaded.clustering.max_reps_per_media == 5
    assert loaded.clustering.ward_sync_batch_limit == 50
    assert loaded.clustering.complete_link_min_floor == 0.70
    assert loaded.clustering.complete_link_avg_threshold == 0.80


def test_get_settings_is_cached_until_cleared(tmp_path, monkeypatch):
    config_file = tmp_path / "settings.yaml"
    config_file.write_text("recognition:\n  default_threshold: 0.9\n")
    monkeypatch.setattr(recognition_settings, "CONFIG_FILE", config_file)
    _reset_settings_cache()

    first = recognition_settings.get_settings()
    config_file.write_text("recognition:\n  default_threshold: 0.2\n")
    second = recognition_settings.get_settings()

    assert first is second
    assert second.recognition.default_threshold == 0.9
