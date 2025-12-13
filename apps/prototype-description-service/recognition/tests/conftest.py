"""Shared pytest fixtures and fakes for recognition tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator, Iterable
from datetime import UTC, datetime
from typing import cast

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import Table, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import Tenant
from recognition.application.assignment.gate import AssignmentGate
from recognition.application.discovery.centroid import CentroidDiscovery
from recognition.application.discovery.graph import GraphDiscovery
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.embedding.service import EmbeddingResult, FaceDetection
from recognition.application.orchestration.cluster_service import ClusterService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.scan.service import ScanService
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.service import SuggestionService
from recognition.domain.job import Job, JobStatus, JobType
from recognition.infrastructure.clustering.hdbscan_adapter import HdbscanGraphAlgorithm
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository
from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository
from recognition.infrastructure.repositories.suggestion_repository import SqlAlchemySuggestionRepository
from recognition.interface_adapters.http.schemas.responses import ClusterResponse
from recognition.shared.ids import generate_id

os.environ.setdefault("RECOGNITION_AUTH_ENABLED", "0")


def _clone_cluster(cluster: ClusterResponse, **updates: object) -> ClusterResponse:
    """Copy a ClusterResponse compatible with both Pydantic v1 and v2."""
    copier_v2 = getattr(cluster, "model_copy", None)
    if callable(copier_v2):
        return cast(ClusterResponse, copier_v2(update=updates))
    copier_v1 = getattr(cluster, "copy", None)
    if callable(copier_v1):
        return cast(ClusterResponse, copier_v1(update=updates))
    return cluster


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated in-memory SQLite session with required tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        tables: list[Table] = [
            Table("identity_clusters", Base.metadata),
            Table("identity_cluster_representatives", Base.metadata),
            Table("identity_members", Base.metadata),
            Table("identity_clustering_jobs", Base.metadata),
            Table("identity_scan_jobs", Base.metadata),
            Table("identity_suggestions", Base.metadata),
            Table("api_keys", Base.metadata),
            Table("clustering_job_reports", Base.metadata),
            Table("assignment_decisions", Base.metadata),
            Table("media_identities", Base.metadata),
            Table("tenants", Base.metadata),
        ]
        await conn.run_sync(Base.metadata.create_all, tables=tables)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.begin_nested()

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(sess, transaction):
            if transaction.nested and not transaction._parent.nested:
                sess.begin_nested()

        try:
            yield session
            await session.rollback()
        finally:
            await session.close()

    await engine.dispose()


@pytest_asyncio.fixture
async def tenant(db_session: AsyncSession) -> Tenant:
    """Insert a tenant row for multi-tenant scoped operations."""
    tenant = Tenant(site_url="http://example.test")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest.fixture
def uuid_str() -> str:
    """Return a new UUID string."""
    return str(uuid.uuid4())


class FakeJobRepository:
    """In-memory job repository for orchestration tests."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    async def save(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def update(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job


class FakeJobService:
    """JobService stand-in that avoids persistence."""

    def __init__(self, repository: FakeJobRepository | None = None) -> None:
        self.repository = repository or FakeJobRepository()

    async def create_job(self, job_type: JobType, tenant_id: str, total: int = 0) -> Job:
        job = Job(
            id=str(generate_id()),
            type=job_type,
            tenant_id=tenant_id,
            progress_total=total,
            progress_completed=0,
            status=JobStatus.PENDING,
        )
        return await self.repository.save(job)

    async def start_job(self, job_id: str) -> Job:
        job = await self.repository.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        job.status = JobStatus.RUNNING
        return await self.repository.update(job)

    async def complete_job(self, job_id: str) -> Job:
        job = await self.repository.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        job.complete()
        return await self.repository.update(job)

    async def get_job_status(self, job_id: str) -> Job | None:
        return await self.repository.get(job_id)

    async def cancel_job(self, job_id: str) -> Job:
        job = await self.repository.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        job.fail("canceled")
        return await self.repository.update(job)


class FakeClusterRepository:
    """In-memory cluster repository stub."""

    def __init__(self) -> None:
        self.clusters: dict[str, ClusterResponse] = {}

    async def get_by_id(self, cluster_id: str) -> ClusterResponse | None:
        return self.clusters.get(cluster_id)

    async def get_by_tenant(self, tenant_id: str, *, limit: int = 100, offset: int = 0) -> list[ClusterResponse]:
        return [c for c in self.clusters.values() if c.tenant_id == tenant_id][offset : offset + limit]

    async def save(self, cluster: ClusterResponse) -> ClusterResponse:
        cluster_id = cluster.id or str(generate_id())
        saved = _clone_cluster(cluster, id=cluster_id)
        self.clusters[cluster_id] = saved
        return saved

    async def update(self, cluster: ClusterResponse) -> ClusterResponse:
        self.clusters[cluster.id] = cluster
        return cluster

    async def delete(self, cluster_id: str) -> None:
        self.clusters.pop(cluster_id, None)

    async def get_unclustered(self, tenant_id: str):
        return []

    async def get_representative_count(self, cluster_id: str) -> int:
        return 0

    async def get_all_representatives(self, cluster_id: str):
        return []

    async def get_member_embeddings(self, cluster_id: str):
        return []

    async def assign_identity_to_cluster(self, identity, cluster_id: str) -> None:  # noqa: ANN001
        return None

    async def add_representative(self, representative) -> None:  # noqa: ANN001
        return None


class FakeClusterService:
    """Fake ClusterService for API contract tests."""

    def __init__(self, clusters: list[ClusterResponse] | None = None) -> None:
        self.clusters = clusters or []
        self.calls: list[dict[str, object]] = []

    async def list_clusters(
        self, tenant_id: str, limit: int, offset: int, include_outliers: bool = False
    ) -> list[ClusterResponse]:
        self.calls.append(
            {"method": "list_clusters", "tenant_id": tenant_id, "include_outliers": include_outliers, "limit": limit}
        )
        filtered = [c for c in self.clusters if c.tenant_id == tenant_id]
        return filtered[offset : offset + limit]

    async def cluster_unclustered_identities(self, tenant_id: str):
        self.calls.append({"method": "cluster_unclustered_identities", "tenant_id": tenant_id})
        now = datetime.now(tz=UTC)
        return type(
            "Result",
            (),
            {
                "job_id": str(generate_id()),
                "started_at": now,
                "finished_at": now,
                "completed": 0,
                "total": 0,
            },
        )()

    async def update_cluster(self, cluster_id: str, tenant_id: str, label: str | None) -> ClusterResponse | None:
        cluster = next((c for c in self.clusters if c.id == cluster_id and c.tenant_id == tenant_id), None)
        if not cluster:
            return None
        updated = self._copy_cluster(cluster, label=label, is_labeled=bool(label))
        self._replace_cluster(updated)
        return updated

    async def merge_cluster(
        self, source_cluster_id: str, tenant_id: str, target_cluster_id: str, target_label: str | None
    ) -> ClusterResponse | None:
        source = next((c for c in self.clusters if c.id == source_cluster_id and c.tenant_id == tenant_id), None)
        target = next((c for c in self.clusters if c.id == target_cluster_id and c.tenant_id == tenant_id), None)
        if not source or not target:
            return None
        updated_target = self._copy_cluster(
            target, label=target_label or target.label, member_count=target.member_count + source.member_count
        )
        self._replace_cluster(updated_target)
        self.clusters = [c for c in self.clusters if c.id != source_cluster_id]
        return updated_target

    async def assign_outlier_to_cluster(
        self, identity_id: str, target_cluster_id: str, tenant_id: str, similarity: float = 0.0
    ) -> ClusterResponse | None:
        target = next((c for c in self.clusters if c.id == target_cluster_id and c.tenant_id == tenant_id), None)
        if not target:
            return None
        updated = self._copy_cluster(target, member_count=target.member_count + 1)
        self._replace_cluster(updated)
        return updated

    def _replace_cluster(self, cluster: ClusterResponse) -> None:
        self.clusters = [c for c in self.clusters if c.id != cluster.id]
        self.clusters.append(cluster)

    def _copy_cluster(self, cluster: ClusterResponse, **updates) -> ClusterResponse:
        return _clone_cluster(cluster, **updates)


# ----------------------------------------------------------------------
# Integration Test Protocol Fakes
# ----------------------------------------------------------------------


class FakeDetector:
    """Deterministic fake detector for integration tests."""

    async def detect(self, media_ids: Iterable[str]) -> list[FaceDetection]:
        detections = []
        for mid in media_ids:
            # Deterministic detection per media ID
            detection = FaceDetection(
                media_id=mid,
                bbox=(10, 10, 100, 100),
                confidence=0.99,
            )
            detections.append(detection)
        return detections


class FakeEmbeddingGenerator:
    """Deterministic fake embedding generator."""

    def __init__(self, embedding_dim: int = 512) -> None:
        self.embedding_dim = embedding_dim

    async def generate(self, face_images: list[bytes]) -> list[EmbeddingResult]:
        results = []
        for idx, img_bytes in enumerate(face_images):
            # Seed based on input bytes to be deterministic
            seed = int.from_bytes(img_bytes[:4], "little") + idx
            rng = np.random.default_rng(seed)
            vector = rng.random(self.embedding_dim).astype(np.float32)
            # Normalize
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector = vector / norm

            results.append(
                EmbeddingResult(
                    media_id="placeholder",
                    embedding=vector,
                    confidence=0.95,
                )
            )
        return results


# ----------------------------------------------------------------------
# Integration Test Fixtures (Real Dependencies)
# ----------------------------------------------------------------------


@pytest.fixture
def job_repository(db_session: AsyncSession) -> SqlAlchemyJobRepository:
    return SqlAlchemyJobRepository(db_session)


@pytest.fixture
def cluster_repository(db_session: AsyncSession) -> SqlAlchemyClusterRepository:
    return SqlAlchemyClusterRepository(db_session)


@pytest.fixture
def member_repository(db_session: AsyncSession, tenant: Tenant) -> SqlAlchemyMemberRepository:
    return SqlAlchemyMemberRepository(db_session, tenant_id=tenant.id)


@pytest.fixture
def suggestion_repository(db_session: AsyncSession, tenant: Tenant) -> SqlAlchemySuggestionRepository:
    return SqlAlchemySuggestionRepository(db_session, tenant_id=tenant.id)


@pytest.fixture
def scan_service(db_session: AsyncSession) -> ScanService:
    # Use deterministic fakes
    return ScanService(
        session=db_session,
        detector=FakeDetector(),
        generator=FakeEmbeddingGenerator(embedding_dim=512),
    )


@pytest.fixture
def assignment_writer(
    cluster_repository: SqlAlchemyClusterRepository, member_repository: SqlAlchemyMemberRepository
) -> AssignmentWriter:
    settings = ClusteringSettings()
    return AssignmentWriter(settings, cluster_repository, member_repository)


@pytest.fixture
def cluster_service(
    db_session: AsyncSession,
    tenant: Tenant,
    cluster_repository: SqlAlchemyClusterRepository,
    member_repository: SqlAlchemyMemberRepository,
    assignment_writer: AssignmentWriter,
    suggestion_repository: SqlAlchemySuggestionRepository,
) -> ClusterService:
    settings = ClusteringSettings()

    # Configure discovery chain
    gate = AssignmentGate(settings, cluster_repository)
    rep_discovery = RepresentativeDiscovery(settings)
    centroid_discovery = CentroidDiscovery(settings)
    graph_discovery = GraphDiscovery(settings, HdbscanGraphAlgorithm())
    suggestions = SuggestionService(suggestion_repository, tenant_id=tenant.id)

    return ClusterService(
        gate=gate,
        representative_discovery=rep_discovery,
        centroid_discovery=centroid_discovery,
        graph_discovery=graph_discovery,
        assignment_writer=assignment_writer,
        suggestion_service=suggestions,
        logger=None,  # Logging not needed for functional integration tests
        session=db_session,  # Required for DB operations in cluster_unclustered_identities
    )
