"""FastAPI dependency injection for shared services."""

import logging
import os
from typing import Optional

from roster.adapters.database_storage_base import DEFAULT_TENANT_ID as DB_DEFAULT_TENANT
from roster.adapters.data_validation_adapter import DataValidationAdapter
from roster.adapters.postgresql_storage_adapter import PostgreSQLStorageAdapter
from roster.domain.interfaces import RosterStoragePort
from roster.domain.roster_service import RosterService
from recognition_core.adapters import EmbeddingRouterAdapter
from recognition_core.services import FaceRecognitionService

logger = logging.getLogger(__name__)

# Global cache for singleton services
_roster_service_instance: Optional[RosterService] = None
_recognition_service_instance: Optional[FaceRecognitionService] = None


def _select_roster_storage() -> RosterStoragePort:
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

    try:
        logger.info("[DEPENDENCY] Using PostgreSQL storage adapter")
        return PostgreSQLStorageAdapter(database_url=database_url, tenant_id=tenant_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to initialise database adapter: %s", exc, exc_info=True)
        raise


def get_roster_service() -> RosterService:
    """
    Get the singleton RosterService instance.
    """
    global _roster_service_instance
    
    if _roster_service_instance is not None:
        logger.debug("[DEPENDENCY] Reusing cached RosterService instance")
        return _roster_service_instance
    
    logger.info("[DEPENDENCY] Creating new RosterService instance")
    
    roster_storage = _select_roster_storage()
    data_validator = DataValidationAdapter()

    _roster_service_instance = RosterService(
        roster_storage=roster_storage,
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


def get_recognition_service() -> FaceRecognitionService:
    """Return the shared FaceRecognitionService instance."""
    global _recognition_service_instance

    if _recognition_service_instance is not None:
        return _recognition_service_instance

    logger.info("[DEPENDENCY] Creating new FaceRecognitionService instance")

    roster_service = get_roster_service()
    storage_adapter = roster_service.roster_storage
    embedding_router = EmbeddingRouterAdapter(storage_adapter=storage_adapter)

    _recognition_service_instance = FaceRecognitionService(embedding_router=embedding_router)
    return _recognition_service_instance


def set_recognition_service(service: FaceRecognitionService) -> None:
    """Inject a FaceRecognitionService singleton (used by startup/tests)."""
    global _recognition_service_instance
    _recognition_service_instance = service
    logger.info("[DEPENDENCY] FaceRecognitionService instance set from startup")


def reset_dependencies():
    """Reset all cached dependencies. Used for testing or reinitialization."""
    global _roster_service_instance, _recognition_service_instance
    _roster_service_instance = None
    _recognition_service_instance = None
    logger.info("[DEPENDENCY] All cached dependencies reset")
