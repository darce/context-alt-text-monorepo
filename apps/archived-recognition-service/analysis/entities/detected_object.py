from dataclasses import dataclass
from typing import Tuple, Any, Dict

@dataclass
class DetectedObject:
    """
    Represents a detected object with its bounding box, class, and confidence score.
    """
    class_id: int
    class_name: str
    bbox: Tuple[int, int, int, int]  # (x_min, y_min, x_max, y_max)
    confidence: float
    area: float = 0.0
    extra: Dict[str, Any] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DetectedObject":
        return DetectedObject(
            class_id=d.get("class_id", -1),
            class_name=d.get("class_name", "unknown"),
            bbox=tuple(d.get("bbox", (0, 0, 0, 0))),
            confidence=d.get("confidence", 0.0),
            area=d.get("area", 0.0),
            extra={k: v for k, v in d.items() if k not in {"class_id", "class_name", "bbox", "confidence", "area"}}
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert DetectedObject to dictionary for serialization."""
        result = {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "bbox": list(self.bbox),
            "confidence": self.confidence,
            "area": self.area
        }
        
        if self.extra:
            result.update(self.extra)
            
        return result
