"""Characterization tests for the face-pipeline seam (FIR-2 S2a).

Pins today's field shapes and contract payloads BEFORE the S2b seam refactor.
TEST-ONLY: no production code changes. No DB, network, or InsightFace model load.

Heuristic anchors (docs/strategy/engineering-heuristics.md):
- CHAR-01: pin observable producer shapes before refactor
- TEST-03: characterization against unmodified production code
- REAL-01: construct real-shaped inputs from producer field contracts
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.identity import MediaIdentity
from recognition.application.embedding.detector import FaceDetection
from recognition.application.embedding.generator import EmbeddingResult, StubEmbeddingGenerator
from recognition.application.services.export_service import TenantExportService
from recognition.infrastructure.embeddings import DetectedFace
from recognition.interface_adapters.http.deps.stores import MediaIdentityService

# --- Expected field / key sets (pinned to current producers) ---

FACE_DETECTION_FIELDS = frozenset(
    {
        "media_id",
        "bbox",
        "confidence",
        "embedding",
        "pose_pitch",
        "pose_yaw",
        "pose_roll",
        "age",
        "gender",
        "image_phash",
        "landmark_quality",
    }
)

DETECTED_FACE_FIELDS = frozenset(
    {
        "bbox",
        "confidence",
        "embedding_512",
        "pose",
        "age",
        "gender",
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
        "age",
        "gender",
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
        "age",
        "gender",
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


def _unit_embedding() -> list[float]:
    return [1.0] + [0.0] * 511


def _media_identity(
    *,
    age: int | None = None,
    gender: int | None = None,
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
        pose_pitch=pose_pitch,
        pose_yaw=pose_yaw,
        pose_roll=pose_roll,
        quality_score=0.91,
        age=age,
        gender=gender,
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
    """CHAR: degrade path — optional pose/age/gender/embedding may be None."""
    detection = FaceDetection(
        media_id="media-1",
        bbox=(0, 0, 10, 10),
        confidence=0.5,
        embedding=None,
        pose_pitch=None,
        pose_yaw=None,
        pose_roll=None,
        age=None,
        gender=None,
        image_phash=None,
        landmark_quality=None,
    )
    assert detection.embedding is None
    assert detection.pose_pitch is None
    assert detection.pose_yaw is None
    assert detection.pose_roll is None
    assert detection.age is None
    assert detection.gender is None


# ---------------------------------------------------------------------------
# 2. Infrastructure: DetectedFace (dataclass only — no InsightFace load)
# ---------------------------------------------------------------------------


def test_detected_face_field_set_is_pinned() -> None:
    """CHAR: DetectedFace exact field set (embedding_512 + pose/age/gender)."""
    assert {f.name for f in fields(DetectedFace)} == DETECTED_FACE_FIELDS


def test_detected_face_accepts_none_optional_metadata() -> None:
    """CHAR: degrade path — pose/age/gender/landmarks may be None."""
    face = DetectedFace(
        bbox=(1, 2, 3, 4),
        confidence=0.9,
        embedding_512=np.zeros(512, dtype=np.float32),
        pose=None,
        age=None,
        gender=None,
        landmarks=None,
    )
    assert face.embedding_512.shape == (512,)
    assert face.pose is None
    assert face.age is None
    assert face.gender is None
    assert face.landmarks is None


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


# ---------------------------------------------------------------------------
# 4a. Export snapshot identity serializer
# ---------------------------------------------------------------------------


def test_serialize_identity_key_set_and_bbox_keys() -> None:
    """CHAR: export _serialize_identity exact keys incl. age/gender + bbox x/y/width/height."""
    service = TenantExportService(session=cast(AsyncSession, SimpleNamespace()))
    identity = _media_identity(age=33, gender=1, pose_pitch=1.0, pose_yaw=2.0, pose_roll=3.0)

    payload = service._serialize_identity(identity)

    assert set(payload.keys()) == EXPORT_IDENTITY_KEYS
    assert set(cast(dict[str, object], payload["bbox"]).keys()) == EXPORT_BBOX_KEYS
    assert payload["age"] == 33
    assert payload["gender"] == 1
    assert payload["bbox"] == {"x": 10, "y": 20, "width": 30, "height": 40}


def test_serialize_identity_degrade_optional_none() -> None:
    """CHAR: export path preserves None for optional pose/age/gender fields."""
    service = TenantExportService(session=cast(AsyncSession, SimpleNamespace()))
    identity = _media_identity(age=None, gender=None, pose_pitch=None, pose_yaw=None, pose_roll=None)

    payload = service._serialize_identity(identity)

    assert set(payload.keys()) == EXPORT_IDENTITY_KEYS
    assert payload["age"] is None
    assert payload["gender"] is None
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
    """CHAR: debug_metrics base keys (no cluster) incl. age/gender + pose pitch/yaw/roll."""
    identity = _media_identity(age=40, gender=1, pose_pitch=5.0, pose_yaw=-3.0, pose_roll=1.5)
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
    assert debug["age"] == 40.0
    assert debug["gender"] == "male"


@pytest.mark.asyncio
async def test_debug_metrics_degrade_optional_none() -> None:
    """CHAR: when pose/age/gender are None, debug_metrics coerces age→0, pose→0, gender→female."""
    identity = _media_identity(age=None, gender=None, pose_pitch=None, pose_yaw=None, pose_roll=None)
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
    assert debug["age"] == 0.0
    assert debug["gender"] == "female"
