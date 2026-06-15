"""S1/S8/S11: description + VLM settings models (env-driven, recognition runtime untouched)."""

from scene.application.settings.vlm import VlmSettings
from scene.config.profiles import DescriptionProfile
from scene.config.settings import DescriptionSettings


def test_description_settings_defaults():
    s = DescriptionSettings()
    assert s.profile is DescriptionProfile.SEEDED
    assert s.max_description_image_bytes == 25 * 1024 * 1024
    assert "image/jpeg" in s.allowed_description_mime_types
    assert s.prompt_or_task_version == "1"


def test_description_settings_env_override(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    monkeypatch.setenv("ACX_DESCRIPTION_MAX_IMAGE_BYTES", "1024")
    s = DescriptionSettings()
    assert s.profile is DescriptionProfile.FLORENCE_SMALL
    assert s.max_description_image_bytes == 1024


def test_vlm_settings_defaults_are_safe():
    s = VlmSettings()
    assert s.async_inline is False
    assert s.worker_concurrency == 1
    assert s.max_image_edge_px == 1024
    assert s.inference_timeout_seconds == 20


def test_vlm_settings_host_caps_env_override(monkeypatch):
    monkeypatch.setenv("ACX_VLM_WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("ACX_VLM_TIMEOUT_SECONDS", "45")
    s = VlmSettings()
    assert s.worker_concurrency == 2
    assert s.inference_timeout_seconds == 45
