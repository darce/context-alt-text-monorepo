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
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.identity import MediaIdentity
from recognition.application.embedding.detector import FaceDetection
from recognition.application.embedding.generator import EmbeddingResult, StubEmbeddingGenerator
from recognition.application.services.export_service import TenantExportService
from recognition.interface_adapters.http.deps.stores import MediaIdentityService

# --- Expected field / key sets (pinned to current producers) ---

# S4 deliberate pin update: age/gender removed from seam, export, debug metrics.
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
        embedding_model="buffalo_l@insightface",
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
    """CHAR: degrade path — optional pose/embedding may be None."""
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
    )
    assert detection.embedding is None
    assert detection.pose_pitch is None
    assert detection.pose_yaw is None
    assert detection.pose_roll is None


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
