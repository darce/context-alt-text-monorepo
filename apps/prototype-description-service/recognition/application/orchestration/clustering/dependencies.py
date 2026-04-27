"""Grouped inputs for incremental clustering orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from recognition.application.assignment import AssignmentGate
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.orchestration.protocols import MergeSuggestionServiceProtocol, SuggestionServiceProtocol
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.observability import ClusteringLogger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from recognition.application.settings import HACSettings
    from recognition.domain.repositories import ConstrainedHACProtocol

ProgressCallback = Callable[[int, int], Awaitable[None]]


@dataclass(frozen=True)
class ClusteringDependencies:
    gate: AssignmentGate
    representative_discovery: RepresentativeDiscovery
    centroid_discovery: CentroidDiscovery
    graph_discovery: GraphDiscovery
    assignment_writer: AssignmentWriter
    suggestion_service: SuggestionServiceProtocol
    merge_suggestion_service: MergeSuggestionServiceProtocol | None = None
    clustering_logger: ClusteringLogger | None = None
    constrained_hac: ConstrainedHACProtocol | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None


@dataclass(frozen=True)
class ClusteringRuntimeConfig:
    hac_settings: HACSettings | None = None
    progress_callback: ProgressCallback | None = None
    commit: bool = True


@dataclass(frozen=True)
class ClusteringContext:
    tenant_id: str
    job_id: str | None = None