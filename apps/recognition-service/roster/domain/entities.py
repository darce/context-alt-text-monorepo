"""
Domain Entities for Roster Service

Core business objects representing roster entries, images, and related data.
These are pure domain objects without any external dependencies.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

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
        self._ensure_augmented_embeddings()
        self._normalize_augmented_embeddings()
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
        vectors = []
        weights: List[float] = []

        for image in self.reference_images:
            if image.embedding:
                vectors.append(np.array(image.embedding, dtype=np.float64))
                weights.append(1.0)

        for augmented in self.metadata.get("augmented_embeddings", []):
            embedding = augmented.get("embedding")
            if not embedding:
                continue
            weight = self._quality_weight(augmented.get("quality_tier"))
            if weight <= 0:
                continue
            vectors.append(np.array(embedding, dtype=np.float64))
            weights.append(weight)

        if not vectors:
            # Preserve an explicitly provided aggregate embedding (e.g. loaded from database)
            if self.aggregate_embedding is not None:
                if isinstance(self.aggregate_embedding, np.ndarray):
                    self.aggregate_embedding = self.aggregate_embedding.tolist()
                return
            self.aggregate_embedding = None
            return

        if len(weights) == len(vectors):
            weighted_average = np.average(vectors, axis=0, weights=weights)
        else:
            weighted_average = np.mean(vectors, axis=0)

        norm = float(np.linalg.norm(weighted_average))
        if norm == 0.0:
            self.aggregate_embedding = weighted_average.tolist()
            return

        normalized = weighted_average / norm
        self.aggregate_embedding = normalized.tolist()
    
    def update_timestamp(self):
        """Update the modification timestamp."""
        self.updated_timestamp = datetime.now().isoformat()
    
    def add_reference_image(self, roster_image: RosterImage):
        """Add a reference image and recompute aggregate embedding."""
        self.reference_images.append(roster_image)
        self._compute_aggregate_embedding()
        self.update_timestamp()

    def add_augmented_embedding(
        self,
        embedding: List[float],
        source: str,
        observation_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add an augmented embedding from an external confirmation workflow.

        Returns:
            True if appended, False when duplicate observation detected.
        """
        self._ensure_augmented_embeddings()
        augmented_embeddings = self.metadata["augmented_embeddings"]

        if any(item.get("observation_id") == observation_id for item in augmented_embeddings):
            return False

        record = self._build_augmented_embedding_record(
            embedding=embedding,
            source=source,
            observation_id=observation_id,
            metadata=metadata or {},
        )

        augmented_embeddings.append(record)
        self._compute_aggregate_embedding()
        self.update_timestamp()
        return True
    
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

    def _ensure_augmented_embeddings(self):
        """Ensure augmented embeddings list exists within metadata."""
        if "augmented_embeddings" not in self.metadata or not isinstance(
            self.metadata.get("augmented_embeddings"), list
        ):
            self.metadata["augmented_embeddings"] = []

    def _normalize_augmented_embeddings(self):
        """Normalize augmented embedding records to enforce schema defaults."""
        augmented = self.metadata.get("augmented_embeddings", [])
        normalized: List[Dict[str, Any]] = []
        for entry in augmented:
            if not isinstance(entry, dict):
                continue
            embedding = entry.get("embedding")
            if not embedding:
                continue
            normalized_entry = dict(entry)
            confidence = normalized_entry.get("confidence")
            normalized_entry.setdefault(
                "quality_tier", self._determine_quality_tier(confidence)
            )
            normalized_entry.setdefault("created_at", self._current_timestamp())
            normalized.append(normalized_entry)
        self.metadata["augmented_embeddings"] = normalized

    @staticmethod
    def _determine_quality_tier(confidence: Optional[float]) -> str:
        """Map confidence values to quality tiers."""
        if confidence is None:
            return "medium"
        if confidence >= 0.85:
            return "high"
        if confidence >= 0.65:
            return "medium"
        return "low"

    @staticmethod
    def _quality_weight(quality_tier: Optional[str]) -> float:
        """Return weighting factor for a quality tier."""
        mapping = {"high": 1.0, "medium": 0.8, "low": 0.5}
        return mapping.get(quality_tier or "medium", 0.8)

    @staticmethod
    def _current_timestamp() -> str:
        """Return current UTC timestamp formatted for storage."""
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _build_augmented_embedding_record(
        self,
        embedding: List[float],
        source: str,
        observation_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create normalized augmented embedding record for metadata storage."""
        confidence = metadata.get("confidence")
        record: Dict[str, Any] = {
            "embedding": embedding,
            "source": source,
            "observation_id": observation_id,
            "attachment_id": metadata.get("attachment_id"),
            "bbox": metadata.get("bbox"),
            "confidence": confidence,
            "created_at": metadata.get("created_at", self._current_timestamp()),
            "quality_tier": metadata.get(
                "quality_tier", self._determine_quality_tier(confidence)
            ),
        }

        reserved_keys = {"attachment_id", "bbox", "confidence", "created_at", "quality_tier"}
        for key, value in metadata.items():
            if key not in reserved_keys:
                record[key] = value

        return record


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
