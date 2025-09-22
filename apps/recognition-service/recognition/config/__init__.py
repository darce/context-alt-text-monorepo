"""
Recognition Service Settings

Pydantic-based configuration for the InsightFace-only recognition service.
Loads from settings.yaml with environment variable overrides.
"""

import os
import yaml
from typing import List, Optional
from pathlib import Path
from pydantic import BaseSettings, Field


class InsightFaceSettings(BaseSettings):
    """InsightFace model configuration."""
    model_name: str = "buffalo_l"  # Standard InsightFace model
    device: str = "auto"
    cache_dir: str = Field(default_factory=lambda: os.getenv("INSIGHTFACE_CACHE_DIR", "/tmp/insightface_models"))
    providers: List[str] = []  # Empty list enables auto-detection based on device


class RecognitionSettings(BaseSettings):
    """Recognition pipeline settings."""
    default_threshold: float = 0.45
    max_faces_per_image: int = 10
    embedding_dimension: int = 512


class EmbeddingRouterSettings(BaseSettings):
    """Embedding router configuration."""
    embeddings_file: str = "/roster/data/insightface_embeddings.json"
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
    If not set, defaults to recognition/config/settings.yaml.
    """
    # Get settings file path from environment or use default
    settings_path = os.getenv(
        "RECOG_SETTINGS", 
        "/recognition/config/settings.yaml"
    )
    
    # If path is relative, make it relative to the project root
    if not os.path.isabs(settings_path):
        project_root = Path(__file__).parent.parent.parent
        settings_path = project_root / settings_path.lstrip("/")
    
    # Load YAML configuration
    config_data = {}
    if os.path.exists(settings_path):
        with open(settings_path, 'r') as f:
            config_data = yaml.safe_load(f) or {}
    
    # Create nested settings objects
    settings_data = {
        "insightface": InsightFaceSettings(**config_data.get("insightface", {})),
        "recognition": RecognitionSettings(**config_data.get("recognition", {})),
        "embedding_router": EmbeddingRouterSettings(**config_data.get("embedding_router", {})),
        "cache": CacheSettings(**config_data.get("cache", {})),
        "performance": PerformanceSettings(**config_data.get("performance", {})),
        "logging": LoggingSettings(**config_data.get("logging", {})),
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
