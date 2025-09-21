"""
Conversion Utilities

Convert between recognition service results and analysis service formats
for API compatibility.
"""

from typing import Dict, List, Any, Optional
import logging

from recognition.domain.entities import RecognitionResult
from analysis.entities.detected_entity import DetectedEntity
from analysis.entities.scene_context import SceneContext
from analysis.entities.detected_object import DetectedObject
from roster.domain.entities import RosterMatch, RosterEntry

logger = logging.getLogger(__name__)


def convert_to_analysis_format(
    recognition_result: RecognitionResult,
    use_roster: bool = True
) -> Dict[str, Any]:
    """
    Convert RecognitionResult to analysis service format for API compatibility.
    
    Args:
        recognition_result: Result from recognition service
        use_roster: Whether roster matching was enabled
        
    Returns:
        Dictionary in the format expected by the analysis API
    """
    try:
        detected_entities = []
        detected_objects = []
        roster_matches = []
        identified_roster_entities = []
        
        # Convert face detections to detected objects and entities
        for i, face_embedding in enumerate(recognition_result.face_embeddings):
            detection = face_embedding.detection
            
            # Create detected object (generic detection)
            detected_object = DetectedObject(
                label="person",
                bbox=detection.bbox,
                confidence=detection.confidence,
                object_type="person",
                area=detection.area()
            )
            detected_objects.append(detected_object)
            
            # Create detected entity (enriched with potential roster info)
            roster_match = None
            
            # Find corresponding match for this face
            if use_roster and i < len(recognition_result.matches):
                match_result = recognition_result.matches[i]
                if match_result.is_match:
                    # Convert to roster entities
                    roster_entry = RosterEntry(
                        name=match_result.entry.name,
                        display_name=match_result.entry.display_name,
                        unique_id=match_result.entry.unique_id,
                        metadata=match_result.entry.metadata
                    )
                    
                    roster_match = RosterMatch(
                        roster_entry=roster_entry,
                        similarity_score=match_result.similarity,
                        confidence_threshold=match_result.threshold,
                        is_match=match_result.is_match
                    )
            
            # Create detected entity
            entity_label = roster_match.roster_entry.display_name if roster_match else "unknown_person"
            detected_entity = DetectedEntity(
                label=entity_label,
                bbox=detection.bbox,
                confidence=detection.confidence,
                entity_type="person",
                area=detection.area(),
                roster_match=roster_match,
                face_data={
                    "embedding_dimension": len(face_embedding.embedding),
                    "similarity_score": roster_match.similarity_score if roster_match else 0.0
                }
            )
            
            detected_entities.append(detected_entity)
            
            # Add to roster matches list
            roster_matches.append(
                roster_match.to_dict() if roster_match else None
            )
            
            # Add to identified roster entities if matched
            if roster_match and roster_match.is_match:
                identified_roster_entities.append(detected_entity)
        
        # Build response in expected format
        return {
            "scene_description": f"Scene with {len(detected_entities)} detected person(s)",
            "processing_time": recognition_result.processing_time_ms,
            "detected_objects": [obj.to_dict() for obj in detected_objects],
            "detected_entities": [entity.to_dict() for entity in detected_entities],
            "roster_matches": roster_matches,
            "identified_roster_entities": [
                entity.roster_match.roster_entry.to_dict() 
                for entity in identified_roster_entities
                if entity.roster_match
            ],
            "processing_metadata": {
                "model": "insightface",
                "total_faces": len(recognition_result.face_embeddings),
                "total_matches": len([m for m in recognition_result.matches if m.is_match]),
                "processing_time_ms": recognition_result.processing_time_ms
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error converting to analysis format: {e}")
        # Return minimal valid response on error
        return {
            "scene_description": "Error processing scene",
            "processing_time": recognition_result.processing_time_ms,
            "detected_objects": [],
            "detected_entities": [],
            "roster_matches": [],
            "identified_roster_entities": [],
            "processing_metadata": {
                "error": str(e)
            }
        }


def clean_numpy_types(obj: Any) -> Any:
    """
    Clean numpy types from objects for JSON serialization.
    
    Args:
        obj: Object that may contain numpy types
        
    Returns:
        Object with numpy types converted to native Python types
    """
    import numpy as np
    
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: clean_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [clean_numpy_types(item) for item in obj]
    else:
        return obj
