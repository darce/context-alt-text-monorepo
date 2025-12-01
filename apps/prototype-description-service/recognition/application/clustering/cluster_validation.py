"""Validation helpers for cluster assignments.

Provides multi-stage validation to prevent false positive cluster assignments:
- Borderline validation: Re-checks against cluster centroid for marginal matches
- Member validation: Checks similarity with random existing cluster members
- Centroid validation: Validates centroid-based matches against members
- Suggestion tier: Borderline matches (0.55-0.68) flagged for user confirmation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityMember, MediaIdentity
from recognition.application.clustering.centroid_utils import _normalize_vector, compute_similarity
from recognition.application.clustering.cluster_repository import ClusterSearchEntry
from recognition.application.clustering.clustering_logger import log_validation_result
from recognition.application.clustering.clustering_settings import ClusteringSettings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class MemberValidationResult:
    """Result of member validation with suggestion flag.
    Attributes:
        should_accept: True if the match should be auto-accepted
        should_suggest: True if the match should be surfaced as a suggestion
        avg_member_similarity: Average similarity with existing cluster members
        min_member_similarity: Minimum similarity with any member
        sample_size: Number of members checked
    """

    should_accept: bool
    should_suggest: bool
    avg_member_similarity: float
    min_member_similarity: float
    sample_size: int


class ClusterValidator:
    """Validates identity-to-cluster matches to prevent false positives."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        settings: ClusteringSettings,
        centroid_cache: list[ClusterSearchEntry] | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.settings = settings
        self._centroid_cache = centroid_cache or []

    def set_centroid_cache(self, cache: list[ClusterSearchEntry]) -> None:
        """Update the centroid cache (called when clusters are loaded)."""
        self._centroid_cache = cache

    async def validate_borderline_match(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        rep_similarity: float,
    ) -> bool:
        """
        Validate a borderline representative match against the cluster centroid.

        Returns True if the match should be accepted, False otherwise.
        """
        # Find the centroid for this cluster
        centroid_entry = next(
            (e for e in self._centroid_cache if e.cluster.id == cluster_id),
            None,
        )

        if not centroid_entry:
            logger.warning(
                "No centroid found for cluster %s during borderline validation. Accepting match.",
                cluster_id,
            )
            return True

        centroid_similarity = compute_similarity(identity_vector, centroid_entry.centroid)

        logger.info(
            "Borderline validation: rep=%.4f, centroid=%.4f, validation_threshold=%.4f",
            rep_similarity,
            centroid_similarity,
            self.settings.borderline_validation_threshold,
        )

        if centroid_similarity < self.settings.borderline_validation_threshold:
            logger.warning(
                "BORDERLINE VALIDATION FAILED: identity=%s, rep=%.4f, centroid=%.4f < threshold=%.4f. "
                "Preventing false positive assignment.",
                identity.id,
                rep_similarity,
                centroid_similarity,
                self.settings.borderline_validation_threshold,
            )
            # Structured logging: validation failed
            log_validation_result(
                tenant_id=self.tenant_id,
                identity_id=identity.id,
                cluster_id=cluster_id,
                validation_type="borderline",
                passed=False,
                similarity=centroid_similarity,
                threshold=self.settings.borderline_validation_threshold,
            )
            return False

        logger.info(
            "Borderline validation PASSED: identity=%s, rep=%.4f, centroid=%.4f >= threshold=%.4f",
            identity.id,
            rep_similarity,
            centroid_similarity,
            self.settings.borderline_validation_threshold,
        )
        # Structured logging: validation passed
        log_validation_result(
            tenant_id=self.tenant_id,
            identity_id=identity.id,
            cluster_id=cluster_id,
            validation_type="borderline",
            passed=True,
            similarity=centroid_similarity,
            threshold=self.settings.borderline_validation_threshold,
        )
        return True

    async def validate_member_similarity(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        rep_similarity: float,
    ) -> bool:
        """
        Validate a representative match by checking similarity with random existing cluster members.

        This catches cases where centroid/representatives have drifted but actual members are dissimilar.
        Returns True if the match should be accepted, False otherwise.
        """
        # Get random sample of existing cluster members
        stmt = (
            select(MediaIdentity.embedding)
            .join(IdentityMember, IdentityMember.identity_id == MediaIdentity.id)
            .where(IdentityMember.cluster_id == cluster_id)
            .where(MediaIdentity.id != identity.id)  # Exclude the candidate itself
            .limit(self.settings.member_validation_sample_size)
        )
        result = await self.session.execute(stmt)
        member_embeddings = [row[0] for row in result.all()]

        if not member_embeddings:
            logger.info(
                "No existing members found for cluster %s, skipping member validation",
                cluster_id,
            )
            return True

        # Check similarity with each sampled member
        similarities = []
        for member_emb in member_embeddings:
            member_vector = _normalize_vector(np.array(member_emb, dtype=np.float32))
            sim = compute_similarity(identity_vector, member_vector)
            similarities.append(sim)

        avg_member_similarity = np.mean(similarities)
        min_member_similarity = np.min(similarities)

        logger.info(
            "Member validation: rep=%.4f, avg_member=%.4f, min_member=%.4f, threshold=%.4f, min_floor=%.4f (checked %d members)",
            rep_similarity,
            avg_member_similarity,
            min_member_similarity,
            self.settings.member_validation_threshold,
            self.settings.member_validation_min_floor,
            len(similarities),
        )

        # Check minimum floor first - ANY member below floor triggers rejection
        # This prevents false positives where avg looks good but one member is very different
        if min_member_similarity < self.settings.member_validation_min_floor:
            logger.warning(
                "MEMBER VALIDATION FAILED (min floor): identity=%s, rep=%.4f, min_member=%.4f < floor=%.4f. "
                "At least one existing member is too dissimilar - preventing false positive.",
                identity.id,
                rep_similarity,
                min_member_similarity,
                self.settings.member_validation_min_floor,
            )
            log_validation_result(
                tenant_id=self.tenant_id,
                identity_id=identity.id,
                cluster_id=cluster_id,
                validation_type="member_min_floor",
                passed=False,
                similarity=float(min_member_similarity),
                threshold=self.settings.member_validation_min_floor,
                extra={"avg_member_similarity": float(avg_member_similarity), "sample_size": len(similarities)},
            )
            return False

        # Require average similarity with existing members
        if avg_member_similarity < self.settings.member_validation_threshold:
            logger.warning(
                "MEMBER VALIDATION FAILED: identity=%s, rep=%.4f, avg_member=%.4f < threshold=%.4f. "
                "Preventing false positive (cluster drift detected).",
                identity.id,
                rep_similarity,
                avg_member_similarity,
                self.settings.member_validation_threshold,
            )
            # Structured logging: member validation failed
            log_validation_result(
                tenant_id=self.tenant_id,
                identity_id=identity.id,
                cluster_id=cluster_id,
                validation_type="member",
                passed=False,
                similarity=float(avg_member_similarity),
                threshold=self.settings.member_validation_threshold,
                extra={"min_member_similarity": float(min_member_similarity), "sample_size": len(similarities)},
            )
            return False

        logger.info(
            "Member validation PASSED: identity=%s, rep=%.4f, avg_member=%.4f, min_member=%.4f >= threshold=%.4f",
            identity.id,
            rep_similarity,
            avg_member_similarity,
            min_member_similarity,
            self.settings.member_validation_threshold,
        )
        # Structured logging: member validation passed
        log_validation_result(
            tenant_id=self.tenant_id,
            identity_id=identity.id,
            cluster_id=cluster_id,
            validation_type="member",
            passed=True,
            similarity=float(avg_member_similarity),
            threshold=self.settings.member_validation_threshold,
            extra={"min_member_similarity": float(min_member_similarity), "sample_size": len(similarities)},
        )
        return True

    async def validate_member_similarity_with_suggestion(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        rep_similarity: float,
    ) -> MemberValidationResult:
        """
        Validate a representative match with suggestion tier support.

        Returns a MemberValidationResult with:
        - should_accept: True if avg_member_similarity >= member_validation_threshold (0.68)
        - should_suggest: True if suggestion_threshold (0.55) <= avg_member_similarity < member_validation_threshold
        - similarity scores for logging/persistence
        """
        # Get random sample of existing cluster members
        stmt = (
            select(MediaIdentity.embedding)
            .join(IdentityMember, IdentityMember.identity_id == MediaIdentity.id)
            .where(IdentityMember.cluster_id == cluster_id)
            .where(MediaIdentity.id != identity.id)
            .limit(self.settings.member_validation_sample_size)
        )
        result = await self.session.execute(stmt)
        member_embeddings = [row[0] for row in result.all()]

        if not member_embeddings:
            logger.info(
                "No existing members found for cluster %s, auto-accepting",
                cluster_id,
            )
            return MemberValidationResult(
                should_accept=True,
                should_suggest=False,
                avg_member_similarity=1.0,
                min_member_similarity=1.0,
                sample_size=0,
            )

        # Check similarity with each sampled member
        similarities = []
        for member_emb in member_embeddings:
            member_vector = _normalize_vector(np.array(member_emb, dtype=np.float32))
            sim = compute_similarity(identity_vector, member_vector)
            similarities.append(sim)

        avg_member_similarity = float(np.mean(similarities))
        min_member_similarity = float(np.min(similarities))
        sample_size = len(similarities)

        accept_threshold = self.settings.member_validation_threshold
        suggest_threshold = self.settings.suggestion_threshold
        min_floor = self.settings.member_validation_min_floor

        # Check minimum floor first - ANY member below floor triggers rejection
        # This prevents false positives where avg looks good but one member is very different
        if min_member_similarity < min_floor:
            logger.warning(
                "MEMBER VALIDATION FAILED (min floor): identity=%s, rep=%.4f, min_member=%.4f < floor=%.4f. "
                "At least one existing member is too dissimilar - preventing false positive.",
                identity.id,
                rep_similarity,
                min_member_similarity,
                min_floor,
            )
            log_validation_result(
                tenant_id=self.tenant_id,
                identity_id=identity.id,
                cluster_id=cluster_id,
                validation_type="member_min_floor",
                passed=False,
                similarity=min_member_similarity,
                threshold=min_floor,
                extra={"avg_member_similarity": avg_member_similarity, "sample_size": sample_size},
            )
            return MemberValidationResult(
                should_accept=False,
                should_suggest=False,  # Don't even suggest if min floor fails
                avg_member_similarity=avg_member_similarity,
                min_member_similarity=min_member_similarity,
                sample_size=sample_size,
            )

        # Determine outcome
        if avg_member_similarity >= accept_threshold:
            # Strong match: auto-accept
            logger.info(
                "Member validation PASSED (accept): identity=%s, rep=%.4f, avg_member=%.4f >= %.4f",
                identity.id,
                rep_similarity,
                avg_member_similarity,
                accept_threshold,
            )
            log_validation_result(
                tenant_id=self.tenant_id,
                identity_id=identity.id,
                cluster_id=cluster_id,
                validation_type="member",
                passed=True,
                similarity=avg_member_similarity,
                threshold=accept_threshold,
                extra={"min_member_similarity": min_member_similarity, "sample_size": sample_size},
            )
            return MemberValidationResult(
                should_accept=True,
                should_suggest=False,
                avg_member_similarity=avg_member_similarity,
                min_member_similarity=min_member_similarity,
                sample_size=sample_size,
            )

        if self.settings.suggestion_enabled and avg_member_similarity >= suggest_threshold:
            # Borderline match: suggest for user confirmation
            logger.info(
                "SUGGESTION CANDIDATE: identity=%s, rep=%.4f, avg_member=%.4f "
                "(>= suggestion_threshold=%.4f but < accept_threshold=%.4f)",
                identity.id,
                rep_similarity,
                avg_member_similarity,
                suggest_threshold,
                accept_threshold,
            )
            log_validation_result(
                tenant_id=self.tenant_id,
                identity_id=identity.id,
                cluster_id=cluster_id,
                validation_type="member_suggestion",
                passed=False,
                similarity=avg_member_similarity,
                threshold=accept_threshold,
                extra={
                    "min_member_similarity": min_member_similarity,
                    "sample_size": sample_size,
                    "suggestion_threshold": suggest_threshold,
                },
            )
            return MemberValidationResult(
                should_accept=False,
                should_suggest=True,
                avg_member_similarity=avg_member_similarity,
                min_member_similarity=min_member_similarity,
                sample_size=sample_size,
            )

        # Poor match: reject
        logger.warning(
            "MEMBER VALIDATION FAILED: identity=%s, rep=%.4f, avg_member=%.4f < suggestion_threshold=%.4f",
            identity.id,
            rep_similarity,
            avg_member_similarity,
            suggest_threshold,
        )
        log_validation_result(
            tenant_id=self.tenant_id,
            identity_id=identity.id,
            cluster_id=cluster_id,
            validation_type="member",
            passed=False,
            similarity=avg_member_similarity,
            threshold=suggest_threshold,
            extra={"min_member_similarity": min_member_similarity, "sample_size": sample_size},
        )
        return MemberValidationResult(
            should_accept=False,
            should_suggest=False,
            avg_member_similarity=avg_member_similarity,
            min_member_similarity=min_member_similarity,
            sample_size=sample_size,
        )

    async def validate_representative_match(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        rep_similarity: float,
    ) -> bool:
        """
        Combined validation for representative matches.

        Checks:
        1. Borderline validation (for 0.6-0.7 range): requires centroid >= 0.65
        2. Member validation (for all matches): requires similarity with existing members >= 0.55
        """
        # Check if this is a borderline match
        is_borderline = (
            self.settings.borderline_validation_enabled and rep_similarity < self.settings.borderline_upper_threshold
        )

        # Run borderline validation if needed
        if is_borderline and not await self.validate_borderline_match(
            identity, identity_vector, cluster_id, rep_similarity
        ):
            return False

        # Always run member validation (catches cluster drift)
        return not (
            self.settings.member_validation_enabled
            and not await self.validate_member_similarity(identity, identity_vector, cluster_id, rep_similarity)
        )

    async def validate_representative_match_with_suggestion(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        rep_similarity: float,
    ) -> MemberValidationResult:
        """
        Combined validation for representative matches with suggestion tier support.

        Checks:
        1. Borderline validation (for 0.6-0.7 range): requires centroid >= 0.65
        2. Member validation with suggestion tier

        Returns:
            MemberValidationResult with should_accept, should_suggest flags and similarity metrics.
        """
        # Check if this is a borderline match (centroid validation)
        is_borderline = (
            self.settings.borderline_validation_enabled and rep_similarity < self.settings.borderline_upper_threshold
        )

        # Run borderline validation if needed
        if is_borderline and not await self.validate_borderline_match(
            identity, identity_vector, cluster_id, rep_similarity
        ):
            # Borderline validation failed - reject completely (don't suggest)
            return MemberValidationResult(
                should_accept=False,
                should_suggest=False,
                avg_member_similarity=0.0,
                min_member_similarity=0.0,
                sample_size=0,
            )

        # Run member validation with suggestion tier
        if self.settings.member_validation_enabled:
            return await self.validate_member_similarity_with_suggestion(
                identity, identity_vector, cluster_id, rep_similarity
            )

        # No member validation - auto accept
        return MemberValidationResult(
            should_accept=True,
            should_suggest=False,
            avg_member_similarity=1.0,
            min_member_similarity=1.0,
            sample_size=0,
        )

    async def validate_centroid_match(
        self,
        identity: MediaIdentity,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        centroid_similarity: float,
    ) -> bool:
        """
        Validate centroid match by checking against cluster members.

        Uses similarity_threshold (0.65) for member validation to prevent
        cluster drift from accepting borderline matches.
        """
        # Fetch sample of cluster members for validation
        members_stmt = (
            select(MediaIdentity)
            .join(IdentityMember, MediaIdentity.id == IdentityMember.identity_id)
            .where(IdentityMember.cluster_id == cluster_id)
            .limit(self.settings.member_validation_sample_size)
        )
        members_result = await self.session.execute(members_stmt)
        members = list(members_result.scalars().all())

        if not members:
            logger.info("Centroid match validation: No members found, accepting")
            return True

        # Check similarity with existing members
        similarities = [float(np.dot(identity_vector, member.embedding)) for member in members]
        avg_similarity = float(np.mean(similarities))
        min_similarity = float(np.min(similarities))

        threshold = self.settings.member_validation_threshold
        min_floor = self.settings.member_validation_min_floor

        # Check both average AND minimum floor (prevents false positive from avg hiding low outlier)
        if avg_similarity >= threshold and min_similarity >= min_floor:
            logger.info(
                "Centroid match validation PASSED: centroid=%.4f, avg_member=%.4f, min_member=%.4f >= %.4f",
                centroid_similarity,
                avg_similarity,
                min_similarity,
                threshold,
            )
            return True
        elif min_similarity < min_floor:
            logger.warning(
                "Centroid match validation FAILED: min_member=%.4f < floor %.4f (lookalike detected)",
                min_similarity,
                min_floor,
            )
            return False
        else:
            logger.warning(
                "Centroid match validation FAILED: centroid=%.4f, avg_member=%.4f < %.4f (cluster drift detected)",
                centroid_similarity,
                avg_similarity,
                threshold,
            )
            return False
