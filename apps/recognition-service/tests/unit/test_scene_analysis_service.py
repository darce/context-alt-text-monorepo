"""Unit tests for SceneAnalysisService and RecognitionService.

Focuses on business logic without FastAPI or network dependencies.
"""

import numpy as np
import pytest
from PIL import Image

from analysis.entities.scene_context import SceneContext
from analysis.services.scene_analysis_service import SceneAnalysisService
from analysis.workflow.scene_composer import SceneComposer
from recognition_core.domain.entities import (
    EmbeddingEntry,
    FaceDetection,
    FaceEmbedding,
    MatchResult,
    RecognitionResult,
)
from recognition_core.domain.interfaces import EmbeddingRouterPort, RecognitionModelPort
from recognition_core.services.recognition_service import RecognitionService


class StubRecognitionModel(RecognitionModelPort):
    def __init__(self, faces=None):
        self.called = False
        self._faces = faces or [
            FaceEmbedding(
                embedding=np.array([1.0, 0.0], dtype=np.float32),
                detection=FaceDetection(bbox=(0, 0, 10, 10), confidence=0.95),
            )
        ]

    async def analyze(self, image: Image.Image):  # type: ignore[override]
        self.called = True
        return self._faces

    def model_info(self):  # type: ignore[override]
        return {"model_name": "stub", "device": "cpu"}


class StubEmbeddingRouter(EmbeddingRouterPort):
    def __init__(self, matches=None):
        self._matches = matches or [
            MatchResult(
                entry=EmbeddingEntry(
                    unique_id="abc123",
                    name="Test User",
                    display_name="Test User",
                    aggregate_embedding=np.array([1.0, 0.0], dtype=np.float32),
                    metadata={"role": "tester"},
                ),
                similarity=0.92,
                threshold=0.5,
                is_match=True,
            )
        ]

    async def load_embeddings(self):  # type: ignore[override]
        return []

    async def find_matches(self, query_embedding, threshold):  # type: ignore[override]
        return self._matches

    async def reload_if_needed(self):  # type: ignore[override]
        return False

    # Convenience helpers to match adapter API
    def get_loaded_count(self):
        return len(self._matches)

    def get_loaded_names(self):
        return [match.entry.name for match in self._matches]


@pytest.mark.asyncio
async def test_recognition_service_returns_matches():
    model = StubRecognitionModel()
    router = StubEmbeddingRouter()
    service = RecognitionService(model=model, embedding_router=router)

    dummy_image = Image.new("RGB", (10, 10), color="white")
    result = await service.recognize_faces(dummy_image, threshold=0.5)

    assert model.called is True
    assert len(result.face_embeddings) == 1
    assert len(result.face_matches) == 1
    assert result.face_matches[0][0].entry.name == "Test User"


@pytest.mark.asyncio
async def test_recognition_service_handles_no_faces():
    model = StubRecognitionModel(faces=[])
    router = StubEmbeddingRouter(matches=[])
    service = RecognitionService(model=model, embedding_router=router)

    dummy_image = Image.new("RGB", (10, 10), color="white")
    result = await service.recognize_faces(dummy_image, threshold=0.5)

    assert result.face_embeddings == []
    assert result.face_matches == []
    assert result.processing_time_ms >= 0


class StubObjectDetector:
    def detect_objects(self, image):
        return [
            {
                "class_id": 0,
                "class_name": "person",
                "bbox": (0, 0, 10, 10),
                "confidence": 0.9,
            }
        ]


class StubCaptionGenerator:
    def is_ready(self):
        return True

    def generate_caption(self, image, prompt=None, **kwargs):
        return "stub caption"


@pytest.mark.asyncio
async def test_scene_analysis_builds_entities():
    scene_composer = SceneComposer(
        object_detector=StubObjectDetector(),
        entity_identifiers=[],
        caption_generator=StubCaptionGenerator(),
    )

    recognition_service = RecognitionService(
        model=StubRecognitionModel(),
        embedding_router=StubEmbeddingRouter(),
    )

    service = SceneAnalysisService(scene_composer=scene_composer, recognition_service=recognition_service)

    dummy_image = Image.new("RGB", (10, 10), color="white")
    context: SceneContext = await service.analyze_scene(dummy_image)

    assert len(context.detected_entities) == 1
    entity = context.detected_entities[0]
    assert entity.roster_match is not None
    assert entity.roster_match.roster_entry.name == "Test User"
    assert context.processing_metadata["faces_detected"] == 1
