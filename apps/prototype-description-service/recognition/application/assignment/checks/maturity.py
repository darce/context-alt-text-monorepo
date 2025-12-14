"""
Cluster maturity validation to prevent singleton snowballing.
"""

from __future__ import annotations

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.base import AssignmentCheck, CheckResult
from recognition.application.settings import ClusteringSettings
from recognition.domain.repositories import ClusterRepository


class MaturityCheck(AssignmentCheck):
    """Ensures a cluster has enough representatives before auto-assignment."""

    name = "maturity"

    def __init__(
        self,
        settings: ClusteringSettings,
        cluster_repository: ClusterRepository,
    ) -> None:
        """Initialize the maturity check.

        Args:
            settings: Threshold configuration for minimum representatives.
            cluster_repository: Repository used to query representative counts.
        """
        self.settings = settings
        self.cluster_repository = cluster_repository

    def is_enabled(self) -> bool:
        """Return whether the maturity guard should run.

        Returns:
            bool: True when the guard is active for the current configuration.
        """
        return self.settings.min_representatives_for_maturity > 0

    async def evaluate(self, candidate: AssignmentCandidate) -> CheckResult:
        """Validate that the target cluster is sufficiently mature.

        Args:
            candidate: Proposed assignment to validate for maturity.

        Returns:
            CheckResult: Pass/fail outcome with maturity metadata.
        """
        # For anchor-linked candidates, check if the target cluster is labeled.
        # Labeled clusters have explicit human validation, so we trust them even
        # with fewer representatives. Unlabeled clusters still need maturity protection
        # to prevent singleton snowballing from incorrect anchor matches.
        if candidate.anchor_linked:
            cluster = await self.cluster_repository.get_by_id(candidate.cluster_id)
            if cluster and cluster.label:
                return CheckResult(
                    passed=True,
                    metadata={
                        "bypass_reason": "anchor_linked_to_labeled_cluster",
                        "cluster_label": cluster.label,
                        "discovery_similarity": candidate.discovery_similarity,
                    },
                )

        rep_count = await self.cluster_repository.get_representative_count(candidate.cluster_id)
        metadata = {"representative_count": rep_count}

        if rep_count < self.settings.min_representatives_for_maturity:
            return CheckResult(
                passed=False,
                is_fatal=True,
                should_reject=False,
                reason="cluster not mature",
                metadata=metadata,
            )

        return CheckResult(passed=True, metadata=metadata)
