"""
Domain Entities for Roster Service

Core business objects representing roster entries, images, and related data.
These are pure domain objects without any external dependencies.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import uuid
import numpy as np


@dataclass
class RosterImage:
    """
    Represents a single reference image with its embedding and metadata.
    """
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    image_path: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "embedding": self.embedding,
            "metadata": self.metadata,
            "image_path": self.image_path
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RosterImage":
        """Create from dictionary during deserialization."""
        return cls(
            embedding=data["embedding"],
            metadata=data.get("metadata", {}),
            image_path=data.get("image_path")
        )


@dataclass
class RosterEntry:
    """
    Represents a single identity in the roster with reference images and aggregated embedding.
    
    Simplified from legacy version:
    - Removed occlusion-related fields
    - Focused on essential identity data
    - Auto-generates IDs and timestamps
    """
    name: str
    reference_images: List[RosterImage] = field(default_factory=list)
    display_name: str = ""
    unique_id: str = ""
    aggregate_embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_timestamp: Optional[str] = None
    updated_timestamp: Optional[str] = None
    
    def __post_init__(self):
        """Post-initialization to set defaults and compute derived fields."""
        self._ensure_unique_id()
        self._ensure_display_name()
        self._ensure_timestamps()
        self._compute_aggregate_embedding()
    
    def _ensure_unique_id(self):
        """Generate unique ID if not provided."""
        if not self.unique_id:
            self.unique_id = str(uuid.uuid4())
    
    def _ensure_display_name(self):
        """Set display name to name if not provided."""
        if not self.display_name:
            self.display_name = self.name
    
    def _ensure_timestamps(self):
        """Set creation and update timestamps."""
        now = datetime.now().isoformat()
        if not self.created_timestamp:
            self.created_timestamp = now
        # Only set updated_timestamp if one wasn't provided by the caller.
        # This preserves deterministic timestamps when tests or callers supply them.
        if not self.updated_timestamp:
            self.updated_timestamp = now
    
    def _compute_aggregate_embedding(self):
        """Compute aggregate embedding from reference images."""
        if not self.reference_images:
            self.aggregate_embedding = None
            return
        
        # Simple averaging of embeddings
        embeddings = [img.embedding for img in self.reference_images]
        if embeddings:
            avg_embedding = np.mean(embeddings, axis=0)
            self.aggregate_embedding = avg_embedding.tolist()
    
    def update_timestamp(self):
        """Update the modification timestamp."""
        self.updated_timestamp = datetime.now().isoformat()
    
    def add_reference_image(self, roster_image: RosterImage):
        """Add a reference image and recompute aggregate embedding."""
        self.reference_images.append(roster_image)
        self._compute_aggregate_embedding()
        self.update_timestamp()
    
    @property
    def image_count(self) -> int:
        """Number of reference images."""
        return len(self.reference_images)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "unique_id": self.unique_id,
            "reference_images": [img.to_dict() for img in self.reference_images],
            "aggregate_embedding": self.aggregate_embedding,
            "metadata": self.metadata,
            "created_timestamp": self.created_timestamp,
            "updated_timestamp": self.updated_timestamp,
            "image_count": self.image_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RosterEntry":
        """Create from dictionary during deserialization."""
        reference_images = [
            RosterImage.from_dict(img_data) 
            for img_data in data.get("reference_images", [])
        ]
        
        return cls(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            unique_id=data.get("unique_id", ""),
            reference_images=reference_images,
            aggregate_embedding=data.get("aggregate_embedding"),
            metadata=data.get("metadata", {}),
            created_timestamp=data.get("created_timestamp"),
            updated_timestamp=data.get("updated_timestamp")
        )


@dataclass
class RosterMatch:
    """
    Represents a similarity match result between a query and roster entry.
    """
    roster_entry: RosterEntry
    similarity_score: float
    confidence_threshold: float
    is_match: Optional[bool] = None
    
    def __post_init__(self):
        """Calculate match status based on threshold."""
        self.is_match = self.similarity_score >= self.confidence_threshold
    
    @property
    def match_confidence(self) -> float:
        """Get match confidence as a percentage."""
        return self.similarity_score * 100
    
    def exceeds_threshold(self) -> bool:
        """Check if similarity exceeds threshold."""
        return self.similarity_score >= self.confidence_threshold
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "roster_entry": self.roster_entry.to_dict(),
            "similarity_score": self.similarity_score,
            "confidence_threshold": self.confidence_threshold,
            "is_match": self.is_match,
            "match_confidence": self.match_confidence
        }
