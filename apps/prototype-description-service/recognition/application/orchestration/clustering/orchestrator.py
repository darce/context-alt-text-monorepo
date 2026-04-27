"""Incremental clustering orchestration entry point."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusteringJob
from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from db.tenant_context import enable_rls_bypass, set_tenant_context
from recognition.application.assignment import AssignmentGate, AssignmentOutcome
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.orchestration.clustering.chunked_processor import ChunkedIdentityProcessor
from recognition.application.orchestration.clustering.dependencies import (
    ClusteringContext,
    ClusteringDependencies,
    ClusteringRuntimeConfig,
)
from recognition.application.orchestration.clustering.decision_handler import DecisionHandler
from recognition.application.orchestration.clustering.discovery_pipeline import (
    prepare_cluster_caches,
    run_discovery_pipeline,
    run_hac_refinement,
    run_singleton_hac_refinement,
    update_cluster_caches_from_new_cluster,
)
from recognition.application.orchestration.clustering.job_result import ClusterJobResult
from recognition.application.orchestration.protocols import MergeSuggestionServiceProtocol, SuggestionServiceProtocol
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.identity import MediaIdentity
from recognition.observability import ClusteringLogger
from recognition.observability.recognition_runs import (
    RecognitionRunContext,
    complete_recognition_run,
    create_recognition_run,
)
from recognition.observability.reports import BatchJobReport
from recognition.shared.ids import generate_id
from recognition.shared.tenant import coerce_tenant_uuid

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from recognition.application.settings import HACSettings
    from recognition.domain.repositories import ConstrainedHACProtocol

logger = logging.getLogger(__name__)


async def cluster_unclustered_identities(
    *,
    session: AsyncSession,
    dependencies: ClusteringDependencies,
    runtime_config: ClusteringRuntimeConfig,
    context: ClusteringContext,
) -> ClusterJobResult:
    """Cluster any identities not yet assigned to a cluster."""
    runner = IncrementalClusteringRunner(
        session=session,
        dependencies=dependencies,
        runtime_config=runtime_config,
    )
    return await runner.run(context=context)


class IncrementalClusteringRunner:
    """Coordinator for chunked, incremental clustering jobs."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        dependencies: ClusteringDependencies,
        runtime_config: ClusteringRuntimeConfig,
    ) -> None:
        self._session = session
        self._gate = dependencies.gate
        self._representative_discovery = dependencies.representative_discovery
        self._centroid_discovery = dependencies.centroid_discovery
        self._graph_discovery = dependencies.graph_discovery
        self._assignment_writer = dependencies.assignment_writer
        self._suggestion_service = dependencies.suggestion_service
        self._merge_suggestion_service = dependencies.merge_suggestion_service
        self._clustering_logger = dependencies.clustering_logger
        self._constrained_hac = dependencies.constrained_hac
        self._hac_settings = runtime_config.hac_settings
        self._progress_callback = runtime_config.progress_callback
        self._commit = runtime_config.commit
        self._obs_session_factory = dependencies.session_factory
        self._decision_handler = DecisionHandler(
            gate=dependencies.gate,
            assignment_writer=dependencies.assignment_writer,
            suggestion_service=dependencies.suggestion_service,
            clustering_logger=dependencies.clustering_logger,
            logger_instance=logger,
        )
        self._bind_writer_context = getattr(dependencies.assignment_writer, "bind_run_context", None)
        self._bind_graph_context = getattr(dependencies.graph_discovery, "bind_run_context", None)

    async def run(self, *, context: ClusteringContext) -> ClusterJobResult:
        job_id_str, job_uuid, started_at = self._build_job_id(context.job_id)
        logger.info(
            "[clustering] batch_start job_id=%s tenant_id=%s",
            job_id_str,
            context.tenant_id,
        )

        tenant_uuid = self._coerce_tenant(context.tenant_id)
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

        await self._cleanup_orphaned_representatives(context.tenant_id)

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
        # Buffer observability events when a separate session_factory is
        # available so that a write failure in the observability path cannot
        # roll back committed clustering data (stretch goal).
        if self._obs_session_factory is not None:
            run_ctx.buffer_events = True
        self._bind_run_context(run_ctx)

        domain_identities = self._build_domain_identities(unclustered)
        self._log_batch_media_ids(job_id_str, domain_identities)

        total_identities = len(domain_identities)
        clustering_job.total_identities = total_identities
        clustering_job.processed_identities = 0
        clustering_job.progress = 0.0
        await self._session.flush()

        accept_count, suggest_count, reject_count, clusters_created, created_cluster_ids = await self._process_chunks(
            tenant_id=context.tenant_id,
            job_id=job_id_str,
            job_label=job_label,
            clustering_job=clustering_job,
            identities=domain_identities,
            run_ctx=run_ctx,
        )

        await self._finalize_job(
            clustering_job=clustering_job,
            run_id=run_ctx.run_id,
            tenant_id=context.tenant_id,
            started_at=started_at,
            job_id=job_id_str,
            total_identities=total_identities,
            accept_count=accept_count,
            suggest_count=suggest_count,
            reject_count=reject_count,
            clusters_created=clusters_created,
            created_cluster_ids=created_cluster_ids,
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
            created_cluster_ids=created_cluster_ids,
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
                pose_pitch=row.pose_pitch,
                pose_yaw=row.pose_yaw,
                pose_roll=row.pose_roll,
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

    async def _persist_and_cache_new_clusters(
        self,
        new_clusters: list[tuple[list[MediaIdentity], list[float]]],
        *,
        tenant_id: str,
        job_id: str,
        representatives_by_cluster: dict,
        centroids_by_cluster: dict,
        resolve_reason: str,
        preserve_suggestion_ids: set[str] | None = None,
        assigned_ids_out: set[str] | None = None,
    ) -> tuple[int, list[str]]:
        """Persist a batch of new clusters, update caches, resolve suggestions, and log.

        Args:
            new_clusters: List of (members, similarities) tuples to persist.
            tenant_id: Tenant identifier for cluster creation.
            job_id: Job identifier for logging.
            representatives_by_cluster: In-memory representative cache to update.
            centroids_by_cluster: In-memory centroid cache to update.
            resolve_reason: Reason string passed to resolve_for_identity_exclusive.
            preserve_suggestion_ids: Identity IDs whose pending suggestions should
                not be auto-resolved (typically identities the gate marked SUGGEST).
            assigned_ids_out: If provided, all processed member IDs are added here.

        Returns:
            (clusters_added, new_cluster_ids)
        """
        clusters_added = 0
        new_ids: list[str] = []
        for members, similarities in new_clusters:
            if not members:
                continue
            cluster = await self._assignment_writer.persist_new_cluster(
                tenant_id=tenant_id,
                identities=members,
                similarities=similarities,
                algorithm=self._graph_discovery.algorithm_name,
                clustering_logger=self._clustering_logger,
            )
            clusters_added += 1
            if cluster and cluster.id:
                new_ids.append(str(cluster.id))
                centroid_arr = np.array(cluster.centroid, dtype=np.float32) if cluster.centroid is not None else None
                update_cluster_caches_from_new_cluster(
                    cluster_id=str(cluster.id),
                    seed_identities=members,
                    centroid=centroid_arr,
                    representatives_by_cluster=representatives_by_cluster,
                    centroids_by_cluster=centroids_by_cluster,
                )
            for member in members:
                if assigned_ids_out is not None:
                    assigned_ids_out.add(member.id)
                if preserve_suggestion_ids is not None and member.id in preserve_suggestion_ids:
                    logger.debug(
                        "[clustering] Preserving pending suggestions for suggested identity %s (fallback cluster %s)",
                        member.id,
                        cluster.id,
                    )
                    continue
                await self._suggestion_service.resolve_for_identity_exclusive(
                    identity_id=member.id,
                    accepted_cluster_id=str(cluster.id),
                    reason=resolve_reason,
                )
            logger.info(
                "[clustering] new_cluster job_id=%s identity_count=%d media_ids=%s",
                job_id,
                len(members),
                [m.media_id for m in members],
            )
        return clusters_added, new_ids

    async def _process_chunks(
        self,
        *,
        tenant_id: str,
        job_id: str,
        job_label: str,
        clustering_job: IdentityClusteringJob,
        identities: list[MediaIdentity],
        run_ctx: RecognitionRunContext | None = None,
    ) -> tuple[int, int, int, int, list[str]]:
        accept_count = 0
        suggest_count = 0
        reject_count = 0
        clusters_created = 0
        created_cluster_ids: list[str] = []

        processor = ChunkedIdentityProcessor(identities)
        total_identities = processor.total_count

        # For large jobs, suppress per-identity gate/decision log lines and rely
        # on the chunk_stats summary instead. This prevents log volume from growing
        # linearly with identity count (stretch goal: chunk-level summary logging mode).
        _verbose_decisions = total_identities <= 100

        # Phase 3: prime cluster caches ONCE before the chunk loop instead of
        # re-loading the full cluster table on every chunk.  The caches are
        # updated incrementally after each batch of new clusters is persisted.
        representatives_by_cluster, centroids_by_cluster, labeled_cluster_ids = await prepare_cluster_caches(
            self._assignment_writer, str(tenant_id)
        )

        for chunk, processed_before in processor.iter_chunks():
            logger.info(
                "[clustering] chunk_processing job_id=%s processed=%d/%d chunk_size=%d",
                job_id,
                processed_before,
                total_identities,
                len(chunk),
            )
            _chunk_t0 = time.perf_counter()
            _chunk_clusters_before = clusters_created

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
            accepted_decisions: list = []

            for candidate in all_candidates:
                decision = await self._decision_handler.evaluate_only(
                    candidate,
                    job_id=job_id,
                    job_label=job_label,
                    verbose=_verbose_decisions,
                )
                if decision.outcome == AssignmentOutcome.ACCEPT:
                    accept_count += 1
                    accepted_ids.add(candidate.identity.id)
                    accepted_decisions.append(decision)
                elif decision.outcome == AssignmentOutcome.SUGGEST:
                    suggest_count += 1
                    suggested_ids.add(candidate.identity.id)
                else:
                    reject_count += 1
                    rejected_ids.add(candidate.identity.id)

            # Bulk-persist all accepted assignments for this chunk: one INSERT per
            # cluster instead of N per-identity round-trips (Phase 3 bulk writes).
            _chunk_reps_added = 0
            if accepted_decisions:
                (
                    _bulk_persisted,
                    _bulk_skipped,
                    _bulk_reps_added,
                ) = await self._assignment_writer.persist_assignments_chunk(accepted_decisions, batch_mode=True)
                _chunk_reps_added += _bulk_reps_added
                if _bulk_skipped:
                    logger.info(
                        "[clustering] bulk_persist job_id=%s accepted=%d skipped=%d",
                        job_id,
                        _bulk_persisted,
                        _bulk_skipped,
                    )
                # Resolve suggestions for each accepted identity after membership is committed.
                for decision in accepted_decisions:
                    await self._suggestion_service.resolve_for_identity_exclusive(
                        identity_id=decision.candidate.identity.id,
                        accepted_cluster_id=decision.candidate.cluster_id,
                        reason="auto_assignment",
                    )
                    if _verbose_decisions:
                        logger.info(
                            "[clustering] ACCEPTED job_id=%s identity=%s media_id=%s cluster=%s",
                            job_id,
                            decision.candidate.identity.id,
                            decision.candidate.identity.media_id,
                            decision.candidate.cluster_id,
                        )

            already_in_new_clusters = {member.id for members, _ in new_cluster_proposals for member in members}
            all_processed_ids = accepted_ids | suggested_ids | rejected_ids | already_in_new_clusters
            no_candidates = [i for i in chunk if i.id not in all_processed_ids]
            rejected_identities = [i for i in chunk if i.id in rejected_ids]
            # Suggested identities need singleton clusters as fallback - they have a suggestion
            # linking them to an existing cluster, but they must still belong to SOME cluster
            suggested_identities = [i for i in chunk if i.id in suggested_ids]
            still_unclustered = no_candidates + rejected_identities + suggested_identities

            logger.info(
                "[clustering] Identities needing new clusters: %d (no candidates: %d, rejected: %d, suggested: %d)",
                len(still_unclustered),
                len(no_candidates),
                len(rejected_identities),
                len(suggested_identities),
            )

            if still_unclustered:
                final_result = await self._graph_discovery.discover(still_unclustered, {})
                assigned_by_graph_fallback: set[str] = set()
                _fallback_added, _fallback_ids = await self._persist_and_cache_new_clusters(
                    final_result.new_clusters,
                    tenant_id=tenant_id,
                    job_id=job_id,
                    representatives_by_cluster=representatives_by_cluster,
                    centroids_by_cluster=centroids_by_cluster,
                    resolve_reason="auto_new_cluster",
                    preserve_suggestion_ids=suggested_ids,
                    assigned_ids_out=assigned_by_graph_fallback,
                )
                clusters_created += _fallback_added
                created_cluster_ids.extend(_fallback_ids)
            else:
                assigned_by_graph_fallback = set()

            _proposal_added, _proposal_ids = await self._persist_and_cache_new_clusters(
                new_cluster_proposals,
                tenant_id=tenant_id,
                job_id=job_id,
                representatives_by_cluster=representatives_by_cluster,
                centroids_by_cluster=centroids_by_cluster,
                resolve_reason="auto_proposal_new_cluster",
            )
            clusters_created += _proposal_added
            created_cluster_ids.extend(_proposal_ids)

            hac_eligible = [i for i in still_unclustered if i.id not in assigned_by_graph_fallback]
            hac_created = await run_hac_refinement(
                still_unclustered=hac_eligible,
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
            clustering_job.payload = {
                **(clustering_job.payload or {}),
                "clusters_created": clusters_created,
                "last_successful_processed_identities": processor.processed_count,
                "current_chunk_size": len(chunk),
            }
            # Commit after every chunk so completed work is durable even if a
            # later chunk fails (finding 1164: durable chunk commit boundaries).
            await self._session.commit()
            # Restore SET LOCAL tenant context cleared by the chunk commit.
            # PostgreSQL SET LOCAL variables are transaction-scoped and are
            # cleared when the transaction commits; without this, subsequent
            # chunks run with no app.current_tenant or app.bypass_rls set,
            # causing RLS to reject observability event INSERTs on autoflush
            # (investigation: rls-tenant-context-lost-after-chunk-commit-2026-03-24).
            await set_tenant_context(self._session, uuid.UUID(tenant_id))
            await enable_rls_bypass(self._session)
            # Flush buffered observability events in a separate session so that
            # an observability failure cannot roll back committed clustering data
            # (stretch goal: decouple observability writes from clustering session).
            if run_ctx is not None and run_ctx.buffer_events:
                try:
                    await run_ctx.flush_pending_events(self._obs_session_factory)
                except Exception:
                    logger.warning("[clustering] observability flush failed for job %s; events discarded", job_id)
            _chunk_elapsed_ms = (time.perf_counter() - _chunk_t0) * 1000
            logger.info(
                "[clustering] chunk_stats job_id=%s processed=%d/%d size=%d "
                "accept=%d suggest=%d reject=%d new_clusters=%d reps_added=%d elapsed_ms=%.1f",
                job_id,
                processed,
                total_identities,
                len(chunk),
                len(accepted_ids),
                len(suggested_ids),
                len(rejected_ids),
                clusters_created - _chunk_clusters_before,
                _chunk_reps_added,
                _chunk_elapsed_ms,
            )
            # Feed latency back to the processor so it can adapt the next chunk size.
            processor.record_chunk_ms(_chunk_elapsed_ms, len(chunk))

            if self._progress_callback:
                await self._progress_callback(processed, total_identities)

        singleton_merges = await run_singleton_hac_refinement(
            tenant_id=str(tenant_id),
            constrained_hac=self._constrained_hac,
            hac_settings=self._hac_settings,
            assignment_writer=self._assignment_writer,
            merge_suggestion_service=self._merge_suggestion_service,
            clustering_logger=self._clustering_logger,
        )
        if singleton_merges > 0:
            logger.info(
                "[clustering] singleton_hac_complete job_id=%s merged_clusters=%d",
                job_id,
                singleton_merges,
            )

        return accept_count, suggest_count, reject_count, clusters_created, created_cluster_ids

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
        created_cluster_ids: list[str],
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
        clustering_job.payload = {
            **(clustering_job.payload or {}),
            "clusters_created": clusters_created,
            "created_cluster_ids": created_cluster_ids,
        }
        await self._session.flush()

        await complete_recognition_run(
            self._session,
            run_id=run_id,
            status="completed",
            completed_at=clustering_job.completed_at,
        )
        if self._commit:
            await self._session.commit()
            # Seam 4: restore tenant context + RLS bypass after the commit clears
            # the SET LOCAL variables.  The HTTP sync path sets commit=True; the
            # worker path sets commit=False so this block is intentionally skipped
            # there (the worker already owns context via ensure_job_context).
            tenant_uuid = uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id
            await set_tenant_context(self._session, tenant_uuid)
            await enable_rls_bypass(self._session)

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
