"""Tenant purge service implementation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, inspect, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    AssignmentDecision,
    ClusteringFeedback,
    ClusteringJobReport,
    ClusterMergeSuggestion,
    CurationReplayRecord,
    IdentityAtlasPoint,
    IdentityAtlasQueueDisposition,
    IdentityAtlasRun,
    IdentityCluster,
    IdentityClusterBlock,
    IdentityClusteringJob,
    IdentityClusterRepresentative,
    IdentityConstraint,
    IdentityMember,
    IdentityScanJob,
    IdentityScanJobItem,
    IdentitySuggestion,
    MediaIdentity,
    NameSuggestion,
    RecognitionEvent,
    RecognitionRun,
    Tenant,
)
from recognition.application.services.audit_service import AuditService
from recognition.infrastructure.repositories._helpers import coerce_uuid
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

ALLOWED_PURGE_SCOPES = ("disposed", "all")
DEFAULT_PURGE_BATCH_SIZE = 1000

logger = logging.getLogger(__name__)


class PurgeRowScope(Enum):
    """Explicit row scope for a purge predicate.

    A bare ``None`` previously meant both "no extra filter, delete every tenant
    row" and "this scope resolved to no ids", so a ``disposed`` purge of a tenant
    with nothing disposed deleted the tenant's live data.
    """

    ALL_TENANT_ROWS = auto()
    NO_ROWS = auto()


@dataclass(frozen=True)
class PurgeScopeIds:
    """IDs that participate in a scoped purge."""

    identity_ids: list[UUID]
    cluster_ids: list[UUID]
    representative_ids: list[UUID]


class TenantPurgeService:
    """Deletes retained machine-derived tenant state."""

    def __init__(
        self,
        session: AsyncSession,
        audit_service: AuditService | None = None,
        batch_size: int = DEFAULT_PURGE_BATCH_SIZE,
    ) -> None:
        self._session = session
        self._audit_service = audit_service or AuditService()
        self._cluster_repository = SqlAlchemyClusterRepository(session)
        self._batch_size = batch_size

    async def purge_tenant_data(self, tenant_id: str, actor: str, scope: str = "disposed") -> dict[str, object]:
        if scope not in ALLOWED_PURGE_SCOPES:
            raise ValueError("invalid purge scope")

        tenant = await self._get_tenant(tenant_id)
        purged_at = datetime.now(tz=UTC)

        await self._audit_service.record_event(
            self._session,
            tenant_id=str(tenant.id),
            event_type="purge_started",
            actor=actor,
            scope="tenant",
            payload={"scope": scope},
        )

        deleted_counts = await self._purge_rows(tenant.id, scope)
        tenant.last_purge_at = purged_at
        await self._session.flush()

        await self._audit_service.record_event(
            self._session,
            tenant_id=str(tenant.id),
            event_type="purge_completed",
            actor=actor,
            scope="tenant",
            payload={
                "scope": scope,
                "deleted_counts": deleted_counts,
                "purged_at": purged_at.isoformat(),
            },
        )

        await self._session.commit()
        await self._session.refresh(tenant)
        return {
            "tenant_id": str(tenant.id),
            "scope": scope,
            "purged_at": purged_at.isoformat(),
            "deleted_counts": deleted_counts,
        }

    async def _purge_rows(self, tenant_id: UUID, scope: str) -> dict[str, int]:
        scope_ids = await self._collect_scope_ids(tenant_id, scope)
        deleted_counts = await self._delete_jobs_for_scope(tenant_id, scope)
        deleted_counts.update(await self._delete_dependency_rows(tenant_id, scope, scope_ids))
        if not await self._cluster_repository.refresh_centroids_view_concurrent():
            logger.warning(
                "[purge] centroid MV refresh failed after purge (tenant_id=%s scope=%s); "
                "centroids may be stale until the next refresh",
                tenant_id,
                scope,
            )
        return deleted_counts

    async def _get_tenant(self, tenant_id: str) -> Tenant:
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            raise ValueError("invalid tenant_id")

        tenant = await self._session.get(Tenant, tenant_uuid)
        if tenant is None:
            raise LookupError("tenant not found")
        return tenant

    async def _collect_scope_ids(self, tenant_id: UUID, scope: str) -> PurgeScopeIds:
        return PurgeScopeIds(
            identity_ids=await self._get_identity_ids(tenant_id, scope),
            cluster_ids=await self._get_cluster_ids(tenant_id, scope),
            representative_ids=await self._get_representative_ids(tenant_id, scope),
        )

    async def _delete_jobs_for_scope(self, tenant_id: UUID, scope: str) -> dict[str, int]:
        if scope != "all":
            return {
                "recognition_events": 0,
                "recognition_runs": 0,
                "clustering_feedback": 0,
                "assignment_decisions": 0,
                "clustering_job_reports": 0,
                "curation_replay_records": 0,
                "identity_scan_job_items": 0,
                "identity_scan_jobs": 0,
                "identity_clustering_jobs": 0,
                "name_suggestions": 0,
            }

        return {
            "recognition_events": await self._delete_rows(
                RecognitionEvent,
                RecognitionEvent.tenant_id == tenant_id,
            ),
            "recognition_runs": await self._delete_rows(
                RecognitionRun,
                RecognitionRun.tenant_id == tenant_id,
            ),
            "clustering_feedback": await self._delete_rows(
                ClusteringFeedback,
                ClusteringFeedback.tenant_id == tenant_id,
            ),
            "assignment_decisions": await self._delete_rows(
                AssignmentDecision,
                AssignmentDecision.tenant_id == tenant_id,
            ),
            "clustering_job_reports": await self._delete_rows(
                ClusteringJobReport,
                ClusteringJobReport.tenant_id == tenant_id,
            ),
            "curation_replay_records": await self._delete_rows(
                CurationReplayRecord,
                CurationReplayRecord.tenant_id == tenant_id,
            ),
            "identity_scan_job_items": await self._delete_rows(
                IdentityScanJobItem,
                IdentityScanJobItem.tenant_id == tenant_id,
            ),
            "identity_scan_jobs": await self._delete_rows(
                IdentityScanJob,
                IdentityScanJob.tenant_id == tenant_id,
            ),
            "identity_clustering_jobs": await self._delete_rows(
                IdentityClusteringJob,
                IdentityClusteringJob.tenant_id == tenant_id,
            ),
        }

    async def _delete_dependency_rows(
        self,
        tenant_id: UUID,
        scope: str,
        scope_ids: PurgeScopeIds,
    ) -> dict[str, int]:
        delete_plan = [
            (
                "identity_atlas_queue_dispositions",
                IdentityAtlasQueueDisposition,
                IdentityAtlasQueueDisposition.tenant_id == tenant_id,
                self._atlas_disposition_predicate(scope),
            ),
            (
                "identity_atlas_points",
                IdentityAtlasPoint,
                IdentityAtlasPoint.tenant_id == tenant_id,
                self._atlas_point_predicate(scope_ids, scope),
            ),
            (
                "identity_atlas_runs",
                IdentityAtlasRun,
                IdentityAtlasRun.tenant_id == tenant_id,
                self._atlas_run_predicate(scope),
            ),
            (
                "identity_constraints",
                IdentityConstraint,
                IdentityConstraint.tenant_id == tenant_id,
                self._identity_constraint_predicate(scope_ids.identity_ids, scope),
            ),
            (
                "identity_cluster_blocks",
                IdentityClusterBlock,
                IdentityClusterBlock.tenant_id == tenant_id,
                self._cluster_block_predicate(scope_ids, scope),
            ),
            (
                "identity_suggestions",
                IdentitySuggestion,
                IdentitySuggestion.tenant_id == tenant_id,
                self._identity_suggestion_predicate(scope_ids, scope),
            ),
            (
                "name_suggestions",
                NameSuggestion,
                NameSuggestion.tenant_id == tenant_id,
                self._name_suggestion_predicate(scope_ids, scope),
            ),
            (
                "cluster_merge_suggestions",
                ClusterMergeSuggestion,
                ClusterMergeSuggestion.tenant_id == tenant_id,
                self._merge_suggestion_predicate(scope_ids.cluster_ids, scope),
            ),
            (
                "identity_members",
                IdentityMember,
                IdentityMember.tenant_id == tenant_id,
                self._member_predicate(scope_ids, scope),
            ),
            (
                "identity_cluster_representatives",
                IdentityClusterRepresentative,
                IdentityClusterRepresentative.tenant_id == tenant_id,
                self._representative_predicate(scope_ids, scope),
            ),
            (
                "identity_clusters",
                IdentityCluster,
                IdentityCluster.tenant_id == tenant_id,
                self._cluster_delete_predicate(scope_ids.cluster_ids, scope),
            ),
            (
                "media_identities",
                MediaIdentity,
                MediaIdentity.tenant_id == tenant_id,
                self._identity_delete_predicate(scope_ids.identity_ids, scope),
            ),
        ]

        deleted_counts: dict[str, int] = {}
        for label, model, tenant_predicate, predicate in delete_plan:
            if label == "identity_atlas_points" and scope == "disposed":
                # Dispositions have no identity/cluster columns, so disposed
                # scope leaves them to the point-delete CASCADE. Capture the
                # disposition IDs first, delete points, then re-count how many
                # of those IDs are actually gone — never report a pre-delete
                # JOIN count that could lie when the FK is missing or
                # foreign_keys is off (FL30-B-04).
                disposition_ids = await self._list_atlas_disposition_ids_for_points(
                    tenant_id, scope_ids, scope
                )
                deleted_counts[label] = await self._delete_rows(model, tenant_predicate, predicate)
                cascaded = await self._count_ids_absent(
                    IdentityAtlasQueueDisposition, disposition_ids
                )
                deleted_counts["identity_atlas_queue_dispositions"] = (
                    deleted_counts.get("identity_atlas_queue_dispositions", 0) + cascaded
                )
            else:
                deleted_counts[label] = await self._delete_rows(model, tenant_predicate, predicate)
        return deleted_counts

    def _atlas_disposition_predicate(self, scope: str) -> Any:
        # Dispositions have no identity/cluster columns; full-tenant purge only.
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        return PurgeRowScope.NO_ROWS

    def _atlas_point_predicate(self, scope_ids: PurgeScopeIds, scope: str) -> Any:
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        # cluster_id on points is denormalized (no FK). Trusting it alone would
        # either delete live-identity points (or_ with cluster_ids) or retain
        # points of disposed clusters forever (identity_ids only). Scope via
        # disposed identity_ids and via authoritative membership of disposed
        # clusters (identity_members), never denormalized point.cluster_id.
        if not scope_ids.identity_ids and not scope_ids.cluster_ids:
            return PurgeRowScope.NO_ROWS
        clauses: list[ColumnElement[bool]] = []
        if scope_ids.identity_ids:
            clauses.append(IdentityAtlasPoint.identity_id.in_(scope_ids.identity_ids))
        if scope_ids.cluster_ids:
            member_identity_ids = select(IdentityMember.identity_id).where(
                IdentityMember.cluster_id.in_(scope_ids.cluster_ids)
            )
            clauses.append(IdentityAtlasPoint.identity_id.in_(member_identity_ids))
        if len(clauses) == 1:
            return clauses[0]
        return or_(*clauses)

    async def _list_atlas_disposition_ids_for_points(
        self,
        tenant_id: UUID,
        scope_ids: PurgeScopeIds,
        scope: str,
    ) -> list[UUID]:
        """List disposition IDs attached to points the point predicate will delete."""
        point_predicate = self._atlas_point_predicate(scope_ids, scope)
        if point_predicate is PurgeRowScope.NO_ROWS:
            return []
        stmt = (
            select(IdentityAtlasQueueDisposition.id)
            .select_from(IdentityAtlasQueueDisposition)
            .join(
                IdentityAtlasPoint,
                IdentityAtlasPoint.id == IdentityAtlasQueueDisposition.point_id,
            )
            .where(IdentityAtlasPoint.tenant_id == tenant_id)
        )
        if point_predicate is not PurgeRowScope.ALL_TENANT_ROWS:
            if not isinstance(point_predicate, ColumnElement):
                raise TypeError(
                    "purge point predicate for disposition cascade count must be a SQL "
                    f"expression or PurgeRowScope member, got {point_predicate!r}"
                )
            stmt = stmt.where(point_predicate)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _count_ids_absent(self, model, ids: list[UUID]) -> int:
        """Return how many of ``ids`` are no longer present (observed deletes)."""
        if not ids:
            return 0
        primary_key = self._primary_key_column(model)
        result = await self._session.execute(
            select(func.count()).select_from(model).where(primary_key.in_(ids))
        )
        remaining = int(result.scalar_one() or 0)
        return len(ids) - remaining

    def _atlas_run_predicate(self, scope: str) -> Any:
        # Runs have no identity/cluster columns; full-tenant purge only.
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        return PurgeRowScope.NO_ROWS

    def _identity_constraint_predicate(self, identity_ids: list[UUID], scope: str) -> Any:
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        if not identity_ids:
            return PurgeRowScope.NO_ROWS
        return or_(
            IdentityConstraint.identity_a.in_(identity_ids),
            IdentityConstraint.identity_b.in_(identity_ids),
        )

    def _cluster_block_predicate(self, scope_ids: PurgeScopeIds, scope: str) -> Any:
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        if not scope_ids.identity_ids and not scope_ids.cluster_ids:
            return PurgeRowScope.NO_ROWS
        return or_(
            IdentityClusterBlock.identity_id.in_(scope_ids.identity_ids),
            IdentityClusterBlock.blocked_cluster_id.in_(scope_ids.cluster_ids),
        )

    def _identity_suggestion_predicate(self, scope_ids: PurgeScopeIds, scope: str) -> Any:
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        if not scope_ids.identity_ids and not scope_ids.cluster_ids:
            return PurgeRowScope.NO_ROWS
        return or_(
            IdentitySuggestion.identity_id.in_(scope_ids.identity_ids),
            IdentitySuggestion.suggested_cluster_id.in_(scope_ids.cluster_ids),
        )

    def _name_suggestion_predicate(self, scope_ids: PurgeScopeIds, scope: str) -> Any:
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        if not scope_ids.cluster_ids:
            return PurgeRowScope.NO_ROWS
        return NameSuggestion.cluster_id.in_(scope_ids.cluster_ids)

    def _merge_suggestion_predicate(self, cluster_ids: list[UUID], scope: str) -> Any:
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        if not cluster_ids:
            return PurgeRowScope.NO_ROWS
        return or_(
            ClusterMergeSuggestion.cluster_a_id.in_(cluster_ids),
            ClusterMergeSuggestion.cluster_b_id.in_(cluster_ids),
        )

    def _member_predicate(self, scope_ids: PurgeScopeIds, scope: str) -> Any:
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        if not scope_ids.identity_ids and not scope_ids.cluster_ids:
            return PurgeRowScope.NO_ROWS
        return or_(
            IdentityMember.identity_id.in_(scope_ids.identity_ids),
            IdentityMember.cluster_id.in_(scope_ids.cluster_ids),
        )

    def _representative_predicate(self, scope_ids: PurgeScopeIds, scope: str) -> Any:
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        if not scope_ids.representative_ids and not scope_ids.identity_ids and not scope_ids.cluster_ids:
            return PurgeRowScope.NO_ROWS
        return or_(
            IdentityClusterRepresentative.id.in_(scope_ids.representative_ids),
            IdentityClusterRepresentative.identity_id.in_(scope_ids.identity_ids),
            IdentityClusterRepresentative.cluster_id.in_(scope_ids.cluster_ids),
        )

    def _cluster_delete_predicate(self, cluster_ids: list[UUID], scope: str) -> Any:
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        if not cluster_ids:
            return PurgeRowScope.NO_ROWS
        return IdentityCluster.id.in_(cluster_ids)

    def _identity_delete_predicate(self, identity_ids: list[UUID], scope: str) -> Any:
        if scope != "disposed":
            return PurgeRowScope.ALL_TENANT_ROWS
        if not identity_ids:
            return PurgeRowScope.NO_ROWS
        return MediaIdentity.id.in_(identity_ids)

    async def _get_identity_ids(self, tenant_id: UUID, scope: str) -> list[UUID]:
        stmt = select(MediaIdentity.id).where(MediaIdentity.tenant_id == tenant_id)
        if scope == "disposed":
            stmt = stmt.where(MediaIdentity.disposed_at.is_not(None))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _get_cluster_ids(self, tenant_id: UUID, scope: str) -> list[UUID]:
        stmt = select(IdentityCluster.id).where(IdentityCluster.tenant_id == tenant_id)
        if scope == "disposed":
            stmt = stmt.where(IdentityCluster.disposed_at.is_not(None))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _get_representative_ids(self, tenant_id: UUID, scope: str) -> list[UUID]:
        stmt = select(IdentityClusterRepresentative.id).where(IdentityClusterRepresentative.tenant_id == tenant_id)
        if scope == "disposed":
            stmt = stmt.where(IdentityClusterRepresentative.disposed_at.is_not(None))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _delete_rows(
        self,
        model,
        tenant_predicate,
        extra_predicate: Any = PurgeRowScope.ALL_TENANT_ROWS,
    ) -> int:
        primary_key = self._primary_key_column(model)
        deleted_total = 0

        while True:
            batch_ids = await self._list_batch_ids(model, primary_key, tenant_predicate, extra_predicate)
            if not batch_ids:
                return deleted_total

            result = await self._session.execute(delete(model).where(primary_key.in_(batch_ids)))
            deleted_total += self._rowcount(result)
            await self._session.commit()

    async def _list_batch_ids(
        self,
        model,
        primary_key,
        tenant_predicate,
        extra_predicate: Any = PurgeRowScope.ALL_TENANT_ROWS,
    ) -> list[object]:
        if extra_predicate is PurgeRowScope.NO_ROWS:
            return []

        stmt = select(primary_key).where(tenant_predicate).order_by(primary_key.asc()).limit(self._batch_size)
        if extra_predicate is not PurgeRowScope.ALL_TENANT_ROWS:
            # Anything else silently widening to a tenant-wide delete is the
            # defect this sentinel exists to prevent, so refuse it outright.
            if not isinstance(extra_predicate, ColumnElement):
                raise TypeError(
                    f"purge predicate for {model.__name__} must be a SQL expression or "
                    f"PurgeRowScope member, got {extra_predicate!r}"
                )
            stmt = stmt.where(extra_predicate)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _primary_key_column(model):
        primary_keys = inspect(model).primary_key
        if len(primary_keys) != 1:
            raise ValueError(f"expected single-column primary key for batched purge: {model}")
        return primary_keys[0]

    @staticmethod
    def _rowcount(result) -> int:
        cursor_result = result if isinstance(result, CursorResult) else None
        return int(cursor_result.rowcount or 0) if cursor_result is not None else 0
