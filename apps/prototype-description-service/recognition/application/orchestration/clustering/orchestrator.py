"""Incremental clustering orchestration entry point."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusteringJob
from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.assignment import AssignmentGate, AssignmentOutcome
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.orchestration.clustering.chunked_processor import ChunkedIdentityProcessor
from recognition.application.orchestration.clustering.decision_handler import DecisionHandler
from recognition.application.orchestration.clustering.discovery_pipeline import (
    prepare_cluster_caches,
    run_discovery_pipeline,
    run_hac_refinement,
)
from recognition.application.orchestration.clustering.job_result import ClusterJobResult
from recognition.application.orchestration.protocols import SuggestionServiceProtocol
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.identity import MediaIdentity
from recognition.observability import ClusteringLogger
from recognition.observability.recognition_runs import complete_recognition_run, create_recognition_run
from recognition.observability.reports import BatchJobReport
from recognition.shared.ids import generate_id
from recognition.shared.tenant import coerce_tenant_uuid

logger = logging.getLogger(__name__)


async def cluster_unclustered_identities(
    *,
    tenant_id: str,
    job_id: str | None,
    session: AsyncSession,
    gate: AssignmentGate,
    representative_discovery: RepresentativeDiscovery,
    centroid_discovery: CentroidDiscovery,
    graph_discovery: GraphDiscovery,
    assignment_writer: AssignmentWriter,
    suggestion_service: SuggestionServiceProtocol,
    clustering_logger: ClusteringLogger | None = None,
    constrained_hac: Any | None = None,
    hac_settings: Any | None = None,
    progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
    commit: bool = True,
) -> ClusterJobResult:
    """Cluster any identities not yet assigned to a cluster."""
    runner = IncrementalClusteringRunner(
        session=session,
        gate=gate,
        representative_discovery=representative_discovery,
        centroid_discovery=centroid_discovery,
        graph_discovery=graph_discovery,
        assignment_writer=assignment_writer,
        suggestion_service=suggestion_service,
        clustering_logger=clustering_logger,
        constrained_hac=constrained_hac,
        hac_settings=hac_settings,
        progress_callback=progress_callback,
        commit=commit,
    )
    return await runner.run(tenant_id=tenant_id, job_id=job_id)


class IncrementalClusteringRunner:
    """Coordinator for chunked, incremental clustering jobs."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        gate: AssignmentGate,
        representative_discovery: RepresentativeDiscovery,
        centroid_discovery: CentroidDiscovery,
        graph_discovery: GraphDiscovery,
        assignment_writer: AssignmentWriter,
        suggestion_service: SuggestionServiceProtocol,
        clustering_logger: ClusteringLogger | None = None,
        constrained_hac: Any | None = None,
        hac_settings: Any | None = None,
        progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
        commit: bool = True,
    ) -> None:
        self._session = session
        self._gate = gate
        self._representative_discovery = representative_discovery
        self._centroid_discovery = centroid_discovery
        self._graph_discovery = graph_discovery
        self._assignment_writer = assignment_writer
        self._suggestion_service = suggestion_service
        self._clustering_logger = clustering_logger
        self._constrained_hac = constrained_hac
        self._hac_settings = hac_settings
        self._progress_callback = progress_callback
        self._commit = commit
        self._decision_handler = DecisionHandler(
            gate=gate,
            assignment_writer=assignment_writer,
            suggestion_service=suggestion_service,
            clustering_logger=clustering_logger,
            logger_instance=logger,
        )
        self._bind_writer_context = getattr(assignment_writer, "bind_run_context", None)
        self._bind_graph_context = getattr(graph_discovery, "bind_run_context", None)

    async def run(self, *, tenant_id: str, job_id: str | None) -> ClusterJobResult:
        job_id_str, job_uuid, started_at = self._build_job_id(job_id)
        logger.info(
            "[clustering] batch_start job_id=%s tenant_id=%s",
            job_id_str,
            tenant_id,
        )

        tenant_uuid = self._coerce_tenant(tenant_id)
        if tenant_uuid is None:
            return ClusterJobResult(
                job_id=job_id_str,
                started_at=started_at,
                finished_at=started_at,
                completed=0,
                total=0,
                clusters_created=0,
            )

        clustering_job = await self._create_or_update_job(job_uuid, tenant_uuid, started_at)
        job_label = str(clustering_job.id)

        await self._cleanup_orphaned_representatives(tenant_id)

        unclustered = await self._fetch_unclustered_identities(tenant_uuid)
        if not unclustered:
            return await self._complete_empty_job(
                clustering_job=clustering_job,
                started_at=started_at,
                job_label=job_label,
            )

        run_ctx = await self._start_run_context(
            tenant_uuid=tenant_uuid,
            clustering_job=clustering_job,
            dataset=unclustered,
            started_at=started_at,
        )
        self._bind_run_context(run_ctx)

        domain_identities = self._build_domain_identities(unclustered)
        self._log_batch_media_ids(job_id_str, domain_identities)

        total_identities = len(domain_identities)
        clustering_job.total_identities = total_identities
        clustering_job.processed_identities = 0
        clustering_job.progress = 0.0
        await self._session.flush()

        accept_count, suggest_count, reject_count, clusters_created = await self._process_chunks(
            tenant_id=tenant_id,
            job_id=job_id_str,
            job_label=job_label,
            clustering_job=clustering_job,
            identities=domain_identities,
        )

        await self._finalize_job(
            clustering_job=clustering_job,
            run_id=run_ctx.run_id,
            tenant_id=tenant_id,
            started_at=started_at,
            job_id=job_id_str,
            total_identities=total_identities,
            accept_count=accept_count,
            suggest_count=suggest_count,
            reject_count=reject_count,
            clusters_created=clusters_created,
            algorithm=self._graph_discovery.algorithm_name,
        )

        finished_at = clustering_job.completed_at or datetime.now(tz=UTC)
        self._bind_run_context(None)

        return ClusterJobResult(
            job_id=job_label,
            started_at=started_at,
            finished_at=finished_at,
            completed=total_identities,
            total=total_identities,
            clusters_created=clusters_created,
            accepted=accept_count,
            suggested=suggest_count,
            rejected=reject_count,
        )

    @staticmethod
    def _build_job_id(job_id: str | None) -> tuple[str, uuid.UUID, datetime]:
        try:
            job_uuid = uuid.UUID(str(job_id)) if job_id is not None else generate_id()
        except ValueError:
            job_uuid = generate_id()
        return str(job_uuid), job_uuid, datetime.now(tz=UTC)

    @staticmethod
    def _coerce_tenant(tenant_id: str) -> uuid.UUID | None:
        try:
            return coerce_tenant_uuid(tenant_id)
        except ValueError as exc:
            logger.error("[clustering] Invalid tenant_id format: %s, error=%s", tenant_id, exc)
            return None

    async def _create_or_update_job(
        self,
        job_uuid: uuid.UUID,
        tenant_uuid: uuid.UUID,
        started_at: datetime,
    ) -> IdentityClusteringJob:
        clustering_job = IdentityClusteringJob(
            id=job_uuid,
            tenant_id=tenant_uuid,
            status="running",
            started_at=started_at,
            progress=0.0,
            total_identities=0,
            processed_identities=0,
        )
        existing_job = await self._session.get(IdentityClusteringJob, job_uuid)
        if existing_job is not None:
            existing_job.status = "running"
            existing_job.started_at = started_at
            existing_job.progress = 0.0
            clustering_job = existing_job
        else:
            self._session.add(clustering_job)
        await self._session.flush()
        return clustering_job

    async def _cleanup_orphaned_representatives(self, tenant_id: str) -> None:
        try:
            cleaned_count = await self._assignment_writer.cluster_repository.cleanup_orphaned_provisional_reps(
                str(tenant_id)
            )
            if cleaned_count > 0:
                logger.info("[clustering] Cleaned up %d orphaned provisional representatives", cleaned_count)
        except Exception as exc:
            logger.warning("[clustering] Failed to cleanup orphaned representatives: %s", exc)

    async def _fetch_unclustered_identities(self, tenant_uuid: uuid.UUID) -> list[MediaIdentityModel]:
        stmt: Select[tuple[MediaIdentityModel]] = (
            select(MediaIdentityModel)
            .where(MediaIdentityModel.tenant_id == tenant_uuid)
            .where(~exists(select(MemberModel.id).where(MemberModel.identity_id == MediaIdentityModel.id)))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _complete_empty_job(
        self,
        *,
        clustering_job: IdentityClusteringJob,
        started_at: datetime,
        job_label: str,
    ) -> ClusterJobResult:
        clustering_job.status = "completed"
        clustering_job.progress = 1.0
        clustering_job.completed_at = datetime.now(tz=UTC)
        finished_at = clustering_job.completed_at
        await self._session.flush()
        if self._commit:
            await self._session.commit()
        return ClusterJobResult(
            job_id=job_label,
            started_at=started_at,
            finished_at=finished_at,
            completed=0,
            total=0,
            clusters_created=0,
        )

    async def _start_run_context(
        self,
        *,
        tenant_uuid: uuid.UUID,
        clustering_job: IdentityClusteringJob,
        dataset: list[MediaIdentityModel],
        started_at: datetime,
    ):
        dataset_media_ids = sorted({int(row.media_id) for row in dataset if row.media_id is not None})
        return await create_recognition_run(
            self._session,
            tenant_id=tenant_uuid,
            source="cluster_unclustered_identities",
            clustering_job_id=clustering_job.id,
            settings_snapshot=self._gate.settings.model_dump(),
            dataset_selector={"media_ids": dataset_media_ids},
            started_at=started_at,
        )

    def _bind_run_context(self, run_context) -> None:
        if self._clustering_logger:
            self._clustering_logger.bind_run_context(run_context)
        if callable(self._bind_writer_context):
            self._bind_writer_context(run_context)
        if callable(self._bind_graph_context):
            self._bind_graph_context(run_context)

    @staticmethod
    def _build_domain_identities(rows: list[MediaIdentityModel]) -> list[MediaIdentity]:
        return [
            MediaIdentity(
                id=str(row.id),
                tenant_id=str(row.tenant_id),
                media_id=str(row.media_id),
                embedding=np.array(row.embedding, dtype=np.float32),
                confidence=row.confidence,
                bbox_width=row.bbox_width,
                bbox_height=row.bbox_height,
                bbox_x=row.bbox_x,
                bbox_y=row.bbox_y,
                image_phash=row.image_phash,
            )
            for row in rows
        ]

    @staticmethod
    def _log_batch_media_ids(job_id: str, identities: list[MediaIdentity]) -> None:
        media_ids = [i.media_id for i in identities]
        logger.info(
            "[clustering] batch_processing job_id=%s count=%d media_ids=%s",
            job_id,
            len(identities),
            media_ids[:20] if len(media_ids) > 20 else media_ids,
        )

    async def _process_chunks(
        self,
        *,
        tenant_id: str,
        job_id: str,
        job_label: str,
        clustering_job: IdentityClusteringJob,
        identities: list[MediaIdentity],
    ) -> tuple[int, int, int, int]:
        accept_count = 0
        suggest_count = 0
        reject_count = 0
        clusters_created = 0

        processor = ChunkedIdentityProcessor(identities)
        total_identities = processor.total_count

        for chunk, processed_before in processor.iter_chunks():
            logger.info(
                "[clustering] chunk_processing job_id=%s processed=%d/%d chunk_size=%d",
                job_id,
                processed_before,
                total_identities,
                len(chunk),
            )

            representatives_by_cluster, centroids_by_cluster, labeled_cluster_ids = await prepare_cluster_caches(
                self._assignment_writer, str(tenant_id)
            )

            all_candidates, new_cluster_proposals = await run_discovery_pipeline(
                chunk=chunk,
                representative_discovery=self._representative_discovery,
                centroid_discovery=self._centroid_discovery,
                graph_discovery=self._graph_discovery,
                representatives_by_cluster=representatives_by_cluster,
                centroids_by_cluster=centroids_by_cluster,
                labeled_cluster_ids=labeled_cluster_ids,
            )
            logger.info("[clustering] Total candidates to evaluate through gate: %d", len(all_candidates))

            accepted_ids: set[str] = set()
            suggested_ids: set[str] = set()
            rejected_ids: set[str] = set()

            for candidate in all_candidates:
                decision = await self._decision_handler.evaluate_and_handle(
                    candidate,
                    job_id=job_id,
                    job_label=job_label,
                )
                if decision.outcome == AssignmentOutcome.ACCEPT:
                    accept_count += 1
                    accepted_ids.add(candidate.identity.id)
                elif decision.outcome == AssignmentOutcome.SUGGEST:
                    suggest_count += 1
                    suggested_ids.add(candidate.identity.id)
                else:
                    reject_count += 1
                    rejected_ids.add(candidate.identity.id)

            already_in_new_clusters = {member.id for members, _ in new_cluster_proposals for member in members}
            all_processed_ids = accepted_ids | suggested_ids | rejected_ids | already_in_new_clusters
            no_candidates = [i for i in chunk if i.id not in all_processed_ids]
            rejected_identities = [i for i in chunk if i.id in rejected_ids]
            still_unclustered = no_candidates + rejected_identities

            logger.info(
                "[clustering] Identities needing new clusters: %d (no candidates: %d, rejected: %d)",
                len(still_unclustered),
                len(no_candidates),
                len(rejected_identities),
            )

            if still_unclustered:
                final_result = await self._graph_discovery.discover(still_unclustered, {})
                for members, similarities in final_result.new_clusters:
                    if members:
                        cluster = await self._assignment_writer.persist_new_cluster(
                            tenant_id=tenant_id,
                            identities=members,
                            similarities=similarities,
                            algorithm=self._graph_discovery.algorithm_name,
                            clustering_logger=self._clustering_logger,
                        )
                        clusters_created += 1

                        for member in members:
                            await self._suggestion_service.resolve_for_identity_exclusive(
                                identity_id=member.id,
                                accepted_cluster_id=str(cluster.id),
                                reason="auto_new_cluster",
                            )
                        logger.info(
                            "[clustering] new_cluster job_id=%s identity_count=%d media_ids=%s",
                            job_id,
                            len(members),
                            [m.media_id for m in members],
                        )

            for members, similarities in new_cluster_proposals:
                if members:
                    cluster = await self._assignment_writer.persist_new_cluster(
                        tenant_id=tenant_id,
                        identities=members,
                        similarities=similarities,
                        algorithm=self._graph_discovery.algorithm_name,
                        clustering_logger=self._clustering_logger,
                    )
                    clusters_created += 1

                    for member in members:
                        await self._suggestion_service.resolve_for_identity_exclusive(
                            identity_id=member.id,
                            accepted_cluster_id=str(cluster.id),
                            reason="auto_proposal_new_cluster",
                        )
                    logger.info(
                        "[clustering] new_cluster job_id=%s identity_count=%d media_ids=%s",
                        job_id,
                        len(members),
                        [m.media_id for m in members],
                    )

            hac_created = await run_hac_refinement(
                still_unclustered=still_unclustered,
                tenant_id=str(tenant_id),
                job_id=job_id,
                constrained_hac=self._constrained_hac,
                hac_settings=self._hac_settings,
                assignment_writer=self._assignment_writer,
                clustering_logger=self._clustering_logger,
            )
            if hac_created > 0:
                clusters_created += hac_created

            processed = processor.processed_count
            clustering_job.processed_identities = processed
            clustering_job.progress = (processed / total_identities) if total_identities else 1.0
            await self._session.flush()

            if self._progress_callback:
                await self._progress_callback(processed, total_identities)

        return accept_count, suggest_count, reject_count, clusters_created

    async def _finalize_job(
        self,
        *,
        clustering_job: IdentityClusteringJob,
        run_id: uuid.UUID,
        tenant_id: str,
        started_at: datetime,
        job_id: str,
        total_identities: int,
        accept_count: int,
        suggest_count: int,
        reject_count: int,
        clusters_created: int,
        algorithm: str,
    ) -> None:
        try:
            confirmed_count = await self._assignment_writer.cluster_repository.confirm_all_provisional_reps(
                str(tenant_id)
            )
            if confirmed_count > 0:
                logger.info("[clustering] Confirmed %d provisional representatives", confirmed_count)
        except Exception as exc:
            logger.warning("[clustering] Failed to confirm provisional representatives: %s", exc)

        logger.info(
            "[clustering] batch_complete job_id=%s accepted=%d suggested=%d rejected=%d new_clusters=%d",
            job_id,
            accept_count,
            suggest_count,
            reject_count,
            clusters_created,
        )

        clustering_job.total_identities = total_identities
        clustering_job.processed_identities = total_identities
        clustering_job.progress = 1.0
        clustering_job.status = "completed"
        clustering_job.completed_at = datetime.now(tz=UTC)
        await self._session.flush()

        await complete_recognition_run(
            self._session,
            run_id=run_id,
            status="completed",
            completed_at=clustering_job.completed_at,
        )
        if self._commit:
            await self._session.commit()

        if self._clustering_logger:
            clustering_job_report = BatchJobReport(
                job_id=str(clustering_job.id),
                algorithm=algorithm,
                started_at=started_at,
                completed_at=clustering_job.completed_at or datetime.now(tz=UTC),
                total_identities=clustering_job.processed_identities,
                accept_count=accept_count,
                suggest_count=suggest_count,
                reject_count=reject_count,
                clusters_created=clusters_created,
                avg_similarity=None,
            )
            self._clustering_logger.log_batch_complete(clustering_job_report)
