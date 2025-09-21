"""
Roster Service Domain Logic

Core business logic for managing roster entries and embeddings.
This is the heart of the domain layer - pure business logic with no external dependencies.
"""

import logging
from typing import List, Optional, Dict, Any
from .entities import RosterEntry, RosterImage, RosterMatch
from .interfaces import RosterStoragePort, EmbeddingStoragePort, DataValidationPort

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
        embedding_storage: EmbeddingStoragePort,
        data_validator: DataValidationPort
    ):
        """
        Initialize roster service with injected dependencies.
        
        Args:
            roster_storage: Storage adapter for roster data
            embedding_storage: Storage adapter for embeddings
            data_validator: Validator for data integrity
        """
        self.roster_storage = roster_storage
        self.embedding_storage = embedding_storage
        self.data_validator = data_validator
        self._cache: Dict[str, List[RosterEntry]] = {}
        
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
            # Validate embedding
            embedding_errors = self.data_validator.validate_embedding(embedding, model)
            if embedding_errors:
                logger.error(f"Embedding validation failed: {embedding_errors}")
                return None
            
            # Create roster image
            roster_image = RosterImage(
                embedding=embedding,
                metadata=metadata or {},
                image_path=image_path
            )
            
            # Check if entry with this name already exists
            existing_entries = self.roster_storage.load_roster_entries(model)
            existing_entry = next((e for e in existing_entries if e.name == name), None)
            
            if existing_entry:
                # Add reference image to existing entry
                existing_entry.add_reference_image(roster_image)
                success = self.roster_storage.save_roster_entry(existing_entry, model)
                if success:
                    self._invalidate_cache(model)
                    logger.info(f"Added reference image to existing entry: {name}")
                    return existing_entry
            else:
                # Create new entry
                roster_entry = RosterEntry(
                    name=name,
                    reference_images=[roster_image],
                    metadata=metadata or {}
                )
                
                # Save the entry (embedding already validated above)
                success = self.roster_storage.save_roster_entry(roster_entry, model)
                if success:
                    self._invalidate_cache(model)
                    logger.info(f"Created new roster entry: {name}")
                    return roster_entry
            
            return None
            
        except Exception as e:
            logger.error(f"Error adding roster entry: {e}")
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
        successful_names = []
        
        # Basic validation - check bulk size limit
        max_bulk_size = self.data_validator.validation_config.get("max_bulk_import_size", 1000)
        if len(entries_data) > max_bulk_size:
            logger.error(f"Bulk import too large: {len(entries_data)} entries (max {max_bulk_size})")
            return successful_names

        for entry_data in entries_data:
            try:
                name = entry_data.get("name")
                embedding = entry_data.get("embedding")
                metadata = entry_data.get("metadata", {})
                image_path = entry_data.get("image_path")
                
                if not name or not embedding:
                    logger.warning(f"Skipping invalid entry: {entry_data}")
                    continue
                
                result = self.add_entry(name, embedding, model, metadata, image_path)
                if result:
                    successful_names.append(name)
                    
            except Exception as e:
                logger.error(f"Error processing bulk entry: {e}")
                continue
        
        logger.info(f"Bulk add completed: {len(successful_names)}/{len(entries_data)} successful")
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
        if use_cache and model in self._cache:
            return self._cache[model]
        
        entries = self.roster_storage.load_roster_entries(model)
        self._cache[model] = entries
        return entries
    
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
        entry = self.roster_storage.get_roster_entry(unique_id, model)
        if not entry:
            return False
        
        try:
            if embedding:
                # Add new reference image
                roster_image = RosterImage(
                    embedding=embedding,
                    metadata=metadata or {},
                    image_path=image_path
                )
                entry.add_reference_image(roster_image)
            
            if metadata:
                entry.metadata.update(metadata)
                entry.update_timestamp()
            
            success = self.roster_storage.save_roster_entry(entry, model)
            if success:
                self._invalidate_cache(model)
            
            return success
            
        except Exception as e:
            logger.error(f"Error updating entry: {e}")
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
        success = self.roster_storage.delete_roster_entry(unique_id, model)
        if success:
            self._invalidate_cache(model)
        return success
    
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
        success = self.roster_storage.clear_roster(model)
        if success:
            self._invalidate_cache(model)
        return success
    
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
        if model in self._cache:
            del self._cache[model]
        logger.debug(f"Cache invalidated for model: {model}")
