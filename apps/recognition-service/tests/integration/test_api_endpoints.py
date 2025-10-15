"""Integration tests for FastAPI endpoints.

These tests stub the heavy adapters so we can validate JSON contracts and
error handling without downloading models. Requirements pulled from
roadmap-v3: analyze scenes, generate embeddings, expose service metadata
and health responses, and guard input validation.
"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.main import router as api_router, set_scene_analysis_service
from analysis.services.scene_analysis_service import SceneAnalysisService
from api.dependencies import get_roster_service, set_roster_service
from recognition_core.domain.entities import (
    EmbeddingEntry,
    FaceDetection,
    FaceEmbedding,
    MatchResult,
    RecognitionResult,
)
from roster.domain.entities import RosterEntry, RosterImage

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "api" / "examples"
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
            insightface=SimpleNamespace(model_name="stub-face", device="cpu", providers=["cpu"]),
            embedding_router=SimpleNamespace(
                auto_reload=False,
                reload_interval=30,
                embeddings_file="/roster/data/insightface_w600k_embeddings.json",
            ),
            performance=SimpleNamespace(batch_size=1, max_concurrent_requests=10),
            cache=SimpleNamespace(hf_home=None, hf_datasets_cache=None, torch_home=None),
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
            "model": {
                "name": self.settings.insightface.model_name,
                "device": self.settings.insightface.device,
                "providers": self.settings.insightface.providers,
            },
            "recognition": {
                "default_threshold": self.settings.recognition.default_threshold,
                "max_faces_per_image": 10,
                "embedding_dimension": 512,
            },
            "embedding_router": {
                "auto_reload": self.settings.embedding_router.auto_reload,
                "reload_interval_seconds": self.settings.embedding_router.reload_interval,
                "embeddings_file": self.settings.embedding_router.embeddings_file,
                "loaded_embeddings": 1,
                "loaded_entities": ["Test User"],
            },
            "performance": {
                "batch_size": self.settings.performance.batch_size,
                "max_concurrent_requests": self.settings.performance.max_concurrent_requests,
            },
            "cache": {
                "hf_home": self.settings.cache.hf_home,
                "hf_datasets_cache": self.settings.cache.hf_datasets_cache,
                "torch_home": self.settings.cache.torch_home,
            },
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


class StubRosterEntry:
    FIXED_TIMESTAMP = "2024-01-01T00:00:00"

    def __init__(self, name: str, embedding: List[float], metadata: Optional[Dict[str, Any]] = None):
        self.name = name
        self.display_name = name
        self.unique_id = name
        self.metadata = metadata or {}
        self.reference_images = [SimpleNamespace(embedding=embedding)]
        self.aggregate_embedding = embedding
        self.created_timestamp = self.FIXED_TIMESTAMP
        self.updated_timestamp = self.FIXED_TIMESTAMP

    @property
    def image_count(self) -> int:
        return len(self.reference_images)

    def add_embedding(self, embedding: List[float], metadata: Optional[Dict[str, Any]] = None):
        self.reference_images.append(SimpleNamespace(embedding=embedding))
        if metadata:
            self.metadata.update(metadata)
        arr = np.mean([img.embedding for img in self.reference_images], axis=0)
        self.aggregate_embedding = arr.tolist()
        self.updated_timestamp = self.FIXED_TIMESTAMP


class StubRosterService:
    def __init__(self):
        self._entries: Dict[str, StubRosterEntry] = {}

    def add_entry(self, name: str, embedding: List[float], model: str, metadata=None, image_path=None):
        entry = self._entries.get(name)
        if entry:
            entry.add_embedding(embedding, metadata)
        else:
            entry = StubRosterEntry(name, embedding, metadata)
            self._entries[name] = entry
        return entry

    def add_entries_bulk(self, entries_data, model):
        successes = []
        for data in entries_data:
            if self.add_entry(data["name"], data["embedding"], model, data.get("metadata")):
                successes.append(data["name"])
        return successes

    def update_entry(self, unique_id, model, embedding=None, metadata=None, image_path=None):
        entry = self._entries.get(unique_id)
        if not entry or embedding is None:
            return False
        entry.add_embedding(embedding, metadata)
        return True

    def get_entry(self, unique_id, model):
        return self._entries.get(unique_id)

    def get_entries(self, model, use_cache=True):
        return list(self._entries.values())

    def get_entry_count(self, model):
        return len(self._entries)

    def delete_entry(self, unique_id, model):
        return self._entries.pop(unique_id, None) is not None

    def get_storage_info(self, model):
        return {"backend": "stub", "model": model}


def load_example(name: str) -> Dict[str, Any]:
    with (EXAMPLES_DIR / name).open("r", encoding="utf-8") as fh:
        import json

        return json.load(fh)


@pytest.fixture(scope="module")
def client() -> TestClient:
    recognition_service = StubRecognitionService()
    scene_service = TestSceneAnalysisService(
        scene_composer=StubSceneComposer(),
        recognition_service=recognition_service,
    )
    set_scene_analysis_service(scene_service)

    stub_roster = StubRosterService()
    set_roster_service(stub_roster)

    app = FastAPI()
    app.state.is_initializing = False
    app.state.initialization_complete = True
    app.include_router(api_router)
    app.dependency_overrides[get_roster_service] = lambda: stub_roster
    return TestClient(app)


def test_analyze_scene_returns_expected_contract(client: TestClient) -> None:
    payload = load_example("analyze-scene.request.json")
    assert payload["images"][0]["image_base64"] == BASE64_IMAGE

    response = client.post("/analyze-scene", json=payload)
    assert response.status_code == 200
    assert response.json() == load_example("analyze-scene.response.json")


def test_embeddings_endpoint_matches_fixture(client: TestClient) -> None:
    payload = load_example("embeddings.request.json")
    response = client.post("/embeddings", json=payload)
    assert response.status_code == 200
    assert response.json() == load_example("embeddings.response.json")


def test_service_info_reports_model_metadata(client: TestClient) -> None:
    response = client.get("/service/info")
    assert response.status_code == 200
    body = response.json()
    assert body == load_example("service-info.response.json")


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == load_example("health.response.json")


def test_analyze_scene_requires_payload(client: TestClient) -> None:
    response = client.post("/analyze-scene", json={})
    assert response.status_code == 422


def test_embeddings_requires_image(client: TestClient) -> None:
    response = client.post("/embeddings", json={})
    assert response.status_code == 422


def test_roster_upsert_embeddings(client: TestClient) -> None:
    payload = {
        "entries": [
            {"name": "Alice", "embedding": [1.0, 0.0], "metadata": {"role": "admin"}}
        ]
    }
    response = client.post("/roster", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["successful"] == ["Alice"]
    assert body["roster_stats"]["total_entries"] == 1


def test_append_reference_embedding_recomputes_average(client: TestClient) -> None:
    payload = {"embedding": [0.0, 1.0], "metadata": {"source": "second"}}
    response = client.post("/roster/Alice/embeddings", json=payload)
    assert response.status_code == 200
    body = response.json()
    entry = body["entry"]
    assert entry["image_count"] == 2
    # Average of [1,0] and [0,1] is [0.5, 0.5]
    assert entry["aggregate_embedding"] == [0.5, 0.5]


def test_delete_roster_entry(client: TestClient) -> None:
    response = client.delete("/roster/Alice")
    assert response.status_code == 200
    body = response.json()
    assert body["roster_stats"]["total_entries"] == 0
