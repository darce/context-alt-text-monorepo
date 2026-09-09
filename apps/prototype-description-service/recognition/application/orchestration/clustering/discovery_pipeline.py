"""Discovery pipeline helpers for incremental clustering."""

from __future__ import annotations

import contextlib
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from recognition.application.assignment import AssignmentCandidate, AssignmentOutcome
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.discovery.graph.helpers import compute_member_similarities
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.identity import MediaIdentity
from recognition.observability import ClusteringLogger
from recognition.shared.similarity import normalize_face_embedding

if TYPE_CHECKING:
    from sqlalchemy import Executable
    from sqlalchemy.engine import Result
    from sqlalchemy.ext.asyncio import AsyncSession

    from recognition.application.assignment import AssignmentDecision
    from recognition.application.orchestration.clustering.decision_handler import DecisionHandler
    from recognition.application.orchestration.protocols import MergeSuggestionServiceProtocol
    from recognition.application.settings import HACSettings
    from recognition.domain.repositories import ConstrainedHACProtocol

logger = logging.getLogger(__name__)


class GalleryProvenanceUnavailableError(RuntimeError):
    """The FIR23-01 gallery filter emptied the gallery for an infrastructure reason.

    Raised so the clustering job fails instead of completing with an empty
    gallery: every probe would miss and open a brand-new cluster, permanently
    fragmenting the tenant. ``scan_worker`` classifies this as deterministic, so
    the job lands in FAILED with a readable ``error_message`` rather than
    retry-looping against a misconfiguration.
    """


@dataclass(frozen=True, slots=True)
class GalleryProvenanceStats:
    """Operator-visible counters for FIR23-01 gallery / centroid filtering.

    Surfaced on the clustering job payload so a wiped gallery is not only a
    log line (R3-G2-1). Counts are zero when the active model is known and
    every representative resolved cleanly to that space.
    """

    active_embedding_model: str | None
    provenance_loaded: bool
    representatives_excluded_unresolvable: int
    clusters_excluded_unresolvable: int
    centroids_excluded_untrusted: int
    gallery_wiped: bool

    def abort_reason(self) -> str | None:
        """Why the job must fail, or ``None`` when clustering may proceed (R3-03).

        Discriminates an *infrastructure*-caused wipe from a *legitimate* space
        migration. A failed job is recoverable; a tenant fragmented into
        duplicate clusters is not — but aborting on a real migration would
        permanently block clustering after a space-token rollout, so the two
        must not be collapsed.

        Abort when the gallery is empty because provenance could not be
        established: no active model, or the provenance query itself failed.
        Unstamped/legacy representatives are the documented both-unstamped
        space (``models_are_same_space(None, None)``), not an infrastructure
        wipe — proceed so single-model tenants that never stamped provenance
        keep clustering. Proceed also when every excluded representative
        resolved to a real model that simply is not the active one — that is
        the migration, and it is the intended behaviour.
        """
        if not self.gallery_wiped:
            return None
        if self.active_embedding_model is None:
            return "active embedding_model unresolved (probe manifest unavailable)"
        if not self.provenance_loaded:
            return f"representative embedding_model provenance unavailable (active={self.active_embedding_model})"
        return None

    def to_payload(self) -> dict[str, object]:
        """JSON-serialisable dict for IdentityClusteringJob.payload."""
        return {
            "active_embedding_model": self.active_embedding_model,
            "provenance_loaded": self.provenance_loaded,
            "representatives_excluded_unresolvable": self.representatives_excluded_unresolvable,
            "clusters_excluded_unresolvable": self.clusters_excluded_unresolvable,
            "centroids_excluded_untrusted": self.centroids_excluded_untrusted,
            "gallery_wiped": self.gallery_wiped,
        }


def _representative_embedding_model(rep: object, model_by_identity: dict[str, str]) -> str | None:
    """Resolve embedding_model for a representative (attr, nested identity, or lookup)."""
    direct = getattr(rep, "embedding_model", None)
    if direct:
        return str(direct)
    identity = getattr(rep, "identity", None)
    if identity is not None:
        nested = getattr(identity, "embedding_model", None)
        if nested:
            return str(nested)
    identity_id = getattr(rep, "identity_id", None)
    if identity_id is not None:
        return model_by_identity.get(str(identity_id))
    return None


def _resolve_assignment_session(
    assignment_writer: AssignmentWriter,
    session: AsyncSession | None = None,
) -> AsyncSession | None:
    """Resolve a DB session for representative embedding_model provenance.

    Priority (R3-G2-5 / CVUP1-GR-21):

    1. Explicit ``session`` — production orchestrator threads the job session so
       provenance does not depend on private attributes.
    2. ``cluster_repository._session`` — same binding that ``get_by_tenant`` uses
       to load clusters; keeps the provenance query in the same transactional
       view as the gallery it will filter.
    3. ``assignment_writer._session`` — optional (often ``None``); present when
       the writer was constructed with an explicit session (HTTP path sets both
       writer and repo to the same request session).

    Writer vs repo can theoretically differ if a caller constructs the writer
    with a different session than the repository. Preferring the repository
    session after the explicit argument avoids filtering against a snapshot
    that never saw the rows ``get_by_tenant`` just returned.
    """
    if session is not None:
        return session
    repo = getattr(assignment_writer, "cluster_repository", None)
    if repo is not None:
        repo_session: AsyncSession | None = getattr(repo, "_session", None)
        if repo_session is not None:
            return repo_session
    writer_session: AsyncSession | None = getattr(assignment_writer, "_session", None)
    if writer_session is not None:
        return writer_session
    return None


async def _execute_provenance_query(session: AsyncSession, stmt: Executable) -> Result[Any]:
    """Run the provenance SELECT, isolated by SAVEPOINT when available (R3-G2-3).

    Mirrors ``recognition.application.health`` readiness probes: a failed
    statement on PostgreSQL aborts the outer transaction, so later job writes
    raise ``InFailedSqlTransaction``. ``session.begin_nested()`` opens a
    SAVEPOINT; rolling it back on error leaves the job session usable.

    Unit stubs without ``begin_nested`` fall through to a plain execute.
    """
    begin_nested = getattr(session, "begin_nested", None)
    if begin_nested is not None:
        async with begin_nested():
            return await session.execute(stmt)
    return await session.execute(stmt)


async def _load_representative_embedding_models(
    assignment_writer: AssignmentWriter,
    tenant_id: str,
    *,
    session: AsyncSession | None = None,
) -> tuple[dict[str, str], bool]:
    """Map representative identity_id → embedding_model via the repository session.

    Domain ClusterRepresentative may drop embedding_model; this recovers provenance
    for FIR23-01 gallery filtering without depending on lane H1's domain field.

    Returns:
        (model_by_identity, provenance_loaded)
        provenance_loaded is True only when a session was available and the query
        completed without error. Unit stubs with no session get ({}, False).
        An empty map with provenance_loaded=True means the query succeeded but
        found no model stamps (still fail-closed for unresolvable domain reps).
    """
    resolved = _resolve_assignment_session(assignment_writer, session)
    if resolved is None:
        return {}, False
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        return {}, False
    try:
        from sqlalchemy import select

        from db.models import IdentityCluster, IdentityClusterRepresentative, MediaIdentity

        stmt = (
            select(IdentityClusterRepresentative.identity_id, MediaIdentity.embedding_model)
            .join(MediaIdentity, MediaIdentity.id == IdentityClusterRepresentative.identity_id)
            .join(IdentityCluster, IdentityCluster.id == IdentityClusterRepresentative.cluster_id)
            .where(IdentityCluster.tenant_id == tenant_uuid)
            .where(MediaIdentity.embedding_model.isnot(None))
        )
        result = await _execute_provenance_query(resolved, stmt)
        return (
            {str(identity_id): str(model) for identity_id, model in result.all() if model},
            True,
        )
    except Exception:
        logger.warning(
            "[clustering] failed to load representative embedding_model map; "
            "unresolvable representatives will be excluded from gallery cache "
            "(FIR23-01 / CVUP1-GR-21 — safer than admitting cross-space anchors)",
            exc_info=True,
        )
        return {}, False


def _resolve_probe_embedding_model() -> str | None:
    """Active runtime embedding space for discovery probes (FIR23-01).

    Returns None when the active model cannot be resolved. Callers must treat
    that as a blind gate and fail closed (R3-G2-4) — never silently disable the
    space filter, which would admit every gallery vector for cross-space cosine.
    """
    try:
        from recognition.application.embedding.manifest import active_embedding_model_id

        return active_embedding_model_id()
    except Exception:
        logger.warning(
            "[clustering] active embedding_model unresolved; gallery and centroid "
            "caches will be emptied so discovery cannot cosine across unknown spaces "
            "(FIR23-01 / R3-G2-4 — fail closed while the gate is blind)",
            exc_info=True,
        )
        return None


async def prepare_cluster_caches(
    assignment_writer: AssignmentWriter,
    tenant_id: str,
    *,
    session: AsyncSession | None = None,
) -> tuple[dict[str, list[np.ndarray]], dict[str, np.ndarray], set[str], GalleryProvenanceStats]:
    """Fetch existing clusters and build cached structures for discovery.

    Should be called ONCE per job before the chunk loop.  Use
    update_cluster_caches_from_new_cluster() to incrementally update the
    returned dicts after each chunk commits new clusters (Phase 3 efficiency).

    FIR23-01: representatives and centroids are restricted to the active
    embedding_model so discovery never cosines across distinct spaces at the
    same dimensionality.

    Centroid provenance (R3-G4-3): the centroid MV does not expose
    ``embedding_model`` on the domain/ORM path (majority-of-members vector is
    framed per-model inside the MV SQL, but that chosen model is not returned).
    The only sound rule with available data: when the active model is known,
    admit a centroid only if the cluster has at least one representative with
    an embedding AND every such representative resolved to the active model.
    Empty-rep clusters, mixed-space clusters, and unresolvable-rep clusters all
    exclude their centroid (fail closed).

    Args:
        assignment_writer: Writer exposing cluster_repository (and optionally a
            bound session).
        tenant_id: Tenant UUID string.
        session: Optional SQLAlchemy session for embedding_model provenance.
            Callers should pass the job/request session explicitly when available
            so this path does not depend on private ``_session`` attributes
            (CVUP1-GR-21). When omitted, falls back to the writer/repository
            binding via ``_resolve_assignment_session``.

    Returns:
        (representatives_by_cluster, centroids_by_cluster, labeled_cluster_ids,
         gallery_provenance_stats)
    """
    existing_clusters = await assignment_writer.cluster_repository.get_by_tenant(tenant_id, limit=1000, offset=0)
    logger.info("[clustering] Found %d existing clusters for discovery", len(existing_clusters))

    target_model = _resolve_probe_embedding_model()
    model_by_identity, provenance_loaded = await _load_representative_embedding_models(
        assignment_writer,
        tenant_id,
        session=session,
    )

    # R3-G2-4: blind gate — empty gallery rather than admit every vector.
    if target_model is None:
        labeled_only: set[str] = set()
        for cluster in existing_clusters:
            if cluster.id is None:
                continue
            is_user_labeled = cluster.user_confirmed or (cluster.label and not cluster.label.startswith("cluster-"))
            if is_user_labeled:
                labeled_only.add(cluster.id)
        stats = GalleryProvenanceStats(
            active_embedding_model=None,
            provenance_loaded=provenance_loaded,
            representatives_excluded_unresolvable=0,
            clusters_excluded_unresolvable=0,
            centroids_excluded_untrusted=0,
            gallery_wiped=bool(existing_clusters),
        )
        if stats.gallery_wiped:
            logger.warning(
                "[clustering] gallery wiped: active embedding_model unresolved; "
                "excluded gallery for %d existing clusters (FIR23-01 / R3-G2-4)",
                len(existing_clusters),
            )
        return {}, {}, labeled_only, stats

    # CVUP1-GR-21: when provenance cannot be loaded, fail closed for unresolvable
    # representatives. Unit stubs without a session must set embedding_model on
    # each rep (or nested identity) directly.
    if not provenance_loaded:
        logger.warning(
            "[clustering] representative embedding_model provenance unavailable while "
            "active model is known (%s); unresolvable representatives will be excluded "
            "from the gallery cache to avoid cross-space cosine (FIR23-01 / CVUP1-GR-21)",
            target_model,
        )

    representatives_by_cluster: dict[str, list[np.ndarray]] = {}
    labeled_cluster_ids: set[str] = set()
    # cluster_id → True iff every embedding-bearing rep resolved to target_model
    # and at least one such rep exists (R3-G4-3 centroid gate).
    centroid_trusted_for_target: dict[str, bool] = {}

    reps_excluded_unresolvable = 0
    clusters_with_unresolvable: set[str] = set()
    clusters_with_any_embedding_rep = 0

    for cluster in existing_clusters:
        if cluster.id is None:
            continue

        is_user_labeled = cluster.user_confirmed or (cluster.label and not cluster.label.startswith("cluster-"))
        if is_user_labeled:
            labeled_cluster_ids.add(cluster.id)

        reps = getattr(cluster, "representatives", []) or []
        kept: list[np.ndarray] = []
        seen_embedding_rep = False
        all_resolved_to_target = True
        cluster_had_unresolvable = False

        for r in reps:
            if getattr(r, "embedding", None) is None:
                continue
            seen_embedding_rep = True
            rep_model = _representative_embedding_model(r, model_by_identity)
            if rep_model is not None and rep_model != target_model:
                all_resolved_to_target = False
                continue
            if rep_model is None:
                # Safe default (CVUP1-GR-21): exclude unresolvable reps whenever
                # the active space is known. Including them reintroduces the GR-02
                # cross-space cosine bug. Stubs without a session still work when
                # they stamp embedding_model on the rep object itself.
                all_resolved_to_target = False
                cluster_had_unresolvable = True
                reps_excluded_unresolvable += 1
                continue
            kept.append(np.array(r.embedding, dtype=np.float32))

        if seen_embedding_rep:
            clusters_with_any_embedding_rep += 1
        if cluster_had_unresolvable:
            clusters_with_unresolvable.add(cluster.id)

        if kept:
            representatives_by_cluster[cluster.id] = kept

        # Centroid admissible only when every embedding-bearing rep resolved to
        # the active model (implies at least one such rep). Empty-rep clusters
        # and mixed/unresolvable clusters are untrusted (R3-G4-3).
        centroid_trusted_for_target[cluster.id] = bool(seen_embedding_rep and all_resolved_to_target)

    centroids_by_cluster: dict[str, np.ndarray] = {}
    centroids_excluded_untrusted = 0
    for cluster in existing_clusters:
        if cluster.id is None:
            continue
        centroid = getattr(cluster, "centroid", None)
        if centroid is None:
            continue
        if centroid_trusted_for_target.get(cluster.id, False):
            centroids_by_cluster[cluster.id] = np.array(centroid, dtype=np.float32)
        else:
            centroids_excluded_untrusted += 1

    # R3-G2-7: warn with counts whenever unresolvable exclusions happened —
    # including provenance_loaded=True with an empty map (query succeeded, no
    # model stamps returned). Previously the warning was gated only on
    # not provenance_loaded, so a successful empty map was silent.
    if reps_excluded_unresolvable > 0:
        logger.warning(
            "[clustering] excluded %d representatives across %d clusters for "
            "unresolvable embedding_model provenance (active=%s, provenance_loaded=%s); "
            "those anchors will not participate in discovery — probes may open "
            "brand-new clusters instead of matching existing identities "
            "(FIR23-01 / CVUP1-GR-21 / R3-G2-7)",
            reps_excluded_unresolvable,
            len(clusters_with_unresolvable),
            target_model,
            provenance_loaded,
        )

    gallery_wiped = clusters_with_any_embedding_rep > 0 and not representatives_by_cluster and not centroids_by_cluster
    if gallery_wiped:
        logger.warning(
            "[clustering] gallery wiped: active model=%s provenance_loaded=%s "
            "excluded_reps=%d excluded_clusters=%d excluded_centroids=%d — "
            "RepresentativeDiscovery will short-circuit and unclustered faces "
            "become brand-new clusters (FIR23-01 / R3-G2-1)",
            target_model,
            provenance_loaded,
            reps_excluded_unresolvable,
            len(clusters_with_unresolvable),
            centroids_excluded_untrusted,
        )

    stats = GalleryProvenanceStats(
        active_embedding_model=target_model,
        provenance_loaded=provenance_loaded,
        representatives_excluded_unresolvable=reps_excluded_unresolvable,
        clusters_excluded_unresolvable=len(clusters_with_unresolvable),
        centroids_excluded_untrusted=centroids_excluded_untrusted,
        gallery_wiped=gallery_wiped,
    )
    return representatives_by_cluster, centroids_by_cluster, labeled_cluster_ids, stats


def update_cluster_caches_from_new_cluster(
    *,
    cluster_id: str,
    seed_identities: list[MediaIdentity],
    centroid: np.ndarray | None,
    representatives_by_cluster: dict[str, list[np.ndarray]],
    centroids_by_cluster: dict[str, np.ndarray],
) -> None:
    """Incrementally update in-memory cluster caches after a new cluster is created.

    Called once per newly persisted cluster inside the chunk loop so that
    subsequent chunks can discover the cluster without reloading from the DB.

    Args:
        cluster_id: UUID string of the newly created cluster.
        seed_identities: The identities that seeded the cluster (their embeddings
            become the initial representative set in the cache).
        centroid: Pre-computed centroid array returned by persist_new_cluster,
            or None if not yet available.
        representatives_by_cluster: Mutable representative cache to update in-place.
        centroids_by_cluster: Mutable centroid cache to update in-place.
    """
    if seed_identities:
        representatives_by_cluster[cluster_id] = [
            normalize_face_embedding(np.asarray(i.embedding, dtype=np.float32))
            for i in seed_identities
            if i.embedding is not None
        ]
    if centroid is not None:
        centroids_by_cluster[cluster_id] = centroid


async def run_discovery_pipeline(
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

    centroid_candidates = await centroid_discovery.discover(chunk_remaining, centroids_by_cluster)
    centroid_matched_ids = {c.identity.id for c in centroid_candidates}
    chunk_remaining = [i for i in chunk_remaining if i.id not in centroid_matched_ids]
    logger.info(
        "[clustering] CentroidDiscovery: %d candidates, %d remaining",
        len(centroid_candidates),
        len(chunk_remaining),
    )

    anchor_embeddings = representatives_by_cluster
    augmented_anchors = (
        {k: list(v) for k, v in anchor_embeddings.items()} if isinstance(anchor_embeddings, dict) else {}
    )
    for candidate in rep_candidates + centroid_candidates:
        if candidate.cluster_id and candidate.identity.embedding is not None:
            augmented_anchors.setdefault(candidate.cluster_id, []).append(candidate.identity.face_vector)

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


@dataclass(frozen=True, slots=True)
class ChunkGateResult:
    """Outcome partition for one chunk's discovery candidates.

    ``*_count`` fields count decisions; the ``*_ids`` sets dedupe by identity id.
    The two can legitimately differ when a single identity produces multiple
    candidates, so both are reported (behaviour-preserving split).
    """

    accepted_decisions: list[AssignmentDecision]
    accepted_ids: set[str]
    suggested_ids: set[str]
    rejected_ids: set[str]
    accept_count: int
    suggest_count: int
    reject_count: int


@dataclass(frozen=True, slots=True)
class ChunkPartition:
    """Identities that still need a new cluster after gate evaluation."""

    still_unclustered: list[MediaIdentity]
    no_candidates: list[MediaIdentity]
    rejected_identities: list[MediaIdentity]
    suggested_identities: list[MediaIdentity]


async def evaluate_chunk_candidates(
    *,
    all_candidates: list[AssignmentCandidate],
    decision_handler: DecisionHandler,
    job_id: str,
    job_label: str,
    verbose: bool,
) -> ChunkGateResult:
    """Evaluate each candidate through the gate and partition it by outcome.

    ACCEPT persistence is deferred to the caller (bulk write per cluster); this
    seam only classifies and accumulates the accepted decisions in order.
    """
    accepted_decisions: list[AssignmentDecision] = []
    accepted_ids: set[str] = set()
    suggested_ids: set[str] = set()
    rejected_ids: set[str] = set()
    accept_count = 0
    suggest_count = 0
    reject_count = 0

    for candidate in all_candidates:
        decision = await decision_handler.evaluate_only(
            candidate,
            job_id=job_id,
            job_label=job_label,
            verbose=verbose,
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

    return ChunkGateResult(
        accepted_decisions=accepted_decisions,
        accepted_ids=accepted_ids,
        suggested_ids=suggested_ids,
        rejected_ids=rejected_ids,
        accept_count=accept_count,
        suggest_count=suggest_count,
        reject_count=reject_count,
    )


def partition_unclustered(
    *,
    chunk: list[MediaIdentity],
    accepted_ids: set[str],
    suggested_ids: set[str],
    rejected_ids: set[str],
    new_cluster_proposals: list[tuple[list[MediaIdentity], list[float]]],
) -> ChunkPartition:
    """Identify the chunk's identities that still need a new cluster.

    Suggested identities need singleton clusters as a fallback: they carry a
    suggestion linking them to an existing cluster but must still belong to some
    cluster. Ordering (no_candidates ++ rejected ++ suggested) is preserved.
    """
    already_in_new_clusters = {member.id for members, _ in new_cluster_proposals for member in members}
    all_processed_ids = accepted_ids | suggested_ids | rejected_ids | already_in_new_clusters
    no_candidates = [i for i in chunk if i.id not in all_processed_ids]
    rejected_identities = [i for i in chunk if i.id in rejected_ids]
    suggested_identities = [i for i in chunk if i.id in suggested_ids]
    still_unclustered = no_candidates + rejected_identities + suggested_identities
    return ChunkPartition(
        still_unclustered=still_unclustered,
        no_candidates=no_candidates,
        rejected_identities=rejected_identities,
        suggested_identities=suggested_identities,
    )


async def run_hac_refinement(
    *,
    still_unclustered: list[MediaIdentity],
    tenant_id: str,
    job_id: str,
    constrained_hac: ConstrainedHACProtocol | None,
    hac_settings: HACSettings | None,
    assignment_writer: AssignmentWriter,
    clustering_logger: ClusteringLogger | None = None,
) -> int:
    """Run constrained HAC refinement on noise identities."""
    if not (
        constrained_hac and hac_settings and still_unclustered and len(still_unclustered) <= hac_settings.max_scope_size
    ):
        return 0

    # HAC requires at least 2 identities to compute pairwise distances
    if len(still_unclustered) < 2:
        logger.debug(
            "[clustering] Skipping HAC refinement: need at least 2 identities, got %d",
            len(still_unclustered),
        )
        return 0

    logger.info(
        "[clustering] Running HAC refinement on %d noise identities",
        len(still_unclustered),
    )

    embeddings_for_hac = {uuid.UUID(i.id): i.face_vector for i in still_unclustered}

    if not embeddings_for_hac:
        return 0

    hac_clusters = await constrained_hac.refine_clusters(tenant_id=uuid.UUID(tenant_id), embeddings=embeddings_for_hac)

    hac_groups: dict[uuid.UUID, list[MediaIdentity]] = {}
    for identity in still_unclustered:
        cluster_uuid = hac_clusters.get(uuid.UUID(identity.id))
        if cluster_uuid:
            hac_groups.setdefault(cluster_uuid, []).append(identity)

    clusters_created = 0
    for members in hac_groups.values():
        if len(members) > 1:
            similarities = compute_member_similarities([member.face_vector for member in members])
            await assignment_writer.persist_new_cluster(
                tenant_id=tenant_id,
                identities=members,
                similarities=similarities,
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


async def run_singleton_hac_refinement(
    *,
    tenant_id: str,
    constrained_hac: ConstrainedHACProtocol | None,
    hac_settings: HACSettings | None,
    assignment_writer: AssignmentWriter,
    merge_suggestion_service: MergeSuggestionServiceProtocol | None = None,
    clustering_logger: ClusteringLogger | None = None,
) -> int:
    """Run constrained HAC refinement on singleton clusters after HDBSCAN."""
    logger.info("[clustering] singleton_hac_start tenant_id=%s", tenant_id)
    if not (constrained_hac and hac_settings):
        logger.info("[clustering] singleton_hac_skip reason=no_hac_configured")
        return 0

    cluster_repo = assignment_writer.cluster_repository
    member_repo = assignment_writer.member_repository

    singletons = await cluster_repo.get_singleton_identities(
        tenant_id,
        limit=hac_settings.max_scope_size,
    )
    logger.info("[clustering] singleton_hac_query singletons_found=%d", len(singletons))
    if len(singletons) < 2:
        logger.info("[clustering] singleton_hac_skip reason=not_enough_singletons count=%d", len(singletons))
        return 0

    embeddings_for_hac: dict[uuid.UUID, np.ndarray] = {}
    identity_to_cluster: dict[uuid.UUID, str] = {}
    for identity in singletons:
        if not identity.cluster_id:
            continue
        try:
            identity_uuid = uuid.UUID(identity.id)
        except ValueError:
            continue
        embeddings_for_hac[identity_uuid] = normalize_face_embedding(np.asarray(identity.embedding, dtype=np.float32))
        identity_to_cluster[identity_uuid] = identity.cluster_id

    logger.info("[clustering] singleton_hac_prepared embeddings=%d", len(embeddings_for_hac))
    if len(embeddings_for_hac) < 2:
        logger.info("[clustering] singleton_hac_skip reason=not_enough_embeddings count=%d", len(embeddings_for_hac))
        return 0

    # Use more lenient threshold for singleton refinement
    singleton_threshold = hac_settings.singleton_distance_threshold
    logger.info(
        "[clustering] singleton_hac_threshold distance=%.3f (similarity=%.1f%%)",
        singleton_threshold,
        (1 - singleton_threshold) * 100,
    )
    hac_clusters = await constrained_hac.refine_clusters(
        tenant_id=uuid.UUID(tenant_id),
        embeddings=embeddings_for_hac,
        distance_threshold_override=singleton_threshold,
    )
    logger.info("[clustering] singleton_hac_refined groups=%d", len(set(hac_clusters.values())))

    hac_groups: dict[uuid.UUID, list[uuid.UUID]] = {}
    for identity_uuid, group_uuid in hac_clusters.items():
        if identity_uuid in identity_to_cluster:
            hac_groups.setdefault(group_uuid, []).append(identity_uuid)

    # Count how many groups have 2+ identities (potential merges)
    merge_candidates = sum(1 for ids in hac_groups.values() if len(ids) >= 2)
    logger.info("[clustering] singleton_hac_groups total=%d merge_candidates=%d", len(hac_groups), merge_candidates)

    merged_clusters = 0
    for identities in hac_groups.values():
        if len(identities) < 2:
            continue
        target_identity = identities[0]
        target_cluster_id = identity_to_cluster.get(target_identity)
        if not target_cluster_id:
            continue

        target_cluster = await cluster_repo.get_by_id(target_cluster_id)
        if not target_cluster:
            continue

        moved_total = 0
        for identity_uuid in identities[1:]:
            source_cluster_id = identity_to_cluster.get(identity_uuid)
            if not source_cluster_id or source_cluster_id == target_cluster_id:
                continue
            moved = await member_repo.move_members(source_cluster_id, target_cluster_id)
            if moved:
                moved_total += moved
                merged_clusters += 1
                delete_by_cluster = getattr(merge_suggestion_service, "delete_by_cluster", None)
                if callable(delete_by_cluster):
                    with contextlib.suppress(Exception):
                        await delete_by_cluster(tenant_id, source_cluster_id)
                        await delete_by_cluster(tenant_id, target_cluster_id)
                await cluster_repo.delete(source_cluster_id)

        if moved_total:
            target_cluster.identity_count = (target_cluster.identity_count or 0) + moved_total
            await cluster_repo.update(target_cluster)
            await assignment_writer.recompute_representatives(target_cluster_id)
            await assignment_writer.recompute_centroid(target_cluster_id)
            logger.info(
                "[clustering] singleton_hac_merge tenant_id=%s target_cluster=%s merged=%d",
                tenant_id,
                target_cluster_id,
                moved_total,
            )

    if merged_clusters:
        # Best-effort: the merges are already applied and their centroids recomputed
        # and persisted above. refresh_centroids_view is fail-fast (INFRA-5), but a
        # transient MV-refresh failure must not flip a completed clustering job to
        # FAILED — the scan worker's periodic concurrent refresh heals the MV lag.
        try:
            await assignment_writer.refresh_centroids_view()
        except Exception:
            logger.warning(
                "[clustering] singleton_hac_merge MV refresh failed tenant_id=%s; "
                "centroids may lag until the next scheduled refresh",
                tenant_id,
                exc_info=True,
            )

    return merged_clusters
