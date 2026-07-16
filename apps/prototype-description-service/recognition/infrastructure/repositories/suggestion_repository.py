"""
SQLAlchemy-backed implementation of SuggestionRepository.

Scaffold for Phase 7.3 suggestion persistence (TDD first).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Select, and_, exists, func, nulls_last, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from db.models import IdentityCluster, IdentityClusterRepresentative, IdentityMember, MediaIdentity
from db.models import IdentitySuggestion as SuggestionModel
from recognition.domain.repositories import SuggestionCreateData, SuggestionRepository
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus
from recognition.domain.suggestion_details import FaceBox, SuggestionDetails
from recognition.infrastructure.repositories._helpers import coerce_uuid as _coerce_uuid


def _clamp_similarity(value: float) -> float:
    """Clamp similarity to [0.0, 1.0] range to satisfy DB constraint.

    Floating-point operations can produce values slightly outside this range
    (e.g., 1.0000001 from cosine similarity), which violates the DB check constraint.
    """
    return max(0.0, min(1.0, value))


class SqlAlchemySuggestionRepository(SuggestionRepository):
    """Persist assignment suggestions using an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, tenant_id: str, payload: SuggestionCreateData) -> AssignmentSuggestion:
        """Persist a new suggestion row."""
        return await self._upsert_suggestion(
            tenant_id=tenant_id,
            payload=payload,
            touch_refreshed_at_on_update=False,
        )

    async def update_scores(
        self,
        tenant_id: str,
        suggestion_id: str,
        *,
        representative_similarity: float,
        member_similarity: float,
        confidence_score: float,
    ) -> AssignmentSuggestion:
        """Update similarity/confidence scores for an existing suggestion row."""
        tenant_uuid = _coerce_uuid(tenant_id)
        suggestion_uuid = _coerce_uuid(suggestion_id)
        if not tenant_uuid or not suggestion_uuid:
            raise ValueError("tenant_id and suggestion_id must be valid UUID-compatible strings")

        # Type narrowing for mypy
        assert tenant_uuid is not None and suggestion_uuid is not None

        stmt = (
            select(SuggestionModel)
            .where(SuggestionModel.tenant_id == tenant_uuid)
            .where(SuggestionModel.id == suggestion_uuid)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise ValueError(f"Suggestion not found: {suggestion_id}")

        # Only update pending suggestions to preserve historical resolved scores.
        if model.resolution != SuggestionStatus.PENDING.value:
            return self._to_domain(model)

        model.representative_similarity = _clamp_similarity(representative_similarity)
        model.avg_member_similarity = _clamp_similarity(member_similarity)
        model.confidence_score = _clamp_similarity(confidence_score)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def get_by_identity(self, tenant_id: str, identity_id: str) -> list[AssignmentSuggestion]:
        """Fetch pending suggestions for an identity, scoped to tenant.

        Only returns suggestions with status 'pending' - rejected/accepted suggestions
        should not be shown to users.
        """
        stmt: Select[tuple[SuggestionModel]] = (
            select(SuggestionModel)
            .where(SuggestionModel.tenant_id == _coerce_uuid(tenant_id))
            .where(SuggestionModel.identity_id == _coerce_uuid(identity_id))
            .where(SuggestionModel.resolution == SuggestionStatus.PENDING.value)
            .order_by(SuggestionModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def list_for_identities(
        self,
        tenant_id: str,
        identity_ids: Sequence[str],
        *,
        top_k: int,
    ) -> list[SuggestionDetails]:
        """Top-k pending labeled-cluster suggestions per identity in one windowed query.

        Filter parity with the per-card route is literal: pending status + truthy
        cluster label only (auto-labels like ``cluster-1234`` pass; ``user_confirmed``
        is NOT required). The filter is applied inside the window so ranks are
        computed over eligible rows only — an identity whose highest-similarity
        suggestion targets an unlabeled cluster still resolves to its next labeled one.

        ``ROW_NUMBER`` is used (never ``DISTINCT ON``: SQLAlchemy silently drops the
        ``ON`` clause under SQLite) and is portable across sqlite+aiosqlite and Postgres.
        """
        tenant_uuid = _coerce_uuid(tenant_id)
        identity_uuids = [item for item in (_coerce_uuid(value) for value in identity_ids) if item is not None]
        if tenant_uuid is None or not identity_uuids or top_k < 1:
            return []

        ranked = (
            select(
                SuggestionModel.id.label("suggestion_id"),
                func.row_number()
                .over(
                    partition_by=SuggestionModel.identity_id,
                    order_by=(
                        SuggestionModel.representative_similarity.desc(),
                        SuggestionModel.created_at.desc(),
                    ),
                )
                .label("suggestion_rank"),
            )
            .join(IdentityCluster, SuggestionModel.suggested_cluster_id == IdentityCluster.id)
            .where(SuggestionModel.tenant_id == tenant_uuid)
            .where(SuggestionModel.identity_id.in_(identity_uuids))
            .where(SuggestionModel.resolution == SuggestionStatus.PENDING.value)
            .where(IdentityCluster.label.is_not(None))
            .where(IdentityCluster.label != "")
            .subquery()
        )

        stmt = (
            select(SuggestionModel)
            .join(ranked, SuggestionModel.id == ranked.c.suggestion_id)
            .where(ranked.c.suggestion_rank <= top_k)
            .options(joinedload(SuggestionModel.suggested_cluster))
            .order_by(SuggestionModel.identity_id, ranked.c.suggestion_rank)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()

        details: list[SuggestionDetails] = []
        for model in models:
            cluster: IdentityCluster | None = model.suggested_cluster
            details.append(
                SuggestionDetails(
                    id=str(model.id),
                    identity_id=str(model.identity_id),
                    cluster_id=str(model.suggested_cluster_id),
                    representative_similarity=float(model.representative_similarity),
                    member_similarity=float(model.avg_member_similarity),
                    status=str(model.resolution),
                    confidence_score=float(model.confidence_score) if model.confidence_score is not None else None,
                    expires_at=model.expires_at,
                    source_job_id=str(model.source_job_id) if model.source_job_id is not None else None,
                    cluster_label=cluster.label if cluster else None,
                    cluster_identity_count=int(cluster.identity_count)
                    if cluster and cluster.identity_count is not None
                    else None,
                )
            )
        return details

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

    def _to_details(self, model: SuggestionModel) -> SuggestionDetails:
        identity: MediaIdentity | None = model.identity
        cluster: IdentityCluster | None = model.suggested_cluster
        representative: MediaIdentity | None = cluster.representative_identity if cluster else None

        return SuggestionDetails(
            id=str(model.id),
            identity_id=str(model.identity_id),
            cluster_id=str(model.suggested_cluster_id),
            representative_similarity=float(model.representative_similarity),
            member_similarity=float(model.avg_member_similarity),
            status=str(model.resolution),
            confidence_score=float(model.confidence_score) if model.confidence_score is not None else None,
            expires_at=model.expires_at,
            source_job_id=str(model.source_job_id) if model.source_job_id is not None else None,
            cluster_label=cluster.label if cluster else None,
            cluster_identity_count=int(cluster.identity_count)
            if cluster and cluster.identity_count is not None
            else None,
            identity_media_id=int(identity.media_id) if identity and identity.media_id is not None else None,
            identity_media_url=identity.media_url if identity else None,
            identity_bbox=self._build_bbox(identity),
            representative_media_id=int(representative.media_id)
            if representative and representative.media_id is not None
            else None,
            representative_media_url=representative.media_url if representative else None,
            representative_bbox=self._build_bbox(representative),
        )

    async def get_by_cluster(self, tenant_id: str, cluster_id: str) -> list[AssignmentSuggestion]:
        """Fetch pending suggestions for a cluster, scoped to tenant.

        Only returns suggestions with status 'pending' - rejected/accepted suggestions
        should not be shown to users.
        """
        stmt: Select[tuple[SuggestionModel]] = (
            select(SuggestionModel)
            .where(SuggestionModel.tenant_id == _coerce_uuid(tenant_id))
            .where(SuggestionModel.suggested_cluster_id == _coerce_uuid(cluster_id))
            .where(SuggestionModel.resolution == SuggestionStatus.PENDING.value)
            .order_by(SuggestionModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def update_status(self, tenant_id: str, suggestion_id: str, status: SuggestionStatus) -> AssignmentSuggestion:
        """Update the resolution of a suggestion."""
        stmt = (
            select(SuggestionModel)
            .where(SuggestionModel.id == _coerce_uuid(suggestion_id))
            .where(SuggestionModel.tenant_id == _coerce_uuid(tenant_id))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise ValueError(f"Suggestion not found: {suggestion_id}")

        model.resolution = status.value
        model.resolved_at = datetime.now(tz=UTC)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def list_pending(self, tenant_id: str, limit: int, offset: int) -> list[AssignmentSuggestion]:
        """Return pending suggestions for a tenant with paging."""
        stmt: Select[tuple[SuggestionModel]] = (
            select(SuggestionModel)
            .where(SuggestionModel.tenant_id == _coerce_uuid(tenant_id))
            .where(SuggestionModel.resolution == SuggestionStatus.PENDING.value)
            .order_by(SuggestionModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def list_pending_with_details(self, tenant_id: str, limit: int, offset: int) -> list[SuggestionDetails]:
        """Return pending suggestions with identity + cluster details.

        Only returns suggestions targeting user-confirmed clusters with human labels.
        Legacy suggestions targeting unconfirmed clusters remain in DB but are filtered
        out at query time. When a cluster becomes confirmed, its suggestions become
        eligible again.

        Also includes stale auto-accepted rows where the identity was never moved into
        the suggested cluster. These rows are normalized back to `pending` in response
        details so users can explicitly confirm or reject them.
        """
        stale_accepted_without_membership = and_(
            SuggestionModel.resolution == SuggestionStatus.ACCEPTED.value,
            ~exists(
                select(1)
                .select_from(IdentityMember)
                .where(IdentityMember.identity_id == SuggestionModel.identity_id)
                .where(IdentityMember.cluster_id == SuggestionModel.suggested_cluster_id)
            ),
        )

        stmt: Select[tuple[SuggestionModel]] = (
            select(SuggestionModel)
            .join(SuggestionModel.suggested_cluster)
            .where(SuggestionModel.tenant_id == _coerce_uuid(tenant_id))
            .where(
                or_(
                    SuggestionModel.resolution == SuggestionStatus.PENDING.value,
                    stale_accepted_without_membership,
                )
            )
            # v4.12.0: Filter to confirmed clusters only
            .where(IdentityCluster.user_confirmed.is_(True))
            .where(IdentityCluster.label.is_not(None))
            .where(~IdentityCluster.label.startswith("cluster-"))
            .order_by(nulls_last(SuggestionModel.confidence_score.desc()), SuggestionModel.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(
                joinedload(SuggestionModel.identity),
                joinedload(SuggestionModel.suggested_cluster).joinedload(IdentityCluster.representative_identity),
            )
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().unique().all()

        details_list = []
        for model in rows:
            details = self._to_details(model)
            if model.resolution == SuggestionStatus.ACCEPTED.value:
                details.status = SuggestionStatus.PENDING.value

            details_list.append(details)

        return details_list

    async def bulk_update_status(
        self,
        tenant_id: str,
        suggestion_ids: Sequence[str],
        status: SuggestionStatus,
    ) -> int:
        """Update status for multiple suggestions in one call.

        Args:
            tenant_id: Tenant UUID string.
            suggestion_ids: Suggestion UUIDs to update.
            status: Status to apply.

        Returns:
            Count of suggestions updated.
        """
        if not suggestion_ids:
            return 0
        tenant_uuid = _coerce_uuid(tenant_id)
        if not tenant_uuid:
            return 0
        ids = [_coerce_uuid(item) for item in suggestion_ids]
        suggestion_uuids = [item for item in ids if item is not None]
        if not suggestion_uuids:
            return 0
        stmt = (
            update(SuggestionModel)
            .where(SuggestionModel.tenant_id == tenant_uuid)
            .where(SuggestionModel.id.in_(suggestion_uuids))
            .values(
                resolution=status.value,
                resolved_at=datetime.now(tz=UTC),
            )
        )
        result = await self._session.execute(stmt)
        rowcount = int(getattr(result, "rowcount", 0) or 0)
        await self._session.flush()
        return rowcount

    async def upsert_by_identity_cluster(
        self,
        tenant_id: str,
        payload: SuggestionCreateData,
    ) -> AssignmentSuggestion:
        """Create or update a suggestion for the identity+cluster pair.

        Args:
            tenant_id: Tenant UUID string.
            payload: Suggestion data (identity, cluster, scores).

        Returns:
            The created or updated suggestion.
        """
        return await self._upsert_suggestion(
            tenant_id=tenant_id,
            payload=payload,
            touch_refreshed_at_on_update=True,
        )

    async def _upsert_suggestion(
        self,
        *,
        tenant_id: str,
        payload: SuggestionCreateData,
        touch_refreshed_at_on_update: bool,
    ) -> AssignmentSuggestion:
        """Create-or-update path shared by `create` and `upsert_by_identity_cluster`."""
        tenant_uuid = _coerce_uuid(tenant_id)
        identity_uuid = _coerce_uuid(payload.identity_id)
        cluster_uuid = _coerce_uuid(payload.cluster_id)
        if not all([tenant_uuid, identity_uuid, cluster_uuid]):
            raise ValueError("tenant_id, identity_id, and cluster_id must be valid UUID-compatible strings")

        assert tenant_uuid is not None and identity_uuid is not None and cluster_uuid is not None

        existing_stmt = (
            select(SuggestionModel)
            .where(SuggestionModel.tenant_id == tenant_uuid)
            .where(SuggestionModel.identity_id == identity_uuid)
            .where(SuggestionModel.suggested_cluster_id == cluster_uuid)
            .order_by(SuggestionModel.evidence_generation.desc(), SuggestionModel.created_at.desc())
            .limit(1)
        )
        existing_result = await self._session.execute(existing_stmt)
        existing_suggestion = existing_result.scalar_one_or_none()

        if existing_suggestion:
            if existing_suggestion.resolution == SuggestionStatus.PENDING.value:
                existing_suggestion.representative_similarity = _clamp_similarity(payload.representative_similarity)
                existing_suggestion.avg_member_similarity = _clamp_similarity(payload.member_similarity)
                existing_suggestion.confidence_score = _clamp_similarity(payload.confidence_score)
                if touch_refreshed_at_on_update:
                    existing_suggestion.refreshed_at = payload.refreshed_at or datetime.now(tz=UTC)
                elif payload.refreshed_at is not None:
                    existing_suggestion.refreshed_at = payload.refreshed_at
                if payload.expires_at is not None:
                    existing_suggestion.expires_at = payload.expires_at
                if payload.source_job_id is not None:
                    existing_suggestion.source_job_id = _coerce_uuid(payload.source_job_id)
                if payload.source:
                    existing_suggestion.source = payload.source
                await self._session.flush()
                await self._session.refresh(existing_suggestion)
                return self._to_domain(existing_suggestion)

            if existing_suggestion.resolution == SuggestionStatus.REJECTED.value:
                resolved_at = existing_suggestion.resolved_at
                if resolved_at is None:
                    return self._to_domain(existing_suggestion)

                if not await self._cluster_context_changed(cluster_uuid, resolved_at):
                    return self._to_domain(existing_suggestion)

                next_generation = await self._next_evidence_generation(
                    tenant_uuid, identity_uuid, cluster_uuid, existing_suggestion.evidence_generation
                )
                model = SuggestionModel(
                    tenant_id=tenant_uuid,
                    identity_id=identity_uuid,
                    suggested_cluster_id=cluster_uuid,
                    representative_similarity=_clamp_similarity(payload.representative_similarity),
                    avg_member_similarity=_clamp_similarity(payload.member_similarity),
                    confidence_score=_clamp_similarity(payload.confidence_score),
                    resolution=SuggestionStatus.PENDING.value,
                    refreshed_at=payload.refreshed_at,
                    expires_at=payload.expires_at,
                    source_job_id=_coerce_uuid(payload.source_job_id),
                    source=payload.source or "backfill_new_evidence",
                    evidence_generation=next_generation,
                )
                self._session.add(model)
                await self._session.flush()
                await self._session.refresh(model)
                return self._to_domain(model)

            return self._to_domain(existing_suggestion)

        model = SuggestionModel(
            tenant_id=tenant_uuid,
            identity_id=identity_uuid,
            suggested_cluster_id=cluster_uuid,
            representative_similarity=_clamp_similarity(payload.representative_similarity),
            avg_member_similarity=_clamp_similarity(payload.member_similarity),
            confidence_score=_clamp_similarity(payload.confidence_score),
            resolution=SuggestionStatus.PENDING.value,
            refreshed_at=payload.refreshed_at,
            expires_at=payload.expires_at,
            source_job_id=_coerce_uuid(payload.source_job_id),
            source=payload.source,
            evidence_generation=0,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    def _to_domain(self, model: SuggestionModel) -> AssignmentSuggestion:
        """Convert ORM model to domain object."""
        return AssignmentSuggestion(
            id=str(model.id),
            identity_id=str(model.identity_id),
            cluster_id=str(model.suggested_cluster_id),
            representative_similarity=model.representative_similarity,
            member_similarity=model.avg_member_similarity,
            status=SuggestionStatus(model.resolution),
            evidence_generation=int(getattr(model, "evidence_generation", 0) or 0),
            confidence_score=float(model.confidence_score) if model.confidence_score is not None else None,
            created_at=model.created_at,
            expires_at=model.expires_at,
            source_job_id=str(model.source_job_id) if model.source_job_id is not None else None,
        )

    async def _next_evidence_generation(
        self,
        tenant_uuid: uuid.UUID,
        identity_uuid: uuid.UUID,
        cluster_uuid: uuid.UUID,
        current_generation: int,
    ) -> int:
        stmt = (
            select(func.max(SuggestionModel.evidence_generation))
            .where(SuggestionModel.tenant_id == tenant_uuid)
            .where(SuggestionModel.identity_id == identity_uuid)
            .where(SuggestionModel.suggested_cluster_id == cluster_uuid)
        )
        result = await self._session.execute(stmt)
        max_generation = result.scalar_one_or_none()
        if max_generation is None:
            return current_generation + 1
        return int(max_generation) + 1

    async def _cluster_context_changed(self, cluster_uuid: uuid.UUID, since: datetime) -> bool:
        """Return True if cluster evidence changed after the provided timestamp."""
        cluster_ts = await self._session.execute(
            select(IdentityCluster.updated_at).where(IdentityCluster.id == cluster_uuid)
        )
        rep_ts = await self._session.execute(
            select(func.max(IdentityClusterRepresentative.created_at)).where(
                IdentityClusterRepresentative.cluster_id == cluster_uuid
            )
        )
        member_ts = await self._session.execute(
            select(func.max(IdentityMember.assigned_at)).where(IdentityMember.cluster_id == cluster_uuid)
        )

        timestamps = [
            cluster_ts.scalar_one_or_none(),
            rep_ts.scalar_one_or_none(),
            member_ts.scalar_one_or_none(),
        ]
        latest = max([ts for ts in timestamps if ts is not None], default=None)
        if latest is None:
            return False

        def _to_utc_naive(value: datetime) -> datetime:
            if value.tzinfo is None:
                return value
            return value.astimezone(UTC).replace(tzinfo=None)

        return _to_utc_naive(latest) > _to_utc_naive(since)


__all__ = ["SqlAlchemySuggestionRepository"]
