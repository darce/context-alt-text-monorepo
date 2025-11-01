"""
Roster Service Configuration

Configuration management for the roster service.
Follows the project's environment variable contract.
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class RosterConfig:
    """
    Configuration manager for roster service.
    
    Follows the global contract from Project Instructions §4:
    - Uses environment variables for runtime paths
    - Loads settings from YAML configuration
    - Provides sensible defaults
    """
    
    def __init__(self, settings_path: Optional[str] = None):
        """
        Initialize configuration.
        
        Args:
            settings_path: Optional path to settings.yaml file
        """
        self.settings_path = settings_path or self._get_settings_path()
        self.settings = self._load_settings()
        
    def _get_settings_path(self) -> str:
        """Get settings file path from environment or default."""
        # Default to the settings file in the config directory
        default_path = os.path.join(os.path.dirname(__file__), "settings.yaml")
        return os.getenv("ROSTER_SETTINGS", default_path)
    
    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from YAML file."""
        try:
            if os.path.exists(self.settings_path):
                with open(self.settings_path, 'r') as f:
                    settings = yaml.safe_load(f) or {}
                    logger.info(f"Loaded roster settings from: {self.settings_path}")
                    return settings
            else:
                logger.warning(f"Settings file not found: {self.settings_path}, using defaults")
                return self._get_default_settings()
        except Exception as e:
            logger.error(f"Error loading settings: {e}, using defaults")
            return self._get_default_settings()
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """Get default configuration settings."""
        return {
            "service": {
                "name": "roster-service",
                "version": "1.0.0",
                "log_level": "INFO"
            },
            "storage": {
                "backend": "filesystem",
                "data_dir": self.get_data_dir(),
                "versioning": {
                    "enabled": True,
                    "retention_count": 5
                },
                "hot_reload": {
                    "enabled": True,
                    "watch_interval": 1.0
                }
            },
            "models": {
                "supported": [
                    "adaface_ir101",
                    "insightface_w600k", 
                    "arcface_ir50"
                ],
                "embedding_dimensions": {
                    "adaface_ir101": 512,
                    "insightface_w600k": 512,
                    "arcface_ir50": 512
                }
            },
            "validation": {
                "max_entries_per_identity": 10,
                "max_bulk_import_size": 1000,
                "required_fields": ["name"]
            }
        }
    
    def get_data_dir(self) -> str:
        """
        Get data directory path from environment or default.
        
        Follows global contract: ${CACHE_DIR}/roster/data
        """
        cache_dir = os.getenv("CACHE_DIR", "/tmp/cvlface-cache")
        return os.getenv("ROSTER_DATA_DIR", f"{cache_dir}/roster/data")
    
    def get_service_config(self) -> Dict[str, Any]:
        """Get service-level configuration."""
        return self.settings.get("service", {})
    
    def get_storage_config(self) -> Dict[str, Any]:
        """Get storage configuration."""
        return self.settings.get("storage", {})
    
    def get_model_config(self) -> Dict[str, Any]:
        """Get model configuration."""
        return self.settings.get("models", {})
    
    def get_validation_config(self) -> Dict[str, Any]:
        """Get validation configuration."""
        return self.settings.get("validation", {})
    
    def get_supported_models(self) -> list:
        """Get list of supported models."""
        return self.get_model_config().get("supported", [])
    
    def get_embedding_dimension(self, model: str) -> int:
        """
        Get expected embedding dimension for a model.
        
        Args:
            model: Model identifier
            
        Returns:
            Expected embedding dimension
        """
        dimensions = self.get_model_config().get("embedding_dimensions", {})
        return dimensions.get(model, 512)  # Default to 512
    
    def is_hot_reload_enabled(self) -> bool:
        """Check if hot-reload is enabled."""
        return self.get_storage_config().get("hot_reload", {}).get("enabled", True)
    
    def get_watch_interval(self) -> float:
        """Get file watch interval in seconds."""
        return self.get_storage_config().get("hot_reload", {}).get("watch_interval", 1.0)
    
    def is_versioning_enabled(self) -> bool:
        """Check if versioning is enabled."""
        return self.get_storage_config().get("versioning", {}).get("enabled", True)
    
    def get_retention_count(self) -> int:
        """Get number of versions to retain."""
        return self.get_storage_config().get("versioning", {}).get("retention_count", 5)


# Global configuration instance
_config: Optional[RosterConfig] = None


def get_config() -> RosterConfig:
    """
    Get global configuration instance.
    
    Returns:
        Singleton configuration instance
    """
    global _config
    if _config is None:
        _config = RosterConfig()
    return _config


def reload_config(settings_path: Optional[str] = None) -> RosterConfig:
    """
    Reload configuration (useful for testing).
    
    Args:
        settings_path: Optional new settings path
        
    Returns:
        New configuration instance
    """
    global _config
    _config = RosterConfig(settings_path)
    return _config
