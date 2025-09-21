"""
Recognition Service Configuration
Configuration management for the recognition service.
"""
from .config_manager import (
    RecognitionConfig, get_config, reload_config, set_config_path
)

__all__ = [
    "RecognitionConfig",
    "get_config", 
    "reload_config",
    "set_config_path"
]
