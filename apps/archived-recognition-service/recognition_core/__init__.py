"""
Recognition Service Module

InsightFace-only recognition service for face detection, embedding extraction,
and roster matching. Simplified from the previous multi-model implementation.

This module provides:
- Face detection using InsightFace
- Face embedding extraction  
- Roster matching with cosine similarity
- Compatible API endpoints

Architecture:
- Domain: Core business logic and interfaces
- Adapters: InsightFace wrapper and embedding router
- Services: Main recognition orchestration
- Ports: FastAPI routes and API contracts
- Utils: Helper functions and format conversion
- Pipelines: Compatibility layer for old pipeline manager
"""

from .config import get_settings, load_settings, reload_settings

__version__ = "2.0.0"

__all__ = [
    "get_settings",
    "load_settings",
    "reload_settings",
]
