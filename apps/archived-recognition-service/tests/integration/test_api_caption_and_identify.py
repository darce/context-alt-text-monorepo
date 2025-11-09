"""Integration tests for caption and identify endpoints.

Covers existing behaviour to guard against regressions and sketches
future features via xfail tests for pending integrations.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Iterator, Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from api.dependencies import reset_dependencies, set_roster_service
from api.routes.main import (
    router as api_router,
    set_scene_analysis_service,
    set_scene_composer,
)


class FakeSceneAnalysisService:
    def __init__(self) -> None:
        self.generate_calls: list[dict[str, object]] = []
        self.recognition_service = SimpleNamespace(
            settings=SimpleNamespace(
                recognition=SimpleNamespace(default_threshold=0.5)
            )
        )

    def generate_caption(self, image, reference_image=None, context=None, **_kwargs):
        self.generate_calls.append(
            {
                "reference_image_present": reference_image is not None,
                "context": context or {},
            }
        )
        return {
            "caption": "synthetic caption",
            "detected_persons": ["Demo Person"],
            "processing_info": {"engine": "FakeCaptioner"},
        }


class FakeSceneComposer:
    def __init__(self) -> None:
        self.results = [
            {"name": "Demo", "similarity": 0.9, "unique_id": "demo-1"}
        ]

    def identify_persons_with_reference(self, image, reference_image):  # type: ignore[override]
        return list(self.results)


def _build_image(filename: str = "image.png", color: Tuple[int, int, int] = (255, 0, 0)) -> Tuple[str, io.BytesIO, str]:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=color).save(buffer, format="PNG")
    buffer.seek(0)
    return filename, buffer, "image/png"


@pytest.fixture()
def api_client() -> Iterator[Tuple[TestClient, FakeSceneAnalysisService, FakeSceneComposer]]:
    fake_service = FakeSceneAnalysisService()
    fake_composer = FakeSceneComposer()

    set_scene_analysis_service(fake_service)
    set_scene_composer(fake_composer)
    set_roster_service(SimpleNamespace())

    app = FastAPI()
    app.state.is_initializing = False
    app.state.initialization_complete = True
    app.include_router(api_router)

    client = TestClient(app)

    try:
        yield client, fake_service, fake_composer
    finally:
        client.close()
        set_scene_analysis_service(None)
        set_scene_composer(None)
        reset_dependencies()


def test_caption_endpoint_returns_caption_and_metadata(
    api_client: Tuple[TestClient, FakeSceneAnalysisService, FakeSceneComposer]
) -> None:
    client, fake_service, _ = api_client

    files = {
        "image": _build_image("scene.png"),
        "reference_image": _build_image("reference.png", color=(0, 0, 255)),
    }
    form = {"caption": "Describe the scene", "post_body": "Some context"}

    response = client.post("/caption", files=files, data=form)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "caption": "synthetic caption",
        "detected_persons": ["Demo Person"],
        "processing_info": {"engine": "FakeCaptioner"},
    }

    assert fake_service.generate_calls, "Caption service should be invoked"
    call = fake_service.generate_calls[-1]
    assert call["reference_image_present"] is True
    assert call["context"] == form


def test_caption_returns_503_while_initializing() -> None:
    fake_service = FakeSceneAnalysisService()
    set_scene_analysis_service(fake_service)

    app = FastAPI()
    app.state.is_initializing = True
    app.state.initialization_complete = False
    app.include_router(api_router)

    client = TestClient(app)
    try:
        response = client.post("/caption", files={"image": _build_image()})
        assert response.status_code == 503
        assert response.json()["detail"].startswith("Models are still loading")
    finally:
        client.close()
        set_scene_analysis_service(None)
        reset_dependencies()


def test_identify_returns_stubbed_results(
    api_client: Tuple[TestClient, FakeSceneAnalysisService, FakeSceneComposer]
) -> None:
    client, _, fake_composer = api_client

    files = {
        "image": _build_image("scene.png"),
        "reference_image": _build_image("reference.png"),
    }

    response = client.post("/identify", files=files)

    assert response.status_code == 200
    assert response.json() == {"results": fake_composer.results}


def test_identify_missing_reference_returns_422(
    api_client: Tuple[TestClient, FakeSceneAnalysisService, FakeSceneComposer]
) -> None:
    client, _, _ = api_client

    response = client.post(
        "/identify",
        files={"image": _build_image("scene.png")},
    )

    assert response.status_code == 422


def test_identify_requires_initialization() -> None:
    fake_composer = FakeSceneComposer()
    set_scene_composer(fake_composer)

    app = FastAPI()
    app.state.is_initializing = False
    app.state.initialization_complete = False
    app.include_router(api_router)

    client = TestClient(app)
    try:
        response = client.post(
            "/identify",
            files={
                "image": _build_image("scene.png"),
                "reference_image": _build_image("reference.png"),
            },
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "Scene composer not initialized"
    finally:
        client.close()
        set_scene_composer(None)
        reset_dependencies()


@pytest.mark.xfail(reason="HF identification pipeline not yet implemented")
def test_identify_hf_returns_results(api_client: Tuple[TestClient, FakeSceneAnalysisService, FakeSceneComposer]) -> None:
    client, _, _ = api_client

    response = client.post("/identify-hf", files={"image": _build_image("scene.png")})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("results"), list)
    assert payload["results"], "Expected pipeline to return at least one result"


def test_caption_rejects_files_exceeding_max_size(
    api_client: Tuple[TestClient, FakeSceneAnalysisService, FakeSceneComposer]
) -> None:
    client, *_ = api_client

    oversized_bytes = io.BytesIO(b"\xff" * (11 * 1024 * 1024))
    oversized_bytes.seek(0)

    response = client.post(
        "/caption",
        files={"image": ("oversized.jpg", oversized_bytes, "image/jpeg")},
    )

    assert response.status_code == 413
