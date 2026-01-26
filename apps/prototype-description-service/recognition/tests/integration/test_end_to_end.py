from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pytest

from db.models import Tenant
from recognition.application.discovery.graph.algorithm import GraphAlgorithm
from recognition.application.embedding.detector import StubFaceDetector
from recognition.application.embedding.generator import EmbeddingResult
from recognition.application.orchestration.cluster_service import ClusterService
from recognition.application.scan.service import ScanService
from recognition.domain.identity import MediaIdentity
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository


class FixedEmbeddingGenerator:
    """Return the same embedding for every face to make clustering deterministic."""

    def __init__(self, embedding: np.ndarray) -> None:
        self._embedding = embedding

    async def generate(self, face_images: Iterable[bytes]) -> list[EmbeddingResult]:
        return [EmbeddingResult(media_id="fixed", embedding=self._embedding, confidence=0.99) for _ in face_images]


class DeterministicGraphAlgorithm(GraphAlgorithm):
    """Assign all embeddings to a single cluster to make outcomes deterministic."""

    def cluster(
        self,
        embeddings: Sequence[np.ndarray],
        identities: Sequence[MediaIdentity] | None = None,
    ) -> list[int]:
        return [0] * len(embeddings)


@pytest.mark.asyncio
async def test_full_clustering_flow(
    db_session,
    tenant: Tenant,
    cluster_service: ClusterService,
    cluster_repository: SqlAlchemyClusterRepository,
    member_repository: SqlAlchemyMemberRepository,
) -> None:
    """Validate full flow: Scan -> Persist -> Cluster -> Verify."""

    tenant_id = str(tenant.id)
    media_ids = ["media1", "media2", "media3"]  # Detects 1 face per media -> 3 total identities

    embedding = np.zeros(512, dtype=np.float32)
    embedding[0] = 1.0
    scan_service = ScanService(
        session=db_session,
        detector=StubFaceDetector(),
        generator=FixedEmbeddingGenerator(embedding),
    )

    # 1. Analyze Media (Detection + Embedding)
    scan_job = await scan_service.analyze_media(tenant_id=tenant_id, media_ids=media_ids)
    assert scan_job.status == "completed"
    assert scan_job.identities_detected == 3

    # 2. Verify Unclustered Identities
    unclustered = await cluster_repository.get_unclustered(tenant_id)
    assert len(unclustered) == 3

    # 3. Running Clustering
    cluster_service.graph_discovery.set_algorithm(DeterministicGraphAlgorithm())
    result = await cluster_service.cluster_unclustered_identities(tenant_id)

    # 4. Verification
    assert result.completed == 3
    assert result.clusters_created == 1

    # Check Persistence
    clusters = await cluster_repository.get_by_tenant(tenant_id)
    assert len(clusters) == 1

    first_cluster = clusters[0]
    assert first_cluster.identity_count == 3

    # Verify members
    members = await member_repository.get_by_cluster(first_cluster.id)
    assert len(members) == first_cluster.identity_count

    # Verify representatives
    reps = await cluster_repository.get_all_representatives(first_cluster.id)
    assert len(reps) == first_cluster.identity_count
