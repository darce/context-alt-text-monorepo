"""
Incremental clustering job runner.

This module owns the "cluster unclustered identities" workflow, including:
- querying unassigned identities
- chunked discovery + gate evaluation
- persisting assignments / suggestions / new clusters
- emitting job progress + summary metrics
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusteringJob
from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.assignment import (
    AssignmentCandidate,
    AssignmentDecision,
    AssignmentGate,
    AssignmentOutcome,
)
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.orchestration.protocols import SuggestionServiceProtocol
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.identity import MediaIdentity
from recognition.domain.locator import IdentityLocator
from recognition.observability import ClusteringLogger, DecisionType
from recognition.observability.recognition_runs import complete_recognition_run, create_recognition_run
from recognition.observability.reports import BatchJobReport
from recognition.shared.ids import generate_id

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ClusterJobResult:
    job_id: str
    started_at: datetime
    finished_at: datetime
    completed: int
    total: int
    clusters_created: int
    accepted: int = 0
    suggested: int = 0
    rejected: int = 0


def get_chunk_size(total_processed: int) -> int:
    """Return adaptive chunk size for incremental cold-start clustering."""
    if total_processed < 20:
        return 5
    if total_processed < 50:
        return 10
    if total_processed < 200:
        return 25
    return 50


async def cluster_unclustered_identities(
    *,
    tenant_id: str,
    job_id: str | None,
    session: AsyncSession | None,
    gate: AssignmentGate,
    representative_discovery: RepresentativeDiscovery,
    centroid_discovery: CentroidDiscovery,
    graph_discovery: GraphDiscovery,
    assignment_writer: AssignmentWriter,
    suggestion_service: SuggestionServiceProtocol,
    clustering_logger: ClusteringLogger | None = None,
    constrained_hac: Any | None = None,
    hac_settings: Any | None = None,
    commit: bool = True,
) -> ClusterJobResult:
    """Cluster any identities not yet assigned to a cluster."""
    try:
        job_uuid = uuid.UUID(str(job_id)) if job_id is not None else generate_id()
    except ValueError:
        job_uuid = generate_id()
    job_id = str(job_uuid)
    logger.info(
        "[clustering] batch_start job_id=%s tenant_id=%s",
        job_id,
        tenant_id,
    )
    started_at = datetime.now(tz=UTC)

    if session is None:
        logger.warning("[clustering] No session available, returning early")
        return ClusterJobResult(
            job_id=job_id,
            started_at=started_at,
            finished_at=started_at,
            completed=0,
            total=0,
            clusters_created=0,
        )

    try:
        # Handle both UUID format and MD5 hash format (32 hex chars without dashes)
        tenant_str = str(tenant_id).replace("-", "")
        if len(tenant_str) == 32:
            # Insert dashes to make it a valid UUID format
            formatted = f"{tenant_str[:8]}-{tenant_str[8:12]}-{tenant_str[12:16]}-{tenant_str[16:20]}-{tenant_str[20:]}"
            tenant_uuid = uuid.UUID(formatted)
        else:
            tenant_uuid = uuid.UUID(str(tenant_id))
    except ValueError as exc:
        logger.error("[clustering] Invalid tenant_id format: %s, error=%s", tenant_id, exc)
        return ClusterJobResult(
            job_id=job_id,
            started_at=started_at,
            finished_at=started_at,
            completed=0,
            total=0,
            clusters_created=0,
        )

    clustering_job = IdentityClusteringJob(
        id=job_uuid,
        tenant_id=tenant_uuid,
        status="running",
        started_at=started_at,
        progress=0.0,
        total_identities=0,
        processed_identities=0,
    )
    session.add(clustering_job)
    await session.flush()
    job_label = str(clustering_job.id)

    # Clean up any orphaned provisional representatives from previous failed runs
    try:
        cleaned_count = await assignment_writer._clusters.cleanup_orphaned_provisional_reps(str(tenant_id))
        if cleaned_count > 0:
            logger.info("[clustering] Cleaned up %d orphaned provisional representatives", cleaned_count)
    except Exception as exc:
        logger.warning("[clustering] Failed to cleanup orphaned representatives: %s", exc)

    stmt: Select[tuple[MediaIdentityModel]] = (
        select(MediaIdentityModel)
        .where(MediaIdentityModel.tenant_id == tenant_uuid)
        .where(~exists(select(MemberModel.id).where(MemberModel.identity_id == MediaIdentityModel.id)))
    )
    result = await session.execute(stmt)
    unclustered = result.scalars().all()

    if not unclustered:
        clustering_job.status = "completed"
        clustering_job.progress = 1.0
        clustering_job.completed_at = datetime.now(tz=UTC)
        finished_at = clustering_job.completed_at
        await session.flush()
        if commit:
            await session.commit()
        return ClusterJobResult(
            job_id=job_label,
            started_at=started_at,
            finished_at=finished_at,
            completed=0,
            total=0,
            clusters_created=0,
        )

    dataset_media_ids = sorted({int(row.media_id) for row in unclustered if row.media_id is not None})
    run_ctx = await create_recognition_run(
        session,
        tenant_id=tenant_uuid,
        source="cluster_unclustered_identities",
        clustering_job_id=clustering_job.id,
        settings_snapshot=gate.settings.model_dump(),
        dataset_selector={"media_ids": dataset_media_ids},
        started_at=started_at,
    )
    if clustering_logger:
        clustering_logger.bind_run_context(run_ctx)
    bind_writer_context = getattr(assignment_writer, "bind_run_context", None)
    if callable(bind_writer_context):
        bind_writer_context(run_ctx)
    bind_graph_context = getattr(graph_discovery, "bind_run_context", None)
    if callable(bind_graph_context):
        bind_graph_context(run_ctx)

    domain_identities = [
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
        for row in unclustered
    ]

    # Log all media IDs in this batch
    media_ids = [i.media_id for i in domain_identities]
    logger.info(
        "[clustering] batch_processing job_id=%s count=%d media_ids=%s",
        job_id,
        len(domain_identities),
        media_ids[:20] if len(media_ids) > 20 else media_ids,  # Limit to first 20 for log readability
    )

    total_identities = len(domain_identities)
    clustering_job.total_identities = total_identities
    clustering_job.processed_identities = 0
    clustering_job.progress = 0.0
    await session.flush()

    # Process higher-confidence faces first to seed good representatives early.
    domain_identities.sort(key=lambda identity: identity.confidence, reverse=True)

    accept_count = 0
    suggest_count = 0
    reject_count = 0
    clusters_created = 0
    processed = 0
    remaining_identities = list(domain_identities)

    while remaining_identities:
        chunk_size = get_chunk_size(processed)
        chunk = remaining_identities[:chunk_size]
        remaining_identities = remaining_identities[chunk_size:]

        logger.info(
            "[clustering] chunk_processing job_id=%s processed=%d/%d chunk_size=%d",
            job_id,
            processed,
            total_identities,
            len(chunk),
        )

        # ============================================================
        # Gather cluster data for discovery algorithms (refresh each chunk)
        # ============================================================
        # ============================================================
        # Gather cluster data for discovery algorithms (refresh each chunk)
        # ============================================================
        (
            representatives_by_cluster,
            centroids_by_cluster,
            labeled_cluster_ids,
        ) = await _prepare_cluster_caches(assignment_writer, str(tenant_id))

        # ============================================================
        # UNIFIED PIPELINE (chunked): Discovery -> Gate -> Writer
        # ============================================================
        all_candidates, new_cluster_proposals = await _run_discovery_pipeline(
            chunk=chunk,
            representative_discovery=representative_discovery,
            centroid_discovery=centroid_discovery,
            graph_discovery=graph_discovery,
            representatives_by_cluster=representatives_by_cluster,
            centroids_by_cluster=centroids_by_cluster,
            labeled_cluster_ids=labeled_cluster_ids,
        )
        logger.info("[clustering] Total candidates to evaluate through gate: %d", len(all_candidates))

        accepted_ids: set[str] = set()
        suggested_ids: set[str] = set()
        rejected_ids: set[str] = set()

        for candidate in all_candidates:
            decision = await gate.evaluate(candidate)
            _log_and_report_decision(
                logger_instance=logger,
                clustering_logger=clustering_logger,
                gate=gate,
                candidate=candidate,
                decision=decision,
                job_label=job_label,
            )

            if decision.outcome == AssignmentOutcome.ACCEPT:
                await assignment_writer.persist_assignment(decision, batch_mode=True)
                accept_count += 1
                accepted_ids.add(candidate.identity.id)

                # Resolve any pending suggestions (accept this cluster, reject others)
                if suggestion_service:
                    await suggestion_service.resolve_for_identity_exclusive(
                        identity_id=candidate.identity.id,
                        accepted_cluster_id=candidate.cluster_id,
                        reason="auto_assignment",
                    )
                logger.info(
                    "[clustering] ACCEPTED job_id=%s identity=%s media_id=%s cluster=%s",
                    job_id,
                    candidate.identity.id,
                    candidate.identity.media_id,
                    candidate.cluster_id,
                )
            elif decision.outcome == AssignmentOutcome.SUGGEST:
                await suggestion_service.create(candidate, decision.suggestion_confidence)
                suggest_count += 1
                suggested_ids.add(candidate.identity.id)
                logger.info(
                    "[clustering] SUGGESTED job_id=%s identity=%s media_id=%s cluster=%s confidence=%.2f reason=%s",
                    job_id,
                    candidate.identity.id,
                    candidate.identity.media_id,
                    candidate.cluster_id,
                    decision.suggestion_confidence or 0.0,
                    decision.rejection_reason,
                )
            else:  # REJECT
                reject_count += 1
                rejected_ids.add(candidate.identity.id)
                logger.info(
                    "[clustering] REJECTED job_id=%s identity=%s media_id=%s cluster=%s reason=%s",
                    job_id,
                    candidate.identity.id,
                    candidate.identity.media_id,
                    candidate.cluster_id,
                    decision.rejection_reason,
                )

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
            final_result = await graph_discovery.discover(still_unclustered, {})
            for members, similarities in final_result.new_clusters:
                if members:
                    cluster = await assignment_writer.persist_new_cluster(
                        tenant_id=tenant_id,
                        identities=members,
                        similarities=similarities,
                        algorithm=graph_discovery.algorithm_name,
                        clustering_logger=clustering_logger,
                    )
                    clusters_created += 1

                    # Resolve any pending suggestions for identities in this new cluster
                    if suggestion_service:
                        for member in members:
                            await suggestion_service.resolve_for_identity_exclusive(
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
                cluster = await assignment_writer.persist_new_cluster(
                    tenant_id=tenant_id,
                    identities=members,
                    similarities=similarities,
                    algorithm=graph_discovery.algorithm_name,
                    clustering_logger=clustering_logger,
                )
                clusters_created += 1

                # Resolve any pending suggestions for identities in this new cluster
                if suggestion_service:
                    for member in members:
                        await suggestion_service.resolve_for_identity_exclusive(
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

        # ============================================================
        # HAC Refinement for Noise Pool (if constraints exist)
        # ============================================================
        hac_created = await _run_hac_refinement(
            still_unclustered=still_unclustered,
            tenant_id=str(tenant_id),
            job_id=job_id,
            constrained_hac=constrained_hac,
            hac_settings=hac_settings,
            assignment_writer=assignment_writer,
            clustering_logger=clustering_logger,
        )
        if hac_created > 0:
            clusters_created += hac_created

        processed += len(chunk)
        clustering_job.processed_identities = processed
        clustering_job.progress = (processed / total_identities) if total_identities else 1.0
        await session.flush()

    # Refresh between chunks so CentroidDiscovery can see centroids for clusters created/updated earlier.
    # [Optimized] We rely on the scheduled background refresh (every 60s) to update the MV.
    # This avoids locking the view during the clustering job.
    # if remaining_identities and centroids_dirty:
    #     refresh = getattr(assignment_writer, "refresh_centroids_view", None)
    #     if callable(refresh):
    #         await refresh()

    # Confirm all provisional representatives created in this batch
    try:
        confirmed_count = await assignment_writer._clusters.confirm_all_provisional_reps(str(tenant_id))
        if confirmed_count > 0:
            logger.info("[clustering] Confirmed %d provisional representatives", confirmed_count)
    except Exception as exc:
        logger.warning("[clustering] Failed to confirm provisional representatives: %s", exc)

    # Refresh centroids view if possible (keeps centroid discovery inputs current in future batches)
    # [Optimized] Removed per-batch refresh.
    # refresh = getattr(assignment_writer, "refresh_centroids_view", None)
    # if callable(refresh):
    #     await refresh()

    logger.info(
        "[clustering] batch_complete job_id=%s accepted=%d suggested=%d rejected=%d new_clusters=%d",
        job_id,
        accept_count,
        suggest_count,
        reject_count,
        clusters_created,
    )

    clustering_job.total_identities = len(domain_identities)
    clustering_job.processed_identities = len(domain_identities)
    clustering_job.progress = 1.0
    clustering_job.status = "completed"
    clustering_job.completed_at = datetime.now(tz=UTC)
    await session.flush()

    await complete_recognition_run(
        session,
        run_id=run_ctx.run_id,
        status="completed",
        completed_at=clustering_job.completed_at,
    )
    if commit:
        await session.commit()
    finished_at = clustering_job.completed_at or datetime.now(tz=UTC)
    if clustering_logger:
        clustering_logger.bind_run_context(None)
    if callable(bind_writer_context):
        bind_writer_context(None)
    if callable(bind_graph_context):
        bind_graph_context(None)
    if clustering_logger:
        clustering_job_report = BatchJobReport(
            job_id=job_label,
            algorithm=graph_discovery.algorithm_name,
            started_at=started_at,
            completed_at=finished_at,
            total_identities=len(domain_identities),
            accept_count=accept_count,
            suggest_count=suggest_count,
            reject_count=reject_count,
            clusters_created=clusters_created,
            avg_similarity=None,
        )
        clustering_logger.log_batch_complete(clustering_job_report)

    return ClusterJobResult(
        job_id=job_label,
        started_at=started_at,
        finished_at=finished_at,
        completed=len(domain_identities),
        total=len(domain_identities),
        clusters_created=clusters_created,
        accepted=accept_count,
        suggested=suggest_count,
        rejected=reject_count,
    )


async def _run_hac_refinement(
    *,
    still_unclustered: list[MediaIdentity],
    tenant_id: str,
    job_id: str,
    constrained_hac: Any,
    hac_settings: Any,
    assignment_writer: AssignmentWriter,
    clustering_logger: ClusteringLogger | None = None,
) -> int:
    """Run constrained HAC refinement on noise identities."""
    if not (
        constrained_hac and hac_settings and still_unclustered and len(still_unclustered) <= hac_settings.max_scope_size
    ):
        return 0

    logger.info(
        "[clustering] Running HAC refinement on %d noise identities",
        len(still_unclustered),
    )

    # Extract embeddings for HAC
    embeddings_for_hac = {uuid.UUID(i.id): i.face_vector for i in still_unclustered}

    if not embeddings_for_hac:
        return 0

    # Run constrained HAC
    hac_clusters = await constrained_hac.refine_clusters(tenant_id=uuid.UUID(tenant_id), embeddings=embeddings_for_hac)

    # Group identities by HAC-assigned cluster
    hac_groups: dict[uuid.UUID, list[MediaIdentity]] = {}
    for identity in still_unclustered:
        cluster_uuid = hac_clusters.get(uuid.UUID(identity.id))
        if cluster_uuid:
            hac_groups.setdefault(cluster_uuid, []).append(identity)

    clusters_created = 0
    # Persist each HAC cluster (only multi-member clusters)
    for members in hac_groups.values():
        if len(members) > 1:
            await assignment_writer.persist_new_cluster(
                tenant_id=tenant_id,
                identities=members,
                similarities=[],  # HAC doesn't provide pairwise sims
                algorithm="constrained_hac",
                clustering_logger=clustering_logger,
            )
            clusters_created += 1
            logger.info(
                "[clustering] hac_cluster job_id=%s identity_count=%d media_ids=%s",
                job_id,
                len(members),
                [m.media_id for m in members],
            )
    return clusters_created


def _log_and_report_decision(
    *,
    logger_instance: logging.Logger,
    clustering_logger: ClusteringLogger | None,
    gate: AssignmentGate,
    candidate: AssignmentCandidate,
    decision: AssignmentDecision,
    job_label: str,
) -> None:
    """Log decision to standard logs and observability backend."""
    logger_instance.info(
        "[clustering] Gate decision for identity %s -> cluster %s: %s (checks passed: %s, failed: %s)",
        candidate.identity.id,
        candidate.cluster_id,
        decision.outcome.value,
        decision.checks_passed,
        decision.checks_failed,
    )

    if not clustering_logger:
        return

    locator_payload: dict[str, object] | None = None
    if candidate.identity.bbox_x is not None and candidate.identity.bbox_y is not None:
        try:
            locator_payload = IdentityLocator(
                media_id=int(candidate.identity.media_id),
                bbox_x=int(candidate.identity.bbox_x),
                bbox_y=int(candidate.identity.bbox_y),
                bbox_width=int(candidate.identity.bbox_width),
                bbox_height=int(candidate.identity.bbox_height),
                crop_hash=None,
            ).to_dict()
        except (TypeError, ValueError):
            locator_payload = None

    decision_metadata: dict[str, Any] = dict(decision.metadata or {})
    # Compute fingerprint for report correlation
    fingerprint = None
    if candidate.identity.embedding is not None:
        import hashlib

        # Use face_vector (normalized) for consistent fingerprinting or extract_face_embedding
        # To match previous behavior safely if we don't want to change hash values:
        # But here we can just use the internal helper logic or raw bytes if needed.
        # Let's use the explicit extract to be safe and consistent with previous code inline.
        from recognition.shared.similarity import extract_face_embedding

        face_vec = extract_face_embedding(np.asarray(candidate.identity.embedding, dtype=np.float32))
        fingerprint = hashlib.sha256(face_vec.tobytes()).hexdigest()[:8]

    decision_metadata.update(
        {
            "identity_id": candidate.identity.id,
            "embedding_fingerprint": fingerprint,
            "image_phash": candidate.identity.image_phash,
            "method": candidate.discovery_method.value,
            "stage": f"{candidate.discovery_method.name.title()}Discovery",
            "threshold": gate.settings.similarity_threshold,
            "gate_checks": {"passed": decision.checks_passed, "failed": decision.checks_failed},
            "anchor_linked": bool(candidate.anchor_linked),
            "confidence": float(decision.suggestion_confidence)
            if decision.suggestion_confidence is not None
            else candidate.discovery_similarity,
        }
    )
    if locator_payload is not None:
        decision_metadata["identity_locator"] = locator_payload

    decision_type = {
        AssignmentOutcome.ACCEPT: DecisionType.ACCEPT,
        AssignmentOutcome.SUGGEST: DecisionType.SUGGEST,
        AssignmentOutcome.REJECT: DecisionType.REJECT,
    }[decision.outcome]

    clustering_logger.log_decision(
        identity_id=candidate.identity.id,
        cluster_id=candidate.cluster_id,
        decision=decision_type,
        similarity=candidate.discovery_similarity,
        reason=decision.rejection_reason,
        metadata=decision_metadata,
        algorithm=candidate.discovery_method.value,
        job_id=job_label,
        media_id=candidate.identity.media_id,
    )


async def _prepare_cluster_caches(
    assignment_writer: AssignmentWriter,
    tenant_id: str,
) -> tuple[dict[str, list[np.ndarray]], dict[str, np.ndarray], set[str]]:
    """Fetch existing clusters and build cached structures for discovery."""
    existing_clusters = await assignment_writer._clusters.get_by_tenant(tenant_id, limit=1000, offset=0)
    logger.info("[clustering] Found %d existing clusters for discovery", len(existing_clusters))

    representatives_by_cluster: dict[str, list[np.ndarray]] = {}
    labeled_cluster_ids: set[str] = set()

    for cluster in existing_clusters:
        if cluster.id is None:
            continue

        is_user_labeled = cluster.user_confirmed or (cluster.label and not cluster.label.startswith("cluster-"))
        if is_user_labeled:
            labeled_cluster_ids.add(cluster.id)

        reps = getattr(cluster, "representatives", []) or []
        if reps:
            representatives_by_cluster[cluster.id] = [
                np.array(r.embedding, dtype=np.float32) for r in reps if r.embedding is not None
            ]

    centroids_by_cluster: dict[str, np.ndarray] = {}
    for cluster in existing_clusters:
        if cluster.id is None:
            continue
        centroid = getattr(cluster, "centroid", None)
        if centroid is not None:
            centroids_by_cluster[cluster.id] = np.array(centroid, dtype=np.float32)

    return representatives_by_cluster, centroids_by_cluster, labeled_cluster_ids


async def _run_discovery_pipeline(
    *,
    chunk: list[MediaIdentity],
    representative_discovery: RepresentativeDiscovery,
    centroid_discovery: CentroidDiscovery,
    graph_discovery: GraphDiscovery,
    representatives_by_cluster: dict[str, list[np.ndarray]],
    centroids_by_cluster: dict[str, np.ndarray],
    labeled_cluster_ids: set[str],
) -> tuple[list[AssignmentCandidate], list[tuple[list[MediaIdentity], list[float]]]]:
    """Run the multi-stage discovery pipeline (Rep -> Centroid -> Graph)."""
    # 1. Representative Discovery
    rep_candidates = await representative_discovery.discover(
        chunk,
        representatives_by_cluster,
        labeled_cluster_ids=labeled_cluster_ids,
    )
    matched_ids = {c.identity.id for c in rep_candidates}
    chunk_remaining = [i for i in chunk if i.id not in matched_ids]
    logger.info(
        "[clustering] RepresentativeDiscovery: %d candidates, %d remaining",
        len(rep_candidates),
        len(chunk_remaining),
    )

    # 2. Centroid Discovery
    centroid_candidates = await centroid_discovery.discover(chunk_remaining, centroids_by_cluster)
    centroid_matched_ids = {c.identity.id for c in centroid_candidates}
    chunk_remaining = [i for i in chunk_remaining if i.id not in centroid_matched_ids]
    logger.info(
        "[clustering] CentroidDiscovery: %d candidates, %d remaining",
        len(centroid_candidates),
        len(chunk_remaining),
    )

    # 3. Augment anchors for Graph Discovery
    anchor_embeddings = representatives_by_cluster
    augmented_anchors = (
        {k: list(v) for k, v in anchor_embeddings.items()} if isinstance(anchor_embeddings, dict) else {}
    )
    for candidate in rep_candidates + centroid_candidates:
        if candidate.cluster_id and candidate.identity.embedding is not None:
            # Use face_vector for consistency with domain object
            augmented_anchors.setdefault(candidate.cluster_id, []).append(candidate.identity.face_vector)

    # 4. Graph Discovery
    graph_result = await graph_discovery.discover(chunk_remaining, augmented_anchors)
    graph_candidates = graph_result.candidates
    new_cluster_proposals = graph_result.new_clusters
    logger.info(
        "[clustering] GraphDiscovery: %d candidates, %d new cluster proposals",
        len(graph_candidates),
        len(new_cluster_proposals),
    )

    all_candidates = rep_candidates + centroid_candidates + graph_candidates
    return all_candidates, new_cluster_proposals
