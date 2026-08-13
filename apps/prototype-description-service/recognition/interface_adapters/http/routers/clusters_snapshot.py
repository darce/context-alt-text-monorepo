"""Cluster read / snapshot-projection routes.

Concern router split out of the former ``clusters.py`` god-router (Slice 6):
the read plane — cluster listing, WordPress snapshot/targeted-snapshot/delta
projections, top-unlabeled bootstrap, and per-cluster member listing — plus the
face-box and snapshot-response builders those reads share.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.label_inference import infer_suggested_label
from recognition.config.security import get_security_settings
from recognition.config.settings import resolve_effective_clustering_settings
from recognition.domain.repositories import ClusterRepository
from recognition.interface_adapters.http.blob_url import build_face_thumb_path
from recognition.interface_adapters.http.deps import (
    get_cluster_repository,
    get_cluster_service_builder,
    get_persisted_cluster_job_service,
    get_session,
    require_auth,
)
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.tenant import get_authenticated_tenant_id
from recognition.interface_adapters.http.face_box import face_box_from_components, representative_response_from_domain
from recognition.interface_adapters.http.routers.clusters_common import assert_tenant_match
from recognition.interface_adapters.http.schemas.responses import (
    ClusterDeltaResponse,
    ClusterMemberResponse,
    ClusterMembersEnvelopeResponse,
    ClusterResponse,
    ClusterSnapshotClusterResponse,
    ClusterSnapshotMemberResponse,
    ClusterSnapshotResponse,
    FaceBoxResponse,
)
from recognition.interface_adapters.http.validation import validate_entity_id, validate_paging

_logger = logging.getLogger(__name__)

CLUSTER_MEMBERS_PAGE_LIMIT = 500

_INFERENCE_CAP = 20

router = APIRouter(tags=["clusters"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])


def _face_box_from_components(bbox_x, bbox_y, bbox_width, bbox_height) -> FaceBoxResponse | None:
    return face_box_from_components(bbox_x, bbox_y, bbox_width, bbox_height)


def _face_box_from_identity(identity) -> FaceBoxResponse | None:
    return _face_box_from_components(
        getattr(identity, "bbox_x", None),
        getattr(identity, "bbox_y", None),
        getattr(identity, "bbox_width", None),
        getattr(identity, "bbox_height", None),
    )


def _face_thumb_url_for_identity(identity, bbox: FaceBoxResponse | None) -> str | None:
    if bbox is None:
        return None
    return build_face_thumb_path(
        getattr(identity, "media_url", None),
        x=bbox.x,
        y=bbox.y,
        width=bbox.width,
        height=bbox.height,
    )


def _build_cluster_responses(
    clusters: list,
) -> list[ClusterSnapshotClusterResponse]:
    """Build cluster snapshot responses from domain cluster objects."""
    responses: list[ClusterSnapshotClusterResponse] = []
    for cluster in clusters:
        curation_state = "dismissed" if cluster.dismissed_at else ("confirmed" if cluster.user_confirmed else "active")

        # Get representative thumb path
        representative_thumb_path = None
        representative_id = None
        is_pinned = False
        if cluster.representatives and len(cluster.representatives) > 0:
            # Sort by id for stable fallback if no user-selected representative exists
            # ( mitigates RSWR-IMPL-007: non-deterministic collection ordering )
            reps = sorted(cluster.representatives, key=lambda r: str(r.id))
            rep = next(
                (candidate for candidate in reps if candidate.is_user_selected),
                reps[0],
            )
            if rep.identity_id:
                representative_id = str(rep.identity_id)
                is_pinned = bool(rep.is_user_selected)
                # Format: acx://cluster/{cluster_uuid}/media/{media_id}
                representative_thumb_path = f"acx://cluster/{cluster.id}/media/{rep.media_id}"

        responses.append(
            ClusterSnapshotClusterResponse(
                cluster_uuid=str(cluster.id),
                label=cluster.label,
                curation_state=curation_state,
                is_user_confirmed=cluster.user_confirmed,
                identity_count=cluster.identity_count,
                representative_thumb_path=representative_thumb_path,
                representative_id=representative_id,
                is_pinned=is_pinned,
            )
        )
    return responses


def _build_member_responses(
    members_with_identities: list,
) -> list[ClusterSnapshotMemberResponse]:
    """Build member snapshot responses from member/identity pairs."""
    responses: list[ClusterSnapshotMemberResponse] = []
    for member, identity in members_with_identities:
        # Note: bbox coordinates may be None for some detections; default to 0
        bbox_x = identity.bbox_x or 0
        bbox_y = identity.bbox_y or 0

        # Note: MediaIdentity doesn't store full image dimensions.
        # Consumer resolves dimensions from WordPress media metadata (wp_postmeta).
        image_width = 0
        image_height = 0

        responses.append(
            ClusterSnapshotMemberResponse(
                identity_uuid=identity.id,
                cluster_uuid=member.cluster_id,
                attachment_id=int(identity.media_id),
                bbox=FaceBoxResponse(
                    x=bbox_x,
                    y=bbox_y,
                    width=identity.bbox_width,
                    height=identity.bbox_height,
                ),
                image_width=image_width,
                image_height=image_height,
                thumb_path=f"acx://identity/{identity.id}/attachment/{identity.media_id}",
                similarity=member.similarity,
            )
        )
    return responses


async def _enrich_with_suggested_labels(
    cluster_responses: list[ClusterSnapshotClusterResponse],
    tenant_id: str,
    session: AsyncSession,
    repo: ClusterRepository,
    settings: ClusteringSettings,
) -> None:
    """Best-effort label inference for unlabeled clusters, bounded to top N."""
    unlabeled = [cr for cr in cluster_responses if cr.label is None and not cr.is_user_confirmed]
    unlabeled.sort(key=lambda cr: cr.identity_count, reverse=True)

    for cluster_resp in unlabeled[:_INFERENCE_CAP]:
        try:
            inferred = await infer_suggested_label(
                tenant_id=tenant_id,
                cluster_id=cluster_resp.cluster_uuid,
                session=session,
                cluster_repository=repo,
                settings=settings,
            )
            if inferred:
                cluster_resp.suggested_label = inferred.label
                cluster_resp.suggested_label_source = inferred.source.value
                cluster_resp.suggested_label_confidence = inferred.confidence
                cluster_resp.suggested_target_cluster_id = inferred.target_cluster_id
        except Exception:
            _logger.warning(
                "suggested_label inference failed for cluster %s (tenant %s); skipping enrichment",
                cluster_resp.cluster_uuid,
                tenant_id,
                exc_info=True,
            )


@router.get("/clusters", response_model=list[ClusterResponse])
async def list_clusters(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    limit: int = Query(50),
    offset: int = Query(0),
    include_outliers: bool = Query(False),
    labeled_only: bool = Query(False),
    search: str | None = Query(None),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> list[ClusterResponse]:
    """List clusters with paging."""
    settings = get_security_settings()
    validate_paging(limit, offset, settings.max_page_size)
    cluster_service = await cluster_service_builder(tenant_id)
    return await cluster_service.list_clusters(
        tenant_id,
        limit=limit,
        offset=offset,
        include_outliers=include_outliers,
        labeled_only=labeled_only,
        search=search,
    )


@router.get("/tenants/{tenant_uuid}/clusters/snapshot", response_model=ClusterSnapshotResponse)
async def get_tenant_cluster_snapshot(
    tenant_uuid: str,
    auth=Depends(require_auth),
    repo=Depends(get_cluster_repository),
    job_service=Depends(get_persisted_cluster_job_service),
    session=Depends(get_session),
) -> ClusterSnapshotResponse:
    """Get complete cluster snapshot for WordPress plugin projection.

    Returns all clusters and members for a tenant in a single response,
    formatted per contracts/cluster-snapshot-api.md.

    Note: Path param is ``tenant_uuid`` (not ``tenant_id``) to avoid a FastAPI
    collision with ``get_tenant_id_optional`` which declares ``tenant_id`` as
    ``Query`` in the transitive dep chain (get_cluster_repository -> get_session
    -> get_tenant_id_optional). See rule 13 in backend-python-guidelines.
    """
    tenant_id = tenant_uuid  # canonical internal name

    # Verify auth if tenant claim exists
    assert_tenant_match(auth, tenant_id)

    # Get snapshot data
    clusters, members_with_identities, snapshot_version, snapshot_generation_id = await repo.get_snapshot(
        tenant_id,
        stamp_export=True,
    )
    latest_clustering_job = await job_service.get_latest_completed_clustering_job_for_tenant(tenant_id)

    if not clusters and not members_with_identities:
        # Return 404 if tenant has no clusters (unknown tenant or empty tenant)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No clusters found for tenant")

    # Build responses
    cluster_responses = _build_cluster_responses(clusters)
    clustering_settings = resolve_effective_clustering_settings()
    await _enrich_with_suggested_labels(cluster_responses, tenant_id, session, repo, clustering_settings)
    member_responses = _build_member_responses(members_with_identities)

    return ClusterSnapshotResponse(
        tenant_id=tenant_uuid,
        snapshot_version=snapshot_version,
        snapshot_generation_id=snapshot_generation_id,
        source_job_id=latest_clustering_job.id if latest_clustering_job is not None else None,
        generated_at=datetime.now(tz=UTC),
        clusters=cluster_responses,
        members=member_responses,
    )


@router.get("/tenants/{tenant_uuid}/clusters/targeted-snapshot", response_model=ClusterSnapshotResponse)
async def get_tenant_targeted_cluster_snapshot(
    tenant_uuid: str,
    cluster_ids: list[str] = Query(default_factory=list),
    auth=Depends(require_auth),
    repo=Depends(get_cluster_repository),
    job_service=Depends(get_persisted_cluster_job_service),
) -> ClusterSnapshotResponse:
    """Get a targeted cluster snapshot for a subset of cluster ids."""
    tenant_id = tenant_uuid

    assert_tenant_match(auth, tenant_id)

    normalized_cluster_ids = [cluster_id.strip() for cluster_id in cluster_ids if cluster_id.strip()]
    if not normalized_cluster_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cluster_ids required")

    clusters = await repo.get_clusters_by_ids(tenant_id, normalized_cluster_ids)
    members_with_identities = await repo.get_members_by_cluster_ids(tenant_id, normalized_cluster_ids)
    snapshot_version = await repo.get_snapshot_version(tenant_id)
    latest_clustering_job = await job_service.get_latest_completed_clustering_job_for_tenant(tenant_id)

    if not clusters and not members_with_identities:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No clusters found for requested ids")

    return ClusterSnapshotResponse(
        tenant_id=tenant_uuid,
        snapshot_version=snapshot_version,
        source_job_id=latest_clustering_job.id if latest_clustering_job is not None else None,
        generated_at=datetime.now(tz=UTC),
        clusters=_build_cluster_responses(clusters),
        members=_build_member_responses(members_with_identities),
    )


@router.get("/tenants/{tenant_uuid}/clusters/delta", response_model=ClusterDeltaResponse)
async def get_tenant_cluster_delta(
    tenant_uuid: str,
    since_version: int = Query(..., ge=0),
    auth=Depends(require_auth),
    repo: ClusterRepository = Depends(get_cluster_repository),
    session=Depends(get_session),
) -> ClusterDeltaResponse:
    """Get version-filtered cluster updates for incremental projection sync."""
    tenant_id = tenant_uuid

    assert_tenant_match(auth, tenant_id)

    clusters, members_with_identities, snapshot_version = await repo.get_delta(tenant_id, since_version=since_version)

    if snapshot_version <= 0 and not clusters and not members_with_identities:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No clusters found for tenant")

    cluster_responses = _build_cluster_responses(clusters)
    clustering_settings = resolve_effective_clustering_settings()
    await _enrich_with_suggested_labels(cluster_responses, tenant_id, session, repo, clustering_settings)

    return ClusterDeltaResponse(
        tenant_id=tenant_uuid,
        snapshot_version=snapshot_version,
        generated_at=datetime.now(tz=UTC),
        clusters=cluster_responses,
        members=_build_member_responses(members_with_identities),
    )


@router.get("/clusters/top-unlabeled", response_model=list[ClusterResponse])
async def get_top_unlabeled_clusters(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    limit: int = Query(10),
    min_identity_count: int = Query(2, ge=1, description="Minimum identity count (default 2 to skip singletons)"),
    repo=Depends(get_cluster_repository),
    session=Depends(get_session),
) -> list[ClusterResponse]:
    """Fetch top unlabeled clusters by member count for bootstrapping suggestions.

    Includes cluster representatives with face thumbnails for display in the
    suggestion panel.
    """
    clusters = await repo.get_top_unlabeled(
        tenant_id,
        limit=limit,
        min_identity_count=min_identity_count,
    )
    allowed_sources = {"identity", "roster", "similar_cluster", "none"}

    responses: list[ClusterResponse] = []
    clustering_settings = resolve_effective_clustering_settings()
    for c in clusters:
        suggested_label = getattr(c, "suggested_label", None)

        raw_source = getattr(c, "suggested_label_source", None)
        if hasattr(raw_source, "value"):
            raw_source = raw_source.value
        suggested_label_source = raw_source if isinstance(raw_source, str) and raw_source in allowed_sources else None

        raw_confidence = getattr(c, "suggested_label_confidence", None)
        try:
            suggested_label_confidence = float(raw_confidence) if raw_confidence is not None else None
        except (TypeError, ValueError):
            suggested_label_confidence = None
        raw_target_cluster_id = getattr(c, "suggested_target_cluster_id", None)
        suggested_target_cluster_id = str(raw_target_cluster_id) if raw_target_cluster_id else None

        if not suggested_label and not c.user_confirmed:
            try:
                inferred = await infer_suggested_label(
                    tenant_id=tenant_id,
                    cluster_id=str(c.id),
                    session=session,
                    cluster_repository=repo,
                    settings=clustering_settings,
                )
                if inferred:
                    suggested_label = inferred.label
                    suggested_label_source = inferred.source.value if inferred.source else None
                    suggested_label_confidence = inferred.confidence
                    suggested_target_cluster_id = inferred.target_cluster_id
            except Exception as exc:  # pragma: no cover - best-effort enrichment
                _logger.debug("top-unlabeled label inference failed cluster_id=%s err=%s", c.id, exc)

        responses.append(
            ClusterResponse(
                id=str(c.id),
                tenant_id=tenant_id,
                label=c.label,
                is_labeled=c.is_labeled,
                is_auto_label=c.is_auto_label,
                identity_count=c.identity_count,
                user_confirmed=c.user_confirmed,
                representatives=[representative_response_from_domain(rep) for rep in (c.representatives or [])],
                suggested_label=suggested_label,
                suggested_label_source=suggested_label_source,
                suggested_label_confidence=suggested_label_confidence,
                suggested_target_cluster_id=suggested_target_cluster_id,
            )
        )

    return responses


@router.get("/clusters/{cluster_id}/members", response_model=ClusterMembersEnvelopeResponse)
async def list_cluster_members(
    cluster_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    cluster_service_builder=Depends(get_cluster_service_builder),
    limit: int = Query(CLUSTER_MEMBERS_PAGE_LIMIT),
    offset: int = Query(0),
) -> ClusterMembersEnvelopeResponse:
    """List identities in a cluster with membership data (paged).

    Returns identity details combined with membership similarity scores,
    formatted for the frontend ClusterReviewPanel. Envelope shape is
    ``{members, limit, total, truncated}``; clients page via limit/offset.
    """
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_paging(limit, offset, CLUSTER_MEMBERS_PAGE_LIMIT)
    cluster_service = await cluster_service_builder(tenant_id)
    cluster_repo = cluster_service.cluster_repository

    cluster = await cluster_repo.get_by_id(cluster_id)
    cluster_label = getattr(cluster, "label", None) if cluster else None
    cluster_is_auto_label = bool(getattr(cluster, "is_auto_label", False)) if cluster else False
    representative_id = getattr(cluster, "representative_identity_id", None) if cluster else None
    representative_id = str(representative_id) if representative_id else None

    total = await cluster_repo.get_member_identity_count(cluster_id)
    visible_members = await cluster_repo.get_member_identities_with_similarity(
        cluster_id,
        limit=limit,
        offset=offset,
    )
    truncated = (offset + len(visible_members)) < total

    return ClusterMembersEnvelopeResponse(
        members=[
            ClusterMemberResponse(
                identity_id=str(identity.id),
                media_id=int(identity.media_id),
                similarity=similarity,
                confidence=float(identity.confidence),
                bbox=(bbox := _face_box_from_identity(identity)),
                thumb_url=_face_thumb_url_for_identity(identity, bbox),
                media_url=getattr(identity, "media_url", None),
                cluster_id=cluster_id,
                cluster_label=cluster_label,
                is_auto_label=cluster_is_auto_label,
                is_pinned=representative_id == str(identity.id) if representative_id else False,
                detected_at=getattr(identity, "created_at", None),
                representative_id=representative_id,
                debug_metrics=getattr(identity, "debug_metrics", None),
            )
            for identity, similarity in visible_members
        ],
        limit=limit,
        total=total,
        truncated=truncated,
    )
