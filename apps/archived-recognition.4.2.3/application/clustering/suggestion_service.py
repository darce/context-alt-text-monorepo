"""Service for managing identity suggestions.

Handles persistence and resolution of borderline cluster match suggestions
that are surfaced to users for confirmation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import IntEnum
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentitySuggestion

logger = logging.getLogger(__name__)


class SuggestionPriority(IntEnum):
    """Priority levels for identity suggestions.

    Lower values = higher priority = should be shown to user first.

    CRITICAL: Cold start phase (< 30 clusters), every match needs confirmation
              to build ground truth and prevent early pollution.
    HIGH: High similarity match (>0.90) but target cluster not yet user-confirmed.
          Important to validate before the cluster grows.
    NORMAL: Standard suggestions with moderate confidence.
    LOW: Borderline matches with low confidence, can wait.
    """

    CRITICAL = 1  # Cold start, needs immediate confirmation
    HIGH = 2  # High similarity, cluster not confirmed
    NORMAL = 3  # Regular suggestions
    LOW = 4  # Borderline, low confidence


class SuggestionService:
    """Service for creating and resolving identity suggestions."""

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def create_suggestion(
        self,
        identity_id: UUID,
        cluster_id: UUID,
        representative_similarity: float,
        avg_member_similarity: float,
        priority: SuggestionPriority = SuggestionPriority.NORMAL,
    ) -> IdentitySuggestion | None:
        """
        Create a suggestion for a borderline cluster match.

        If a pending suggestion already exists for this identity+cluster pair,
        the existing suggestion is returned unchanged to avoid duplicates.

        Args:
            identity_id: The identity that might belong to the cluster
            cluster_id: The suggested cluster
            representative_similarity: Similarity to cluster representative
            avg_member_similarity: Average similarity to existing cluster members
            priority: Suggestion priority level (default NORMAL)

        Returns:
            The created or existing IdentitySuggestion record, or None if skipped
        """
        # Check if a pending suggestion already exists for this identity+cluster pair
        existing_stmt = select(IdentitySuggestion).where(
            IdentitySuggestion.tenant_id == self.tenant_id,
            IdentitySuggestion.identity_id == identity_id,
            IdentitySuggestion.suggested_cluster_id == cluster_id,
            IdentitySuggestion.resolution == "pending",
        )
        existing_result = await self.session.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()

        if existing:
            logger.debug(
                "Skipping duplicate suggestion: identity=%s -> cluster=%s (already pending)",
                identity_id,
                cluster_id,
            )
            return existing

        confidence_score = self._compute_confidence(representative_similarity, avg_member_similarity)

        suggestion = IdentitySuggestion(
            tenant_id=self.tenant_id,
            identity_id=identity_id,
            suggested_cluster_id=cluster_id,
            representative_similarity=representative_similarity,
            avg_member_similarity=avg_member_similarity,
            confidence_score=confidence_score,
            priority=int(priority),
            resolution="pending",
        )

        self.session.add(suggestion)

        logger.info(
            "Created suggestion: identity=%s -> cluster=%s (rep=%.4f, avg_member=%.4f, confidence=%.4f, priority=%s)",
            identity_id,
            cluster_id,
            representative_similarity,
            avg_member_similarity,
            confidence_score,
            priority.name,
        )

        return suggestion

    async def accept_suggestion(self, suggestion_id: UUID) -> IdentitySuggestion | None:
        """
        Accept a suggestion and assign the identity to the cluster.

        Args:
            suggestion_id: The suggestion to accept

        Returns:
            The updated suggestion, or None if not found
        """
        suggestion = await self.session.get(IdentitySuggestion, suggestion_id)
        if not suggestion or suggestion.tenant_id != self.tenant_id:
            return None

        if suggestion.resolution != "pending":
            logger.warning(
                "Attempted to accept non-pending suggestion %s (resolution=%s)",
                suggestion_id,
                suggestion.resolution,
            )
            return suggestion

        suggestion.resolution = "accepted"
        suggestion.resolved_at = datetime.now(UTC)

        logger.info(
            "Accepted suggestion: identity=%s -> cluster=%s",
            suggestion.identity_id,
            suggestion.suggested_cluster_id,
        )

        return suggestion

    async def reject_suggestion(self, suggestion_id: UUID) -> IdentitySuggestion | None:
        """
        Reject a suggestion.

        Args:
            suggestion_id: The suggestion to reject

        Returns:
            The updated suggestion, or None if not found
        """
        suggestion = await self.session.get(IdentitySuggestion, suggestion_id)
        if not suggestion or suggestion.tenant_id != self.tenant_id:
            return None

        if suggestion.resolution != "pending":
            logger.warning(
                "Attempted to reject non-pending suggestion %s (resolution=%s)",
                suggestion_id,
                suggestion.resolution,
            )
            return suggestion

        suggestion.resolution = "rejected"
        suggestion.resolved_at = datetime.now(UTC)

        logger.info(
            "Rejected suggestion: identity=%s (cluster=%s)",
            suggestion.identity_id,
            suggestion.suggested_cluster_id,
        )

        return suggestion

    async def expire_suggestions_for_identity(self, identity_id: UUID) -> int:
        """
        Expire all pending suggestions for an identity (e.g., when assigned to a cluster).

        Args:
            identity_id: The identity whose suggestions should be expired

        Returns:
            Number of suggestions expired
        """
        stmt = (
            update(IdentitySuggestion)
            .where(IdentitySuggestion.tenant_id == self.tenant_id)
            .where(IdentitySuggestion.identity_id == identity_id)
            .where(IdentitySuggestion.resolution == "pending")
            .values(resolution="expired", resolved_at=datetime.now(UTC))
        )
        result = await self.session.execute(stmt)
        count: int = result.rowcount  # type: ignore[attr-defined]

        if count > 0:
            logger.info("Expired %d pending suggestions for identity %s", count, identity_id)

        return count

    async def expire_suggestions_for_cluster(self, cluster_id: UUID) -> int:
        """
        Expire all pending suggestions for a cluster (e.g., when cluster is deleted).

        Args:
            cluster_id: The cluster whose suggestions should be expired

        Returns:
            Number of suggestions expired
        """
        stmt = (
            update(IdentitySuggestion)
            .where(IdentitySuggestion.tenant_id == self.tenant_id)
            .where(IdentitySuggestion.suggested_cluster_id == cluster_id)
            .where(IdentitySuggestion.resolution == "pending")
            .values(resolution="expired", resolved_at=datetime.now(UTC))
        )
        result = await self.session.execute(stmt)
        count: int = result.rowcount  # type: ignore[attr-defined]

        if count > 0:
            logger.info("Expired %d pending suggestions for cluster %s", count, cluster_id)

        return count

    async def get_pending_suggestions(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[IdentitySuggestion]:
        """
        Get pending suggestions ordered by priority (highest first), then confidence.

        Args:
            limit: Maximum number of suggestions to return
            offset: Number of suggestions to skip

        Returns:
            List of pending suggestions
        """
        stmt = (
            select(IdentitySuggestion)
            .where(IdentitySuggestion.tenant_id == self.tenant_id)
            .where(IdentitySuggestion.resolution == "pending")
            .order_by(
                IdentitySuggestion.priority.asc(),  # Lower priority number = higher urgency
                IdentitySuggestion.confidence_score.desc(),  # Then by confidence
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_pending_suggestions(self) -> int:
        """Count pending suggestions for the tenant."""
        stmt = (
            select(func.count(IdentitySuggestion.id))
            .where(IdentitySuggestion.tenant_id == self.tenant_id)
            .where(IdentitySuggestion.resolution == "pending")
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_suggestion_by_id(self, suggestion_id: UUID) -> IdentitySuggestion | None:
        """Get a suggestion by ID."""
        suggestion = await self.session.get(IdentitySuggestion, suggestion_id)
        if suggestion and suggestion.tenant_id == self.tenant_id:
            return suggestion
        return None

    @staticmethod
    def compute_priority(
        representative_similarity: float,
        cluster_count: int,
        cluster_user_confirmed: bool,
        maturity_point: int = 30,
    ) -> SuggestionPriority:
        """
        Compute suggestion priority based on system state and match quality.

        Priority is determined by:
        1. Cold start phase (< maturity_point clusters) → CRITICAL
        2. High similarity (>0.90) to unconfirmed cluster → HIGH
        3. Normal suggestions → NORMAL
        4. Low confidence/borderline → LOW

        Args:
            representative_similarity: Similarity to cluster representative
            cluster_count: Total number of clusters in the system
            cluster_user_confirmed: Whether the target cluster has been user-confirmed
            maturity_point: Number of clusters at which cold start phase ends

        Returns:
            SuggestionPriority level
        """
        # Cold start: every suggestion is critical
        if cluster_count < maturity_point:
            return SuggestionPriority.CRITICAL

        # High similarity to unconfirmed cluster: important to validate
        if representative_similarity >= 0.90 and not cluster_user_confirmed:
            return SuggestionPriority.HIGH

        # Borderline/low confidence
        if representative_similarity < 0.65:
            return SuggestionPriority.LOW

        return SuggestionPriority.NORMAL

    def _compute_confidence(
        self,
        representative_similarity: float,
        avg_member_similarity: float,
    ) -> float:
        """
        Compute a confidence score for ranking suggestions.

        Combines representative and member similarity with weights:
        - Representative similarity: 60% weight (primary signal)
        - Member similarity: 40% weight (secondary signal)

        Returns a score between 0 and 1.
        """
        return representative_similarity * 0.6 + avg_member_similarity * 0.4
