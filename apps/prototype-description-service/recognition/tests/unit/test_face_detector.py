"""TDD tests for face detection adapter.

Tests cover:
- StubFaceDetector: Deterministic hash-based detection for tests
- FaceDetectorProtocol: Interface contract verification
- InsightFaceFaceDetector: Real detection (with mocked adapter)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from recognition.application.embedding.detector import (
    FaceDetector,
    FaceDetectorProtocol,
    InsightFaceFaceDetector,
    StubFaceDetector,
)
from recognition.application.embedding.service import FaceDetection


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
        mock_adapter.detect_faces = AsyncMock(return_value=[mock_face])

        detector = InsightFaceFaceDetector(mock_adapter)
        detections = await detector.detect([b"real-image-bytes"])

        mock_adapter.detect_faces.assert_called_once()
        assert len(detections) == 1
        assert detections[0].bbox == (10, 20, 100, 150)
        assert detections[0].confidence == 0.95

    @pytest.mark.asyncio
    async def test_skips_url_sources_with_warning(self) -> None:
        """URL sources should be skipped (not yet supported)."""
        mock_adapter = MagicMock()
        mock_adapter.detect_faces = AsyncMock(return_value=[])

        detector = InsightFaceFaceDetector(mock_adapter)
        detections = await detector.detect(["http://example.com/image.jpg"])

        # Should not call adapter for URL
        mock_adapter.detect_faces.assert_not_called()
        assert detections == []

    @pytest.mark.asyncio
    async def test_handles_multiple_faces_per_image(self) -> None:
        """Should return multiple detections if adapter finds multiple faces."""
        mock_adapter = MagicMock()
        mock_face1 = MagicMock(bbox=(10, 10, 50, 50), confidence=0.9)
        mock_face2 = MagicMock(bbox=(100, 100, 150, 150), confidence=0.85)
        mock_adapter.detect_faces = AsyncMock(return_value=[mock_face1, mock_face2])

        detector = InsightFaceFaceDetector(mock_adapter)
        detections = await detector.detect([b"image-with-two-faces"])

        assert len(detections) == 2
        assert detections[0].confidence == 0.9
        assert detections[1].confidence == 0.85

    @pytest.mark.asyncio
    async def test_handles_adapter_exception_gracefully(self) -> None:
        """Should log error and continue if adapter raises exception."""
        mock_adapter = MagicMock()
        mock_adapter.detect_faces = AsyncMock(side_effect=RuntimeError("Model failed"))

        detector = InsightFaceFaceDetector(mock_adapter)
        detections = await detector.detect([b"bad-image"])

        # Should return empty list, not raise
        assert detections == []


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
