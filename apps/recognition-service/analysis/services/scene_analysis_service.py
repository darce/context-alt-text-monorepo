import logging
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image

from analysis.workflow.scene_composer import SceneComposer
from analysis.entities.detected_object import DetectedObject
from analysis.entities.detected_entity import DetectedEntity
from analysis.entities.scene_context import SceneContext
from recognition_core.services.recognition_service import RecognitionService
from recognition_core.domain.entities import EmbeddingEntry
from roster.domain.entities import RosterMatch, RosterEntry, RosterImage
from shared.config.config_service import ConfigService

logger = logging.getLogger(__name__)


class SceneAnalysisService:
    """High-level orchestration for object detection and face recognition."""

    def __init__(
        self,
        scene_composer: SceneComposer,
        roster_service=None,
        config_service: Optional[ConfigService] = None,
        recognition_service: Optional[RecognitionService] = None,
    ) -> None:
        self.scene_composer = scene_composer
        self.roster_service = roster_service
        self.config_service = config_service or ConfigService()
        self.recognition_service = recognition_service or RecognitionService()
        self._settings = self.recognition_service.settings

        logger.info("SceneAnalysisService initialized (device=%s)", self._settings.insightface.device)

    async def analyze_scene(
        self,
        image: Image.Image,
        threshold_override: Optional[float] = None,
    ) -> SceneContext:
        """Analyze an image and return detected objects/entities plus roster matches."""
        threshold = self._resolve_threshold(threshold_override)

        detected_objects = self._detect_objects(image)
        recognition_result = await self.recognition_service.recognize_faces(
            image=image,
            threshold=threshold,
        )

        detected_entities: List[DetectedEntity] = []
        roster_entities: List[DetectedEntity] = []

        matches_per_face = recognition_result.face_matches or []

        for idx, face_embedding in enumerate(recognition_result.face_embeddings):
            detection = face_embedding.detection
            bbox = detection.bbox
            area = float(max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1]))

            match_candidates = matches_per_face[idx] if idx < len(matches_per_face) else []
            face_data = [
                {
                    "name": match.entry.name,
                    "similarity": match.similarity,
                    "unique_id": match.entry.unique_id,
                    "metadata": match.entry.metadata,
                    "meets_threshold": match.is_match,
                }
                for match in match_candidates
            ]

            entity = DetectedEntity(
                label="face",
                bbox=bbox,
                confidence=float(detection.confidence),
                entity_type="person",
                area=area,
                roster_match=None,
                face_data={
                    "threshold": threshold,
                    "candidates": face_data,
                },
            )

            if match_candidates:
                top_match = match_candidates[0]
                if top_match.is_match:
                    roster_match = RosterMatch(
                        roster_entry=self._build_roster_entry(top_match.entry),
                        similarity_score=top_match.similarity,
                        confidence_threshold=threshold,
                    )
                    entity.roster_match = roster_match
                    roster_entities.append(entity)

            detected_entities.append(entity)

        metadata = {
            "faces_detected": len(recognition_result.face_detections),
            "processing_time_ms": recognition_result.processing_time_ms,
            "threshold": threshold,
        }

        return SceneContext(
            detected_objects=detected_objects,
            detected_entities=detected_entities,
            identified_roster_entities=roster_entities,
            processing_metadata=metadata,
        )

    def generate_caption(
        self,
        image: Image.Image,
        reference_image: Optional[Image.Image] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Delegate caption generation to the configured caption adapter if available."""
        caption_adapter = getattr(self.scene_composer, "caption_generator", None)
        context = context or {}

        if not caption_adapter:
            logger.debug("No caption adapter configured; returning placeholder caption.")
            return {
                "caption": "",
                "detected_persons": [],
                "processing_info": {"engine": "none"},
            }

        if hasattr(caption_adapter, "is_ready") and not caption_adapter.is_ready():
            init_callable = getattr(caption_adapter, "initialize", None)
            if callable(init_callable):
                caption_adapter.initialize()

        prompt = context.get("caption")
        generated_caption = caption_adapter.generate_caption(
            image=image,
            prompt=prompt,
            reference_image=reference_image,
            **kwargs,
        )

        return {
            "caption": generated_caption,
            "detected_persons": [],
            "processing_info": {
                "engine": caption_adapter.__class__.__name__,
            },
        }

    def _detect_objects(self, image: Image.Image) -> List[DetectedObject]:
        detector = getattr(self.scene_composer, "object_detector", None)
        if not detector:
            return []
        raw_objects = detector.detect_objects(image)
        return [DetectedObject.from_dict(obj) for obj in raw_objects]

    def _resolve_threshold(self, override: Optional[float]) -> float:
        if override is not None:
            return float(override)
        return float(self._settings.recognition.default_threshold)

    def _build_roster_entry(self, embedding_entry: EmbeddingEntry) -> RosterEntry:
        embedding_vector = embedding_entry.aggregate_embedding
        if isinstance(embedding_vector, np.ndarray):
            vector = embedding_vector.tolist()
        else:
            vector = list(embedding_vector)

        roster_image = RosterImage(
            embedding=vector,
            metadata=embedding_entry.metadata,
        )

        entry = RosterEntry(
            name=embedding_entry.name,
            display_name=embedding_entry.display_name,
            unique_id=embedding_entry.unique_id,
            reference_images=[roster_image],
            metadata=embedding_entry.metadata,
        )
        return entry
