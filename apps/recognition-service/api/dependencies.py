"""
FastAPI dependency injection for shared services.

This module provides singleton instances of heavy components to avoid
repeated initialization and memory waste.
"""

import logging
from typing import Optional

from roster.domain.roster_service import RosterService
from roster.adapters.file_storage_adapter import FileRosterStorageAdapter
from roster.adapters.embedding_storage_adapter import EmbeddingStorageAdapter
from roster.adapters.data_validation_adapter import DataValidationAdapter

logger = logging.getLogger(__name__)

# Global cache for singleton services
_roster_service_instance: Optional[RosterService] = None


def get_roster_service() -> RosterService:
    """
    Get the singleton RosterService instance, with dynamic roster file selection
    based on the active entity recognition pipeline.
    """
    global _roster_service_instance
    
    if _roster_service_instance is not None:
        logger.debug("[DEPENDENCY] Reusing cached RosterService instance")
        return _roster_service_instance
    
    logger.info("[DEPENDENCY] Creating new RosterService instance")
    
    roster_storage = FileRosterStorageAdapter()
    embedding_storage = EmbeddingStorageAdapter()
    data_validator = DataValidationAdapter()

    _roster_service_instance = RosterService(
        roster_storage=roster_storage,
        embedding_storage=embedding_storage,
        data_validator=data_validator,
    )
    logger.info("[DEPENDENCY] RosterService instance created and cached")
    return _roster_service_instance


def set_roster_service(roster_service: RosterService):
    """
    Set the singleton RosterService instance (e.g., from startup pipeline).
    """
    global _roster_service_instance
    _roster_service_instance = roster_service
    logger.info("[DEPENDENCY] RosterService instance set from startup")


def reset_dependencies():
    """Reset all cached dependencies. Used for testing or reinitialization."""
    global _roster_service_instance
    _roster_service_instance = None
    logger.info("[DEPENDENCY] All cached dependencies reset")
