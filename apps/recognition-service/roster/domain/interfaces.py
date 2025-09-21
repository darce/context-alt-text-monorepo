"""
Domain Interfaces (Ports) for Roster Service

Abstract interfaces that define the contracts for external dependencies.
These follow the dependency inversion principle - domain defines what it needs,
adapters implement how to provide it.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from .entities import RosterEntry


class RosterStoragePort(ABC):
    """
    Port for roster persistence operations.
    
    Simplified from legacy IRosterStorage:
    - Removed complex query methods not needed for MVP
    - Focused on essential CRUD operations
    - Consistent return types for error handling
    """
    
    @abstractmethod
    def save_roster_entry(self, entry: RosterEntry, model: str) -> bool:
        """
        Save or update a roster entry for a specific model.
        
        Args:
            entry: The roster entry to save
            model: Model identifier (e.g., 'adaface_ir101')
            
        Returns:
            True if saved successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def load_roster_entries(self, model: str) -> List[RosterEntry]:
        """
        Load all roster entries for a specific model.
        
        Args:
            model: Model identifier
            
        Returns:
            List of roster entries (empty if none found)
        """
        pass
    
    @abstractmethod
    def get_roster_entry(self, unique_id: str, model: str) -> Optional[RosterEntry]:
        """
        Get a specific roster entry by ID.
        
        Args:
            unique_id: Unique identifier of the entry
            model: Model identifier
            
        Returns:
            RosterEntry if found, None otherwise
        """
        pass
    
    @abstractmethod
    def delete_roster_entry(self, unique_id: str, model: str) -> bool:
        """
        Delete a roster entry by ID.
        
        Args:
            unique_id: Unique identifier of the entry
            model: Model identifier
            
        Returns:
            True if deleted successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def roster_exists(self, model: str) -> bool:
        """
        Check if a roster exists for the given model.
        
        Args:
            model: Model identifier
            
        Returns:
            True if roster exists, False otherwise
        """
        pass
    
    @abstractmethod
    def clear_roster(self, model: str) -> bool:
        """
        Clear all entries from a roster.
        
        Args:
            model: Model identifier
            
        Returns:
            True if cleared successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def get_storage_info(self, model: str) -> Dict[str, Any]:
        """
        Get storage information for debugging/monitoring.
        
        Args:
            model: Model identifier
            
        Returns:
            Dictionary with storage metadata
        """
        pass


class EmbeddingStoragePort(ABC):
    """
    Port for embedding-specific storage operations.
    
    Handles model-specific embedding files and versioning.
    """
    
    @abstractmethod
    def save_embeddings(self, entries: List[RosterEntry], model: str) -> bool:
        """
        Save embeddings to model-specific storage.
        
        Args:
            entries: List of roster entries with embeddings
            model: Model identifier
            
        Returns:
            True if saved successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def load_embeddings(self, model: str) -> List[Dict[str, Any]]:
        """
        Load embeddings from model-specific storage.
        
        Args:
            model: Model identifier
            
        Returns:
            List of embedding data dictionaries
        """
        pass
    
    @abstractmethod
    def watch_embeddings_file(self, model: str, callback) -> bool:
        """
        Set up file watcher for hot-reload functionality.
        
        Args:
            model: Model identifier
            callback: Function to call when file changes
            
        Returns:
            True if watcher set up successfully, False otherwise
        """
        pass


class DataValidationPort(ABC):
    """
    Port for data validation operations.
    
    Handles validation of imports, schema validation, etc.
    """
    
    @abstractmethod
    def validate_roster_entry(self, entry_data: Dict[str, Any]) -> List[str]:
        """
        Validate roster entry data.
        
        Args:
            entry_data: Raw entry data to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        pass
    
    @abstractmethod
    def validate_embedding(self, embedding: List[float], model: str) -> List[str]:
        """
        Validate embedding data for a specific model.
        
        Args:
            embedding: Embedding vector to validate
            model: Model identifier for dimension checking
            
        Returns:
            List of validation errors (empty if valid)
        """
        pass
    
    @abstractmethod
    def validate_bulk_import(self, import_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate bulk import data.
        
        Args:
            import_data: List of entries to validate
            
        Returns:
            Validation result with errors and warnings
        """
        pass
