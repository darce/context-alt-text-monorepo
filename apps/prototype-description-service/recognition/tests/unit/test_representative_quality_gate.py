"""FIR-6 S3b: quality-gated enrollment + representative scoring multiplier.

Pins:
- below-floor exclusion when floors are active
- no-op default floors change nothing (dark parity)
- f≡1 when any factor is None or floors are no-op (GR-09)
- per-source weighting constants are declared and sum to 1
- _create_and_add_representative refuses below-floor identities
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.assignment.quality import compute_identity_quality
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.persistence.representative_selector import (
    REPRESENTATIVE_MULTIPLIER_WEIGHT_EMBEDDING_NORM,
    REPRESENTATIVE_MULTIPLIER_WEIGHT_OCCLUSION,
    REPRESENTATIVE_MULTIPLIER_WEIGHT_SHARPNESS,
    EnrollmentFloors,
    RepresentativeSelector,
    _compute_identity_quality,
    enrollment_floors_from_settings,
    passes_enrollment_floors,
    representative_quality_multiplier,
)
from recognition.application.settings.clustering import ClusteringSettings, QualitySettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.domain.representative import ClusterRepresentative


def _unit_vector(index: int = 0, length: int = 512) -> np.ndarray:
    vec = np.zeros(length, dtype=np.float32)
    vec[index % length] = 1.0
    return vec


def _identity(
    *,
    index: int = 0,
    confidence: float = 0.95,
    sharpness: float | None = None,
    embedding_norm: float | None = None,
    occlusion_severity: float | None = None,
) -> MediaIdentity:
    return MediaIdentity(
        id=f"id-{index}",
        tenant_id="tenant-1",
        media_id=f"media-{index}",
        embedding=_unit_vector(index),
        confidence=confidence,
        bbox_width=120,
        bbox_height=120,
        sharpness=sharpness,
        embedding_norm=embedding_norm,
        occlusion_severity=occlusion_severity,
    )


def _active_quality() -> QualitySettings:
    return QualitySettings(
        factor_floor_sharpness=10.0,
        factor_floor_embedding_norm=3.0,
        factor_ceiling_occlusion=0.5,
    )


def _active_settings() -> ClusteringSettings:
    return ClusteringSettings(
        max_representatives_per_cluster=5,
        pose_diversity_bonus=2,
        representative_diversity_threshold=0.9,
        quality=_active_quality(),
    )


def _noop_settings() -> ClusteringSettings:
    return ClusteringSettings(
        max_representatives_per_cluster=5,
        pose_diversity_bonus=2,
        representative_diversity_threshold=0.9,
    )


def _accept(identity: MediaIdentity, cluster_id: str = "c1") -> AssignmentDecision:
    candidate = AssignmentCandidate(
        identity=identity,
        identity_vector=np.asarray(identity.embedding, dtype=np.float32),
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.92,
    )
    return AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=["all"],
        checks_failed=[],
    )


class TestEnrollmentFloors:
    def test_noop_defaults_accept_everything(self) -> None:
        floors = EnrollmentFloors()
        assert floors.is_noop is True
        assert passes_enrollment_floors(_identity(sharpness=0.0, embedding_norm=0.0, occlusion_severity=1.0), floors)
        assert passes_enrollment_floors(_identity(), floors)  # all None factors

    def test_active_floors_exclude_below_sharpness(self) -> None:
        floors = EnrollmentFloors(floor_sharpness=10.0, floor_embedding_norm=0.0, ceiling_occlusion=1.0)
        assert not passes_enrollment_floors(
            _identity(sharpness=5.0, embedding_norm=10.0, occlusion_severity=0.1), floors
        )

    def test_active_floors_exclude_below_embedding_norm(self) -> None:
        floors = EnrollmentFloors(floor_sharpness=0.0, floor_embedding_norm=3.0, ceiling_occlusion=1.0)
        assert not passes_enrollment_floors(
            _identity(sharpness=50.0, embedding_norm=1.0, occlusion_severity=0.1), floors
        )

    def test_active_floors_exclude_high_occlusion(self) -> None:
        floors = EnrollmentFloors(floor_sharpness=0.0, floor_embedding_norm=0.0, ceiling_occlusion=0.5)
        assert not passes_enrollment_floors(
            _identity(sharpness=50.0, embedding_norm=10.0, occlusion_severity=0.9), floors
        )

    def test_active_floors_accept_passing_observation(self) -> None:
        floors = EnrollmentFloors(floor_sharpness=10.0, floor_embedding_norm=3.0, ceiling_occlusion=0.5)
        assert passes_enrollment_floors(
            _identity(sharpness=50.0, embedding_norm=10.0, occlusion_severity=0.2), floors
        )

    def test_none_factors_never_fail_active_floors(self) -> None:
        """Insightface path: missing factors must not exclude (dark parity)."""
        floors = EnrollmentFloors(floor_sharpness=10.0, floor_embedding_norm=3.0, ceiling_occlusion=0.5)
        assert passes_enrollment_floors(_identity(), floors)

    def test_floors_from_quality_settings(self) -> None:
        settings = _active_settings()
        floors = enrollment_floors_from_settings(settings)
        assert floors.floor_sharpness == 10.0
        assert floors.floor_embedding_norm == 3.0
        assert floors.ceiling_occlusion == 0.5
        assert floors.is_noop is False


class TestRepresentativeQualityMultiplier:
    def test_weights_declared_and_sum_to_one(self) -> None:
        total = (
            REPRESENTATIVE_MULTIPLIER_WEIGHT_SHARPNESS
            + REPRESENTATIVE_MULTIPLIER_WEIGHT_EMBEDDING_NORM
            + REPRESENTATIVE_MULTIPLIER_WEIGHT_OCCLUSION
        )
        assert total == pytest.approx(1.0)

    def test_f_equals_one_when_any_factor_none(self) -> None:
        floors = EnrollmentFloors(floor_sharpness=10.0, floor_embedding_norm=3.0, ceiling_occlusion=0.5)
        assert (
            representative_quality_multiplier(
                sharpness=None,
                embedding_norm=5.0,
                occlusion_severity=0.1,
                floors=floors,
            )
            == 1.0
        )
        assert (
            representative_quality_multiplier(
                sharpness=50.0,
                embedding_norm=None,
                occlusion_severity=0.1,
                floors=floors,
            )
            == 1.0
        )
        assert (
            representative_quality_multiplier(
                sharpness=50.0,
                embedding_norm=5.0,
                occlusion_severity=None,
                floors=floors,
            )
            == 1.0
        )

    def test_f_equals_one_when_floors_noop(self) -> None:
        """Even with full factors present, no-op floors keep f≡1 (pre-S4 dark)."""
        f = representative_quality_multiplier(
            sharpness=1.0,
            embedding_norm=0.5,
            occlusion_severity=0.9,
            floors=EnrollmentFloors(),
        )
        assert f == 1.0

    def test_f_discriminates_when_floors_active(self) -> None:
        floors = EnrollmentFloors(floor_sharpness=10.0, floor_embedding_norm=3.0, ceiling_occlusion=0.5)
        weak = representative_quality_multiplier(
            sharpness=10.0,
            embedding_norm=3.0,
            occlusion_severity=0.4,
            floors=floors,
        )
        strong = representative_quality_multiplier(
            sharpness=40.0,
            embedding_norm=12.0,
            occlusion_severity=0.05,
            floors=floors,
        )
        assert 0.0 < weak < strong <= 1.0

    def test_score_parity_with_base_when_factorless(self) -> None:
        settings = _noop_settings()
        identity = _identity(confidence=0.9)
        base = compute_identity_quality(
            confidence=identity.confidence,
            bbox_width=identity.bbox_width,
            bbox_height=identity.bbox_height,
            settings=settings.quality,
        ).score
        assert _compute_identity_quality(identity, settings) == base

    def test_score_parity_with_factors_under_noop_floors(self) -> None:
        settings = _noop_settings()
        identity = _identity(
            confidence=0.9,
            sharpness=5.0,
            embedding_norm=1.0,
            occlusion_severity=0.8,
        )
        base = compute_identity_quality(
            confidence=identity.confidence,
            bbox_width=identity.bbox_width,
            bbox_height=identity.bbox_height,
            settings=settings.quality,
            occlusion_severity=identity.occlusion_severity,
        ).score
        assert _compute_identity_quality(identity, settings) == base

    def test_score_multiplied_when_floors_active(self) -> None:
        """Pin expected f and scored value with literals (not the multiplier under test).

        floors s=10, n=3, o=0.5; factors at floor (10, 3) and o=0.4:
        s_term=10/(2*10)=0.5, n_term=3/(2*3)=0.5, o_term=1-0.4/0.5=0.2
        equal 1/3 weights → f = (0.5+0.5+0.2)/3 = 0.4 exactly.
        base score = conf*size = 0.95*1.0 = 0.95 → scored = round(0.95*0.4, 3) = 0.38.
        """
        settings = _active_settings()
        identity = _identity(
            confidence=0.95,
            sharpness=10.0,
            embedding_norm=3.0,
            occlusion_severity=0.4,
        )
        base = compute_identity_quality(
            confidence=identity.confidence,
            bbox_width=identity.bbox_width,
            bbox_height=identity.bbox_height,
            settings=settings.quality,
            occlusion_severity=identity.occlusion_severity,
        ).score
        assert base == pytest.approx(0.95)
        scored = _compute_identity_quality(identity, settings)
        # Literal pins — must not call representative_quality_multiplier for expected.
        assert representative_quality_multiplier(
            sharpness=10.0,
            embedding_norm=3.0,
            occlusion_severity=0.4,
            floors=EnrollmentFloors(floor_sharpness=10.0, floor_embedding_norm=3.0, ceiling_occlusion=0.5),
        ) == pytest.approx(0.4)
        assert scored == pytest.approx(0.38)
        assert scored < base

    def test_f_can_reach_zero_when_all_soft_terms_bottom_out(self) -> None:
        """Soft terms clamp to 0 → f ∈ [0, 1], not (0, 1]."""
        floors = EnrollmentFloors(floor_sharpness=10.0, floor_embedding_norm=3.0, ceiling_occlusion=0.5)
        f = representative_quality_multiplier(
            sharpness=0.0,
            embedding_norm=0.0,
            occlusion_severity=0.5,
            floors=floors,
        )
        assert f == pytest.approx(0.0)


class TestShouldAddRepresentativeGate:
    @pytest.fixture
    def cluster_repo(self) -> AsyncMock:
        repo = AsyncMock(spec=ClusterRepository)
        repo.get_all_representatives.return_value = []
        return repo

    @pytest.mark.asyncio
    async def test_below_floor_excluded_when_active(self, cluster_repo: AsyncMock) -> None:
        selector = RepresentativeSelector(_active_settings(), cluster_repo)
        weak = _identity(sharpness=1.0, embedding_norm=10.0, occlusion_severity=0.1)
        adm = await selector.should_add_representative(_accept(weak))
        assert adm.should_add is False
        assert adm.was_upgrade is False
        cluster_repo.remove_representative.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passing_factors_allowed_when_active(self, cluster_repo: AsyncMock) -> None:
        selector = RepresentativeSelector(_active_settings(), cluster_repo)
        good = _identity(sharpness=50.0, embedding_norm=10.0, occlusion_severity=0.1)
        adm = await selector.should_add_representative(_accept(good))
        assert adm.should_add is True

    @pytest.mark.asyncio
    async def test_noop_floors_admit_weak_factors(self, cluster_repo: AsyncMock) -> None:
        selector = RepresentativeSelector(_noop_settings(), cluster_repo)
        weak = _identity(sharpness=0.1, embedding_norm=0.1, occlusion_severity=0.99)
        adm = await selector.should_add_representative(_accept(weak))
        assert adm.should_add is True

    @pytest.mark.asyncio
    async def test_factorless_admitted_under_active_floors(self, cluster_repo: AsyncMock) -> None:
        """Insightface: None factors + active floors still admit (factors unknown)."""
        selector = RepresentativeSelector(_active_settings(), cluster_repo)
        adm = await selector.should_add_representative(_accept(_identity()))
        assert adm.should_add is True


class TestBestAvailableFallback:
    """FIR6S3B-M-01: all-excluded clusters still get a rep (+centroid path)."""

    @pytest.mark.asyncio
    async def test_persist_new_cluster_falls_back_when_all_below_floor(self) -> None:
        cluster_repo = AsyncMock(spec=ClusterRepository)
        member_repo = AsyncMock(spec=MemberRepository)
        saved = []

        async def _save(cluster):  # noqa: ANN001
            if not cluster.id:
                cluster.id = str(uuid.uuid4())
            saved.append(cluster)
            return cluster

        cluster_repo.save = AsyncMock(side_effect=_save)
        cluster_repo.update = AsyncMock(side_effect=lambda c: c)
        cluster_repo.add_representative = AsyncMock()
        cluster_repo.get_all_representatives = AsyncMock(return_value=[])
        member_repo.bulk_add_members_if_not_exists = AsyncMock(return_value=([], 0))

        writer = AssignmentWriter(_active_settings(), cluster_repo, member_repo)
        weak_a = _identity(index=0, sharpness=1.0, embedding_norm=0.5, occlusion_severity=0.9)
        weak_b = _identity(index=1, sharpness=2.0, embedding_norm=0.5, occlusion_severity=0.9)

        cluster = await writer.persist_new_cluster(
            tenant_id="tenant-1",
            identities=[weak_a, weak_b],
            similarities=[1.0, 0.9],
        )

        assert cluster is not None
        # Best-available still creates at least one rep despite active floors.
        assert cluster_repo.add_representative.await_count >= 1
        # Centroid recompute is attempted (empty reps list → None is ok in unit stub;
        # the call path runs only when rep_pool non-empty, which it is).
        # Enforce: create was not floor-gated out (would leave add_representative uncalled).

    @pytest.mark.asyncio
    async def test_recompute_never_null_rep_when_all_below_floor(self) -> None:
        cluster_repo = AsyncMock(spec=ClusterRepository)
        member_repo = AsyncMock(spec=MemberRepository)
        cluster_id = "c-all-weak"
        cluster = type("C", (), {})()
        cluster.id = cluster_id
        cluster.representative_identity_id = "stale"
        cluster_repo.get_by_id = AsyncMock(return_value=cluster)
        cluster_repo.get_all_representatives = AsyncMock(return_value=[])
        cluster_repo.clear_representatives = AsyncMock()
        cluster_repo.add_representative = AsyncMock()
        cluster_repo.update = AsyncMock(side_effect=lambda c: c)

        weak_a = _identity(index=0, sharpness=1.0, embedding_norm=0.5, occlusion_severity=0.9, confidence=0.8)
        weak_b = _identity(index=1, sharpness=2.0, embedding_norm=0.5, occlusion_severity=0.9, confidence=0.99)
        cluster_repo.get_member_identities = AsyncMock(return_value=[weak_a, weak_b])

        writer = AssignmentWriter(_active_settings(), cluster_repo, member_repo)
        await writer.recompute_representatives(cluster_id)

        assert cluster.representative_identity_id is not None
        assert cluster.representative_identity_id == weak_b.id  # higher confidence/quality first
        assert cluster_repo.add_representative.await_count >= 1


class TestCreateAndAddRepresentativeGate:
    @pytest.mark.asyncio
    async def test_create_skips_below_floor(self) -> None:
        cluster_repo = AsyncMock(spec=ClusterRepository)
        member_repo = AsyncMock(spec=MemberRepository)
        writer = AssignmentWriter(_active_settings(), cluster_repo, member_repo)
        weak = _identity(sharpness=1.0, embedding_norm=10.0, occlusion_severity=0.1)

        rep = await writer._create_and_add_representative(
            cluster_id="c1",
            identity=weak,
            reason="diverse_addition",
        )

        assert rep is None
        cluster_repo.add_representative.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_persists_when_passing(self) -> None:
        cluster_repo = AsyncMock(spec=ClusterRepository)
        member_repo = AsyncMock(spec=MemberRepository)
        writer = AssignmentWriter(_active_settings(), cluster_repo, member_repo)
        good = _identity(sharpness=50.0, embedding_norm=10.0, occlusion_severity=0.1)

        rep = await writer._create_and_add_representative(
            cluster_id="c1",
            identity=good,
            reason="diverse_addition",
        )

        assert rep is not None
        assert isinstance(rep, ClusterRepresentative)
        assert rep.quality_score is not None
        cluster_repo.add_representative.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_noop_floors_persists_weak(self) -> None:
        cluster_repo = AsyncMock(spec=ClusterRepository)
        member_repo = AsyncMock(spec=MemberRepository)
        writer = AssignmentWriter(_noop_settings(), cluster_repo, member_repo)
        weak = _identity(sharpness=0.1, embedding_norm=0.1, occlusion_severity=0.99)

        rep = await writer._create_and_add_representative(
            cluster_id="c1",
            identity=weak,
            reason="fps_seed",
        )

        assert rep is not None
        # f≡1 under no-op → quality matches pose-neutral base score.
        base = compute_identity_quality(
            confidence=weak.confidence,
            bbox_width=weak.bbox_width,
            bbox_height=weak.bbox_height,
            settings=_noop_settings().quality,
            occlusion_severity=weak.occlusion_severity,
        ).score
        assert rep.quality_score == base
        cluster_repo.add_representative.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_quality_score_uses_multiplier_when_active(self) -> None:
        cluster_repo = AsyncMock(spec=ClusterRepository)
        member_repo = AsyncMock(spec=MemberRepository)
        settings = _active_settings()
        writer = AssignmentWriter(settings, cluster_repo, member_repo)
        identity = _identity(
            sharpness=10.0,
            embedding_norm=3.0,
            occlusion_severity=0.4,
            confidence=0.95,
        )

        rep = await writer._create_and_add_representative(
            cluster_id="c1",
            identity=identity,
            reason="diverse_addition",
        )

        assert rep is not None
        expected = _compute_identity_quality(identity, settings)
        assert rep.quality_score == expected
        base = compute_identity_quality(
            confidence=identity.confidence,
            bbox_width=identity.bbox_width,
            bbox_height=identity.bbox_height,
            settings=settings.quality,
            occlusion_severity=identity.occlusion_severity,
        ).score
        assert expected < base
