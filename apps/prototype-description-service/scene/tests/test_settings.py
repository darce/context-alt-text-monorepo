"""S1/S8/S11: description + VLM settings models (env-driven, recognition runtime untouched)."""

import math

import pytest

from scene.application.settings.vlm import VlmSettings
from scene.config.profiles import DescriptionProfile
from scene.config.settings import DEFAULT_GENERATION_TIMEOUT_SECONDS, DescriptionSettings


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


# ---------------------------------------------------------------------------
# GUIDEDFIX-2 [S10]: the generation timeout is the per-item leg of the run
# deadline the submit route publishes, so it needs a positive floor.
# ---------------------------------------------------------------------------



def test_generation_timeout_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", raising=False)
    assert DescriptionSettings().generation_timeout_seconds == DEFAULT_GENERATION_TIMEOUT_SECONDS


def test_generation_timeout_accepts_a_positive_override(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "42.5")
    assert DescriptionSettings().generation_timeout_seconds == 42.5


@pytest.mark.parametrize("raw", ["0", "0.0", "-1", "-0.5", "nan", "inf", "-inf", "not-a-number"])
def test_non_positive_generation_timeout_is_refused_at_load(monkeypatch, raw):
    """[S10] RED before the fix: the field was a bare ``float(os.environ[...])``.

    ``ACX_DESCRIPTION_TIMEOUT_SECONDS=0`` was accepted silently, and the submit
    route then published ``deadline_seconds: 0`` — a payload that fails this
    service's own published contract (``exclusiveMinimum: 0``) while every item
    is born already timed out. Refuse the value where it enters the process.
    """
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", raw)
    with pytest.raises(ValueError, match="ACX_DESCRIPTION_TIMEOUT_SECONDS"):
        DescriptionSettings()


def test_the_floor_keeps_the_published_deadline_contract_satisfiable(monkeypatch):
    """Whatever survives the floor must be usable as a positive, finite deadline."""
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "0.001")
    seconds = DescriptionSettings().generation_timeout_seconds
    assert seconds > 0 and math.isfinite(seconds)
