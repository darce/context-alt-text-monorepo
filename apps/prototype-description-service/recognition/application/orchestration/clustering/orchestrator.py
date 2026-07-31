"""Incremental clustering orchestration entry point."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusteringJob
from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from db.tenant_context import enable_rls_bypass, set_tenant_context
from recognition.application.assignment.joint import group_accepted_by_media, resolve_photo_conflicts
from recognition.application.orchestration.clustering.chunked_processor import ChunkedIdentityProcessor
from recognition.application.orchestration.clustering.decision_handler import DecisionHandler
from recognition.application.orchestration.clustering.dependencies import (
    ClusteringContext,
    ClusteringDependencies,
    ClusteringRuntimeConfig,
)
from recognition.application.orchestration.clustering.discovery_pipeline import (
    GalleryProvenanceStats,
    GalleryProvenanceUnavailableError,
    evaluate_chunk_candidates,
    partition_unclustered,
    prepare_cluster_caches,
    run_discovery_pipeline,
    run_hac_refinement,
    run_singleton_hac_refinement,
    update_cluster_caches_from_new_cluster,
)
from recognition.application.orchestration.clustering.job_result import ClusterJobResult
from recognition.domain.identity import MediaIdentity
from recognition.domain.job import JobStatus
from recognition.observability.recognition_runs import (
    RecognitionRunContext,
    complete_recognition_run,
    create_recognition_run,
)
from recognition.observability.reports import BatchJobReport
from recognition.shared.ids import generate_id
from recognition.shared.tenant import coerce_tenant_uuid

if TYPE_CHECKING:
    from recognition.application.assignment import AssignmentDecision

logger = logging.getLogger(__name__)


def _joint_assignment_active() -> bool:
    """True when face_pipeline profile is active and joint assignment is enabled."""
    from recognition.config import get_settings as get_recognition_settings
    from recognition.config.settings import resolve_face_pipeline_knobs

    settings = get_recognition_settings()
    knobs = resolve_face_pipeline_knobs(
        face_pipeline=settings.face_pipeline,
        clustering=settings.clustering,
        clustering_limits=settings.clustering_limits,
        identity_detection=settings.identity_detection,
    )
    return knobs.profile == "face_pipeline" and bool(knobs.joint_assignment_enabled)


@dataclass(frozen=True, slots=True)
class _ChunkOutcome:
    """Per-chunk deltas accumulated by the _process_chunks loop."""

    accept_count: int
    suggest_count: int
    reject_count: int
    clusters_created: int
    created_cluster_ids: list[str]


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
            status=JobStatus.RUNNING,
            started_at=started_at,
            progress=0.0,
            total_identities=0,
            processed_identities=0,
        )
        existing_job = await self._session.get(IdentityClusteringJob, job_uuid)
        if existing_job is not None:
            existing_job.status = JobStatus.RUNNING
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
        """Load unclustered identities for this tenant.

        FIR23-01: when multiple embedding_model values coexist, keep only the
        active runtime model (never mix spaces). A single-model tenant is a
        no-op — every row is returned unchanged.
        """
        stmt: Select[tuple[MediaIdentityModel]] = (
            select(MediaIdentityModel)
            .where(MediaIdentityModel.tenant_id == tenant_uuid)
            .where(~exists(select(MemberModel.id).where(MemberModel.identity_id == MediaIdentityModel.id)))
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        models = {str(row.embedding_model) for row in rows if getattr(row, "embedding_model", None)}
        if len(models) <= 1:
            return rows
        try:
            from recognition.application.embedding.manifest import active_embedding_model_id

            active = active_embedding_model_id()
        except Exception:
            logger.warning(
                "[clustering] mixed embedding_model present but active model unresolved; "
                "fail-closed empty batch (FIR23-01)"
            )
            return []
        filtered = [row for row in rows if getattr(row, "embedding_model", None) == active]
        if not filtered:
            logger.warning(
                "[clustering] mixed embedding_model=%s none match active=%s; fail-closed empty batch",
                sorted(models),
                active,
            )
        elif len(filtered) < len(rows):
            logger.info(
                "[clustering] embedding_model filter active=%s kept=%d skipped=%d",
                active,
                len(filtered),
                len(rows) - len(filtered),
            )
        return filtered

    async def _complete_empty_job(
        self,
        *,
        clustering_job: IdentityClusteringJob,
        started_at: datetime,
        job_label: str,
    ) -> ClusterJobResult:
        clustering_job.status = JobStatus.COMPLETED
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
                sharpness=row.sharpness,
                embedding_norm=row.embedding_norm,
                occlusion_severity=row.occlusion_severity,
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

        processor = ChunkedIdentityProcessor(
            identities,
            photo_atomic=_joint_assignment_active(),
        )
        total_identities = processor.total_count

        # For large jobs, suppress per-identity gate/decision log lines and rely
        # on the chunk_stats summary instead. This prevents log volume from growing
        # linearly with identity count (stretch goal: chunk-level summary logging mode).
        _verbose_decisions = total_identities <= 100

        # Phase 3: prime cluster caches ONCE before the chunk loop instead of
        # re-loading the full cluster table on every chunk.  The caches are
        # updated incrementally after each batch of new clusters is persisted.
        # CVUP1-GR-21: thread the job session explicitly. AssignmentWriter._session
        # is optional, so leaving provenance to the private-attribute fallback would
        # make the fail-closed default silently empty the gallery cache.
        (
            representatives_by_cluster,
            centroids_by_cluster,
            labeled_cluster_ids,
            gallery_stats,
        ) = await prepare_cluster_caches(self._assignment_writer, str(tenant_id), session=self._session)
        # R3-G2-1: surface fail-closed gallery exclusions on the job payload so
        # operators see a wiped gallery without grepping logs. Subsequent chunk
        # payload merges preserve this key via **(payload or {}).
        self._record_gallery_provenance(clustering_job, gallery_stats)
        # R3-03: an infrastructure-caused wipe must fail the job, not complete it.
        self._abort_on_unprovenanced_gallery(job_label, gallery_stats)

        for chunk, processed_before in processor.iter_chunks():
            outcome = await self._process_single_chunk(
                chunk=chunk,
                processed_before=processed_before,
                clusters_created_before=clusters_created,
                representatives_by_cluster=representatives_by_cluster,
                centroids_by_cluster=centroids_by_cluster,
                labeled_cluster_ids=labeled_cluster_ids,
                tenant_id=tenant_id,
                job_id=job_id,
                job_label=job_label,
                clustering_job=clustering_job,
                processor=processor,
                total_identities=total_identities,
                run_ctx=run_ctx,
                verbose=_verbose_decisions,
            )
            accept_count += outcome.accept_count
            suggest_count += outcome.suggest_count
            reject_count += outcome.reject_count
            clusters_created += outcome.clusters_created
            created_cluster_ids.extend(outcome.created_cluster_ids)

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

    async def _process_single_chunk(
        self,
        *,
        chunk: list[MediaIdentity],
        processed_before: int,
        clusters_created_before: int,
        representatives_by_cluster: dict[str, list[np.ndarray]],
        centroids_by_cluster: dict[str, np.ndarray],
        labeled_cluster_ids: set[str],
        tenant_id: str,
        job_id: str,
        job_label: str,
        clustering_job: IdentityClusteringJob,
        processor: ChunkedIdentityProcessor,
        total_identities: int,
        run_ctx: RecognitionRunContext | None,
        verbose: bool,
    ) -> _ChunkOutcome:
        """Process one chunk end to end: discover -> gate -> persist -> new clusters -> commit."""
        logger.info(
            "[clustering] chunk_processing job_id=%s processed=%d/%d chunk_size=%d",
            job_id,
            processed_before,
            total_identities,
            len(chunk),
        )
        _chunk_t0 = time.perf_counter()

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

        gate_result = await evaluate_chunk_candidates(
            all_candidates=all_candidates,
            decision_handler=self._decision_handler,
            job_id=job_id,
            job_label=job_label,
            verbose=verbose,
        )

        accepted_decisions = list(gate_result.accepted_decisions)
        accepted_ids = set(gate_result.accepted_ids)
        suggested_ids = set(gate_result.suggested_ids)
        rejected_ids = set(gate_result.rejected_ids)
        accept_count = gate_result.accept_count
        suggest_count = gate_result.suggest_count
        reject_count = gate_result.reject_count

        joint_active = _joint_assignment_active()
        if joint_active and accepted_decisions:
            joint_result = resolve_photo_conflicts(group_accepted_by_media(accepted_decisions))
            accepted_decisions = list(joint_result.accepted)
            accepted_ids = {decision.candidate.identity.id for decision in accepted_decisions}
            # Losers drop out of accepted/suggested/rejected so partition_unclustered
            # routes them to the new-cluster/unknown path (GR2-01 — never orphan).
            accept_count = len(accepted_decisions)
            if joint_result.loser_identity_ids:
                logger.info(
                    "[clustering] joint_assignment job_id=%s losers=%d kept=%d",
                    job_id,
                    len(joint_result.loser_identity_ids),
                    accept_count,
                )

        reps_added, guard_rejected_ids = await self._persist_accepted_assignments(
            accepted_decisions,
            job_id=job_id,
            verbose=verbose,
            joint_uniqueness_enabled=joint_active,
        )
        if guard_rejected_ids:
            accepted_decisions = [
                decision for decision in accepted_decisions if decision.candidate.identity.id not in guard_rejected_ids
            ]
            accepted_ids -= guard_rejected_ids
            accept_count = len(accepted_ids)

        partition = partition_unclustered(
            chunk=chunk,
            accepted_ids=accepted_ids,
            suggested_ids=suggested_ids,
            rejected_ids=rejected_ids,
            new_cluster_proposals=new_cluster_proposals,
        )
        logger.info(
            "[clustering] Identities needing new clusters: %d (no candidates: %d, rejected: %d, suggested: %d)",
            len(partition.still_unclustered),
            len(partition.no_candidates),
            len(partition.rejected_identities),
            len(partition.suggested_identities),
        )

        clusters_added, created_cluster_ids = await self._create_new_clusters_for_chunk(
            still_unclustered=partition.still_unclustered,
            suggested_ids=suggested_ids,
            new_cluster_proposals=new_cluster_proposals,
            representatives_by_cluster=representatives_by_cluster,
            centroids_by_cluster=centroids_by_cluster,
            tenant_id=tenant_id,
            job_id=job_id,
        )

        processed = processor.processed_count
        await self._commit_chunk_progress(
            clustering_job=clustering_job,
            processed=processed,
            total_identities=total_identities,
            clusters_created=clusters_created_before + clusters_added,
            chunk_len=len(chunk),
            tenant_id=tenant_id,
            job_id=job_id,
            run_ctx=run_ctx,
        )

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
            clusters_added,
            reps_added,
            _chunk_elapsed_ms,
        )
        # Feed latency back to the processor so it can adapt the next chunk size.
        processor.record_chunk_ms(_chunk_elapsed_ms, len(chunk))

        if self._progress_callback:
            await self._progress_callback(processed, total_identities)

        return _ChunkOutcome(
            accept_count=accept_count,
            suggest_count=suggest_count,
            reject_count=reject_count,
            clusters_created=clusters_added,
            created_cluster_ids=created_cluster_ids,
        )

    async def _persist_accepted_assignments(
        self,
        accepted_decisions: list[AssignmentDecision],
        *,
        job_id: str,
        verbose: bool,
        joint_uniqueness_enabled: bool = False,
    ) -> tuple[int, set[str]]:
        """Bulk-persist a chunk's accepted assignments and resolve their suggestions.

        Returns (reps_added, guard_rejected_ids). Uses one INSERT per cluster
        (batch mode) instead of N per-identity round-trips (Phase 3 bulk writes).
        """
        if not accepted_decisions:
            return 0, set()

        (
            _bulk_persisted,
            _bulk_skipped,
            reps_added,
            guard_rejected_ids,
        ) = await self._assignment_writer.persist_assignments_chunk(
            accepted_decisions,
            batch_mode=True,
            joint_uniqueness_enabled=joint_uniqueness_enabled,
        )
        if _bulk_skipped or guard_rejected_ids:
            logger.info(
                "[clustering] bulk_persist job_id=%s accepted=%d skipped=%d guard_rejected=%d",
                job_id,
                _bulk_persisted,
                _bulk_skipped,
                len(guard_rejected_ids),
            )
        # Resolve suggestions only for identities that actually persisted.
        for decision in accepted_decisions:
            if decision.candidate.identity.id in guard_rejected_ids:
                continue
            await self._suggestion_service.resolve_for_identity_exclusive(
                identity_id=decision.candidate.identity.id,
                accepted_cluster_id=decision.candidate.cluster_id,
                reason="auto_assignment",
            )
            if verbose:
                logger.info(
                    "[clustering] ACCEPTED job_id=%s identity=%s media_id=%s cluster=%s",
                    job_id,
                    decision.candidate.identity.id,
                    decision.candidate.identity.media_id,
                    decision.candidate.cluster_id,
                )
        return reps_added, set(guard_rejected_ids)

    async def _create_new_clusters_for_chunk(
        self,
        *,
        still_unclustered: list[MediaIdentity],
        suggested_ids: set[str],
        new_cluster_proposals: list[tuple[list[MediaIdentity], list[float]]],
        representatives_by_cluster: dict[str, list[np.ndarray]],
        centroids_by_cluster: dict[str, np.ndarray],
        tenant_id: str,
        job_id: str,
    ) -> tuple[int, list[str]]:
        """Create new clusters for a chunk: graph fallback for still-unclustered
        identities, then persist graph proposals, then constrained-HAC refinement.

        Returns (clusters_created_delta, created_cluster_ids) for this chunk.
        """
        clusters_added = 0
        created_cluster_ids: list[str] = []

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
            clusters_added += _fallback_added
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
        clusters_added += _proposal_added
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
            clusters_added += hac_created

        return clusters_added, created_cluster_ids

    @staticmethod
    def _record_gallery_provenance(
        clustering_job: IdentityClusteringJob,
        gallery_stats: GalleryProvenanceStats,
    ) -> None:
        """Attach gallery provenance counters to the job payload (R3-G2-1).

        Does not change job status — fail-closed exclusion is still correct;
        this only makes the consequence operator-visible when every production
        representative was dropped and discovery will open brand-new clusters.
        """
        clustering_job.payload = {
            **(clustering_job.payload or {}),
            "gallery_provenance": gallery_stats.to_payload(),
        }
        if gallery_stats.gallery_wiped or gallery_stats.representatives_excluded_unresolvable > 0:
            logger.warning(
                "[clustering] gallery_provenance job_id=%s active=%s provenance_loaded=%s "
                "excluded_reps=%d excluded_clusters=%d excluded_centroids=%d gallery_wiped=%s",
                clustering_job.id,
                gallery_stats.active_embedding_model,
                gallery_stats.provenance_loaded,
                gallery_stats.representatives_excluded_unresolvable,
                gallery_stats.clusters_excluded_unresolvable,
                gallery_stats.centroids_excluded_untrusted,
                gallery_stats.gallery_wiped,
            )

    @staticmethod
    def _abort_on_unprovenanced_gallery(
        job_label: str,
        gallery_stats: GalleryProvenanceStats,
    ) -> None:
        """Fail the job when the gallery was wiped for an infrastructure reason (R3-03).

        Recording the counters (R3-G2-1) makes the wipe visible, but a COMPLETED
        job with an empty gallery still fragments the tenant: every probe misses
        and opens a brand-new cluster. Raising rolls the run back and lets the
        worker record FAILED with the reason, which an operator can retry once
        provenance is restored.

        A legitimate space migration — every representative resolved to a real
        model that is not the active one — is explicitly *not* an abort; see
        ``GalleryProvenanceStats.abort_reason``.
        """
        reason = gallery_stats.abort_reason()
        if reason is None:
            return
        message = (
            f"clustering aborted: gallery wiped by FIR23-01 provenance filter — {reason}; "
            f"excluded_reps={gallery_stats.representatives_excluded_unresolvable} "
            f"excluded_clusters={gallery_stats.clusters_excluded_unresolvable} "
            f"excluded_centroids={gallery_stats.centroids_excluded_untrusted}"
        )
        logger.error("[clustering] job_id=%s %s", job_label, message)
        raise GalleryProvenanceUnavailableError(message)

    async def _commit_chunk_progress(
        self,
        *,
        clustering_job: IdentityClusteringJob,
        processed: int,
        total_identities: int,
        clusters_created: int,
        chunk_len: int,
        tenant_id: str,
        job_id: str,
        run_ctx: RecognitionRunContext | None,
    ) -> None:
        """Persist chunk progress, commit, and restore tenant/RLS context.

        Commits after every chunk so completed work is durable even if a later
        chunk fails (finding 1164: durable chunk commit boundaries). PostgreSQL
        SET LOCAL tenant/bypass variables are transaction-scoped and cleared by
        the commit, so they are restored afterwards; without this, subsequent
        chunks run with no app.current_tenant/app.bypass_rls and RLS rejects
        observability INSERTs (rls-tenant-context-lost-after-chunk-commit-2026-03-24).
        """
        clustering_job.processed_identities = processed
        clustering_job.progress = (processed / total_identities) if total_identities else 1.0
        clustering_job.payload = {
            **(clustering_job.payload or {}),
            "clusters_created": clusters_created,
            "last_successful_processed_identities": processed,
            "current_chunk_size": chunk_len,
        }
        await self._session.commit()
        await set_tenant_context(self._session, uuid.UUID(tenant_id))
        await enable_rls_bypass(self._session)
        # Flush buffered observability events in a separate session so an
        # observability failure cannot roll back committed clustering data
        # (stretch goal: decouple observability writes from clustering session).
        if run_ctx is not None and run_ctx.buffer_events:
            try:
                await run_ctx.flush_pending_events(self._obs_session_factory)
            except Exception:
                logger.warning("[clustering] observability flush failed for job %s; events discarded", job_id)

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
        clustering_job.status = JobStatus.COMPLETED
        clustering_job.completed_at = datetime.now(tz=UTC)
        # Preserve gallery_provenance (R3-G2-1) and chunk progress keys via merge.
        clustering_job.payload = {
            **(clustering_job.payload or {}),
            "clusters_created": clusters_created,
            "created_cluster_ids": created_cluster_ids,
        }
        await self._session.flush()

        await complete_recognition_run(
            self._session,
            run_id=run_id,
            status=JobStatus.COMPLETED,
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
