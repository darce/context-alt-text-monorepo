"""
Adapters Module

Exports all adapter implementations for external integrations.

Note: This project requires PostgreSQL 17+ with pgvector extension.
"""

from .postgresql_storage_adapter import PostgreSQLStorageAdapter
from .data_validation_adapter import DataValidationAdapter

__all__ = [
    "PostgreSQLStorageAdapter",
    "DataValidationAdapter"
]
