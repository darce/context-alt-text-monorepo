"""RED contracts for FIR final post-merge runtime findings (FINALA/FINALB).

TESTS ONLY. These specify intended production behavior and must fail on the
current implementation until GREEN lands. No production edits here.

Findings:
  FINALA-02 / FINALB-02 — live pgvector width drift must not report ready
  FINALA-03 — admission must not succeed after its deadline
  FINALA-04 — face_pipeline timeout_s must be finite and strictly positive
  FINALB-01 — ConfidenceCheck must not grant quality leniency for extreme/missing pose
  FINALB-04 — readiness cache must observe license drift (not model-only)

Canon: CAL-01, EMB-05, DRIFT-02, SERVE-07, OBS-08, TEST-06, TEST-08, rg-005
Heuristics-canon @ 3e1135039ba1e5f98dc50ce46ee5b290e4bdde35.
"""

from __future__ import annotations

import importlib
import math
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from pydantic import ValidationError

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.checks.confidence import ConfidenceCheck
from recognition.application.assignment.quality import compute_identity_quality
from recognition.application.health import CheckResult, check_database
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.maturity import ClusterMaturityInfo, ClusterMaturityLevel
from recognition.shared.ids import generate_id
from shared.health import HealthStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_settings_caches() -> None:
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()


def _rereload_touched_modules() -> None:
    """Final reload so sibling files see consistent settings + cleared caches."""
    import recognition.config.settings as settings_module

    importlib.reload(settings_module)
    _clear_settings_caches()
    fpa = importlib.import_module(
        "recognition.infrastructure.embeddings.face_pipeline_adapter"
    )
    fpa.reset_shared_face_pipeline_runtime_for_tests()


@pytest.fixture(autouse=True)
def _restore_settings_caches() -> None:
    yield
    _rereload_touched_modules()


def _fresh_settings_module():
    import recognition.config.settings as settings_module

    return importlib.reload(settings_module)


def _mock_session_with_vector_typmods(
    rows: list[tuple[str, str, int]] | list[Any],
) -> AsyncMock:
    """Build an AsyncSession-like mock that returns live pgvector typmod rows.

    GREEN may query pg_attribute / format_type or a dedicated seam; the mock
    surfaces rows as ``(table_name, column_name, vector_dim)`` via ``.all()``
    so either path can consume a realistic result set without a live DB.
    """
    result = MagicMock()
    result.all = MagicMock(return_value=list(rows))
    result.fetchall = MagicMock(return_value=list(rows))
    result.__iter__ = MagicMock(return_value=iter(rows))
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# Identity embedding columns that must share the configured PGVECTOR_DIM.
# GREEN must validate all of these (not one convenient column only).
_IDENTITY_VECTOR_COLUMNS: tuple[tuple[str, str], ...] = (
    ("media_identities", "embedding"),
    ("identity_cluster_representatives", "embedding"),
    ("mv_identity_cluster_centroids", "centroid"),
)


# ---------------------------------------------------------------------------
# FINALA-02 / FINALB-02 — live pgvector width drift vs readiness
# ---------------------------------------------------------------------------


class TestFinalA02LivePgvectorWidthReadiness:
    """Configured PGVECTOR_DIM must match live identity vector typmods on /ready.

    ``check_database`` currently only treats a non-None session as reachable
    (SELECT 1 already done by the dependency). Drift of live ``vector(N)``
    typmods vs PGVECTOR_DIM must flip the database check UNHEALTHY with
    actionable dimension detail ([OBS-08], [rg-005], [EMB-05]).
    """

    @pytest.mark.asyncio
    async def test_dim_mismatch_reports_unhealthy_with_actionable_detail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PGVECTOR_DIM=128 vs live vector(512) columns → UNHEALTHY database check."""
        monkeypatch.setenv("PGVECTOR_DIM", "128")
        monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
        _clear_settings_caches()

        # Live schema still typed at 512 while process is configured for 128.
        rows = [(table, col, 512) for table, col in _IDENTITY_VECTOR_COLUMNS]
        session = _mock_session_with_vector_typmods(rows)

        result = await check_database(session)

        assert isinstance(result, CheckResult)
        assert result.name == "database"
        assert result.status is HealthStatus.UNHEALTHY, (
            "live pgvector width drift must not report database ready; "
            f"got status={result.status!r} detail={result.detail!r}"
        )
        detail_l = result.detail.lower()
        assert "dimension" in detail_l or "mismatch" in detail_l or "vector" in detail_l, (
            f"detail must name dimension mismatch; got {result.detail!r}"
        )
        # Actionable: both configured and live widths visible to operators.
        assert "128" in result.detail, f"detail must include configured dim 128: {result.detail!r}"
        assert "512" in result.detail, f"detail must include live typmod 512: {result.detail!r}"

    @pytest.mark.asyncio
    async def test_matching_dimensions_remain_healthy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When every identity vector column matches PGVECTOR_DIM, database is OK."""
        monkeypatch.setenv("PGVECTOR_DIM", "128")
        monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
        _clear_settings_caches()

        rows = [(table, col, 128) for table, col in _IDENTITY_VECTOR_COLUMNS]
        session = _mock_session_with_vector_typmods(rows)

        result = await check_database(session)

        assert result.status is HealthStatus.OK
        # Contract requires an actual typmod probe, not SELECT-1-only readiness.
        session.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_partial_column_mismatch_is_unhealthy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GREEN must validate all identity embedding columns, not one sample."""
        monkeypatch.setenv("PGVECTOR_DIM", "128")
        _clear_settings_caches()

        rows = [
            ("media_identities", "embedding", 128),  # matches
            ("identity_cluster_representatives", "embedding", 512),  # drift
            ("mv_identity_cluster_centroids", "centroid", 128),
        ]
        session = _mock_session_with_vector_typmods(rows)

        result = await check_database(session)

        assert result.status is HealthStatus.UNHEALTHY
        assert "512" in result.detail or "mismatch" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_missing_or_empty_vector_schema_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No typmod rows (missing schema) must not report database ready."""
        monkeypatch.setenv("PGVECTOR_DIM", "128")
        _clear_settings_caches()

        session = _mock_session_with_vector_typmods([])

        result = await check_database(session)

        assert result.status is HealthStatus.UNHEALTHY
        detail_l = result.detail.lower()
        assert (
            "missing" in detail_l
            or "schema" in detail_l
            or "vector" in detail_l
            or "dimension" in detail_l
            or "typmod" in detail_l
        ), f"fail-closed detail expected; got {result.detail!r}"

    @pytest.mark.asyncio
    async def test_malformed_typmod_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unparseable / non-positive vector dims fail closed (no silent OK)."""
        monkeypatch.setenv("PGVECTOR_DIM", "128")
        _clear_settings_caches()

        rows = [
            ("media_identities", "embedding", 0),
            ("identity_cluster_representatives", "embedding", -1),
        ]
        session = _mock_session_with_vector_typmods(rows)

        result = await check_database(session)

        assert result.status is HealthStatus.UNHEALTHY

    def test_typmod_sql_scopes_to_current_schema_not_hardcoded_public(self) -> None:
        """FIR-FINAL2-LOCAL-02: readiness catalog probe must follow schema contract.

        Migration/heal/verify use current_schema(); hardcoding n.nspname='public'
        leaves correct non-public search_path installs permanently unready
        ([rg-005], [SERVE-01]).
        """
        from recognition.application import health as health_mod

        sql = health_mod._IDENTITY_VECTOR_TYPMOD_SQL
        assert "current_schema()" in sql, (
            "typmod probe must filter by current_schema() (or equivalent visible "
            f"relation strategy); got SQL:\n{sql}"
        )
        # Hardcoded public is the bug: reject exact nspname = 'public' / "public".
        assert "nspname = 'public'" not in sql
        assert 'nspname = "public"' not in sql
        assert "nspname='public'" not in sql.replace(" ", "")


# ---------------------------------------------------------------------------
# FINALA-03 — admission must not succeed after deadline
# ---------------------------------------------------------------------------


class TestFinalA03AdmissionDeadlineHonored:
    """FacePipelineAdmissionGate must not consume a permit after its deadline.

    Current poll loop checks remaining time before ``asyncio.sleep`` but may
    ``acquire`` after a delayed wake once a permit appears. That launches
    inference past the caller's budget ([RES-02/03], [TEST-08]).
    """

    @pytest.mark.asyncio
    async def test_delayed_wake_after_deadline_does_not_consume_permit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from recognition.infrastructure.embeddings.face_pipeline_adapter import (
            FacePipelineAdmissionGate,
        )

        gate = FacePipelineAdmissionGate(1)

        # Occupy the sole permit so the waiter must poll.
        await gate.acquire(timeout_s=1.0)

        clock = {"t": 1000.0}

        def fake_perf_counter() -> float:
            return clock["t"]

        async def overshooting_sleep(delay: float) -> None:
            # Wake after the deadline (simulates scheduler delay / overshoot).
            clock["t"] += max(float(delay), 0.0) + 0.05
            # Permit becomes available only after the deadline has passed.
            gate.release()

        monkeypatch.setattr(
            "recognition.infrastructure.embeddings.face_pipeline_adapter.time.perf_counter",
            fake_perf_counter,
        )
        monkeypatch.setattr(
            "recognition.infrastructure.embeddings.face_pipeline_adapter.asyncio.sleep",
            overshooting_sleep,
        )

        with pytest.raises(TimeoutError):
            await gate.acquire(timeout_s=0.01)

        # The permit released after the deadline must remain free — not stolen
        # by the timed-out waiter. Immediate non-blocking re-acquire proves it.
        reclaimed = gate._sem.acquire(blocking=False)
        assert reclaimed is True, (
            "timed-out admission must not consume a permit that became free "
            "only after the deadline (would launch useless inference)"
        )
        gate.release()


# ---------------------------------------------------------------------------
# FINALA-04 — finite strictly-positive face_pipeline timeout
# ---------------------------------------------------------------------------


class TestFinalA04TimeoutFinitePositive:
    """DB_EMBEDDING_TIMEOUT_SECONDS / FacePipelineSettings.timeout_s validation.

    nan / ±inf / 0 / negative must not load into a serving timeout that can
    create an unbounded saturated admission wait ([CFG-01/02], [RES-03]).
    """

    @pytest.mark.parametrize(
        "raw",
        ["nan", "NaN", "inf", "+inf", "-inf", "0", "-1", "-0.5", "0.0"],
    )
    def test_db_embedding_timeout_rejects_non_finite_or_non_positive(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, tmp_path
    ) -> None:
        import db.settings as db_settings_mod

        monkeypatch.setenv("DB_EMBEDDING_TIMEOUT_SECONDS", raw)
        for key in (
            "PGUSER",
            "PGPASSWORD",
            "PGHOST",
            "PGPORT",
            "DB_NAME",
            "POSTGRES_DSN",
            "POSTGRES_SYNC_DSN",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(db_settings_mod, "ENV_FILE", tmp_path / ".env")
        db_settings_mod.get_database_settings.cache_clear()

        with pytest.raises((ValueError, ValidationError)):
            db_settings_mod.get_database_settings()

        db_settings_mod.get_database_settings.cache_clear()

    @pytest.mark.parametrize(
        "bad",
        [float("nan"), float("inf"), float("-inf"), 0.0, -1.0, -0.01],
    )
    def test_face_pipeline_timeout_s_rejects_non_finite_or_non_positive(
        self, bad: float
    ) -> None:
        mod = _fresh_settings_module()
        with pytest.raises((ValueError, ValidationError)):
            mod.FacePipelineSettings(timeout_s=bad)

    def test_face_pipeline_timeout_s_preserves_valid_positive(self) -> None:
        mod = _fresh_settings_module()
        settings = mod.FacePipelineSettings(timeout_s=7.5)
        assert settings.timeout_s == 7.5
        assert math.isfinite(settings.timeout_s)
        assert settings.timeout_s > 0

    def test_db_embedding_timeout_preserves_valid_positive(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        import db.settings as db_settings_mod

        monkeypatch.setenv("DB_EMBEDDING_TIMEOUT_SECONDS", "12.25")
        for key in (
            "PGUSER",
            "PGPASSWORD",
            "PGHOST",
            "PGPORT",
            "DB_NAME",
            "POSTGRES_DSN",
            "POSTGRES_SYNC_DSN",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(db_settings_mod, "ENV_FILE", tmp_path / ".env")
        db_settings_mod.get_database_settings.cache_clear()
        try:
            settings = db_settings_mod.get_database_settings()
            assert settings.embedding_timeout_s == 12.25
            assert math.isfinite(settings.embedding_timeout_s)
            assert settings.embedding_timeout_s > 0
        finally:
            db_settings_mod.get_database_settings.cache_clear()
            monkeypatch.delenv("DB_EMBEDDING_TIMEOUT_SECONDS", raising=False)

    def test_nan_env_does_not_propagate_into_face_pipeline_timeout(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """End-to-end: nan DB timeout must not load RecognitionSettings.timeout_s."""
        import db.settings as db_settings_mod

        monkeypatch.setenv("DB_EMBEDDING_TIMEOUT_SECONDS", "nan")
        for key in (
            "PGUSER",
            "PGPASSWORD",
            "PGHOST",
            "PGPORT",
            "DB_NAME",
            "POSTGRES_DSN",
            "POSTGRES_SYNC_DSN",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(db_settings_mod, "ENV_FILE", tmp_path / ".env")
        db_settings_mod.get_database_settings.cache_clear()
        _clear_settings_caches()

        mod = _fresh_settings_module()
        with pytest.raises((ValueError, ValidationError)):
            # Either DatabaseSettings or FacePipelineSettings must reject.
            db = db_settings_mod.get_database_settings()
            # If DB unexpectedly accepts nan, FacePipelineSettings must still fail.
            mod.FacePipelineSettings(timeout_s=db.embedding_timeout_s)

        db_settings_mod.get_database_settings.cache_clear()


# ---------------------------------------------------------------------------
# FINALB-01 — ConfidenceCheck pose safety (canonical quality stays pose-neutral)
# ---------------------------------------------------------------------------


def _make_settings() -> ClusteringSettings:
    return ClusteringSettings(
        similarity_threshold=0.75,
        suggestion_floor=0.65,
        suggestion_ceiling=0.75,
        early_stage_suggestion_enabled=True,
    )


def _make_candidate(
    *,
    similarity: float,
    confidence: float = 0.99,
    bbox_size: int = 200,
    pose_pitch: float | None = 0.0,
    pose_yaw: float | None = 0.0,
    pose_roll: float | None = 0.0,
    cluster_id: str = "cluster-1",
) -> AssignmentCandidate:
    """Candidate exercising real pose fields on MediaIdentity (not quality API)."""
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=np.zeros(128, dtype=np.float32),
        confidence=confidence,
        bbox_width=bbox_size,
        bbox_height=bbox_size,
        pose_pitch=pose_pitch,
        pose_yaw=pose_yaw,
        pose_roll=pose_roll,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=np.zeros(128, dtype=np.float32),
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=similarity,
    )


def _maturity_repo(
    level: ClusterMaturityLevel = ClusterMaturityLevel.MATURE,
    adj: float = 0.0,
    *,
    identity_count: int = 20,
    representative_count: int = 5,
):
    """Repo stub. MATURE dampening=1.0 so quality_adj is undamped (-0.05 high)."""
    repo = MagicMock()
    repo.get_maturity_info = AsyncMock(
        return_value=ClusterMaturityInfo(
            level=level,
            identity_count=identity_count,
            representative_count=representative_count,
            user_confirmed=False,
            threshold_adjustment=adj,
        )
    )
    repo.get_curriculum_t = AsyncMock(return_value=0.0)
    return repo


class TestFinalB01ConfidenceCheckPoseSafety:
    """Assignment-policy safety at ConfidenceCheck — not IdentityQualityInfo.

    FIR2-BR-03 keeps canonical ``IdentityQualityInfo.score`` pose-neutral
    (confidence × bbox only). That correctly avoids disadvantaging pose-free
    models in the score formula, but assignment must still refuse quality-derived
    *leniency* for extreme or unknown pose ([CAL-01]).
    """

    def test_canonical_quality_score_remains_pose_neutral(self) -> None:
        """Do not reintroduce pose into IdentityQualityInfo.score / pose_penalty."""
        frontal = compute_identity_quality(confidence=0.99, bbox_width=200, bbox_height=200)
        # Pose is not a quality input — score is confidence×size only.
        again = compute_identity_quality(confidence=0.99, bbox_width=200, bbox_height=200)
        assert frontal.score == again.score
        assert not hasattr(frontal, "pose_penalty")

    @pytest.mark.asyncio
    async def test_extreme_pose_does_not_receive_quality_leniency(self) -> None:
        """Large pitch/yaw must not inherit high-quality threshold relaxation."""
        # maturity_adj=0 so quality_adj is isolated; MATURE dampening keeps -0.05 full.
        check = ConfidenceCheck(_make_settings(), _maturity_repo(adj=0.0))
        # High confidence + large bbox would normally yield quality_adj=-0.05.
        extreme = _make_candidate(
            similarity=0.70,
            confidence=0.99,
            bbox_size=200,
            pose_pitch=60.0,
            pose_yaw=80.0,
            pose_roll=0.0,
        )

        result = await check.evaluate(extreme)

        quality_adj = result.metadata["quality_adj"]
        assert quality_adj >= 0.0, (
            "extreme pose must not receive quality-derived leniency "
            f"(quality_adj={quality_adj}); retain conservative / non-negative adj"
        )
        # Canonical score may still be high (pose-neutral); policy is the gate.
        assert result.metadata["quality_score"] >= 0.9

    @pytest.mark.asyncio
    async def test_missing_pose_does_not_receive_quality_leniency(self) -> None:
        """Pose-unknown detections must not silently get high-quality leniency."""
        check = ConfidenceCheck(_make_settings(), _maturity_repo(adj=0.0))
        missing = _make_candidate(
            similarity=0.70,
            confidence=0.99,
            bbox_size=200,
            pose_pitch=None,
            pose_yaw=None,
            pose_roll=None,
        )

        result = await check.evaluate(missing)

        quality_adj = result.metadata["quality_adj"]
        assert quality_adj >= 0.0, (
            "missing pose must not receive quality-derived leniency "
            f"(quality_adj={quality_adj}); fail closed without pose evidence"
        )

    @pytest.mark.asyncio
    async def test_frontal_pose_may_retain_quality_derived_leniency(self) -> None:
        """Demonstrably frontal high-quality faces may keep normal leniency."""
        check = ConfidenceCheck(_make_settings(), _maturity_repo(adj=0.0))
        frontal = _make_candidate(
            similarity=0.70,
            confidence=0.99,
            bbox_size=200,
            pose_pitch=0.0,
            pose_yaw=0.0,
            pose_roll=0.0,
        )

        result = await check.evaluate(frontal)

        quality_adj = result.metadata["quality_adj"]
        assert quality_adj < 0.0, (
            "frontal high-quality face should retain quality-derived leniency; "
            f"got quality_adj={quality_adj}"
        )
        assert quality_adj == pytest.approx(-0.05, abs=0.0001)

    @pytest.mark.asyncio
    async def test_extreme_vs_frontal_threshold_direction(self) -> None:
        """Extreme pose final_threshold must be strictly stricter than frontal leniency."""
        check = ConfidenceCheck(_make_settings(), _maturity_repo(adj=0.0))
        common = {"similarity": 0.70, "confidence": 0.99, "bbox_size": 200}

        frontal = await check.evaluate(
            _make_candidate(**common, pose_pitch=0.0, pose_yaw=0.0, pose_roll=0.0)
        )
        extreme = await check.evaluate(
            _make_candidate(**common, pose_pitch=55.0, pose_yaw=70.0, pose_roll=10.0)
        )

        # Same pose-neutral quality_score; assignment policy differs on quality_adj.
        assert extreme.metadata["quality_score"] == frontal.metadata["quality_score"]
        assert frontal.metadata["quality_adj"] < 0.0, "frontal high-quality retains leniency"
        assert extreme.metadata["quality_adj"] >= 0.0, (
            "extreme must drop leniency (non-negative quality_adj); "
            f"got {extreme.metadata['quality_adj']}"
        )
        assert extreme.metadata["final_threshold"] > frontal.metadata["final_threshold"], (
            "extreme pose must tighten vs frontal leniency; "
            f"extreme={extreme.metadata['final_threshold']} "
            f"frontal={frontal.metadata['final_threshold']}"
        )
