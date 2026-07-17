"""Unit tests for InsightFaceAdapter infrastructure component.

These tests verify the adapter's behavior using mocks, without requiring
the actual InsightFace model to be installed.

Note: Some tests are skipped if cv2/insightface are not properly installed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import numpy as np
import pytest

# Try to import - skip tests if dependencies are broken
try:
    from recognition.application.embedding.detector import FaceDetection
    from recognition.application.embedding.manifest import incumbent_embedding_model_manifest
    from recognition.infrastructure.embeddings import InsightFaceAdapter

    HAS_ADAPTER = True
except (ImportError, AttributeError) as e:
    HAS_ADAPTER = False
    SKIP_REASON = f"InsightFace adapter dependencies not available: {e}"


@pytest.mark.skipif(not HAS_ADAPTER, reason="InsightFace adapter dependencies not available")
class TestInsightFaceAdapterInit:
    """Tests for adapter initialization and configuration."""

    def test_adapter_initializes_without_loading_model(self) -> None:
        """Adapter should not load the model on init (lazy loading)."""
        adapter = InsightFaceAdapter()

        assert adapter._model_loaded is False
        assert adapter._app is None

    def test_model_info_returns_settings(self) -> None:
        """model_info should return configuration without loading model."""
        adapter = InsightFaceAdapter()
        info = adapter.model_info()

        assert "model_name" in info
        assert "device" in info
        assert "det_thresh" in info
        assert info["model_loaded"] is False
        assert info["model_id"] == incumbent_embedding_model_manifest().model_id


@pytest.mark.skipif(not HAS_ADAPTER, reason="InsightFace adapter dependencies not available")
class TestInsightFaceAdapterProviders:
    """Tests for execution provider selection."""

    def test_auto_device_returns_all_providers(self) -> None:
        """Auto device should return CUDA, CoreML, and CPU providers."""
        adapter = InsightFaceAdapter()
        adapter.settings.insightface.device = "auto"
        adapter.settings.insightface.providers = []

        providers = adapter._get_providers()

        assert "CUDAExecutionProvider" in providers
        assert "CoreMLExecutionProvider" in providers
        assert "CPUExecutionProvider" in providers

    def test_cuda_device_returns_cuda_and_cpu(self) -> None:
        """CUDA device should return CUDA and CPU providers."""
        adapter = InsightFaceAdapter()
        adapter.settings.insightface.device = "cuda"
        adapter.settings.insightface.providers = []

        providers = adapter._get_providers()

        assert providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def test_mps_device_returns_coreml_and_cpu(self) -> None:
        """MPS device should return CoreML and CPU providers."""
        adapter = InsightFaceAdapter()
        adapter.settings.insightface.device = "mps"
        adapter.settings.insightface.providers = []

        providers = adapter._get_providers()

        assert providers == ["CoreMLExecutionProvider", "CPUExecutionProvider"]

    def test_cpu_device_returns_cpu_only(self) -> None:
        """CPU device should return only CPU provider."""
        adapter = InsightFaceAdapter()
        adapter.settings.insightface.device = "cpu"
        adapter.settings.insightface.providers = []

        providers = adapter._get_providers()

        assert providers == ["CPUExecutionProvider"]

    def test_explicit_providers_override_device(self) -> None:
        """Explicit providers list should override device setting."""
        adapter = InsightFaceAdapter()
        adapter.settings.insightface.providers = ["CustomProvider"]

        providers = adapter._get_providers()

        assert providers == ["CustomProvider"]


@pytest.mark.skipif(not HAS_ADAPTER, reason="InsightFace adapter dependencies not available")
class TestInsightFaceAdapterContextId:
    """Tests for context ID (GPU index) selection."""

    def test_cuda_device_returns_gpu_context(self) -> None:
        """CUDA device should return ctx_id=0 for GPU."""
        adapter = InsightFaceAdapter()
        adapter.settings.insightface.device = "cuda"

        ctx_id = adapter._get_ctx_id()

        assert ctx_id == 0

    def test_auto_device_returns_gpu_context(self) -> None:
        """Auto device should return ctx_id=0 (prefer GPU)."""
        adapter = InsightFaceAdapter()
        adapter.settings.insightface.device = "auto"

        ctx_id = adapter._get_ctx_id()

        assert ctx_id == 0

    def test_cpu_device_returns_cpu_context(self) -> None:
        """CPU device should return ctx_id=-1."""
        adapter = InsightFaceAdapter()
        adapter.settings.insightface.device = "cpu"

        ctx_id = adapter._get_ctx_id()

        assert ctx_id == -1


@pytest.mark.skipif(not HAS_ADAPTER, reason="InsightFace adapter dependencies not available")
class TestInsightFaceAdapterExecutorOffload:
    """CPU-bound inference must not block the asyncio event loop."""

    @pytest.mark.asyncio
    async def test_detect_faces_offloads_sync_inference_to_executor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = InsightFaceAdapter()
        adapter._model_loaded = True
        adapter._app = MagicMock(return_value=[])

        executor_calls: list[tuple[object, ...]] = []
        loop = asyncio.get_running_loop()
        original_run_in_executor = loop.run_in_executor

        async def _tracking_run_in_executor(executor, fn, *args):  # noqa: ANN001
            executor_calls.append((executor, fn, *args))
            return await original_run_in_executor(executor, fn, *args)

        monkeypatch.setattr(loop, "run_in_executor", _tracking_run_in_executor)
        monkeypatch.setattr(adapter, "_bytes_to_cv2", lambda _image_bytes: np.zeros((8, 8, 3), dtype=np.uint8))

        await adapter.detect_faces(b"fake-image-bytes")

        assert len(executor_calls) == 1
        assert executor_calls[0][1] is adapter._app.get


@pytest.mark.skipif(not HAS_ADAPTER, reason="InsightFace adapter dependencies not available")
class TestFaceDetectionSeamFromAdapter:
    """Adapter emits the neutral FaceDetection seam (DetectedFace removed)."""

    def test_face_detection_holds_seam_fields(self) -> None:
        """FaceDetection stores detection metadata used by the scan path."""
        embedding = np.random.randn(512).astype(np.float32)
        model_id = incumbent_embedding_model_manifest().model_id

        face = FaceDetection(
            media_id="",
            bbox=(10, 20, 100, 150),
            confidence=0.95,
            embedding=embedding,
            pose_pitch=5.0,
            pose_yaw=-10.0,
            pose_roll=2.0,
            age=35,
            gender=1,
            model_id=model_id,
        )

        assert face.bbox == (10, 20, 100, 150)
        assert face.confidence == 0.95
        np.testing.assert_array_equal(face.embedding, embedding)
        assert face.pose_pitch == 5.0
        assert face.pose_yaw == -10.0
        assert face.pose_roll == 2.0
        assert face.age == 35
        assert face.gender == 1
        assert face.model_id == model_id

    def test_optional_fields_can_be_none(self) -> None:
        """Optional pose/age/gender may be None on the seam."""
        embedding = np.random.randn(512).astype(np.float32)

        face = FaceDetection(
            media_id="",
            bbox=(10, 20, 100, 150),
            confidence=0.95,
            embedding=embedding,
            pose_pitch=None,
            pose_yaw=None,
            pose_roll=None,
            age=None,
            gender=None,
            model_id=incumbent_embedding_model_manifest().model_id,
        )

        assert face.pose_pitch is None
        assert face.age is None
        assert face.gender is None
