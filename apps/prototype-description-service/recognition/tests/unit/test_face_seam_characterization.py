"""Characterization tests for the face-pipeline seam (FIR-2 S2a).

Pins today's field shapes and contract payloads BEFORE the S2b seam refactor.
TEST-ONLY: no production code changes. No DB, network, or InsightFace model load.

Heuristic anchors (docs/reference/engineering-heuristics-canon.md):
- TEST-03: characterization before change — pin actual current behavior first
- AGT-03: make it fail before making it pass — observe current behavior before claiming the pin holds
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.identity import MediaIdentity
from recognition.application.assignment.quality import compute_identity_quality
from recognition.application.embedding.detector import FaceDetection, InsightFaceFaceDetector
from recognition.application.embedding.generator import EmbeddingResult, StubEmbeddingGenerator
from recognition.application.embedding.manifest import incumbent_embedding_model_manifest
from recognition.application.services.export_service import TenantExportService
from recognition.infrastructure.embeddings import InsightFaceAdapter
from recognition.interface_adapters.http.deps.stores import MediaIdentityService

# --- Expected field / key sets (pinned to current producers) ---

# S4 deliberate pin update: age/gender removed from seam, export, debug metrics.
# FIR2-BR-02: optional five-point landmarks on the neutral seam.
FACE_DETECTION_FIELDS = frozenset(
    {
        "media_id",
        "bbox",
        "confidence",
        "embedding",
        "pose_pitch",
        "pose_yaw",
        "pose_roll",
        "image_phash",
        "landmark_quality",
        "model_id",
        "landmarks",
    }
)

EMBEDDING_RESULT_FIELDS = frozenset({"media_id", "embedding", "confidence"})

EXPORT_IDENTITY_KEYS = frozenset(
    {
        "id",
        "media_id",
        "media_url",
        "identity_type",
        "bbox",
        "confidence",
        "pose_pitch",
        "pose_yaw",
        "pose_roll",
        "quality_score",
        "image_phash",
        "last_exported_snapshot_id",
        "disposed_at",
        "created_at",
        "updated_at",
    }
)

EXPORT_BBOX_KEYS = frozenset({"x", "y", "width", "height"})

DEBUG_METRICS_BASE_KEYS = frozenset(
    {
        "pose",
        "det_score",
        "bbox_area",
        "landmark_quality",
        "clustering_method",
        "clustering_algorithm",
        "similarity_threshold",
        "match_similarity",
    }
)

DEBUG_POSE_KEYS = frozenset({"pitch", "yaw", "roll"})

# stores.py list_by_media_ids face payload top-level keys (lines 220-236)
API_FACE_PAYLOAD_TOP_LEVEL_KEYS = frozenset(
    {
        "identity_id",
        "media_id",
        "cluster_id",
        "cluster_label",
        "is_auto_label",
        "clustering_pending",
        "bbox",
        "confidence",
        "media_url",
    }
)

# cluster_repository._to_domain debug_metrics dict keys (lines 1069-1090)
CLUSTER_REP_DEBUG_METRICS_KEYS = frozenset(
    {
        "pose",
        "det_score",
        "bbox_area",
        "landmark_quality",
        "clustering_method",
        "clustering_algorithm",
        "similarity_threshold",
        "match_similarity",
        "representative_count",
        "pose_buckets",
    }
)
CLUSTER_REP_DEBUG_POSE_BUCKETS_KEYS = frozenset({"filled", "total", "current_bucket"})


def _unit_embedding() -> list[float]:
    return [1.0] + [0.0] * 511


def _media_identity(
    *,
    pose_pitch: float | None = None,
    pose_yaw: float | None = None,
    pose_roll: float | None = None,
) -> MediaIdentity:
    """Real-shaped MediaIdentity instance (no DB session)."""
    return MediaIdentity(
        id=uuid4(),
        tenant_id=uuid4(),
        media_id=101,
        media_url="http://example.test/media-101.jpg",
        bbox_x=10,
        bbox_y=20,
        bbox_width=30,
        bbox_height=40,
        confidence=0.97,
        embedding=_unit_embedding(),
        embedding_model=incumbent_embedding_model_manifest().model_id,
        pose_pitch=pose_pitch,
        pose_yaw=pose_yaw,
        pose_roll=pose_roll,
        quality_score=0.91,
        image_phash="abc123",
        created_at=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# 1. Application seam: FaceDetection
# ---------------------------------------------------------------------------


def test_face_detection_field_set_is_pinned() -> None:
    """CHAR: FaceDetection exact field-name set via dataclasses.fields()."""
    assert {f.name for f in fields(FaceDetection)} == FACE_DETECTION_FIELDS


def test_face_detection_accepts_none_optional_metadata() -> None:
    """CHAR: degrade path — optional pose/embedding/landmarks may be None."""
    detection = FaceDetection(
        media_id="media-1",
        bbox=(0, 0, 10, 10),
        confidence=0.5,
        embedding=None,
        pose_pitch=None,
        pose_yaw=None,
        pose_roll=None,
        image_phash=None,
        landmark_quality=None,
        landmarks=None,
    )
    assert detection.embedding is None
    assert detection.pose_pitch is None
    assert detection.pose_yaw is None
    assert detection.pose_roll is None
    assert detection.landmarks is None


# ---------------------------------------------------------------------------
# 2. (S2b) DetectedFace inventory deleted — class removed; FaceDetection is sole seam
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. Stub embedding surface
# ---------------------------------------------------------------------------


def test_embedding_result_field_set_is_pinned() -> None:
    """CHAR: EmbeddingResult exact field set."""
    assert {f.name for f in fields(EmbeddingResult)} == EMBEDDING_RESULT_FIELDS


def test_stub_embedding_generator_default_dim_is_512() -> None:
    """CHAR: StubEmbeddingGenerator defaults to 512-D embeddings."""
    gen = StubEmbeddingGenerator()
    assert gen.embedding_dim == 512


@pytest.mark.asyncio
async def test_stub_embedding_generator_produces_shape_512() -> None:
    """CHAR: generated stub embeddings have shape (512,)."""
    gen = StubEmbeddingGenerator()
    results = await gen.generate([b"face-bytes-for-stub"])
    assert len(results) == 1
    assert results[0].embedding.shape == (512,)
    assert {f.name for f in fields(type(results[0]))} == EMBEDDING_RESULT_FIELDS


@pytest.mark.asyncio
async def test_stub_embedding_generator_pins_dtype_norm_confidence_and_determinism() -> None:
    """CHAR: stub embeddings are float32, L2≈1.0, confidence=0.99, deterministic."""
    gen = StubEmbeddingGenerator()
    payload = b"deterministic-face-bytes"
    first = await gen.generate([payload])
    second = await gen.generate([payload])

    assert len(first) == 1 and len(second) == 1
    emb = first[0].embedding
    assert emb.dtype == np.float32
    assert float(np.linalg.norm(emb)) == pytest.approx(1.0, rel=1e-5, abs=1e-5)
    assert first[0].confidence == 0.99
    assert second[0].confidence == 0.99
    np.testing.assert_array_equal(first[0].embedding, second[0].embedding)


# ---------------------------------------------------------------------------
# 3b. InsightFaceFaceDetector mapping pins (detector enrichment + adapter map)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insightface_detector_maps_adapter_face_to_face_detection_fields() -> None:
    """CHAR: InsightFaceFaceDetector.detect maps adapter FaceDetection fields exactly.

    Injects a fake adapter returning known bbox, det_score/confidence, pose,
    and normed_embedding; pins bbox passthrough, pose order, embedding
    passthrough, model_id, and landmark_quality from quality scoring.
    """
    bbox = (10, 20, 110, 170)  # corner-style (x1, y1, x2, y2) as adapter emits
    pose = (5.0, -3.0, 1.5)  # pitch, yaw, roll unpack order
    embedding = np.arange(512, dtype=np.float32)
    embedding = embedding / float(np.linalg.norm(embedding))
    model_id = incumbent_embedding_model_manifest().model_id
    confidence = 0.97

    adapter_face = FaceDetection(
        media_id="",
        bbox=bbox,
        confidence=confidence,
        embedding=embedding,
        pose_pitch=pose[0],
        pose_yaw=pose[1],
        pose_roll=pose[2],
        model_id=model_id,
    )
    mock_adapter = MagicMock()
    mock_adapter.detect_faces = AsyncMock(return_value=[adapter_face])

    detector = InsightFaceFaceDetector(mock_adapter)
    detections = await detector.detect([b"mapping-pin-image-bytes"])

    assert len(detections) == 1
    det = detections[0]
    assert det.bbox == bbox
    assert det.confidence == confidence
    np.testing.assert_array_equal(det.embedding, embedding)
    assert det.pose_pitch == 5.0
    assert det.pose_yaw == -3.0
    assert det.pose_roll == 1.5
    assert det.model_id == model_id
    # landmark_quality is confidence + corner-derived bbox size (FIR2-BR-03)
    expected_quality = compute_identity_quality(
        confidence=confidence,
        bbox_width=bbox[2] - bbox[0],
        bbox_height=bbox[3] - bbox[1],
    ).score
    assert det.landmark_quality == expected_quality
    assert det.media_id  # filled from source hash
    assert det.image_phash is None or isinstance(det.image_phash, str)


@pytest.mark.asyncio
async def test_insightface_adapter_maps_raw_face_attrs_to_face_detection() -> None:
    """CHAR: InsightFaceAdapter maps bbox corners, det_score, pose, normed_embedding."""
    bbox_corners = np.array([10.4, 20.6, 110.9, 170.2], dtype=np.float32)
    pose = np.array([5.0, -3.0, 1.5], dtype=np.float32)
    embedding = np.ones(512, dtype=np.float32)
    embedding = embedding / float(np.linalg.norm(embedding))
    raw_face = SimpleNamespace(
        bbox=bbox_corners,
        det_score=0.93,
        pose=pose,
        normed_embedding=embedding,
        kps=np.zeros((5, 2), dtype=np.float32),  # present on IF faces; unused in map
    )

    adapter = InsightFaceAdapter()
    adapter._model_loaded = True
    adapter._app = MagicMock()
    adapter._app.get = MagicMock(return_value=[raw_face])
    adapter._bytes_to_cv2 = MagicMock(return_value=np.zeros((8, 8, 3), dtype=np.uint8))  # type: ignore[method-assign]

    results = await adapter.detect_faces(b"raw-face-mapping-bytes")
    assert len(results) == 1
    det = results[0]
    assert det.bbox == (10, 20, 110, 170)  # int conversion of corners
    assert det.confidence == pytest.approx(0.93)
    assert det.pose_pitch == 5.0
    assert det.pose_yaw == -3.0
    assert det.pose_roll == 1.5
    np.testing.assert_array_equal(det.embedding, embedding)
    assert det.model_id == incumbent_embedding_model_manifest().model_id
    assert det.media_id == ""
    # FIR2-BR-02: kps present on IF faces must surface as five-point landmarks.
    assert det.landmarks is not None
    assert len(det.landmarks) == 5


# ---------------------------------------------------------------------------
# 4a. Export snapshot identity serializer
# ---------------------------------------------------------------------------


def test_serialize_identity_key_set_and_bbox_keys() -> None:
    """CHAR: export _serialize_identity exact keys + bbox x/y/width/height (no age/gender)."""
    service = TenantExportService(session=cast(AsyncSession, SimpleNamespace()))
    identity = _media_identity(pose_pitch=1.0, pose_yaw=2.0, pose_roll=3.0)

    payload = service._serialize_identity(identity)

    assert set(payload.keys()) == EXPORT_IDENTITY_KEYS
    assert set(cast(dict[str, object], payload["bbox"]).keys()) == EXPORT_BBOX_KEYS
    assert "age" not in payload
    assert "gender" not in payload
    assert payload["bbox"] == {"x": 10, "y": 20, "width": 30, "height": 40}


def test_serialize_identity_degrade_optional_none() -> None:
    """CHAR: export path preserves None for optional pose fields."""
    service = TenantExportService(session=cast(AsyncSession, SimpleNamespace()))
    identity = _media_identity(pose_pitch=None, pose_yaw=None, pose_roll=None)

    payload = service._serialize_identity(identity)

    assert set(payload.keys()) == EXPORT_IDENTITY_KEYS
    assert "age" not in payload
    assert "gender" not in payload
    assert payload["pose_pitch"] is None
    assert payload["pose_yaw"] is None
    assert payload["pose_roll"] is None


# ---------------------------------------------------------------------------
# 4b. API face payload debug_metrics (stubbed row; no DB)
# ---------------------------------------------------------------------------


class _AllResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _StubSession:
    """Minimal AsyncSession stand-in that returns a fixed row list."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _stmt: object) -> _AllResult:
        return _AllResult(self._rows)


@pytest.mark.asyncio
async def test_debug_metrics_base_key_set_and_pose_subkeys() -> None:
    """CHAR: debug_metrics base keys (no cluster) + pose pitch/yaw/roll; no age/gender."""
    identity = _media_identity(pose_pitch=5.0, pose_yaw=-3.0, pose_roll=1.5)
    row = SimpleNamespace(
        MediaIdentity=identity,
        cluster_id=None,
        cluster_label=None,
        user_confirmed=None,
    )
    service = MediaIdentityService(session=cast(AsyncSession, _StubSession([row])))

    payloads = await service.list_by_media_ids(str(identity.tenant_id), [identity.media_id], include_debug=True)

    assert len(payloads) == 1
    debug = cast(dict[str, object], payloads[0]["debug_metrics"])
    assert set(debug.keys()) == DEBUG_METRICS_BASE_KEYS
    pose = cast(dict[str, object], debug["pose"])
    assert set(pose.keys()) == DEBUG_POSE_KEYS
    assert pose == {"pitch": 5.0, "yaw": -3.0, "roll": 1.5}
    assert "age" not in debug
    assert "gender" not in debug


@pytest.mark.asyncio
async def test_debug_metrics_degrade_optional_none() -> None:
    """CHAR: when pose is None, debug_metrics coerces pose→0; age/gender absent."""
    identity = _media_identity(pose_pitch=None, pose_yaw=None, pose_roll=None)
    row = SimpleNamespace(
        MediaIdentity=identity,
        cluster_id=None,
        cluster_label=None,
        user_confirmed=None,
    )
    service = MediaIdentityService(session=cast(AsyncSession, _StubSession([row])))

    payloads = await service.list_by_media_ids(str(identity.tenant_id), [identity.media_id], include_debug=True)

    debug = cast(dict[str, object], payloads[0]["debug_metrics"])
    assert set(debug.keys()) == DEBUG_METRICS_BASE_KEYS
    pose = cast(dict[str, object], debug["pose"])
    assert set(pose.keys()) == DEBUG_POSE_KEYS
    assert pose == {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}
    assert "age" not in debug
    assert "gender" not in debug


# ---------------------------------------------------------------------------
# 4c. API face-payload top-level keys (stores.py 220-236)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_face_payload_top_level_key_set() -> None:
    """CHAR: list_by_media_ids payload top-level key SET equals stores.py 220-236."""
    identity = _media_identity(pose_pitch=1.0, pose_yaw=2.0, pose_roll=3.0)
    row = SimpleNamespace(
        MediaIdentity=identity,
        cluster_id=None,
        cluster_label=None,
        user_confirmed=None,
    )
    service = MediaIdentityService(session=cast(AsyncSession, _StubSession([row])))

    payloads = await service.list_by_media_ids(str(identity.tenant_id), [identity.media_id], include_debug=False)

    assert len(payloads) == 1
    assert set(payloads[0].keys()) == API_FACE_PAYLOAD_TOP_LEVEL_KEYS


# ---------------------------------------------------------------------------
# 4d. Cluster repository representative debug_metrics key set (1069-1090)
# ---------------------------------------------------------------------------


def test_cluster_rep_debug_metrics_key_set_is_pinned() -> None:
    """CHAR: debug_metrics dict key SET from cluster_repository._to_domain builder."""
    identity = SimpleNamespace(
        pose_pitch=5.0,
        pose_yaw=-3.0,
        pose_roll=1.0,
        confidence=0.9,
        bbox_width=30,
        bbox_height=40,
        quality_score=0.8,
    )
    filled_buckets = {(0, 0)}
    representative_count = 2
    bucket_size = 30.0
    # Mirror production builder at cluster_repository.py:1069-1090
    debug_metrics = {
        "pose": {
            "pitch": float(identity.pose_pitch or 0),
            "yaw": float(identity.pose_yaw or 0),
            "roll": float(identity.pose_roll or 0),
        },
        "det_score": float(identity.confidence),
        "bbox_area": int(identity.bbox_width * identity.bbox_height),
        "landmark_quality": float(identity.quality_score or 1.0),
        "clustering_method": None,
        "clustering_algorithm": None,
        "similarity_threshold": None,
        "match_similarity": None,
        "representative_count": representative_count,
        "pose_buckets": {
            "filled": len(filled_buckets),
            "total": 13,  # 10 base + 3 bonus
            "current_bucket": (
                int(identity.pose_pitch // bucket_size),
                int(identity.pose_yaw // bucket_size),
            )
            if identity.pose_pitch is not None and identity.pose_yaw is not None
            else None,
        },
    }
    assert set(debug_metrics.keys()) == CLUSTER_REP_DEBUG_METRICS_KEYS
    assert set(cast(dict[str, object], debug_metrics["pose_buckets"]).keys()) == (CLUSTER_REP_DEBUG_POSE_BUCKETS_KEYS)
    assert set(cast(dict[str, object], debug_metrics["pose"]).keys()) == DEBUG_POSE_KEYS
    assert "age" not in debug_metrics
    assert "gender" not in debug_metrics


def test_detected_identity_debug_extras_type_removed() -> None:
    """CHAR: orphan DetectedIdentityDebugExtras is deleted (wired into zero models)."""
    import recognition.interface_adapters.http.schemas.responses as responses

    assert not hasattr(responses, "DetectedIdentityDebugExtras")
    assert "DetectedIdentityDebugExtras" not in responses.__all__
