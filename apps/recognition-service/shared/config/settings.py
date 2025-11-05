from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel

from .models import SharedSettings

_settings: Optional[SharedSettings] = None


def load_settings(config_path: Optional[str] = None) -> SharedSettings:
    """
    Load shared settings from the optional YAML override file.

    When the file is absent or empty we rely entirely on the defaults
    defined in :mod:`shared.config.models`.
    """
    path = Path(config_path) if config_path else Path(__file__).with_name("settings.yaml")
    override_data: Dict[str, Any] = {}

    if path.exists():
        with path.open("r") as handle:
            override_data = yaml.safe_load(handle) or {}

    return SharedSettings(**override_data)


def get_settings() -> SharedSettings:
    """Return the cached SharedSettings instance."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """Clear the cached settings instance (primarily used in tests)."""
    global _settings
    _settings = None


def get_config() -> Dict[str, Any]:
    """
    Return the full configuration as a dictionary.

    This maintains backwards compatibility with existing call sites that
    expect a plain mapping instead of a Pydantic model.
    """
    settings = get_settings()

    def _to_dict(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.dict()
        return value

    adapters: Dict[str, Any] = {
        "object_detector": settings.object_detector.dict(),
        "caption_generator": settings.caption_generator.dict(),
    }

    face_detector = getattr(settings, "face_detector", None)
    if face_detector is not None:
        adapters["face_detector"] = _to_dict(face_detector)

    config: Dict[str, Any] = {
        "adapters": adapters,
        "server": settings.server.dict(),
        "caption": settings.caption.dict(),
        "caption_generator": settings.caption_generator.dict(),
        "environment": settings.environment.dict(),
        "media_storage": settings.media_storage.dict(),
        "startup": settings.startup.dict(),
        "context_builder": settings.context_builder.dict(),
        "debug": settings.debug.dict(),
        "clustering": settings.clustering.dict(),
        "runtime_optimizations": settings.runtime_optimizations.dict(),
        "vision_model": settings.vision_model.dict(),
        "attention": settings.attention.dict(),
        "hardware": settings.hardware.dict(),
        "roster_storage": {},
    }

    if face_detector is not None:
        config["face_detector"] = _to_dict(face_detector)

    # Preserve any additional keys supplied via overrides/extras
    for key, value in settings.__dict__.items():
        if key.startswith("_"):
            continue
        if key in {
            "vision_model",
            "object_detector",
            "caption_generator",
            "attention",
            "server",
            "caption",
            "environment",
            "hardware",
            "runtime_optimizations",
            "media_storage",
            "startup",
            "context_builder",
            "debug",
            "clustering",
            "face_detector",
        }:
            continue
        if key == "roster_storage":
            config[key] = _to_dict(value)
            continue
        if key in config:
            continue
        config[key] = _to_dict(value)

    return config


def get_clustering_config() -> Dict[str, Any]:
    """
    Return clustering configuration merged with environment overrides.

    Environment variables:
        CLUSTER_ALGORITHM: dbscan or agglomerative
        CLUSTER_THRESHOLD: float within [0.0, 2.0]
        CLUSTER_MIN_SAMPLES: integer within [1, 10]
        CLUSTER_LINKAGE: average, complete, or single
    """
    settings = get_settings()
    result = settings.clustering.dict()

    env_algorithm = os.getenv("CLUSTER_ALGORITHM")
    if env_algorithm:
        if env_algorithm not in {"dbscan", "agglomerative"}:
            raise ValueError(
                f"Invalid CLUSTER_ALGORITHM: {env_algorithm}. Expected 'dbscan' or 'agglomerative'."
            )
        result["algorithm"] = env_algorithm

    env_threshold = os.getenv("CLUSTER_THRESHOLD")
    if env_threshold:
        try:
            threshold_value = float(env_threshold)
        except ValueError as exc:
            raise ValueError(f"Invalid CLUSTER_THRESHOLD: {env_threshold}. {exc}") from exc
        if not 0.0 <= threshold_value <= 2.0:
            raise ValueError(
                f"Invalid CLUSTER_THRESHOLD: {threshold_value}. Must be between 0.0 and 2.0"
            )
        result["distance_threshold"] = threshold_value

    env_min_samples = os.getenv("CLUSTER_MIN_SAMPLES")
    if env_min_samples:
        try:
            min_samples_value = int(env_min_samples)
        except ValueError as exc:
            raise ValueError(f"Invalid CLUSTER_MIN_SAMPLES: {env_min_samples}. {exc}") from exc
        if not 1 <= min_samples_value <= 10:
            raise ValueError(
                f"Invalid CLUSTER_MIN_SAMPLES: {min_samples_value}. Must be between 1 and 10"
            )
        result["min_samples"] = min_samples_value

    env_linkage = os.getenv("CLUSTER_LINKAGE")
    if env_linkage:
        if env_linkage not in {"average", "complete", "single"}:
            raise ValueError(
                f"Invalid CLUSTER_LINKAGE: {env_linkage}. Expected 'average', 'complete', or 'single'."
            )
        result["linkage"] = env_linkage

    return result
