"""
FastAPI dependency injection for shared services.

This module provides singleton instances of heavy components to avoid
repeated initialization and memory waste.
"""

import logging
from typing import Optional, Union
from functools import lru_cache

from roster.domain.roster_service import RosterService
from shared.config.config_service import ConfigService
from roster.adapters.file_storage_adapter import FileRosterStorageAdapter
from recognition.pipelines.pipeline_manager import get_hf_pipeline

logger = logging.getLogger(__name__)

# Global cache for singleton services
_roster_service_instance: Optional[RosterService] = None
_entity_identifier_instance: Optional[Union[object]] = None


def get_pipeline_specific_roster_path(config: dict) -> str:
    """
    Determine the roster file path based on the active entity recognition pipeline.
    
    Args:
        config: The application configuration
        
    Returns:
        Path to the appropriate roster file
    """
    # Check for new entity_recognition configuration
    if 'entity_recognition' in config:
        entity_recognition = config['entity_recognition']
        pipeline_type = entity_recognition.get('pipeline', 'insightface')
        
        # Get pipeline-specific roster file if specified
        pipeline_config = entity_recognition.get(pipeline_type, {})
        roster_file_path = pipeline_config.get('roster_file_path')
        
        if roster_file_path:
            logger.info(f"[DEPENDENCY] Using {pipeline_type}-specific roster: {roster_file_path}")
            return roster_file_path
    
    # Fall back to legacy entity_identifier config
    adapters_config = config.get('adapters', {})
    if 'entity_identifier' in adapters_config:
        entity_identifier_config = adapters_config['entity_identifier']
        entity_type = entity_identifier_config.get('type', 'insightface')
        
        # Try to get roster path from pipeline-specific config
        pipeline_config = entity_identifier_config.get(f'{entity_type}_config', {})
        roster_file_path = pipeline_config.get('roster_file_path')
        
        if roster_file_path:
            logger.info(f"[DEPENDENCY] Using legacy {entity_type}-specific roster: {roster_file_path}")
            return roster_file_path
    
    # Final fallback to global roster_storage config
    roster_storage_config = config.get('roster_storage', {}).get('config', {})
    default_path = roster_storage_config.get('roster_file_path', 'data/roster.json')
    
    logger.info(f"[DEPENDENCY] Using default roster: {default_path}")
    return default_path


def get_roster_service() -> RosterService:
    """
    Get the singleton RosterService instance, with dynamic roster file selection
    based on the active entity recognition pipeline.
    """
    global _roster_service_instance, _entity_identifier_instance
    
    if _roster_service_instance is not None:
        logger.debug("[DEPENDENCY] Reusing cached RosterService instance")
        return _roster_service_instance
    
    logger.info("[DEPENDENCY] Creating new RosterService instance")
    
    # Set up config and storage with dynamic roster file selection
    config_service = ConfigService()
    config = config_service._config
    
    # Determine which roster file to use based on active pipeline
    roster_file_path = get_pipeline_specific_roster_path(config)
    logger.info(f"[DEPENDENCY] Using roster file: {roster_file_path}")
    
    roster_storage = FileRosterStorageAdapter()
    
    # Try to get the already-initialized entity_identifier from the scene_composer
    entity_identifier = None
    try:
        from api.routes.main import _scene_analysis_service
        scene_analysis_service = _scene_analysis_service
        if (scene_analysis_service and 
            hasattr(scene_analysis_service, 'scene_composer') and 
            hasattr(scene_analysis_service.scene_composer, 'entity_identifier')):
            entity_identifier = scene_analysis_service.scene_composer.entity_identifier
            logger.info("[DEPENDENCY] Reusing entity_identifier from scene_composer")
        else:
            logger.debug("[DEPENDENCY] Scene analysis service or entity_identifier not available yet")
    except Exception as e:
        logger.debug(f"[DEPENDENCY] Could not access scene_composer entity_identifier: {e}")
    
    # Only create entity_identifier if not available from scene_composer AND not cached
    if entity_identifier is None:
        if _entity_identifier_instance is not None:
            logger.info("[DEPENDENCY] Reusing cached entity_identifier instance")
            entity_identifier = _entity_identifier_instance
        else:
            logger.warning("[DEPENDENCY] Creating new entity_identifier instance - this should only happen during testing or early startup")
            # Use pipeline manager to get the appropriate pipeline (AdaFace or InsightFace)
            entity_identifier = get_hf_pipeline(roster_service=None)  # Will be set below
            _entity_identifier_instance = entity_identifier
    
    # Create roster service
    _roster_service_instance = RosterService(roster_storage, entity_identifier, config)
    
    # Set bidirectional reference
    if entity_identifier:
        entity_identifier.roster_service = _roster_service_instance
    
    logger.info("[DEPENDENCY] RosterService instance created and cached")
    return _roster_service_instance


def set_entity_identifier(entity_identifier: Union[object]):
    """
    Set the singleton entity_identifier instance (e.g., from startup pipeline).
    Works with any pipeline type (AdaFace, InsightFace, etc.).
    """
    global _entity_identifier_instance
    _entity_identifier_instance = entity_identifier
    logger.info("[DEPENDENCY] Entity identifier instance set from startup")


def set_roster_service(roster_service: RosterService):
    """
    Set the singleton RosterService instance (e.g., from startup pipeline).
    """
    global _roster_service_instance
    _roster_service_instance = roster_service
    logger.info("[DEPENDENCY] RosterService instance set from startup")


def reset_dependencies():
    """Reset all cached dependencies. Used for testing or reinitialization."""
    global _roster_service_instance, _entity_identifier_instance
    _roster_service_instance = None
    _entity_identifier_instance = None
    logger.info("[DEPENDENCY] All cached dependencies reset")