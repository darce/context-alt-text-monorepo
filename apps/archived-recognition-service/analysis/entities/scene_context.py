from dataclasses import dataclass
from typing import List, Any, Optional, Dict
from .detected_entity import DetectedEntity
from .detected_object import DetectedObject

@dataclass
class SceneContext:
    # detected_objects: All objects detected in the scene (raw, generic, including persons, cars, etc.)
    detected_objects: List[DetectedObject]
    # detected_entities: Enriched entities (usually persons) with possible identification/roster info.
    # This is a higher-level semantic representation, often a subset or transformation of detected_objects.
    detected_entities: List[DetectedEntity]
    # identified_roster_entities: Subset of detected_entities that have a positive roster match (i.e., are identified as someone in the roster)
    identified_roster_entities: Optional[List[DetectedEntity]] = None
    processing_metadata: Optional[Dict[str, Any]] = None
    # All person/entity/roster data is now unified via DetectedEntity and RosterMatch
