"""
Adapters Module

Exports all adapter implementations for external integrations.
"""

from .file_storage_adapter import FileRosterStorageAdapter
from .embedding_storage_adapter import EmbeddingStorageAdapter
from .data_validation_adapter import DataValidationAdapter

__all__ = [
    "FileRosterStorageAdapter",
    "EmbeddingStorageAdapter", 
    "DataValidationAdapter"
]
