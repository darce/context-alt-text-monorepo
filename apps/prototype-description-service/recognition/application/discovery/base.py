"""
Base interfaces for discovery algorithms that propose assignment candidates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from recognition.domain.identity import MediaIdentity


class DiscoveryAlgorithm(ABC):
    """Defines the contract for generating assignment candidates."""

    @abstractmethod
    async def discover(
        self,
        identities: Sequence[MediaIdentity],
        cluster_data: object,
    ) -> object:
        """Generate candidate assignments from a set of identities.

        Args:
            identities: Detected identities requiring cluster evaluation.
            cluster_data: Discovery-specific cluster metadata or embeddings.

        Returns:
            Discovery-specific result. Most algorithms return a list of AssignmentCandidate.

        Raises:
            NotImplementedError: Always, until algorithm is implemented.
        """
        raise NotImplementedError("TODO: Implement discovery algorithm")
