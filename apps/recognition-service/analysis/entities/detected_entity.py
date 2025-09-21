from dataclasses import dataclass
from typing import Tuple, Optional, Dict, Any
from roster.domain.entities import RosterMatch
import numpy as np
from recognition.utils.face_utils import clean_numpy_types

@dataclass
class DetectedEntity:
    """
    Canonical representation for any detected entity (person/object) in a scene.
    If a roster match exists, it is attached as roster_match.
    For face entities, includes detailed identification scoring information.
    """
    label: str
    bbox: Tuple[int, int, int, int] # (x_min, y_min, x_max, y_max)
    confidence: float
    entity_type: str # e.g., 'person', 'object', 'scene'
    area: float = 0.0  # Area of the bounding box, can be calculated as (x_max - x_min) * (y_max - y_min) 
    roster_match: Optional[RosterMatch] = None
    # Face identification details
    face_data: Optional[Dict[str, Any]] = None  # Stores detailed face identification results

    def __post_init__(self):
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence score must be between 0 and 1. Received: {self.confidence}")
        if self.area < 0:
            self.area = 0.0

    @classmethod
    def from_dict(cls, data: Dict) -> 'DetectedEntity':
        """Create DetectedEntity from dictionary."""
        roster_match = None
        if "roster_match" in data and data["roster_match"]:
            roster_match = RosterMatch.from_dict(data["roster_match"])
            
        return cls(
            label=data["label"],
            bbox=tuple(data["bbox"]),
            confidence=data["confidence"],
            entity_type=data["entity_type"],
            area=data.get("area", 0.0),
            roster_match=roster_match,
            face_data=data.get("face_data")
        )

    def to_dict(self) -> Dict:
        """Convert DetectedEntity to dictionary."""
        result = {
            "label": self.label,
            "bbox": list(self.bbox),
            "confidence": self.confidence,
            "entity_type": self.entity_type,
            "area": self.area
        }
        
        if self.roster_match:
            result["roster_match"] = self.roster_match.to_dict()
        
        if self.face_data:
            # Clean numpy types in face_data
            result["face_data"] = clean_numpy_types(self.face_data)
        
        return result