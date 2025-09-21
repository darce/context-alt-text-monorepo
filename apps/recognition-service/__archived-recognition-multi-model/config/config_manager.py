"""
Recognition Service Configuration Manager
Loads and manages configuration for the recognition service.
"""
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional
import yaml

logger = logging.getLogger(__name__)


class RecognitionConfig:
    """Recognition service configuration manager."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_path: Path to configuration file
        """
        self.config_path = config_path or self._get_default_config_path()
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _get_default_config_path(self) -> str:
        """Get default configuration path."""
        # Check environment variable
        env_path = os.getenv('RECOG_SETTINGS')
        if env_path and os.path.exists(env_path):
            return env_path
        
        # Check relative to current file
        current_dir = Path(__file__).parent
        config_file = current_dir / 'settings.yaml'
        if config_file.exists():
            return str(config_file)
        
        # Check project root
        project_root = current_dir.parent.parent
        config_file = project_root / 'recognition_settings.yaml'
        if config_file.exists():
            return str(config_file)
        
        # Default fallback
        return str(current_dir / 'settings.yaml')
    
    def _load_config(self):
        """Load configuration from file."""
        try:
            with open(self.config_path, 'r') as f:
                self._config = yaml.safe_load(f)
            
            # Resolve environment variables
            self._resolve_env_vars()
            
            logger.info(f"✅ Configuration loaded from {self.config_path}")
            
        except FileNotFoundError:
            logger.warning(f"⚠️ Configuration file not found: {self.config_path}")
            self._config = self._get_default_config()
        except Exception as e:
            logger.error(f"❌ Failed to load configuration: {e}")
            self._config = self._get_default_config()
    
    def _resolve_env_vars(self):
        """Resolve environment variables in configuration."""
        def resolve_value(value):
            if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
                # Extract environment variable with optional default
                env_spec = value[2:-1]  # Remove ${ and }
                if ':-' in env_spec:
                    env_var, default_value = env_spec.split(':-', 1)
                    return os.getenv(env_var, default_value)
                else:
                    return os.getenv(env_spec, value)
            elif isinstance(value, dict):
                return {k: resolve_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [resolve_value(item) for item in value]
            return value
        
        self._config = resolve_value(self._config)
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            'service': {
                'name': 'face-recognition-service',
                'version': '1.0.0',
                'port': 7860,
                'host': '0.0.0.0',
                'debug': False,
                'log_level': 'INFO'
            },
            'models': {
                'adaface_ir101': {
                    'type': 'cvlface_adaface',
                    'model_id': 'minchul/cvlface_adaface_ir101_webface12m',
                    'device': 'auto',
                    'face_detection_threshold': 0.5,
                    'face_recognition_threshold': 0.5,
                    'embeddings_file': 'adaface_ir101_embeddings.json'
                },
                'insightface_w600k': {
                    'type': 'cvlface_insight',
                    'model_id': 'deepinsight/insightface-scrfd-arcface-w600k',
                    'insightface_model': 'buffalo_l',
                    'device': 'auto',
                    'face_detection_threshold': 0.5,
                    'face_recognition_threshold': 0.5,
                    'embeddings_file': 'insightface_w600k_embeddings.json'
                },
                'arcface_ir50': {
                    'type': 'cvlface_arcface',
                    'model_id': 'minchul/cvlface_arcface_ir50_webface4m',
                    'device': 'auto',
                    'face_detection_threshold': 0.5,
                    'face_recognition_threshold': 0.5,
                    'embeddings_file': 'arcface_ir50_embeddings.json'
                }
            },
            'embeddings': {
                'roster_data_dir': 'roster/data',
                'auto_reload': True,
                'format': 'json',
                'normalize_embeddings': True,
                'distance_metric': 'cosine'
            }
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value.
        
        Args:
            key: Configuration key (dot notation supported)
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def get_service_config(self) -> Dict[str, Any]:
        """Get service configuration."""
        return self.get('service', {})
    
    def get_model_config(self, model_name: str) -> Dict[str, Any]:
        """
        Get model configuration.
        
        Args:
            model_name: Model name
            
        Returns:
            Model configuration
        """
        return self.get(f'models.{model_name}', {})
    
    def get_models_config(self) -> Dict[str, Dict[str, Any]]:
        """Get all models configuration."""
        return self.get('models', {})
    
    def get_embeddings_config(self) -> Dict[str, Any]:
        """Get embeddings configuration."""
        return self.get('embeddings', {})
    
    def get_performance_config(self) -> Dict[str, Any]:
        """Get performance configuration."""
        return self.get('performance', {})
    
    def get_quality_config(self) -> Dict[str, Any]:
        """Get quality configuration."""
        return self.get('quality', {})
    
    def get_alignment_config(self) -> Dict[str, Any]:
        """Get alignment configuration."""
        return self.get('alignment', {})
    
    def get_logging_config(self) -> Dict[str, Any]:
        """Get logging configuration."""
        return self.get('logging', {})
    
    def get_environment_config(self) -> Dict[str, Any]:
        """Get environment configuration."""
        return self.get('environment', {})
    
    def reload(self):
        """Reload configuration from file."""
        self._load_config()
        logger.info("🔄 Configuration reloaded")
    
    def to_dict(self) -> Dict[str, Any]:
        """Get full configuration as dictionary."""
        return self._config.copy()


# Global configuration instance
_config: Optional[RecognitionConfig] = None


def get_config() -> RecognitionConfig:
    """
    Get global configuration instance.
    
    Returns:
        Configuration instance
    """
    global _config
    if _config is None:
        _config = RecognitionConfig()
    return _config


def reload_config():
    """Reload global configuration."""
    global _config
    if _config is not None:
        _config.reload()
    else:
        _config = RecognitionConfig()


def set_config_path(path: str):
    """
    Set configuration file path.
    
    Args:
        path: Path to configuration file
    """
    global _config
    _config = RecognitionConfig(path)
