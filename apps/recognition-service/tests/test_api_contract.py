from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.main import router, set_scene_analysis_service
from analysis.services.scene_analysis_service import SceneAnalysisService
from recognition.domain.entities import (
    EmbeddingEntry,
    FaceDetection,
    FaceEmbedding,
    MatchResult,
    RecognitionResult,
)
from roster.domain.entities import RosterEntry, RosterImage

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "api" / "examples"
BASE64_IMAGE = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "Xw8AAnEB7SBSYQAAAABJRU5ErkJggg=="
)


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


class StubRecognitionService:
    def __init__(self):
        self.settings = SimpleNamespace(
            recognition=SimpleNamespace(default_threshold=0.5),
            insightface=SimpleNamespace(model_name="stub-face", device="cpu"),
            embedding_router=SimpleNamespace(auto_reload=False),
        )

    async def recognize_faces(self, image, threshold=None):
        detection = FaceDetection(bbox=(0, 0, 10, 10), confidence=0.95)
        embedding = FaceEmbedding(
            embedding=np.array([1.0, 0.0], dtype=np.float32),
            detection=detection,
        )
        entry = EmbeddingEntry(
            unique_id="roster-1",
            name="Test User",
            display_name="Test User",
            aggregate_embedding=np.array([1.0, 0.0], dtype=np.float32),
            metadata={"role": "tester"},
        )
        match = MatchResult(
            entry=entry,
            similarity=0.92,
            threshold=threshold or self.settings.recognition.default_threshold,
            is_match=True,
        )
        return RecognitionResult(
            face_detections=[detection],
            face_embeddings=[embedding],
            matches=[match],
            processing_time_ms=12.3,
            face_matches=[[match]],
        )

    async def get_service_info(self):
        return {
            "model_name": self.settings.insightface.model_name,
            "device": self.settings.insightface.device,
            "default_threshold": self.settings.recognition.default_threshold,
            "loaded_embeddings": 1,
            "entity_names": ["Test User"],
            "auto_reload": self.settings.embedding_router.auto_reload,
        }

    async def reload_embeddings(self):
        return True


class StubSceneComposer:
    def __init__(self):
        self.object_detector = StubObjectDetector()
        self.caption_generator = StubCaptionGenerator()


class TestSceneAnalysisService(SceneAnalysisService):
    def _build_roster_entry(self, embedding_entry: EmbeddingEntry) -> RosterEntry:
        vector = (
            embedding_entry.aggregate_embedding.tolist()
            if hasattr(embedding_entry.aggregate_embedding, "tolist")
            else list(embedding_entry.aggregate_embedding)
        )

        roster_image = RosterImage(
            embedding=vector,
            metadata=embedding_entry.metadata,
            image_path=None,
        )

        return RosterEntry(
            name=embedding_entry.name,
            display_name=embedding_entry.display_name,
            unique_id=embedding_entry.unique_id,
            reference_images=[roster_image],
            metadata=embedding_entry.metadata,
            created_timestamp="2024-01-01T00:00:00",
            updated_timestamp="2024-01-01T00:00:00",
        )


def load_example(name: str):
    with (EXAMPLES_DIR / name).open("r", encoding="utf-8") as fh:
        import json

        return json.load(fh)


@pytest.fixture(scope="module")
def test_client():
    recognition_service = StubRecognitionService()
    scene_service = TestSceneAnalysisService(
        scene_composer=StubSceneComposer(),
        recognition_service=recognition_service,
    )
    set_scene_analysis_service(scene_service)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    return client


def test_analyze_scene_contract(test_client):
    payload = load_example("analyze-scene.request.json")
    assert payload["images"][0]["image_base64"] == BASE64_IMAGE
    response = test_client.post("/analyze-scene", json=payload)
    assert response.status_code == 200
    assert response.json() == load_example("analyze-scene.response.json")


def test_embeddings_contract(test_client):
    payload = load_example("embeddings.request.json")
    assert payload["image"]["image_base64"] == BASE64_IMAGE
    response = test_client.post("/embeddings", json=payload)
    assert response.status_code == 200
    assert response.json() == load_example("embeddings.response.json")


def test_service_info_contract(test_client):
    response = test_client.get("/service/info")
    assert response.status_code == 200
    assert response.json() == load_example("service-info.response.json")


def test_health_contract(test_client):
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == load_example("health.response.json")
