"""
Recognition Service Settings

Pydantic-based configuration for the InsightFace-only recognition service.
Loads from settings.yaml with environment variable overrides.
"""

import os
import platform
import yaml
from typing import List, Optional, Mapping, Any
from pathlib import Path
from pydantic import BaseSettings, Field


def _resolve_default_cache_root() -> Path:
    """Infer a sensible cache root based on environment and platform."""
    for env_var in ("INSIGHTFACE_CACHE_DIR", "CACHE_DIR", "LOCAL_CACHE_ROOT"):
        value = os.getenv(env_var)
        if value:
            return Path(value)

    # Hugging Face deployments typically set HF_HOME / HF_HUB_CACHE
    hf_home = os.getenv("HF_HOME")
    if hf_home:
        return Path(hf_home)

    for env_var in ("HF_HUB_CACHE", "TRANSFORMERS_CACHE"):
        value = os.getenv(env_var)
        if value:
            candidate = Path(value)
            return candidate.parent if candidate.is_file() else candidate

    # macOS local default
    if platform.system() == "Darwin":
        butter = Path("/Volumes/Butter")
        if butter.exists():
            return butter

    # Fallback to user cache directory
    return Path.home() / ".cache" / "context-alt-text"


def _default_insightface_cache_dir() -> str:
    root = _resolve_default_cache_root()
    # If the root already points to a specific directory for insightface, keep it
    if root.name.lower().startswith("insightface"):
        return str(root)
    return str(root / "insightface")


def _strip_none_values(data: Mapping[str, Any]) -> dict:
    """Remove keys that explicitly set None so default factories still run."""
    return {key: value for key, value in data.items() if value is not None}


class InsightFaceSettings(BaseSettings):
    """InsightFace model configuration."""
    model_name: str = "buffalo_l"  # Standard InsightFace model
    device: str = "auto"
    cache_dir: str = Field(default_factory=_default_insightface_cache_dir)
    providers: List[str] = []  # Empty list enables auto-detection based on device


class RecognitionSettings(BaseSettings):
    """Recognition pipeline settings."""
    default_threshold: float = 0.45
    max_faces_per_image: int = 10
    embedding_dimension: int = 512


class EmbeddingRouterSettings(BaseSettings):
    """Embedding router configuration."""
    embeddings_file: str = "/roster/data/insightface_w600k_embeddings.json"
    auto_reload: bool = True
    reload_interval: int = 30


class CacheSettings(BaseSettings):
    """Cache directory configuration for Hugging Face / Torch."""

    hf_home: Optional[str] = Field(default=None)
    hf_datasets_cache: Optional[str] = Field(default=None)
    torch_home: Optional[str] = Field(default=None)


class PerformanceSettings(BaseSettings):
    """Performance and concurrency settings."""
    batch_size: int = 1
    max_concurrent_requests: int = 10


class LoggingSettings(BaseSettings):
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class Settings(BaseSettings):
    """Main settings class for the recognition service."""
    
    insightface: InsightFaceSettings = Field(default_factory=InsightFaceSettings)
    recognition: RecognitionSettings = Field(default_factory=RecognitionSettings)
    embedding_router: EmbeddingRouterSettings = Field(default_factory=EmbeddingRouterSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    performance: PerformanceSettings = Field(default_factory=PerformanceSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    
    class Config:
        """Pydantic configuration."""
        env_prefix = "RECOG_"
        case_sensitive = False


def load_settings() -> Settings:
    """
    Load settings from YAML file with environment variable overrides.
    
    The RECOG_SETTINGS environment variable can specify the path to settings.yaml.
    If not set, defaults to recognition_core/config/settings.yaml.
    """
    default_settings = Path(__file__).with_name("settings.yaml")
    env_setting = os.getenv("RECOG_SETTINGS")
    settings_path = Path(env_setting) if env_setting else default_settings

    if not settings_path.is_absolute():
        project_root = Path(__file__).parent.parent.parent
        settings_path = (project_root / settings_path).resolve()
    
    # Load YAML configuration
    config_data = {}
    if settings_path.exists():
        with settings_path.open('r') as f:
            config_data = yaml.safe_load(f) or {}
    
    # Create nested settings objects
    settings_data = {
        "insightface": InsightFaceSettings(**_strip_none_values(config_data.get("insightface", {}))),
        "recognition": RecognitionSettings(**_strip_none_values(config_data.get("recognition", {}))),
        "embedding_router": EmbeddingRouterSettings(**_strip_none_values(config_data.get("embedding_router", {}))),
        "cache": CacheSettings(**_strip_none_values(config_data.get("cache", {}))),
        "performance": PerformanceSettings(**_strip_none_values(config_data.get("performance", {}))),
        "logging": LoggingSettings(**_strip_none_values(config_data.get("logging", {}))),
    }
    
    return Settings(**settings_data)


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance (singleton pattern)."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings from file."""
    global _settings
    _settings = load_settings()
    return _settings
