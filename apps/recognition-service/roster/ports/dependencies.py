"""
Dependency Injection for Roster Service

Manages service instance creation and dependency injection.
Follows the same pattern as the recognition service.
"""

import logging
import os
from typing import Optional

from ..domain import RosterService
from ..adapters import (
    DataValidationAdapter,
    PostgreSQLStorageAdapter,
)
from ..config import get_config
from ..adapters.database_storage_base import DEFAULT_TENANT_ID as DB_DEFAULT_TENANT

logger = logging.getLogger(__name__)

# Global service instance
_roster_service: Optional[RosterService] = None


def get_roster_service() -> RosterService:
    """
    Get or create roster service instance.
    
    Returns:
        Roster service singleton
    """
    global _roster_service
    
    if _roster_service is None:
        _roster_service = create_roster_service()
    
    return _roster_service


def _create_roster_storage():
    """
    Create PostgreSQL storage adapter.
    
    This project requires PostgreSQL 17+ with pgvector extension.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError(
            "DATABASE_URL environment variable is required. "
            "This project requires PostgreSQL 17+ with pgvector extension. "
            "Example: postgresql://user:pass@localhost:5432/recognition"
        )

    if not database_url.startswith("postgresql"):
        raise ValueError(
            f"Invalid DATABASE_URL scheme: {database_url}. "
            "Only PostgreSQL is supported (postgresql:// or postgresql+psycopg2://). "
            "SQLite and other databases are not supported."
        )

    tenant_id = os.getenv("DEFAULT_TENANT_ID", str(DB_DEFAULT_TENANT))

    logger.info("📦 Creating PostgreSQL roster storage adapter")
    return PostgreSQLStorageAdapter(database_url=database_url, tenant_id=tenant_id)


def create_roster_service() -> RosterService:
    """
    Create and configure roster service with all dependencies.
    
    Returns:
        Configured roster service
    """
    logger.info("🚀 Creating roster service...")
    
    try:
        # Get configuration
        config = get_config()
        logger.info(f"Loaded configuration for data directory: {config.get_data_dir()}")
        
        # Create adapters
        logger.info("📁 Creating storage adapters...")
        roster_storage = _create_roster_storage()
        data_validator = DataValidationAdapter()
        
        # Create domain service
        logger.info("🏗️ Creating domain service...")
        roster_service = RosterService(
            roster_storage=roster_storage,
            data_validator=data_validator
        )
        
        logger.info("✅ Roster service created successfully")
        return roster_service
        
    except Exception as e:
        logger.error(f"❌ Failed to create roster service: {e}")
        raise


def reset_roster_service():
    """
    Reset the global service instance (useful for testing).
    """
    global _roster_service
    _roster_service = None
    logger.info("🔄 Roster service instance reset")
