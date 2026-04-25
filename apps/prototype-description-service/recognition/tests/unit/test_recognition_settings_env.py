"""Env-override tests for the new E15-11 RecognitionSettings fields (BR-04).

Decision #2357 documented blob_root, max_upload_bytes, and
allowed_upload_mime_types as env-overridable; only the first two were
actually wired. These tests pin down the contract for all three so the
documentation and the code agree.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _fresh_settings_class():
    """Re-import the settings module so the field defaults are recomputed
    against the current environment (the default_factory captures os.environ
    at field-evaluation time)."""
    import recognition.config.settings as settings_module

    importlib.reload(settings_module)
    return settings_module.RecognitionSettings


def test_blob_root_honours_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RECOGNITION_BLOB_ROOT", str(tmp_path / "custom-root"))
    settings_cls = _fresh_settings_class()
    settings = settings_cls()
    assert settings.blob_root == tmp_path / "custom-root"


def test_max_upload_bytes_honours_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_MAX_UPLOAD_BYTES", "1234567")
    settings_cls = _fresh_settings_class()
    settings = settings_cls()
    assert settings.max_upload_bytes == 1234567


def test_allowed_upload_mime_types_honours_env_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BR-04: comma-separated env override for the MIME allow-list."""
    monkeypatch.setenv(
        "RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES",
        "image/jpeg,image/heic, image/avif",
    )
    settings_cls = _fresh_settings_class()
    settings = settings_cls()
    assert settings.allowed_upload_mime_types == ["image/jpeg", "image/heic", "image/avif"]


def test_allowed_upload_mime_types_default_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES", raising=False)
    settings_cls = _fresh_settings_class()
    settings = settings_cls()
    assert settings.allowed_upload_mime_types == ["image/jpeg", "image/png", "image/webp"]


def test_allowed_upload_mime_types_empty_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty string env var should not produce an empty allow-list (which
    would refuse every upload). Treat empty as 'use the default'."""
    monkeypatch.setenv("RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES", "   ")
    settings_cls = _fresh_settings_class()
    settings = settings_cls()
    assert settings.allowed_upload_mime_types == ["image/jpeg", "image/png", "image/webp"]
