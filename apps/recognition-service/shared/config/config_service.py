from typing import Dict, Any, Optional, Union, List
from shared.config.settings import get_config
import logging
import threading

logger = logging.getLogger(__name__)

class ConfigService:
    """
    Centralized configuration service with thread-safe caching and comprehensive configuration access.
    
    Provides thread-safe access to configuration values with intelligent caching,
    robust error handling, and comprehensive methods for different configuration domains.
    
    Implements singleton pattern to ensure consistent configuration access across the application.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Implement singleton pattern with thread safety."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ConfigService, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the configuration service (called only once due to singleton)."""
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self._config = get_config()
        self._cache: Dict[str, Any] = {}
        self._cache_lock = threading.RLock()
        self._initialized = True
        
        # Model type registry for extensibility
        self._model_type_registry = {
            'phi3': {'multimodal': True, 'supports_vision': True},
            'mock': {'multimodal': False, 'supports_vision': False},
            # Add more model types here as needed
        }
        
    def get(self, key: str, default: Any = None):
        """
        Get a config value with error checking and optional default.
        
        Args:
            key: Configuration key to retrieve
            default: Default value if key is not found (if None, raises KeyError)
            
        Returns:
            Configuration value
            
        Raises:
            KeyError: If key not found and no default provided
        """
        if key not in self._config:
            if default is not None:
                return default
            raise KeyError(f"Missing required config key: {key}")
        return self._config[key]

    def get_section(self, section: str, default: Dict[str, Any] = None):
        """
        Get a config section with error checking and optional default.
        
        Args:
            section: Configuration section to retrieve
            default: Default value if section is not found (if None, raises KeyError)
            
        Returns:
            Configuration section
            
        Raises:
            KeyError: If section not found and no default provided
        """
        if section not in self._config:
            if default is not None:
                return default
            raise KeyError(f"Missing required config section: {section}")
        return self._config[section]
    
    def get_nested(self, *keys: str, default: Any = None):
        """
        Get a nested configuration value using dot notation or multiple keys.
        
        Args:
            *keys: Nested keys to traverse (e.g., 'caption_generator', 'config', 'model_id')
            default: Default value if path not found
            
        Returns:
            Nested configuration value
        """
        current = self._config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                if default is not None:
                    return default
                raise KeyError(f"Missing nested config path: {' -> '.join(keys)}")
        return current
    
    def get_config(self) -> Dict[str, Any]:
        """
        Get the complete configuration dictionary.
        
        Returns:
            Complete configuration dictionary
        """
        return self._config
    
    def get_caption_model_type(self) -> str:
        """
        Get the type of caption generator model with thread-safe caching.
        
        Returns:
            Model type in lowercase, or empty string if not found
        """
        cache_key = 'caption_model_type'
        
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
                
            try:
                caption_config = self.get_section('caption_generator')
                model_type = caption_config.get('type', '').lower()
                self._cache[cache_key] = model_type
                logger.debug(f"Cached caption model type: {model_type}")
                return model_type
            except (KeyError, AttributeError) as e:
                logger.warning(f"Could not determine caption model type: {e}")
                self._cache[cache_key] = ''
                return ''

    def is_model_type(self, model_type: str) -> bool:
        """
        Check if caption generator is of specific type.
        
        Args:
            model_type: Model type to check (case-insensitive)
            
        Returns:
            True if model matches, False otherwise
        """
        return self.get_caption_model_type() == model_type.lower()

    def is_phi3_model(self) -> bool:
        """
        Check if caption generator is using Phi-3 with thread-safe caching.
        
        Returns:
            True if using Phi-3, False otherwise
        """
        cache_key = 'is_phi3_model'
        
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
                
            is_phi3 = self.is_model_type('phi3')
            self._cache[cache_key] = is_phi3
            logger.debug(f"Cached Phi-3 model check: {is_phi3}")
            return is_phi3
    
    def is_multimodal_model(self) -> bool:
        """
        Check if caption generator is a multimodal model with thread-safe caching.
        
        Returns:
            True if model supports vision, False otherwise
        """
        cache_key = 'is_multimodal_model'
        
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
                
            model_type = self.get_caption_model_type()
            model_info = self._model_type_registry.get(model_type, {})
            is_multimodal = model_info.get('multimodal', False)
            
            self._cache[cache_key] = is_multimodal
            logger.debug(f"Cached multimodal model check: {is_multimodal}")
            return is_multimodal
    
    def get_model_memory_requirements(self) -> Optional[Dict[str, Any]]:
        """
        Get memory requirements for the current caption model with thread-safe caching.
        
        Returns:
            Memory configuration dict or None if not available
        """
        cache_key = 'model_memory_requirements'
        
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
                
            try:
                memory_config = self.get_nested('caption_generator', 'config', 'memory_allocation')
                self._cache[cache_key] = memory_config
                return memory_config
            except KeyError:
                self._cache[cache_key] = None
                return None

    
    def clear_cache(self):
        """Clear all cached values with thread safety. Useful for testing or config reloads."""
        with self._cache_lock:
            self._cache.clear()
            logger.debug("ConfigService cache cleared")

