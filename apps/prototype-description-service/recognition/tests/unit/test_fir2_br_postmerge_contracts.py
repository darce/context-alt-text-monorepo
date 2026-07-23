"""RED contracts for FIR2-BR-01/02/03 (post-merge review findings).

TEST-ONLY pass: these tests specify the intended production contracts and must
fail on current code until GREEN lands. No production or migration edits here.

Findings:
  FIR2-BR-01 — single embedding-dimension root (PGVECTOR_DIM / DatabaseSettings)
  FIR2-BR-02 — neutral seam carries five-point landmarks when available
  FIR2-BR-03 — canonical identity quality is pose-neutral (model-fair)

Heuristics: EMB-01/03/05, CAL-01/02/05, PROV-04/06, FAIR-03, SSOT/CFG/TEST,
rg-005/015. Canon @ 3e1135039ba1e5f98dc50ce46ee5b290e4bdde35.
"""

from __future__ import annotations

import importlib
import inspect
import re
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from recognition.application.assignment.quality import (
    IdentityQualityInfo,
    compute_identity_quality,
    compute_quality_adjustment,
)
from recognition.application.embedding.detector import FaceDetection
from recognition.application.embedding.manifest import incumbent_embedding_model_manifest
from recognition.infrastructure.face_pipeline._common import RawDetection

# recognition/tests/unit/this → parents[3] = service root
_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION_PATH = (
    _SERVICE_ROOT / "db" / "migrations" / "versions" / "001_identity_schema.py"
)


def _clear_settings_caches() -> None:
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()


def _fresh_settings_module():
    import recognition.config.settings as settings_module

    return importlib.reload(settings_module)


def _fresh_db_settings_module():
    import db.settings as db_settings

    return importlib.reload(db_settings)


def _fresh_migration_module():
    return importlib.reload(
        importlib.import_module("db.migrations.versions.001_identity_schema")
    )


def _rereload_touched_modules() -> None:
    """Final reload so sibling files see consistent settings module objects."""
    import db.settings as db_settings
    import recognition.config.settings as settings_module

    importlib.reload(settings_module)
    importlib.reload(db_settings)
    _clear_settings_caches()
    fpa = importlib.import_module(
        "recognition.infrastructure.embeddings.face_pipeline_adapter"
    )
    fpa.reset_shared_face_pipeline_runtime_for_tests()


@pytest.fixture(autouse=True)
def _restore_settings_caches() -> None:
    """Do not leak PGVECTOR_DIM / RECOGNITION_EMBEDDING_DIMENSION across tests."""
    yield
    _rereload_touched_modules()


# ---------------------------------------------------------------------------
# FIR2-BR-01 — one embedding-dimension root
# ---------------------------------------------------------------------------


class TestFir2Br01EmbeddingDimensionSsot:
    """PGVECTOR_DIM / DatabaseSettings.pgvector_dimension is the sole root.

    ORM Vector columns, Alembic 001 Vector + matview casts, and
    RecognitionSettings.identity_detection.embedding_dimension must all follow
    that root. RECOGNITION_EMBEDDING_DIMENSION must not create a second root.
    """

    def test_pgvector_dim_drives_db_and_recognition_embedding_dimension(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With PGVECTOR_DIM=384, db + recognition dims both resolve to 384."""
        monkeypatch.setenv("PGVECTOR_DIM", "384")
        monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
        _clear_settings_caches()
        db_mod = _fresh_db_settings_module()
        rec_mod = _fresh_settings_module()

        db_settings = db_mod.get_database_settings()
        rec_settings = rec_mod.RecognitionSettings()

        assert db_settings.pgvector_dimension == 384
        assert rec_settings.identity_detection.embedding_dimension == 384

    def test_recognition_embedding_dimension_env_is_not_a_second_root(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RECOGNITION_EMBEDDING_DIMENSION alone must not diverge from PGVECTOR_DIM.

        When PGVECTOR_DIM=384 and RECOGNITION_EMBEDDING_DIMENSION=128, the sole
        root (PGVECTOR_DIM) wins: identity_detection.embedding_dimension is 384
        and settings load without a dual-root pairing conflict.
        """
        monkeypatch.setenv("PGVECTOR_DIM", "384")
        monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "128")
        _clear_settings_caches()
        _fresh_db_settings_module()
        rec_mod = _fresh_settings_module()

        settings = rec_mod.RecognitionSettings()
        assert settings.identity_detection.embedding_dimension == 384

    def test_migration_embedding_dimension_follows_pgvector_dim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """001 identity schema EMBEDDING_DIMENSION resolves from PGVECTOR_DIM."""
        monkeypatch.setenv("PGVECTOR_DIM", "384")
        monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
        _clear_settings_caches()
        _fresh_db_settings_module()

        migration = _fresh_migration_module()
        assert migration.EMBEDDING_DIMENSION == 384

    def test_migration_source_has_no_hardcoded_512_dimension_literal(self) -> None:
        """Executable schema text must not pin vector dim to 512.

        After GREEN, EMBEDDING_DIMENSION is derived from PGVECTOR_DIM / settings,
        not a bare module-level ``= 512``. Source must not reintroduce
        ``Vector(512)`` or ``::vector(512)`` literals.
        """
        source = _MIGRATION_PATH.read_text(encoding="utf-8")
        assert "Vector(512)" not in source, (
            "001_identity_schema must not hardcode Vector(512); use the SSOT dim"
        )
        assert re.search(r"::vector\(\s*512\s*\)", source) is None, (
            "001_identity_schema must not hardcode ::vector(512) casts"
        )
        assert re.search(r"EMBEDDING_DIMENSION\s*=\s*512\b", source) is None, (
            "001_identity_schema must not assign EMBEDDING_DIMENSION = 512; "
            "derive from PGVECTOR_DIM / DatabaseSettings.pgvector_dimension"
        )

    def test_resolve_embedding_dimension_reads_pgvector_not_recognition_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_resolve_embedding_dimension (if present) must bind to PGVECTOR_DIM."""
        monkeypatch.setenv("PGVECTOR_DIM", "384")
        monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "128")
        _clear_settings_caches()
        _fresh_db_settings_module()
        rec_mod = _fresh_settings_module()

        # Prefer explicit helper when GREEN keeps it; else settings field is SSOT.
        if hasattr(rec_mod, "_resolve_embedding_dimension"):
            assert rec_mod._resolve_embedding_dimension() == 384
        else:
            assert rec_mod.RecognitionSettings().identity_detection.embedding_dimension == 384

    def test_orm_vector_columns_use_pgvector_dimension_not_literal_512(self) -> None:
        """Identity ORM Vector columns are constructed from settings, not 512."""
        import db.models.identity as identity_mod

        source = inspect.getsource(identity_mod)
        # Must not hardcode Vector(512) on identity tables.
        assert "Vector(512)" not in source
        # Must reference the settings-driven dimension (pgvector_dimension).
        assert "pgvector_dimension" in source


# ---------------------------------------------------------------------------
# FIR2-BR-02 — five-point landmarks on the neutral seam
# ---------------------------------------------------------------------------


def _five_landmarks() -> tuple[tuple[float, float], ...]:
    return (
        (20.0, 20.0),
        (40.0, 20.0),
        (30.0, 30.0),
        (22.0, 40.0),
        (38.0, 40.0),
    )


class TestFir2Br02LandmarksSeam:
    """FaceDetection carries exactly five point landmarks when available."""

    def test_face_detection_has_landmarks_field(self) -> None:
        field_names = {f.name for f in fields(FaceDetection)}
        assert "landmarks" in field_names, (
            "FaceDetection must expose landmarks (tuple of five (x,y) or None)"
        )

    def test_face_detection_landmarks_default_none(self) -> None:
        det = FaceDetection(
            media_id="m1",
            bbox=(0, 0, 10, 10),
            confidence=0.9,
        )
        assert det.landmarks is None

    def test_face_detection_accepts_five_point_tuple(self) -> None:
        lm = _five_landmarks()
        det = FaceDetection(
            media_id="m1",
            bbox=(0, 0, 50, 50),
            confidence=0.9,
            landmarks=lm,
        )
        assert det.landmarks == lm
        # Immutable / JSON-persistence-safe: nested tuples of floats.
        assert isinstance(det.landmarks, tuple)
        assert len(det.landmarks) == 5
        assert all(isinstance(p, tuple) and len(p) == 2 for p in det.landmarks)
        assert all(
            isinstance(coord, float) for p in det.landmarks for coord in p
        )

    def test_normalize_landmarks_helper_accepts_five_finite_points(self) -> None:
        from recognition.application.embedding.detector import normalize_landmarks

        raw = [[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]]
        out = normalize_landmarks(raw)
        assert out == _five_landmarks()
        assert isinstance(out, tuple)
        assert all(isinstance(p, tuple) for p in out)

    def test_normalize_landmarks_helper_none_passthrough(self) -> None:
        from recognition.application.embedding.detector import normalize_landmarks

        assert normalize_landmarks(None) is None

    @pytest.mark.parametrize(
        "bad",
        [
            [],  # empty
            [(0.0, 0.0)] * 4,  # too few
            [(0.0, 0.0)] * 6,  # too many
            [(0.0, 0.0, 0.0)] * 5,  # wrong pair arity
            [(0.0, float("nan"))] + [(1.0, 1.0)] * 4,  # non-finite
            [(0.0, float("inf"))] + [(1.0, 1.0)] * 4,  # non-finite
            "not-a-sequence-of-points",
        ],
    )
    def test_normalize_landmarks_helper_rejects_invalid(self, bad: object) -> None:
        from recognition.application.embedding.detector import normalize_landmarks

        with pytest.raises((TypeError, ValueError)):
            normalize_landmarks(bad)

    @pytest.mark.asyncio
    async def test_face_pipeline_detector_surfaces_raw_landmarks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FacePipelineFaceDetector maps RawDetection.landmarks onto the seam."""
        from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
        from recognition.infrastructure.face_pipeline.provenance import DEFAULT_MODELS_DIR
        from recognition.tests.unit.face_pipeline_support import SFACE_EMBEDDING_DIM

        monkeypatch.setenv("PGVECTOR_DIM", str(SFACE_EMBEDDING_DIM))
        monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", str(SFACE_EMBEDDING_DIM))
        _clear_settings_caches()
        fpa.reset_shared_face_pipeline_runtime_for_tests()

        landmarks_np = np.array(
            [[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]],
            dtype=np.float32,
        )
        raw = RawDetection(
            bbox=np.array([10.0, 10.0, 40.0, 50.0], dtype=np.float32),
            landmarks=landmarks_np,
            score=0.97,
        )
        manifest = fpa.sface_embedding_model_manifest()
        runtime = fpa.FacePipelineRuntime(
            detector=MagicMock(),
            aligner=MagicMock(),
            embedder=MagicMock(),
            manifest=manifest,
            models_dir=DEFAULT_MODELS_DIR,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
        )
        runtime.detector.detect.return_value = [[raw]]  # type: ignore[attr-defined]
        crop = np.zeros((112, 112, 3), dtype=np.uint8)
        aligned = MagicMock()
        aligned.crop = crop
        runtime.aligner.align.return_value = aligned  # type: ignore[attr-defined]
        emb = np.ones(SFACE_EMBEDDING_DIM, dtype=np.float32)
        emb /= float(np.linalg.norm(emb))
        runtime.embedder.embed.return_value = [emb]  # type: ignore[attr-defined]

        import io

        from PIL import Image

        det = fpa.FacePipelineFaceDetector(runtime, timeout=5.0)
        img = Image.new("RGB", (64, 64), color=(12, 34, 56))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        faces = await det.detect([buf.getvalue()])

        assert len(faces) == 1
        assert faces[0].landmarks is not None
        assert len(faces[0].landmarks) == 5
        for got, exp in zip(faces[0].landmarks, landmarks_np, strict=True):
            assert got[0] == pytest.approx(float(exp[0]))
            assert got[1] == pytest.approx(float(exp[1]))

        fpa.reset_shared_face_pipeline_runtime_for_tests()

    @pytest.mark.asyncio
    async def test_insightface_adapter_surfaces_kps_as_landmarks(self) -> None:
        """InsightFaceAdapter maps face.kps → FaceDetection.landmarks when present."""
        from recognition.infrastructure.embeddings import InsightFaceAdapter

        kps = np.array(
            [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0], [9.0, 10.0]],
            dtype=np.float32,
        )
        embedding = np.ones(512, dtype=np.float32)
        embedding = embedding / float(np.linalg.norm(embedding))
        raw_face = SimpleNamespace(
            bbox=np.array([10.0, 20.0, 110.0, 170.0], dtype=np.float32),
            det_score=0.93,
            pose=np.array([5.0, -3.0, 1.5], dtype=np.float32),
            normed_embedding=embedding,
            kps=kps,
        )

        adapter = InsightFaceAdapter()
        adapter._model_loaded = True
        adapter._app = MagicMock()
        adapter._app.get = MagicMock(return_value=[raw_face])
        adapter._bytes_to_cv2 = MagicMock(  # type: ignore[method-assign]
            return_value=np.zeros((8, 8, 3), dtype=np.uint8)
        )

        results = await adapter.detect_faces(b"landmarks-kps-mapping")
        assert len(results) == 1
        assert results[0].landmarks is not None
        assert len(results[0].landmarks) == 5
        for got, exp in zip(results[0].landmarks, kps, strict=True):
            assert got[0] == pytest.approx(float(exp[0]))
            assert got[1] == pytest.approx(float(exp[1]))

    @pytest.mark.asyncio
    async def test_insightface_adapter_landmarks_none_when_kps_absent(self) -> None:
        """Producers without landmarks leave FaceDetection.landmarks as None."""
        from recognition.infrastructure.embeddings import InsightFaceAdapter

        embedding = np.ones(512, dtype=np.float32)
        embedding = embedding / float(np.linalg.norm(embedding))
        raw_face = SimpleNamespace(
            bbox=np.array([10.0, 20.0, 110.0, 170.0], dtype=np.float32),
            det_score=0.93,
            pose=None,
            normed_embedding=embedding,
            # no kps attribute
        )

        adapter = InsightFaceAdapter()
        adapter._model_loaded = True
        adapter._app = MagicMock()
        adapter._app.get = MagicMock(return_value=[raw_face])
        adapter._bytes_to_cv2 = MagicMock(  # type: ignore[method-assign]
            return_value=np.zeros((8, 8, 3), dtype=np.uint8)
        )

        results = await adapter.detect_faces(b"landmarks-none-fallback")
        assert len(results) == 1
        assert results[0].landmarks is None


# ---------------------------------------------------------------------------
# FIR2-BR-03 — model-neutral canonical quality (pose optional elsewhere)
# ---------------------------------------------------------------------------


class TestFir2Br03PoseNeutralQuality:
    """Canonical quality must not silently reward models that cannot emit pose.

    Pose remains available for pose-bucket / diversity uses, but confidence+bbox
    quality used by thresholds is identical for extreme, frontal, and missing
    pose. Prefer removing pose from the quality formula over inventing a
    missing-pose constant. Embedding model_id stays beside quality.
    """

    def _quality(
        self,
        *,
        confidence: float = 0.9,
        bbox_width: int = 100,
        bbox_height: int = 100,
    ):
        return compute_identity_quality(
            confidence=confidence,
            bbox_width=bbox_width,
            bbox_height=bbox_height,
        )

    def test_quality_identical_for_extreme_frontal_and_missing_pose(self) -> None:
        # Pose is no longer a quality input; score is confidence+bbox only.
        a = self._quality(confidence=0.9, bbox_width=100, bbox_height=100)
        b = self._quality(confidence=0.9, bbox_width=100, bbox_height=100)
        c = self._quality(confidence=0.9, bbox_width=100, bbox_height=100)

        assert a.score == b.score == c.score
        assert (
            a.threshold_adjustment
            == b.threshold_adjustment
            == c.threshold_adjustment
        )

    def test_extreme_pose_not_penalized_relative_to_frontal(self) -> None:
        """RED rewrite of the old extreme-pose-penalty expectation."""
        info = self._quality(confidence=0.9, bbox_width=100, bbox_height=100)
        frontal = self._quality(confidence=0.9, bbox_width=100, bbox_height=100)
        # Same confidence + bbox → same score (pose not in quality formula).
        assert info.score == frontal.score
        assert info.score == pytest.approx(0.9, abs=0.001)

    def test_identity_quality_info_has_no_pose_penalty_field(self) -> None:
        """Prefer removing pose from quality output over a missing-pose constant."""
        names = {f.name for f in fields(IdentityQualityInfo)}
        assert "pose_penalty" not in names, (
            "IdentityQualityInfo.pose_penalty embeds pose into canonical quality; "
            "remove it so model profiles without pose are not disadvantaged"
        )

    def test_quality_settings_has_no_pose_penalty_divisor(self) -> None:
        from recognition.application.settings import QualitySettings

        names = set(QualitySettings.model_fields)
        assert "pose_penalty_divisor" not in names, (
            "QualitySettings.pose_penalty_divisor must leave the quality formula "
            "(pose stays optional for diversity/buckets, not threshold quality)"
        )

    def test_detection_quality_helper_pose_neutral(self) -> None:
        from recognition.application.embedding.detector import _compute_detection_quality

        conf = 0.88
        bbox = (10, 20, 110, 120)  # 100×100
        # Signature is confidence+bbox only; repeated calls are identical.
        a = _compute_detection_quality(conf, bbox)
        b = _compute_detection_quality(conf, bbox)
        c = _compute_detection_quality(conf, bbox)
        assert a == b == c

    def test_threshold_adjustment_matches_for_pose_variants(self) -> None:
        a = self._quality(confidence=0.9, bbox_width=100, bbox_height=100)
        b = self._quality(confidence=0.9, bbox_width=100, bbox_height=100)
        assert a.threshold_adjustment == b.threshold_adjustment
        # And matches adjustment derived from the shared score alone.
        assert a.threshold_adjustment == compute_quality_adjustment(a.score)

    def test_face_detection_still_carries_model_id_beside_quality(self) -> None:
        """model_id remains the provenance stamp next to quality (PROV-04/06)."""
        names = {f.name for f in fields(FaceDetection)}
        assert "model_id" in names
        assert "landmark_quality" in names
        det = FaceDetection(
            media_id="m",
            bbox=(0, 0, 10, 10),
            confidence=0.9,
            landmark_quality=0.9,
            model_id=incumbent_embedding_model_manifest().model_id,
        )
        assert det.model_id
        assert det.landmark_quality == 0.9
