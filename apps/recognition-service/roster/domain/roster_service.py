"""
Roster Service Domain Logic

Core business logic for managing roster entries and embeddings.
This is the heart of the domain layer - pure business logic with no external dependencies.
"""

import logging
from typing import Any, Dict, List, Optional

from .cache import RosterCache
from .embedding_sync import sync_embeddings_store
from .entities import RosterEntry, RosterMatch
from .interfaces import DataValidationPort, EmbeddingStoragePort, RosterStoragePort
from .operations import (
    add_augmented_embedding,
    add_entries_bulk,
    add_entry,
    clear_roster,
    delete_entry,
    update_entry,
)

logger = logging.getLogger(__name__)


class RosterService:
    """
    Main domain service for roster management.
    
    Simplified architecture compared to legacy:
    - Single service instead of multiple domain services
    - Dependency injection for all external concerns
    - Pure business logic without adapter knowledge
    """
    
    def __init__(
        self,
        roster_storage: RosterStoragePort,
        data_validator: DataValidationPort,
        embedding_storage: Optional[EmbeddingStoragePort] = None,
    ):
        """
        Initialize roster service with injected dependencies.
        
        Args:
            roster_storage: Storage adapter for roster data (required)
            data_validator: Validator for data integrity (required)
            embedding_storage: Optional auxiliary storage hook (unused in pgvector path)
        """
        self.roster_storage = roster_storage
        self.embedding_storage = embedding_storage
        self.data_validator = data_validator
        self.default_model = "insightface_w600k"
        self._cache = RosterCache()
        
    def add_entry(
        self,
        name: str,
        embedding: List[float],
        model: str,
        metadata: Optional[Dict[str, Any]] = None,
        image_path: Optional[str] = None
    ) -> Optional[RosterEntry]:
        """
        Add a new entry to the roster.
        
        Args:
            name: Identity name
            embedding: Face embedding vector
            model: Model identifier
            metadata: Optional metadata
            image_path: Optional path to reference image
            
        Returns:
            Created RosterEntry if successful, None otherwise
        """
        try:
            result = add_entry(
                name,
                embedding,
                model,
                self.roster_storage,
                self.data_validator,
                metadata=metadata,
                image_path=image_path,
                logger=logger,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error adding roster entry %s: %s", name, exc)
            return None

        if result.success and result.entry:
            self._after_mutation(model)
            return result.entry

        return None
    
    def add_entries_bulk(
        self,
        entries_data: List[Dict[str, Any]],
        model: str
    ) -> List[str]:
        """
        Add multiple entries in bulk.
        
        Args:
            entries_data: List of entry data dictionaries
            model: Model identifier
            
        Returns:
            List of successfully added entry names
        """
        try:
            successful_names, failures = add_entries_bulk(
                entries_data,
                model,
                self.roster_storage,
                self.data_validator,
                logger=logger,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Bulk add failed for model %s: %s", model, exc)
            return []

        if failures:
            logger.debug("Bulk add encountered failures: %s", failures)

        if successful_names:
            self._after_mutation(model)
        return successful_names
    
    def get_entries(self, model: str, use_cache: bool = True) -> List[RosterEntry]:
        """
        Get all roster entries for a model.
        
        Args:
            model: Model identifier
            use_cache: Whether to use cached entries
            
        Returns:
            List of roster entries
        """
        if use_cache:
            cached = self._cache.peek(model)
            if cached is not None:
                return cached

        return self._cache.get_or_load(model, lambda: self.roster_storage.load_roster_entries(model))
    
    def get_entry(self, unique_id: str, model: str) -> Optional[RosterEntry]:
        """
        Get a specific roster entry by ID.
        
        Args:
            unique_id: Unique identifier
            model: Model identifier
            
        Returns:
            RosterEntry if found, None otherwise
        """
        return self.roster_storage.get_roster_entry(unique_id, model)
    
    def update_entry(
        self,
        unique_id: str,
        model: str,
        embedding: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        image_path: Optional[str] = None
    ) -> bool:
        """
        Update an existing roster entry.
        
        Args:
            unique_id: Unique identifier
            model: Model identifier
            embedding: New embedding (optional)
            metadata: New metadata (optional)
            image_path: New image path (optional)
            
        Returns:
            True if updated successfully, False otherwise
        """
        try:
            result = update_entry(
                unique_id,
                model,
                self.roster_storage,
                embedding=embedding,
                metadata=metadata,
                image_path=image_path,
                validator=self.data_validator,
                logger=logger,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error updating roster entry %s: %s", unique_id, exc)
            return False

        if result.success:
            self._after_mutation(model)
        return result.success
    
    def add_augmented_embedding(
        self,
        unique_id: str,
        model: str,
        embedding: List[float],
        source: str,
        observation_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Append an augmented embedding to an existing roster entry.

        Args:
            unique_id: Roster entry identifier.
            model: Model identifier.
            embedding: Embedding vector from confirmation workflow.
            source: Origin of the embedding (e.g., 'external_confirm').
            observation_id: Observation identifier used for deduplication.
            metadata: Additional metadata (confidence, bbox, attachment_id, etc.).

        Returns:
            True if the embedding was stored, False otherwise.
        """
        try:
            result = add_augmented_embedding(
                unique_id,
                model,
                embedding,
                source,
                observation_id,
                self.roster_storage,
                self.data_validator,
                metadata=metadata,
                logger=logger,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "Error augmenting roster entry %s with observation %s: %s",
                unique_id,
                observation_id,
                exc,
            )
            return False

        if result.success:
            self._after_mutation(model)
            return True

        return False
    
    def delete_entry(self, unique_id: str, model: str) -> bool:
        """
        Delete a roster entry.
        
        Args:
            unique_id: Unique identifier
            model: Model identifier
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            result = delete_entry(unique_id, model, self.roster_storage)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error deleting roster entry %s: %s", unique_id, exc)
            return False
        if result.success:
            self._after_mutation(model)
        return result.success
    
    def get_entry_count(self, model: str) -> int:
        """
        Get the number of entries in a roster.
        
        Args:
            model: Model identifier
            
        Returns:
            Number of entries
        """
        entries = self.get_entries(model)
        return len(entries)
    
    def clear_roster(self, model: str) -> bool:
        """
        Clear all entries from a roster.
        
        Args:
            model: Model identifier
            
        Returns:
            True if cleared successfully, False otherwise
        """
        try:
            result = clear_roster(model, self.roster_storage)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error clearing roster for model %s: %s", model, exc)
            return False
        if result.success:
            self._after_mutation(model)
        return result.success
    
    def get_storage_info(self, model: str) -> Dict[str, Any]:
        """
        Get storage information for monitoring.
        
        Args:
            model: Model identifier
            
        Returns:
            Storage information dictionary
        """
        return self.roster_storage.get_storage_info(model)
    
    def get_roster_images(self, model: str = "insightface_w600k") -> List[Dict[str, Any]]:
        """
        Get roster entries in the format expected by scene analysis service.
        
        Args:
            model: Model identifier to get entries for
            
        Returns:
            List of dictionaries with roster entry information
        """
        try:
            entries = self.get_entries(model)
            roster_images = []
            
            for entry in entries:
                # Convert each roster entry to the expected dictionary format
                roster_dict = {
                    'name': entry.name,
                    'display_name': entry.display_name,
                    'unique_id': entry.unique_id,
                    'aggregate_embedding': entry.aggregate_embedding,
                    'image_count': entry.image_count,
                    'metadata': entry.metadata
                }
                roster_images.append(roster_dict)
                
            logger.debug(f"Retrieved {len(roster_images)} roster images for model: {model}")
            return roster_images
            
        except Exception as e:
            logger.error(f"Failed to get roster images for model {model}: {e}")
            return []
    
    def _invalidate_cache(self, model: str):
        """Invalidate cache for a specific model."""
        self._cache.invalidate(model)
        logger.debug(f"Cache invalidated for model: {model}")

    def _sync_embeddings_store(self, model: str):
        """Persist merged embeddings for recognition service consumption."""
        sync_embeddings_store(self.embedding_storage, self.roster_storage, model, logger)

    def _after_mutation(self, model: str) -> None:
        """Common post-mutation hooks."""
        self._invalidate_cache(model)
        self._sync_embeddings_store(model)
