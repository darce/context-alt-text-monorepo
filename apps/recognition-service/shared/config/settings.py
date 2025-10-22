import yaml
import logging
import os
from typing import Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

def load_yaml_config(config_path: str = None) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    if config_path is None:
        # Default to settings.yaml in the same directory as this file
        config_dir = Path(__file__).parent
        config_path = config_dir / "settings.yaml"
    
    try:
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
        return config
    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    except yaml.YAMLError as e:
        raise ValueError(f"Error parsing YAML configuration: {e}")

def get_config() -> Dict[str, Any]:
    """Get the complete configuration from settings.yaml only (no environment overrides)."""
    # Load base config from YAML
    base_config = load_yaml_config()
    
    if 'object_detector' not in base_config:
        raise ValueError("Missing 'object_detector' configuration section in settings.yaml")

    if 'caption_generator' not in base_config:
        raise ValueError("Missing 'caption_generator' configuration section in settings.yaml")
    if 'caption' not in base_config:
        raise ValueError("Missing 'caption' configuration section in settings.yaml")
    if 'environment' not in base_config:
        raise ValueError("Missing 'environment' configuration section in settings.yaml")
    if 'roster_storage' not in base_config:
        raise ValueError("Missing 'roster_storage' configuration section in settings.yaml")
    
    # Validate roster storage configuration
    roster_storage_config = base_config['roster_storage'].get('config', {})
    if 'roster_file_path' not in roster_storage_config:
        raise ValueError("Missing 'roster_file_path' in 'roster_storage.config' in settings.yaml")

    # Validate media storage configuration
    if 'media_storage' not in base_config:
        raise ValueError("Missing 'media_storage' configuration section in settings.yaml")
    media_storage_config = base_config['media_storage'].get('config', {})
    if 'upload_directory' not in media_storage_config:
        raise ValueError("Missing 'upload_directory' in 'media_storage.config' in settings.yaml")

    # Validate startup configuration
    if 'startup' not in base_config:
        raise ValueError("Missing 'startup' configuration section in settings.yaml")
    startup_config = base_config['startup']
    required_startup_keys = ['timeout_seconds', 'background_initialization', 'warmup_check_enabled', 
        'flash_attention_check_enabled', 'device_auto_detection', 'enable_metrics', 'verbose_logging']
    for key in required_startup_keys:
        if key not in startup_config:
            raise ValueError(f"Missing '{key}' in 'startup' configuration in settings.yaml")

    # Validate context_builder configuration
    if 'context_builder' not in base_config:
        raise ValueError("Missing 'context_builder' configuration section in settings.yaml")
    context_builder_config = base_config['context_builder']
    required_context_keys = ['max_excerpt_length', 'caption_prefix', 'context_prefix', 'separator']
    for key in required_context_keys:
        if key not in context_builder_config:
            raise ValueError(f"Missing '{key}' in 'context_builder' configuration in settings.yaml")

    environment_config = base_config['environment']
    caption_generator_config = base_config['caption_generator']

    if 'config' not in caption_generator_config:
        raise ValueError("Missing 'config' section in 'caption_generator' configuration in settings.yaml")
    if 'model_id' not in caption_generator_config['config']:
        raise ValueError("Caption generator 'model_id' is missing from settings.yaml")

    adapters_config = {
        'object_detector': {**base_config['object_detector']},
        'caption_generator': {**caption_generator_config},
    }

    if 'face_detector' in base_config:
        adapters_config['face_detector'] = {**base_config['face_detector']}

    result_config = {
        'adapters': adapters_config,
        'server': base_config.get('server', {}),
        'caption': base_config.get('caption', {}),
        'caption_generator': caption_generator_config,
        'environment': environment_config,
        'roster_storage': base_config.get('roster_storage', {}),
        'media_storage': base_config.get('media_storage', {}),
        'startup': base_config.get('startup', {}),
        'context_builder': base_config.get('context_builder', {}),
        'debug': base_config.get('debug', {}),
        'clustering': base_config.get('clustering', {}),
        'runtime_optimizations': base_config.get('runtime_optimizations', {}),
        'vision_model': base_config.get('vision_model', {}),
        'attention': base_config.get('attention', {}),
        'hardware': base_config.get('hardware', {}),
    }

    return result_config


def get_clustering_config() -> Dict[str, Any]:
    """
    Get clustering configuration with environment variable overrides.
    
    Environment variables override YAML settings:
    - CLUSTER_ALGORITHM: dbscan or agglomerative
    - CLUSTER_THRESHOLD: float (0.0-2.0)
    - CLUSTER_MIN_SAMPLES: int (1-10)
    - CLUSTER_LINKAGE: average, complete, or single
    
    Returns:
        Dictionary with clustering configuration
        
    Raises:
        ValueError: If configuration is invalid
    """
    config = get_config()
    clustering_config = config.get('clustering', {})
    
    # Default values
    defaults = {
        'algorithm': 'dbscan',
        'distance_threshold': 0.6,
        'min_samples': 2,
        'linkage': 'average',
    }
    
    # Merge YAML config with defaults
    result = {**defaults, **clustering_config}
    
    # Environment variable overrides
    if env_algorithm := os.getenv('CLUSTER_ALGORITHM'):
        if env_algorithm not in ['dbscan', 'agglomerative']:
            raise ValueError(
                f"Invalid CLUSTER_ALGORITHM: {env_algorithm}. "
                "Must be 'dbscan' or 'agglomerative'"
            )
        result['algorithm'] = env_algorithm
    
    if env_threshold := os.getenv('CLUSTER_THRESHOLD'):
        try:
            threshold = float(env_threshold)
            if not 0.0 <= threshold <= 2.0:
                raise ValueError("Threshold must be between 0.0 and 2.0")
            result['distance_threshold'] = threshold
        except ValueError as e:
            raise ValueError(f"Invalid CLUSTER_THRESHOLD: {env_threshold}. {e}")
    
    if env_min_samples := os.getenv('CLUSTER_MIN_SAMPLES'):
        try:
            min_samples = int(env_min_samples)
            if not 1 <= min_samples <= 10:
                raise ValueError("min_samples must be between 1 and 10")
            result['min_samples'] = min_samples
        except ValueError as e:
            raise ValueError(f"Invalid CLUSTER_MIN_SAMPLES: {env_min_samples}. {e}")
    
    if env_linkage := os.getenv('CLUSTER_LINKAGE'):
        if env_linkage not in ['average', 'complete', 'single']:
            raise ValueError(
                f"Invalid CLUSTER_LINKAGE: {env_linkage}. "
                "Must be 'average', 'complete', or 'single'"
            )
        result['linkage'] = env_linkage
    
    logger.debug(
        f"Clustering config loaded: algorithm={result['algorithm']}, "
        f"threshold={result['distance_threshold']}, "
        f"min_samples={result['min_samples']}, "
        f"linkage={result['linkage']}"
    )
    
    return result
