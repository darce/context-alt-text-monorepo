"""
Data Transfer Objects (DTOs) for the Entity Identifier API

This module contains DTOs used for API communication and data transfer
between different layers of the application.
"""

from dataclasses import dataclass
from typing import Optional, Dict, List, Any
from datetime import datetime


@dataclass
class AddRosterCmd:
    """Command object for adding an entity to the roster."""
    name: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class RosterEntryDTO:
    """Data Transfer Object for roster entries."""
    unique_id: str
    name: str
    display_name: str
    roster_image_path: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_timestamp: Optional[datetime] = None
    updated_timestamp: Optional[datetime] = None
    face_bbox: Optional[List[float]] = None
    face_confidence: Optional[float] = None
    image_count: int = 0
    aggregate_embedding: Optional[List[float]] = None
    embedding_length: Optional[int] = None
    reference_embeddings: Optional[List[List[float]]] = None

    def model_dump(self) -> Dict[str, Any]:
        """Return a dict representation of this DTO for serialization."""
        from dataclasses import asdict
        return asdict(self)
