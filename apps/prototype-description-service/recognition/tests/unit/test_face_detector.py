"""TDD tests for face detection adapter.

Tests cover:
- StubFaceDetector: Deterministic hash-based detection for tests
- FaceDetectorProtocol: Interface contract verification
- InsightFaceFaceDetector: Real detection (with mocked adapter)
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from recognition.application.embedding.detector import (
    DetectionAdapterError,
    DetectionTimeoutError,
    FaceDetection,
    FaceDetector,
    FaceDetectorProtocol,
    InsightFaceFaceDetector,
    StubFaceDetector,
)
from recognition.application.integrations import AdapterBreakerConfig, AdapterBreakerOpenError, AdapterCircuitBreaker


class TestStubFaceDetector:
    """Tests for the deterministic stub detector."""

    @pytest.mark.asyncio
    async def test_detection_returns_bboxes_and_confidence(self) -> None:
        """Detector should return bounding boxes with confidence for each source."""
        detector = StubFaceDetector()

        detections = await detector.detect([b"\xff\xd8fake-image", "http://example.test/face.jpg"])

        assert len(detections) == 2
        for detection in detections:
            assert isinstance(detection.bbox, tuple)
            assert len(detection.bbox) == 4
            assert all(isinstance(coord, int) for coord in detection.bbox)
            assert 0 <= detection.confidence <= 1

    @pytest.mark.asyncio
    async def test_detection_handles_empty_source(self) -> None:
        """Detector should gracefully return an empty list for empty sources."""
        detector = StubFaceDetector()

        detections = await detector.detect([b""])

        assert detections == []

    @pytest.mark.asyncio
    async def test_detection_is_deterministic(self) -> None:
        """Same input should produce same output (hash-based)."""
        detector = StubFaceDetector()
        source = b"test-image-data"

        result1 = await detector.detect([source])
        result2 = await detector.detect([source])

        assert len(result1) == len(result2) == 1
        assert result1[0].bbox == result2[0].bbox
        assert result1[0].confidence == result2[0].confidence

    @pytest.mark.asyncio
    async def test_different_inputs_produce_different_outputs(self) -> None:
        """Different inputs should produce different detections."""
        detector = StubFaceDetector()

        result1 = await detector.detect([b"image-a"])
        result2 = await detector.detect([b"image-b"])

        # Bboxes should differ (hash-based)
        assert result1[0].bbox != result2[0].bbox


class TestFaceDetectorProtocol:
    """Tests verifying protocol compliance."""

    def test_stub_implements_protocol(self) -> None:
        """StubFaceDetector should implement FaceDetectorProtocol."""
        detector = StubFaceDetector()
        assert isinstance(detector, FaceDetectorProtocol)

    def test_insightface_implements_protocol(self) -> None:
        """InsightFaceFaceDetector should implement FaceDetectorProtocol."""
        mock_adapter = MagicMock()
        detector = InsightFaceFaceDetector(mock_adapter)
        assert isinstance(detector, FaceDetectorProtocol)


class TestInsightFaceFaceDetector:
    """Tests for InsightFace-backed detector (with mocked adapter)."""

    @pytest.mark.asyncio
    async def test_calls_adapter_for_bytes_source(self) -> None:
        """Should call adapter.detect_faces for bytes input."""
        mock_adapter = MagicMock()
        mock_face = MagicMock()
        mock_face.bbox = (10, 20, 100, 150)
        mock_face.confidence = 0.95
        mock_face.embedding_512 = np.random.randn(512).astype(np.float32)
        mock_face.pose = (5.0, -3.0, 1.0)
        mock_face.age = 30
        mock_face.gender = 1
        mock_face.landmarks = np.array([[10.0, 12.0], [20.0, 18.0], [15.0, 25.0], [9.0, 30.0], [24.0, 33.0]])
        mock_adapter.detect_faces = AsyncMock(return_value=[mock_face])

        detector = InsightFaceFaceDetector(mock_adapter)
        detections = await detector.detect([b"real-image-bytes"])

        mock_adapter.detect_faces.assert_called_once()
        assert len(detections) == 1
        assert detections[0].bbox == (10, 20, 100, 150)
        assert detections[0].confidence == 0.95
        assert detections[0].embedding is not None
        assert detections[0].pose_pitch == 5.0
        assert detections[0].age == 30
        assert detections[0].gender == 1
        assert detections[0].landmark_quality is not None
        assert 0.0 <= detections[0].landmark_quality <= 1.0

    @pytest.mark.asyncio
    async def test_fetches_url_sources(self) -> None:
        """URL sources should be fetched and processed."""
        mock_adapter = MagicMock()
        mock_face = MagicMock(
            bbox=(10, 20, 100, 150),
            confidence=0.95,
            embedding_512=np.random.randn(512).astype(np.float32),
            pose=None,
            age=None,
            gender=None,
        )
        mock_adapter.detect_faces = AsyncMock(return_value=[mock_face])

        detector = InsightFaceFaceDetector(mock_adapter)

        # Mock httpx to return fake image bytes
        with pytest.MonkeyPatch.context() as mp:
            import httpx

            async def mock_get(*args, **kwargs):
                response = MagicMock()
                response.content = b"\xff\xd8fake-jpeg-bytes"
                response.raise_for_status = MagicMock()
                return response

            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mp.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

            detections = await detector.detect(["http://example.com/image.jpg"])

        # Should call adapter for fetched URL
        mock_adapter.detect_faces.assert_called_once()
        assert len(detections) == 1
        assert detections[0].media_id == "http://example.com/image.jpg"

    @pytest.mark.asyncio
    async def test_uses_shared_client_when_provided(self) -> None:
        """Should use provided AsyncClient instead of creating a new one."""
        mock_adapter = MagicMock()
        mock_face = MagicMock(
            bbox=(10, 20, 100, 150),
            confidence=0.95,
            embedding_512=np.random.randn(512).astype(np.float32),
            pose=None,
            age=None,
            gender=None,
        )
        mock_adapter.detect_faces = AsyncMock(return_value=[mock_face])

        mock_response = MagicMock()
        mock_response.content = b"\xff\xd8fake-jpeg-bytes"
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        detector = InsightFaceFaceDetector(mock_adapter, client=mock_client)

        with pytest.MonkeyPatch.context() as mp:
            import httpx

            def fail_client(*args, **kwargs):
                raise AssertionError("AsyncClient should not be constructed when client is provided")

            mp.setattr(httpx, "AsyncClient", fail_client)
            detections = await detector.detect(["http://example.com/image.jpg"])

        mock_client.get.assert_called_once()
        assert len(detections) == 1

    @pytest.mark.asyncio
    async def test_handles_multiple_faces_per_image(self) -> None:
        """Should return multiple detections if adapter finds multiple faces."""
        mock_adapter = MagicMock()
        mock_face1 = MagicMock(
            bbox=(10, 10, 50, 50),
            confidence=0.9,
            embedding_512=np.random.randn(512).astype(np.float32),
            pose=(1.0, 2.0, 3.0),
            age=25,
            gender=0,
        )
        mock_face2 = MagicMock(
            bbox=(100, 100, 150, 150),
            confidence=0.85,
            embedding_512=np.random.randn(512).astype(np.float32),
            pose=(-1.0, -2.0, -3.0),
            age=35,
            gender=1,
        )
        mock_adapter.detect_faces = AsyncMock(return_value=[mock_face1, mock_face2])

        detector = InsightFaceFaceDetector(mock_adapter)
        detections = await detector.detect([b"image-with-two-faces"])

        assert len(detections) == 2
        assert detections[0].confidence == 0.9
        assert detections[1].confidence == 0.85

    @pytest.mark.asyncio
    async def test_raises_typed_error_for_adapter_exception(self) -> None:
        """Generic adapter failures should propagate as typed detection errors."""
        mock_adapter = MagicMock()
        mock_adapter.detect_faces = AsyncMock(side_effect=RuntimeError("Model failed"))

        detector = InsightFaceFaceDetector(mock_adapter)

        with pytest.raises(DetectionAdapterError, match="Model failed"):
            await detector.detect([b"bad-image"])

    @pytest.mark.asyncio
    async def test_times_out_slow_adapter_calls(self) -> None:
        """Should raise a typed timeout when adapter detection exceeds the deadline."""

        async def slow_detect(_image_bytes: bytes) -> list[MagicMock]:
            await asyncio.sleep(0.05)
            return []

        mock_adapter = MagicMock()
        mock_adapter.detect_faces = AsyncMock(side_effect=slow_detect)

        detector = InsightFaceFaceDetector(mock_adapter, timeout=0.01)

        with pytest.raises(DetectionTimeoutError):
            await detector.detect([b"slow-image"])

    @pytest.mark.asyncio
    async def test_fast_fails_when_breaker_is_open(self) -> None:
        """Breaker-open state should surface as a fast failure on the detector seam."""

        breaker = AdapterCircuitBreaker(
            adapter_name="insightface.detect_faces",
            config=AdapterBreakerConfig(
                failure_count_threshold=1,
                failure_window_seconds=60.0,
                half_open_probe_count=1,
                success_close_threshold=1,
                open_state_cooldown_seconds=30.0,
            ),
        )

        failing_adapter = MagicMock()
        failing_adapter.detect_faces = AsyncMock(side_effect=RuntimeError("Model failed"))
        detector = InsightFaceFaceDetector(failing_adapter, breaker=breaker)

        with pytest.raises(DetectionAdapterError):
            await detector.detect([b"first-image"])

        with pytest.raises(AdapterBreakerOpenError):
            await detector.detect([b"second-image"])

    @pytest.mark.asyncio
    async def test_logs_warning_when_breaker_is_open(self, caplog: pytest.LogCaptureFixture) -> None:
        """Breaker-open state should emit a warning before re-raising."""

        breaker = AdapterCircuitBreaker(
            adapter_name="insightface.detect_faces",
            config=AdapterBreakerConfig(
                failure_count_threshold=1,
                failure_window_seconds=60.0,
                half_open_probe_count=1,
                success_close_threshold=1,
                open_state_cooldown_seconds=30.0,
            ),
        )

        failing_adapter = MagicMock()
        failing_adapter.detect_faces = AsyncMock(side_effect=RuntimeError("Model failed"))
        detector = InsightFaceFaceDetector(failing_adapter, breaker=breaker)

        with pytest.raises(DetectionAdapterError):
            await detector.detect([b"first-image"])

        with caplog.at_level(logging.WARNING):
            with pytest.raises(AdapterBreakerOpenError):
                await detector.detect([b"second-image"])

        assert "Detection breaker open for" in caplog.text


# Backwards compatibility alias test
@pytest.mark.asyncio
async def test_detection_returns_bboxes_and_confidence() -> None:
    """Legacy test: FaceDetector alias should work."""
    detector = FaceDetector()

    detections = await detector.detect([b"\xff\xd8fake-image", "http://example.test/face.jpg"])

    assert len(detections) == 2


@pytest.mark.asyncio
async def test_detection_handles_no_faces() -> None:
    """Legacy test: FaceDetector should handle empty sources."""
    detector = FaceDetector()

    detections = await detector.detect([b""])

    assert detections == []
