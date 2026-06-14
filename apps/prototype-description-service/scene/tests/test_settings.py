"""S1/S8: description + VLM settings models (env-driven, recognition runtime untouched)."""

from scene.application.settings.vlm import VlmSettings
from scene.config.settings import DescriptionSettings
from scene.domain.description import DescriptionAdapterKind


def test_description_settings_defaults():
    s = DescriptionSettings()
    assert s.adapter_mode is DescriptionAdapterKind.SEEDED
    assert s.max_description_image_bytes == 25 * 1024 * 1024
    assert "image/jpeg" in s.allowed_description_mime_types
    assert s.prompt_or_task_version == "1"


def test_description_settings_env_override(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "local_cpu")
    monkeypatch.setenv("ACX_DESCRIPTION_MAX_IMAGE_BYTES", "1024")
    s = DescriptionSettings()
    assert s.adapter_mode is DescriptionAdapterKind.LOCAL_CPU
    assert s.max_description_image_bytes == 1024


def test_vlm_settings_defaults_are_safe():
    s = VlmSettings()
    assert s.adapter_mode is DescriptionAdapterKind.SEEDED
    assert s.async_inline is False
    assert s.worker_concurrency == 1
    assert s.max_image_edge_px == 1024
    assert s.florence_model_id == "microsoft/Florence-2-base-ft"


def test_vlm_settings_enable_local_cpu(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "local_cpu")
    monkeypatch.setenv("ACX_VLM_WORKER_CONCURRENCY", "2")
    s = VlmSettings()
    assert s.adapter_mode is DescriptionAdapterKind.LOCAL_CPU
    assert s.worker_concurrency == 2
