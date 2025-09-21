import yaml
import logging
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
    
    # STRICT VALIDATION - No fallbacks allowed
    if 'object_detector' not in base_config:
        raise ValueError("Missing 'object_detector' configuration section in settings.yaml")
    # face_detector is optional - some configurations may not use face detection
    
    # Check for either new entity_recognition or legacy entity_identifier config
    has_entity_recognition = 'entity_recognition' in base_config
    has_entity_identifier = 'entity_identifier' in base_config
    
    if not has_entity_recognition and not has_entity_identifier:
        raise ValueError("Missing 'entity_recognition' or 'entity_identifier' configuration section in settings.yaml")
    
    # Validate entity identifier thresholds (legacy config)
    if has_entity_identifier:
        eid_root = base_config['entity_identifier']
        
        # Check if it's old-style with config section
        if 'config' in eid_root:
            eid_config = eid_root['config']
            if 'face_detection_threshold' not in eid_config:
                raise ValueError("Missing 'face_detection_threshold' in 'entity_identifier.config' in settings.yaml")
            if 'face_recognition_threshold' not in eid_config:
                raise ValueError("Missing 'face_recognition_threshold' in 'entity_identifier.config' in settings.yaml")
        
        # Check new-style nested configs (adaface_config, insightface_config)
        has_valid_config = False
        for conf_name in ['adaface_config', 'insightface_config']:
            conf = eid_root.get(conf_name, {})
            if conf:
                has_valid_config = True
                if 'face_detection_threshold' not in conf:
                    raise ValueError(f"Missing 'face_detection_threshold' in 'entity_identifier.{conf_name}' in settings.yaml")
                if 'face_recognition_threshold' not in conf:
                    raise ValueError(f"Missing 'face_recognition_threshold' in 'entity_identifier.{conf_name}' in settings.yaml")
        
        # If no config section and no nested configs, it's invalid
        if 'config' not in eid_root and not has_valid_config:
            raise ValueError("Entity identifier must have either 'config' section or 'adaface_config'/'insightface_config' sections in settings.yaml")
    
    # Validate entity recognition config (new config)
    if has_entity_recognition:
        er_config = base_config['entity_recognition']
        pipeline = er_config.get('pipeline', 'insightface')
        pipeline_config = er_config.get(pipeline, {})
        if not pipeline_config:
            raise ValueError(f"Missing '{pipeline}' pipeline configuration in entity_recognition section")
        if 'face_detection_threshold' not in pipeline_config:
            raise ValueError(f"Missing 'face_detection_threshold' in 'entity_recognition.{pipeline}' in settings.yaml")
        if 'face_recognition_threshold' not in pipeline_config:
            raise ValueError(f"Missing 'face_recognition_threshold' in 'entity_recognition.{pipeline}' in settings.yaml")
    
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

    # Configuration validation simplified for new recognition service
    # InsightFace now uses standard processing only

    environment_config = base_config['environment']
    caption_generator_config = base_config['caption_generator']

    # Validate caption generator configuration
    if 'config' not in caption_generator_config:
        raise ValueError("Missing 'config' section in 'caption_generator' configuration in settings.yaml")
    if 'model_id' not in caption_generator_config['config']:
        raise ValueError("Caption generator 'model_id' is missing from settings.yaml")
    
    # Validate MPS fallback configuration (optional)
    mps_fallback_config = caption_generator_config['config'].get('mps_fallback', {})
    if not isinstance(mps_fallback_config, dict):
        raise ValueError("Caption generator 'mps_fallback' must be a dict in settings.yaml")

    # Build adapters configuration from settings.yaml
    adapters_config = {
        'object_detector': {
            **base_config['object_detector']
        },
        'caption_generator': {
            **base_config['caption_generator']
        }
    }
    
    # Handle entity identification - check for new entity_recognition config first
    if 'entity_recognition' in base_config:
        # New structure - create backward-compatible entity_identifier from entity_recognition
        entity_recognition = base_config['entity_recognition']
        pipeline_type = entity_recognition.get('pipeline', 'insightface')
        
        # Get pipeline-specific config
        pipeline_config = entity_recognition.get(pipeline_type, {})
        
        # Create backward-compatible entity_identifier config
        adapters_config['entity_identifier'] = {
            'type': pipeline_type,
            'config': pipeline_config,
            f'{pipeline_type}_config': pipeline_config
        }
    elif 'entity_identifier' in base_config:
        # Legacy structure - use as-is
        adapters_config['entity_identifier'] = {
            **base_config['entity_identifier']
        }
    else:
        # Fallback - create minimal InsightFace config
        logger.warning("No entity recognition configuration found, using minimal InsightFace defaults")
        adapters_config['entity_identifier'] = {
            'type': 'insightface',
            'config': {
                'model_path': 'buffalo_l',
                'device': 'auto'
            },
            'insightface_config': {
                'model_path': 'buffalo_l',
                'device': 'auto'
            }
        }
    
    # Add face_detector only if it's configured
    if 'face_detector' in base_config:
        adapters_config['face_detector'] = {
            **base_config['face_detector']
        }

    # Return all relevant top-level keys, including runtime_optimizations and others
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
        'cache_dirs': base_config.get('cache_dirs', {}),
        'runtime_optimizations': base_config.get('runtime_optimizations', {}),
        'vision_model': base_config.get('vision_model', {}),
        'attention': base_config.get('attention', {}),
        'use_cache': base_config.get('use_cache', False),
        # Add new entity recognition configuration
        'entity_recognition': base_config.get('entity_recognition', {}),
        # Add any other top-level keys as needed
    }
    
    return result_config
