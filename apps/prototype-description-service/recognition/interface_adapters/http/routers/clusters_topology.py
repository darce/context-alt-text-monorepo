"""Cluster topology-mutation routes.

Concern router split out of the former ``clusters.py`` god-router (Slice 6):
the write plane — dismiss/undismiss, label patch, create-for-identity, merge,
split (sync/async + topology-command), reassign, revert-merge, outlier assign,
representative pin — plus the idempotency-replay and staleness-guard helpers
those mutations share.
"""

from __future__ import annotations

import json
import logging
from json import JSONDecodeError
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import select

import db.session as db_session_module
from db.models.identity import CurationReplayRecord
from recognition.application.tasks.clustering import run_background_surface_suggestions
from recognition.domain.cluster import ReservedClusterLabelError
from recognition.domain.constraints import ConstraintSource, ConstraintType
from recognition.domain.job import SplitJobPayload
from recognition.domain.suggestion import SuggestionRefreshReason
from recognition.infrastructure.repositories import (
    SqlAlchemyConstraintRepository,
    SqlAlchemyIdentityClusterBlockRepository,
)
from recognition.interface_adapters.http.deps import (
    build_cluster_service,
    get_cluster_repository,
    get_cluster_service_builder,
    get_persisted_cluster_job_service,
    get_session,
    get_suggestion_refresh_service,
    get_suggestion_service,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.routers.clusters_common import assert_tenant_match
from recognition.interface_adapters.http.schemas.requests import (
    AssignOutlierRequest,
    CreateClusterForIdentityRequest,
    MergeClusterRequest,
    PatchClusterRequest,
    PinRepresentativeRequest,
    ReassignIdentityRequest,
    RevertMergeClusterRequest,
    SplitClusterRequest,
    SplitTopologyCommandRequest,
)
from recognition.interface_adapters.http.schemas.responses import (
    AsyncSplitClusterResponse,
    ClusterResponse,
    CreateClusterForIdentityResponse,
    ReassignIdentityResponse,
    RevertMergeClusterResponse,
    SplitClusterResponse,
    SplitCommandCreatedCluster,
    SplitCommandMemberDelta,
    SplitTopologyCommandResponse,
)
from recognition.interface_adapters.http.validation import validate_entity_id, validate_label
from recognition.shared.ids import generate_id

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["clusters"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])


async def _load_topology_replay(session, tenant_id: str, idempotency_key: str | None) -> dict | None:
    if not idempotency_key:
        return None

    tenant_uuid = UUID(tenant_id)
    result = await session.execute(
        select(CurationReplayRecord).where(
            CurationReplayRecord.tenant_id == tenant_uuid,
            CurationReplayRecord.idempotency_key == idempotency_key,
        )
    )
    record = result.scalar_one_or_none()

    if not isinstance(record, CurationReplayRecord):
        return None

    if not isinstance(record.machine_payload_json, str) or not record.machine_payload_json.strip():
        return None

    try:
        payload = json.loads(record.machine_payload_json)
    except JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None


async def _store_topology_replay(session, tenant_id: str, idempotency_key: str | None, payload: dict) -> None:
    if not idempotency_key:
        return

    tenant_uuid = UUID(tenant_id)
    existing = await _load_topology_replay(session, tenant_id, idempotency_key)
    if existing is not None:
        return

    session.add(
        CurationReplayRecord(
            tenant_id=tenant_uuid,
            idempotency_key=idempotency_key,
            result_status="acknowledged",
            backend_version=0,
            machine_payload_json=json.dumps(payload, sort_keys=True),
        )
    )
    await session.flush()


async def _get_cluster_backend_version(cluster_repo, cluster_id: str) -> int:
    cluster = await cluster_repo.get_by_id(cluster_id)
    if cluster is None:
        return 0
    return int(getattr(cluster, "backend_version", 0) or 0)


async def _raise_if_cluster_stale(*, cluster_repo, cluster_id: str, expected_base_version: int) -> None:
    if expected_base_version <= 0:
        return

    backend_version = await _get_cluster_backend_version(cluster_repo, cluster_id)
    if backend_version <= expected_base_version:
        return

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "conflict_code": "version_conflict",
            "backend_version": backend_version,
            "source_cluster_id": cluster_id,
            "machine_payload": {
                "entity_type": "cluster",
                "entity_key": cluster_id,
                "backend_version": backend_version,
            },
        },
    )


@router.post("/clusters/{cluster_id}/dismiss", status_code=204)
async def dismiss_cluster(
    cluster_id: str,
    repo=Depends(get_cluster_repository),
    auth=Depends(require_write_access),
) -> Response:
    """Dismiss a cluster from the naming queue so the next cluster surfaces."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    dismissed = await repo.dismiss_cluster(cluster_id)
    if not dismissed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found or already dismissed")
    return Response(status_code=204)


@router.delete("/clusters/{cluster_id}/dismiss", status_code=204)
async def undismiss_cluster(
    cluster_id: str,
    repo=Depends(get_cluster_repository),
    auth=Depends(require_write_access),
) -> Response:
    """Undo dismissal so the cluster reappears in the naming queue."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    undismissed = await repo.undismiss_cluster(cluster_id)
    if not undismissed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found or not dismissed")
    return Response(status_code=204)


@router.patch("/clusters/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    request: PatchClusterRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> ClusterResponse:
    """Update cluster label."""
    import time as _time

    _t_start = _time.perf_counter()

    label = validate_label(request.label)
    validate_entity_id(cluster_id, field_name="cluster_id")
    assert_tenant_match(auth, request.tenant_id)

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    old_cluster = await cluster_repo.get_by_id(cluster_id)
    was_user_confirmed = old_cluster.user_confirmed if old_cluster else False

    cluster = await cluster_service.update_cluster(
        cluster_id,
        request.tenant_id,
        label=label,
        surface_suggestions=False,
    )
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")

    # Commit before returning the response so that any client-side refetch
    # (triggered by invalidateQueries in onSuccess) sees the committed state.
    # Without this, the commit runs in get_session() teardown which executes
    # AFTER the response is sent, creating a race where refetches can read
    # stale pre-commit data — causing intermittent label revert to UUID.
    await session.commit()

    _t_update_done = _time.perf_counter()
    _logger.info(
        "PATCH /clusters/%s: update completed in %.3fs, label='%s' was_user_confirmed=%s",
        cluster_id,
        _t_update_done - _t_start,
        label,
        was_user_confirmed,
    )

    if label and not was_user_confirmed:
        _logger.info(
            "PATCH /clusters/%s: scheduling background suggestion surfacing for label='%s'",
            cluster_id,
            label,
        )
        background_tasks.add_task(
            run_background_surface_suggestions,
            request.tenant_id,
            cluster_id,
            label,  # Pass label directly (optimistic update pattern)
            session_factory=db_session_module.async_session_factory,
            cluster_service_builder=build_cluster_service,
        )

    _t_response = _time.perf_counter()
    _logger.info(
        "PATCH /clusters/%s: returning response in %.3fs total",
        cluster_id,
        _t_response - _t_start,
    )
    return cluster


@router.post("/clusters/create-for-identity", response_model=CreateClusterForIdentityResponse)
async def create_cluster_for_identity(
    request: CreateClusterForIdentityRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> CreateClusterForIdentityResponse:
    """Create a new labeled cluster for a single identity."""
    validate_entity_id(request.identity_id, field_name="identity_id")
    label = validate_label(request.label)
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return CreateClusterForIdentityResponse.model_validate(cached_response)
    assert_tenant_match(auth, request.tenant_id)

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    if request.desired_cluster_id:
        await _raise_if_cluster_stale(
            cluster_repo=cluster_repo,
            cluster_id=request.desired_cluster_id,
            expected_base_version=request.expected_base_version,
        )
    try:
        cluster = await cluster_service.create_cluster_for_identity(
            identity_id=request.identity_id,
            label=label,
            tenant_id=request.tenant_id,
            desired_cluster_id=request.desired_cluster_id,
        )
    except ReservedClusterLabelError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if not cluster or not cluster.id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Cluster creation failed")

    # Commit before response so client refetches see committed state (see PATCH handler comment).
    response_obj = CreateClusterForIdentityResponse(
        cluster_id=cluster.id,
        label=cluster.label or label,
        identity_id=request.identity_id,
        message="Cluster created",
        backend_version=await _get_cluster_backend_version(cluster_repo, cluster.id),
    )
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()

    return response_obj


@router.post("/clusters/{cluster_id}/merge", response_model=ClusterResponse)
async def merge_cluster(
    cluster_id: str,
    request: MergeClusterRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    job_service=Depends(get_persisted_cluster_job_service),
) -> ClusterResponse:
    """Merge cluster into target (by label)."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_entity_id(request.target_cluster_id, field_name="target_cluster_id")
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return ClusterResponse.model_validate(cached_response)
    assert_tenant_match(auth, request.tenant_id)

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    await _raise_if_cluster_stale(
        cluster_repo=cluster_repo,
        cluster_id=cluster_id,
        expected_base_version=request.expected_base_version,
    )
    cluster = await cluster_service.merge_cluster(
        source_cluster_id=cluster_id,
        tenant_id=request.tenant_id,
        target_cluster_id=request.target_cluster_id,
        target_label=request.target_label,
        defer_recompute=True,
        moved_by_merge_id=str(generate_id()),
    )
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")

    # Queue curation job for deferred work (replaces background tasks).
    # Skip if source == target (merge becomes a metadata update and should not trigger delete).
    if cluster_id.lower() != request.target_cluster_id.lower():
        await job_service.queue_curation_followup(
            tenant_id=request.tenant_id,
            cluster_ids=[request.target_cluster_id],
            source_cluster_id=cluster_id,
        )

    # Commit before response so client refetches see committed state (see PATCH handler comment).
    response_obj = ClusterResponse.model_validate(cluster)
    response_obj.backend_version = await _get_cluster_backend_version(cluster_repo, request.target_cluster_id)
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()

    return response_obj


@router.post("/clusters/{cluster_id}/split", response_model=SplitClusterResponse | AsyncSplitClusterResponse)
async def split_cluster(
    cluster_id: str,
    request: SplitClusterRequest,
    response: Response,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    suggestion_refresh_service=Depends(get_suggestion_refresh_service),
    job_service=Depends(get_persisted_cluster_job_service),
) -> SplitClusterResponse | AsyncSplitClusterResponse:
    """
    Split a cluster using hierarchical clustering.

    If n_clusters=0 (default), automatically determines the optimal split
    based on face similarity. If n_clusters>=2, forces exactly that many groups.
    The largest group stays in the original cluster; others become new clusters.

    If mode="async", the split is queued and returns 202 Accepted with a job ID.
    """
    validate_entity_id(cluster_id, field_name="cluster_id")
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        if "job_id" in cached_response:
            return AsyncSplitClusterResponse.model_validate(cached_response)
        return SplitClusterResponse.model_validate(cached_response)
    assert_tenant_match(auth, request.tenant_id)

    if request.mode == "async":
        if not hasattr(job_service, "queue_split"):
            job_service = await get_persisted_cluster_job_service(
                session=session,
                tenant_id=request.tenant_id,
                cluster_service_builder=cluster_service_builder,
            )
        payload = SplitJobPayload(
            cluster_id=cluster_id,
            n_clusters=request.n_clusters,
            anchor_identity_id=request.anchor_identity_id,
            split_mode=request.split_mode,
        )
        job = await job_service.queue_split(tenant_id=request.tenant_id, payload=payload)
        response.status_code = status.HTTP_202_ACCEPTED
        response_obj = AsyncSplitClusterResponse(
            job_id=job.id,
            status=job.status.value,
            message=f"Split operation queued for cluster {cluster_id[:8]}",
        )
        await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
        await session.commit()
        return response_obj

    if getattr(suggestion_refresh_service, "tenant_id", None) != request.tenant_id:
        suggestion_refresh_service = await get_suggestion_refresh_service(
            session=session,
            tenant_id=request.tenant_id,
        )

    cluster_service = await cluster_service_builder(request.tenant_id)
    new_ids, counts = await cluster_service.split_cluster(
        cluster_id,
        n_clusters=request.n_clusters,
        anchor_identity_id=request.anchor_identity_id,
        split_mode=request.split_mode,
        recompute=False,
    )
    if new_ids:
        await job_service.queue_curation_followup(
            tenant_id=request.tenant_id,
            cluster_ids=[cluster_id, *new_ids],
        )

    # Build response with both new list format and legacy single-cluster fields
    response_obj = SplitClusterResponse(
        new_cluster_ids=new_ids,
        moved_counts=counts,
        # Legacy fields: use first new cluster if any
        new_cluster_id=new_ids[0] if new_ids else None,
        moved_count=counts[0] if counts else 0,
    )

    # Refresh suggestions for affected clusters
    for cid in [cluster_id, *new_ids]:
        await suggestion_refresh_service.refresh_for_cluster(cid)

    # Commit before response so client refetches see committed state (see PATCH handler comment).
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()

    return response_obj


@router.post("/topology-commands/split", response_model=SplitTopologyCommandResponse)
async def split_topology_command(
    request: SplitTopologyCommandRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    cluster_repo=Depends(get_cluster_repository),
) -> SplitTopologyCommandResponse:
    """Execute a split through the topology-command plane."""
    validate_entity_id(request.cluster_id, field_name="cluster_id")
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return SplitTopologyCommandResponse.model_validate(cached_response)
    assert_tenant_match(auth, request.tenant_id)

    source_cluster = await cluster_repo.get_by_id(request.cluster_id)
    if source_cluster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")

    source_tenant_id = getattr(source_cluster, "tenant_id", None)
    if source_tenant_id and str(source_tenant_id) != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")

    backend_version = int(getattr(source_cluster, "backend_version", 0) or 0)
    if request.expected_base_version > 0 and backend_version > request.expected_base_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "conflict_code": "version_conflict",
                "backend_version": backend_version,
                "source_cluster_id": request.cluster_id,
                "machine_payload": {
                    "entity_type": "cluster",
                    "entity_key": request.cluster_id,
                    "backend_version": backend_version,
                },
            },
        )

    cluster_service = await cluster_service_builder(request.tenant_id)
    new_ids, counts = await cluster_service.split_cluster(
        request.cluster_id,
        n_clusters=request.n_clusters,
        anchor_identity_id=request.anchor_identity_id,
        split_mode=request.split_mode,
        desired_cluster_ids=request.desired_cluster_ids,
        recompute=False,
    )

    # Ensure the snapshot read sees the split writes before deriving response lineage.
    await session.flush()

    affected_cluster_ids = [request.cluster_id, *new_ids]
    snapshot_members = await cluster_repo.get_members_by_cluster_ids(request.tenant_id, affected_cluster_ids)
    snapshot_version = await cluster_repo.get_snapshot_version(request.tenant_id)
    remaining_identity_ids: list[str] = []
    created_clusters: list[SplitCommandCreatedCluster] = []
    for member, _identity in snapshot_members:
        if member.cluster_id == request.cluster_id:
            remaining_identity_ids.append(member.identity_id)
            continue
        if member.cluster_id in new_ids:
            matching_cluster = next(
                (cluster for cluster in created_clusters if cluster.cluster_id == member.cluster_id),
                None,
            )
            if matching_cluster is None:
                matching_cluster = SplitCommandCreatedCluster(cluster_id=member.cluster_id, identity_ids=[])
                created_clusters.append(matching_cluster)
            matching_cluster.identity_ids.append(member.identity_id)

    response_obj = SplitTopologyCommandResponse(
        command_id=str(generate_id()),
        status="applied",
        original_cluster_id=request.cluster_id,
        new_cluster_ids=new_ids,
        member_delta=SplitCommandMemberDelta(
            source_cluster_id=request.cluster_id,
            remaining_identity_ids=remaining_identity_ids,
            created_clusters=created_clusters,
        ),
        moved_counts=counts,
        affected_cluster_ids=affected_cluster_ids,
        result_snapshot_version=snapshot_version,
    )
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()
    return response_obj


@router.post("/clusters/reassign", response_model=ReassignIdentityResponse)
async def reassign_identity(
    request: ReassignIdentityRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    suggestion_service=Depends(get_suggestion_service),
    suggestion_refresh_service=Depends(get_suggestion_refresh_service),
    job_service=Depends(get_persisted_cluster_job_service),
) -> ReassignIdentityResponse:
    """Reassign an identity to a different cluster.

    This endpoint is used for:
    - Accepting inline suggestions (moving singleton to labeled cluster)
    - Correcting misassigned identities
    - Removing from cluster (set target_cluster_id to null)

    When reassigning to a cluster, any pending suggestion for that identity+cluster
    is automatically marked as accepted.
    """
    validate_entity_id(request.identity_id, field_name="identity_id")
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return ReassignIdentityResponse.model_validate(cached_response)
    if request.target_cluster_id:
        validate_entity_id(request.target_cluster_id, field_name="target_cluster_id")
    assert_tenant_match(auth, request.tenant_id)

    if getattr(suggestion_service, "tenant_id", None) != request.tenant_id:
        suggestion_service = await get_suggestion_service(
            session=session,
            tenant_id=request.tenant_id,
        )
    if getattr(suggestion_refresh_service, "tenant_id", None) != request.tenant_id:
        suggestion_refresh_service = await get_suggestion_refresh_service(
            session=session,
            tenant_id=request.tenant_id,
        )

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    if request.target_cluster_id:
        await _raise_if_cluster_stale(
            cluster_repo=cluster_repo,
            cluster_id=request.target_cluster_id,
            expected_base_version=request.expected_base_version,
        )

    # Get identity's current cluster (if any)
    source_cluster_id = await cluster_service.get_identity_cluster_id(request.identity_id)

    if request.target_cluster_id:
        block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=request.tenant_id)
        await block_repo.remove_block(
            tenant_id=request.tenant_id,
            identity_id=request.identity_id,
            blocked_cluster_id=request.target_cluster_id,
        )
        # Assign to target cluster
        result = await cluster_service.assign_outlier_to_cluster(
            identity_id=request.identity_id,
            target_cluster_id=request.target_cluster_id,
            tenant_id=request.tenant_id,
            similarity=0.0,  # Not known at this point
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Identity or target cluster not found",
            )

        # Resolve any pending suggestion for this identity+cluster as accepted
        await suggestion_service.resolve_for_identity_exclusive(
            identity_id=request.identity_id,
            accepted_cluster_id=request.target_cluster_id,
            reason="manual_assign",
        )
        await suggestion_refresh_service.refresh_for_identity(
            identity_id=request.identity_id,
            reason=SuggestionRefreshReason.MANUAL_ASSIGN,
        )
    else:
        # Remove from current cluster (make orphan)
        await cluster_service.remove_identity_from_cluster(request.identity_id, recompute=True)
        if source_cluster_id:
            if request.block_from_cluster:
                block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=request.tenant_id)
                await block_repo.add_block(
                    tenant_id=request.tenant_id,
                    identity_id=request.identity_id,
                    blocked_cluster_id=source_cluster_id,
                    reason="manual_removal",
                )

                # Create CANNOT_LINK constraint to permanently prevent linking
                try:
                    # We need the cluster's representative to anchor the constraint
                    cluster_repo = cluster_service.assignment_writer.cluster_repository
                    source_cluster = await cluster_repo.get_by_id(source_cluster_id)

                    if source_cluster and source_cluster.representative_identity_id:
                        constraint_repo = SqlAlchemyConstraintRepository(session)
                        await constraint_repo.create(
                            tenant_id=request.tenant_id,
                            identity_a=request.identity_id,
                            identity_b=str(source_cluster.representative_identity_id),
                            constraint_type=ConstraintType.CANNOT_LINK.value,
                            source=ConstraintSource.WRONG_PERSON.value,
                            created_by_user_id=None,  # User ID not currently available in request
                        )
                except Exception as exc:
                    # Don't fail the request if constraint creation fails
                    _logger.warning(
                        "Failed to create CANNOT_LINK constraint for identity %s: %s", request.identity_id, exc
                    )

            await job_service.queue_curation_followup(
                tenant_id=request.tenant_id,
                cluster_ids=[source_cluster_id],
                identity_ids=[request.identity_id],
            )
        if source_cluster_id:
            await suggestion_service.resolve_for_identity(
                identity_id=request.identity_id,
                cluster_id=source_cluster_id,
                resolution="rejected",
            )
        await suggestion_refresh_service.refresh_for_identity(
            identity_id=request.identity_id,
            reason=SuggestionRefreshReason.WRONG_PERSON,
        )

        # Refresh suggestions for the affected clusters
        if source_cluster_id:
            await suggestion_refresh_service.refresh_for_cluster(source_cluster_id)

    # Commit before response so client refetches see committed state (see PATCH handler comment).
    response_obj = ReassignIdentityResponse(
        identity_id=request.identity_id,
        source_cluster_id=source_cluster_id,
        target_cluster_id=request.target_cluster_id,
        success=True,
        backend_version=(
            await _get_cluster_backend_version(
                cluster_repo,
                request.target_cluster_id if request.target_cluster_id else (source_cluster_id or ""),
            )
            if request.target_cluster_id or source_cluster_id
            else 0
        ),
    )
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()

    return response_obj


@router.post("/clusters/revert-merge", response_model=RevertMergeClusterResponse)
async def revert_merge_cluster(
    request: RevertMergeClusterRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> RevertMergeClusterResponse:
    """Restore moved identities into a recreated source cluster."""
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return RevertMergeClusterResponse.model_validate(cached_response)
    assert_tenant_match(auth, request.tenant_id)

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    await _raise_if_cluster_stale(
        cluster_repo=cluster_repo,
        cluster_id=request.target_cluster_id,
        expected_base_version=request.expected_base_version,
    )

    target_cluster = await cluster_repo.get_by_id(request.target_cluster_id)
    if target_cluster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target cluster not found")

    for identity_id in request.moved_identity_ids:
        current_cluster_id = await cluster_service.get_identity_cluster_id(identity_id)
        if current_cluster_id != request.target_cluster_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="One or more identities are no longer assigned to the target cluster",
            )

    restored_label = request.source_label or ""
    source_cluster_id = request.desired_source_cluster_id or str(generate_id())
    restored_cluster = await cluster_service.create_cluster_for_identity(
        identity_id=request.moved_identity_ids[0],
        label=restored_label,
        tenant_id=request.tenant_id,
        desired_cluster_id=source_cluster_id,
    )

    for identity_id in request.moved_identity_ids[1:]:
        reassigned = await cluster_service.assign_outlier_to_cluster(
            identity_id=identity_id,
            target_cluster_id=restored_cluster.id,
            tenant_id=request.tenant_id,
            similarity=0.0,
        )
        if reassigned is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identity not found")

    refreshed_target = await cluster_repo.get_by_id(request.target_cluster_id)
    response_obj = RevertMergeClusterResponse(
        restored_cluster_id=restored_cluster.id,
        restored_identity_count=len(request.moved_identity_ids),
        target_cluster_id=request.target_cluster_id,
        target_identity_count=int(getattr(refreshed_target, "identity_count", 0) or 0),
        restored_label=request.source_label,
        backend_version=await _get_cluster_backend_version(cluster_repo, request.target_cluster_id),
    )
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()
    return response_obj


@router.post("/clusters/{cluster_id}/assign", response_model=ClusterResponse)
async def assign_outlier(
    cluster_id: str,
    request: AssignOutlierRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
    suggestion_refresh_service=Depends(get_suggestion_refresh_service),
) -> ClusterResponse:
    """Assign an unclustered identity (outlier) to an existing cluster."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_entity_id(request.identity_id, field_name="identity_id")
    cached_response = await _load_topology_replay(session, request.tenant_id, request.idempotency_key)
    if cached_response is not None:
        return ClusterResponse.model_validate(cached_response)
    assert_tenant_match(auth, request.tenant_id)

    if getattr(suggestion_refresh_service, "tenant_id", None) != request.tenant_id:
        suggestion_refresh_service = await get_suggestion_refresh_service(
            session=session,
            tenant_id=request.tenant_id,
        )

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    await _raise_if_cluster_stale(
        cluster_repo=cluster_repo,
        cluster_id=cluster_id,
        expected_base_version=request.expected_base_version,
    )
    cluster = await cluster_service.assign_outlier_to_cluster(
        identity_id=request.identity_id,
        target_cluster_id=cluster_id,
        tenant_id=request.tenant_id,
        similarity=request.similarity,
    )
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster or identity not found")

    # Refresh suggestions for the target cluster
    await suggestion_refresh_service.refresh_for_cluster(cluster_id)

    # Commit before response so client refetches see committed state (see PATCH handler comment).
    response_obj = ClusterResponse.model_validate(cluster)
    response_obj.backend_version = await _get_cluster_backend_version(cluster_repo, cluster_id)
    await _store_topology_replay(session, request.tenant_id, request.idempotency_key, response_obj.model_dump())
    await session.commit()

    return response_obj


@router.patch("/clusters/{cluster_id}/representatives/{representative_id}/pin", status_code=status.HTTP_204_NO_CONTENT)
async def pin_representative(
    cluster_id: str,
    representative_id: str,
    request: PinRepresentativeRequest,
    auth=Depends(require_write_access),
    repo=Depends(get_cluster_repository),
) -> None:
    """Pin or unpin a cluster representative."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_entity_id(representative_id, field_name="representative_id")
    assert_tenant_match(auth, request.tenant_id)

    await repo.mark_representative_user_selected(
        representative_id=representative_id,
        is_selected=request.is_pinned,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
