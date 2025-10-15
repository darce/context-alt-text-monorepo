"""Tests for cache directory resolution and environment setup.

These cover the platform-aware logic recently added to support local
(`/Volumes/Butter`) and remote (Hugging Face cache) deployments.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path
from types import SimpleNamespace

import pytest

from recognition_core.config import _default_insightface_cache_dir, _resolve_default_cache_root
from shared.config import setup_environment


@pytest.fixture(autouse=True)
def clear_cache_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear cache-related environment variables before each test."""
    for var in [
        "INSIGHTFACE_CACHE_DIR",
        "CACHE_DIR",
        "LOCAL_CACHE_ROOT",
        "HF_HOME",
        "HF_HUB_CACHE",
        "TRANSFORMERS_CACHE",
        "TORCH_HOME",
        "YOLO_CONFIG_DIR",
        "MPLCONFIGDIR",
    ]:
        monkeypatch.delenv(var, raising=False)


def test_resolve_cache_root_prefers_insightface_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSIGHTFACE_CACHE_DIR", "/tmp/custom-insightface")

    root = _resolve_default_cache_root()
    assert root == Path("/tmp/custom-insightface")
    expected = root / "insightface"
    assert Path(_default_insightface_cache_dir()) == expected


def test_resolve_cache_root_prefers_cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache-base"
    monkeypatch.setenv("CACHE_DIR", str(cache_dir))

    root = _resolve_default_cache_root()
    assert root == cache_dir
    expected = cache_dir / "insightface"
    assert Path(_default_insightface_cache_dir()) == expected


def test_resolve_cache_root_uses_hf_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    hf_home = tmp_path / "hf-home"
    monkeypatch.setenv("HF_HOME", str(hf_home))

    root = _resolve_default_cache_root()
    assert root == hf_home


def test_resolve_cache_root_falls_back_to_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    def fake_exists(self: Path) -> bool:  # pragma: no cover - patched behaviour only
        return str(self) == "/Volumes/Butter"

    monkeypatch.setattr(Path, "exists", fake_exists)

    root = _resolve_default_cache_root()
    assert root == Path("/Volumes/Butter")


def test_resolve_cache_root_defaults_to_user_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(Path, "exists", lambda self: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    root = _resolve_default_cache_root()
    assert root == tmp_path / ".cache" / "context-alt-text"


def test_setup_environment_honours_cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache-root"
    monkeypatch.setenv("CACHE_DIR", str(cache_dir))

    config = {
        "startup": {},
        "debug": {"face_crop_dir": str(tmp_path / "debug" / "crops")},
        "roster_storage": {
            "config": {
                "roster_file_path": str(tmp_path / "data" / "roster.json"),
                "backup_directory": str(tmp_path / "data" / "backups"),
            }
        },
        "media_storage": {"config": {"upload_directory": str(tmp_path / "uploads")}},
        "context_builder": {},
    }

    monkeypatch.setattr("shared.config.get_config", lambda: config)
    cache_dirs = setup_environment()

    # Core directories are created and exported
    assert Path(cache_dirs["INSIGHTFACE_CACHE_DIR"]).exists()
    assert os.environ["CACHE_DIR"] == str(cache_dir)
    assert (cache_dir / "huggingface_cache").exists()
    assert (cache_dir / "torch").exists()
    assert (cache_dir / "matplotlib").exists()

    # Debug directories honour configuration
    assert Path(os.environ["DEBUG_CROP_DIR"]) == Path(config["debug"]["face_crop_dir"])