"""SQLAlchemy-backed implementation of MergeSuggestionRepository."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from db.models import ClusterMergeSuggestion as MergeSuggestionModel
from db.models import IdentityCluster, MediaIdentity
from recognition.domain.repositories import MergeSuggestionCreateData, MergeSuggestionRepository
from recognition.domain.suggestion import MergeSuggestion, SuggestionStatus
from recognition.domain.suggestion_details import FaceBox, MergeSuggestionDetails
from recognition.infrastructure.repositories._helpers import coerce_uuid as _coerce_uuid
from recognition.shared.db.helpers import execute_dml, get_rowcount


def _clamp_similarity(value: float) -> float:
    """Clamp similarity to [0.0, 1.0] range to satisfy DB constraint."""
    return max(0.0, min(1.0, value))


class SqlAlchemyMergeSuggestionRepository(MergeSuggestionRepository):
    """Persist cluster merge suggestions using an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_pending(self, tenant_id: str, payload: MergeSuggestionCreateData) -> MergeSuggestion:
        """Create or update a pending merge suggestion for a cluster pair."""
        tenant_uuid = _coerce_uuid(tenant_id)
        if tenant_uuid is None:
            raise ValueError("tenant_id must be a valid UUID-compatible string")

        cluster_a_uuid = _coerce_uuid(payload.cluster_a_id)
        cluster_b_uuid = _coerce_uuid(payload.cluster_b_id)
        if cluster_a_uuid is None or cluster_b_uuid is None:
            raise ValueError("cluster ids must be valid UUID-compatible strings")
        if cluster_a_uuid == cluster_b_uuid:
            raise ValueError("cluster ids must be different")

        survivor_uuid = _coerce_uuid(payload.survivor_cluster_id) if payload.survivor_cluster_id else None
        if survivor_uuid is not None and survivor_uuid not in {cluster_a_uuid, cluster_b_uuid}:
            raise ValueError("survivor_cluster_id must be one of the pair")

        cluster_a_uuid, cluster_b_uuid = _canonical_pair(cluster_a_uuid, cluster_b_uuid)

        existing_stmt = (
            select(MergeSuggestionModel)
            .where(MergeSuggestionModel.tenant_id == tenant_uuid)
            .where(MergeSuggestionModel.cluster_a_id == cluster_a_uuid)
            .where(MergeSuggestionModel.cluster_b_id == cluster_b_uuid)
        )
        existing = (await self._session.execute(existing_stmt)).scalar_one_or_none()

        if existing:
            if existing.resolution == SuggestionStatus.PENDING.value:
                existing.similarity = _clamp_similarity(payload.similarity)
                existing.confidence_score = payload.confidence_score
                existing.survivor_cluster_id = survivor_uuid
                if payload.refreshed_at:
                    existing.refreshed_at = payload.refreshed_at
                if payload.expires_at is not None:
                    existing.expires_at = payload.expires_at
                if payload.source_job_id is not None:
                    existing.source_job_id = _coerce_uuid(payload.source_job_id)
                if payload.source:
                    existing.source = payload.source
                await self._session.flush()
                await self._session.refresh(existing)
            return self._to_domain(existing)

        model = MergeSuggestionModel(
            tenant_id=tenant_uuid,
            cluster_a_id=cluster_a_uuid,
            cluster_b_id=cluster_b_uuid,
            survivor_cluster_id=survivor_uuid,
            similarity=_clamp_similarity(payload.similarity),
            confidence_score=payload.confidence_score,
            resolution=SuggestionStatus.PENDING.value,
            refreshed_at=payload.refreshed_at,
            expires_at=payload.expires_at,
            source_job_id=_coerce_uuid(payload.source_job_id),
            source=payload.source,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def list_pending_with_details(
        self,
        tenant_id: str,
        limit: int,
        offset: int,
    ) -> list[MergeSuggestionDetails]:
        """Return pending merge suggestions with cluster details."""
        tenant_uuid = _coerce_uuid(tenant_id)
        if tenant_uuid is None:
            return []
        stmt = (
            select(MergeSuggestionModel)
            .where(MergeSuggestionModel.tenant_id == tenant_uuid)
            .where(MergeSuggestionModel.resolution == SuggestionStatus.PENDING.value)
            .order_by(MergeSuggestionModel.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(
                joinedload(MergeSuggestionModel.cluster_a).joinedload(IdentityCluster.representative_identity),
                joinedload(MergeSuggestionModel.cluster_b).joinedload(IdentityCluster.representative_identity),
            )
        )
        result = await self._session.execute(stmt)
        return [self._to_details(model) for model in result.scalars().all()]

    async def update_status(
        self,
        tenant_id: str,
        suggestion_id: str,
        status: SuggestionStatus,
    ) -> MergeSuggestion:
        """Update the resolution of a merge suggestion."""
        tenant_uuid = _coerce_uuid(tenant_id)
        suggestion_uuid = _coerce_uuid(suggestion_id)
        if not tenant_uuid or not suggestion_uuid:
            raise ValueError("tenant_id and suggestion_id must be valid UUID-compatible strings")
        stmt = (
            select(MergeSuggestionModel)
            .where(MergeSuggestionModel.tenant_id == tenant_uuid)
            .where(MergeSuggestionModel.id == suggestion_uuid)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise ValueError(f"Merge suggestion not found: {suggestion_id}")
        model.resolution = status.value
        model.resolved_at = datetime.now(tz=UTC)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def get_by_id(self, tenant_id: str, suggestion_id: str) -> MergeSuggestion | None:
        """Fetch a merge suggestion by id."""
        tenant_uuid = _coerce_uuid(tenant_id)
        suggestion_uuid = _coerce_uuid(suggestion_id)
        if not tenant_uuid or not suggestion_uuid:
            return None
        stmt = (
            select(MergeSuggestionModel)
            .where(MergeSuggestionModel.tenant_id == tenant_uuid)
            .where(MergeSuggestionModel.id == suggestion_uuid)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
        """Delete pending merge suggestions involving the provided cluster."""
        tenant_uuid = _coerce_uuid(tenant_id)
        cluster_uuid = _coerce_uuid(cluster_id)
        if tenant_uuid is None or cluster_uuid is None:
            return 0
        stmt = (
            delete(MergeSuggestionModel)
            .where(MergeSuggestionModel.tenant_id == tenant_uuid)
            .where(MergeSuggestionModel.resolution == SuggestionStatus.PENDING.value)
            .where(
                or_(
                    MergeSuggestionModel.cluster_a_id == cluster_uuid,
                    MergeSuggestionModel.cluster_b_id == cluster_uuid,
                )
            )
        )
        result = await execute_dml(self._session, stmt)
        await self._session.flush()
        return get_rowcount(result)

    def _to_domain(self, model: MergeSuggestionModel) -> MergeSuggestion:
        """Convert ORM model to domain object."""
        return MergeSuggestion(
            id=str(model.id),
            cluster_a_id=str(model.cluster_a_id),
            cluster_b_id=str(model.cluster_b_id),
            similarity=float(model.similarity),
            status=SuggestionStatus(model.resolution),
            confidence_score=float(model.confidence_score) if model.confidence_score is not None else None,
            created_at=model.created_at,
            expires_at=model.expires_at,
            source_job_id=str(model.source_job_id) if model.source_job_id is not None else None,
            resolved_at=model.resolved_at,
            refreshed_at=model.refreshed_at,
            source=model.source,
            survivor_cluster_id=str(model.survivor_cluster_id) if model.survivor_cluster_id is not None else None,
        )

    def _build_bbox(self, identity: MediaIdentity | None) -> FaceBox | None:
        if identity is None:
            return None
        if None in (identity.bbox_x, identity.bbox_y, identity.bbox_width, identity.bbox_height):
            return None
        return FaceBox(
            x=int(identity.bbox_x),
            y=int(identity.bbox_y),
            width=int(identity.bbox_width),
            height=int(identity.bbox_height),
        )

    def _to_details(self, model: MergeSuggestionModel) -> MergeSuggestionDetails:
        cluster_a: IdentityCluster | None = model.cluster_a
        cluster_b: IdentityCluster | None = model.cluster_b
        rep_a: MediaIdentity | None = cluster_a.representative_identity if cluster_a else None
        rep_b: MediaIdentity | None = cluster_b.representative_identity if cluster_b else None
        details_a = _build_cluster_details(cluster_a, rep_a, self._build_bbox)
        details_b = _build_cluster_details(cluster_b, rep_b, self._build_bbox)

        return MergeSuggestionDetails(
            id=str(model.id),
            cluster_a_id=str(model.cluster_a_id),
            cluster_b_id=str(model.cluster_b_id),
            similarity=float(model.similarity),
            status=str(model.resolution),
            confidence_score=float(model.confidence_score) if model.confidence_score is not None else None,
            created_at=model.created_at,
            expires_at=model.expires_at,
            source_job_id=str(model.source_job_id) if model.source_job_id is not None else None,
            cluster_a_label=details_a["label"],
            cluster_b_label=details_b["label"],
            cluster_a_identity_count=details_a["identity_count"],
            cluster_b_identity_count=details_b["identity_count"],
            cluster_a_representative_media_id=details_a["representative_media_id"],
            cluster_a_representative_media_url=details_a["representative_media_url"],
            cluster_a_representative_bbox=details_a["representative_bbox"],
            cluster_b_representative_media_id=details_b["representative_media_id"],
            cluster_b_representative_media_url=details_b["representative_media_url"],
            cluster_b_representative_bbox=details_b["representative_bbox"],
            survivor_cluster_id=str(model.survivor_cluster_id) if model.survivor_cluster_id is not None else None,
        )


def _build_cluster_details(
    cluster: IdentityCluster | None,
    rep: MediaIdentity | None,
    build_bbox: Callable[[MediaIdentity | None], FaceBox | None],
) -> dict:
    """Extract common cluster detail fields for merge suggestion."""
    return {
        "label": cluster.label if cluster else None,
        "identity_count": int(cluster.identity_count) if cluster and cluster.identity_count is not None else None,
        "representative_media_id": int(rep.media_id) if rep and rep.media_id is not None else None,
        "representative_media_url": rep.media_url if rep else None,
        "representative_bbox": build_bbox(rep),
    }


def _canonical_pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    if a.int <= b.int:
        return a, b
    return b, a


__all__ = ["SqlAlchemyMergeSuggestionRepository"]
