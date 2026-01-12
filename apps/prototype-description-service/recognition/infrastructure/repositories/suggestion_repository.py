"""
SQLAlchemy-backed implementation of SuggestionRepository.

Scaffold for Phase 7.3 suggestion persistence (TDD first).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentitySuggestion as SuggestionModel
from db.models import MediaIdentity
from db.settings import get_database_settings
from recognition.domain.repositories import SuggestionCreateData, SuggestionRepository
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus

_DB_SETTINGS = get_database_settings()


def _clamp_similarity(value: float) -> float:
    """Clamp similarity to [0.0, 1.0] range to satisfy DB constraint.

    Floating-point operations can produce values slightly outside this range
    (e.g., 1.0000001 from cosine similarity), which violates the DB check constraint.
    """
    return max(0.0, min(1.0, value))


class SqlAlchemySuggestionRepository(SuggestionRepository):
    """Persist assignment suggestions using an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def create(self, tenant_id: str, payload: SuggestionCreateData) -> AssignmentSuggestion:
        """Persist a new suggestion row."""
        tenant_uuid = _coerce_uuid(tenant_id)
        identity_uuid = _coerce_uuid(payload.identity_id)
        cluster_uuid = _coerce_uuid(payload.cluster_id)
        if not all([tenant_uuid, identity_uuid, cluster_uuid]):
            raise ValueError("tenant_id, identity_id, and cluster_id must be valid UUID-compatible strings")

        # Type narrowing for mypy
        assert tenant_uuid is not None and identity_uuid is not None and cluster_uuid is not None

        await _ensure_media_identity(self._session, tenant_uuid, identity_uuid)

        # Check for existing pending suggestion to avoid unique constraint violations
        existing_stmt = (
            select(SuggestionModel)
            .where(SuggestionModel.tenant_id == tenant_uuid)
            .where(SuggestionModel.identity_id == identity_uuid)
            .where(SuggestionModel.suggested_cluster_id == cluster_uuid)
        )
        existing_result = await self._session.execute(existing_stmt)
        existing_suggestion = existing_result.scalar_one_or_none()

        if existing_suggestion:
            # Upsert scoring fields for pending suggestions to keep UI similarity fresh.
            if existing_suggestion.resolution == SuggestionStatus.PENDING.value:
                existing_suggestion.representative_similarity = _clamp_similarity(payload.representative_similarity)
                existing_suggestion.avg_member_similarity = _clamp_similarity(payload.member_similarity)
                existing_suggestion.confidence_score = _clamp_similarity(payload.confidence_score)
                if payload.refreshed_at:
                    existing_suggestion.refreshed_at = payload.refreshed_at
                if payload.source:
                    existing_suggestion.source = payload.source
                await self._session.flush()
                await self._session.refresh(existing_suggestion)
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
            source=payload.source,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

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
        """Fetch suggestions for an identity, scoped to tenant."""
        stmt: Select[tuple[SuggestionModel]] = (
            select(SuggestionModel)
            .where(SuggestionModel.tenant_id == _coerce_uuid(tenant_id))
            .where(SuggestionModel.identity_id == _coerce_uuid(identity_id))
            .order_by(SuggestionModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def get_by_cluster(self, tenant_id: str, cluster_id: str) -> list[AssignmentSuggestion]:
        """Fetch suggestions for a cluster, scoped to tenant."""
        stmt: Select[tuple[SuggestionModel]] = (
            select(SuggestionModel)
            .where(SuggestionModel.tenant_id == _coerce_uuid(tenant_id))
            .where(SuggestionModel.suggested_cluster_id == _coerce_uuid(cluster_id))
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
        tenant_uuid = _coerce_uuid(tenant_id)
        identity_uuid = _coerce_uuid(payload.identity_id)
        cluster_uuid = _coerce_uuid(payload.cluster_id)
        if not all([tenant_uuid, identity_uuid, cluster_uuid]):
            raise ValueError("tenant_id, identity_id, and cluster_id must be valid UUID-compatible strings")

        assert tenant_uuid is not None and identity_uuid is not None and cluster_uuid is not None

        await _ensure_media_identity(self._session, tenant_uuid, identity_uuid)

        stmt = (
            select(SuggestionModel)
            .where(SuggestionModel.tenant_id == tenant_uuid)
            .where(SuggestionModel.identity_id == identity_uuid)
            .where(SuggestionModel.suggested_cluster_id == cluster_uuid)
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            if existing.resolution == SuggestionStatus.PENDING.value:
                existing.representative_similarity = _clamp_similarity(payload.representative_similarity)
                existing.avg_member_similarity = _clamp_similarity(payload.member_similarity)
                existing.confidence_score = _clamp_similarity(payload.confidence_score)
                existing.refreshed_at = payload.refreshed_at or datetime.now(tz=UTC)
                if payload.source:
                    existing.source = payload.source
                await self._session.flush()
                await self._session.refresh(existing)
            return self._to_domain(existing)

        model = SuggestionModel(
            tenant_id=tenant_uuid,
            identity_id=identity_uuid,
            suggested_cluster_id=cluster_uuid,
            representative_similarity=_clamp_similarity(payload.representative_similarity),
            avg_member_similarity=_clamp_similarity(payload.member_similarity),
            confidence_score=_clamp_similarity(payload.confidence_score),
            resolution=SuggestionStatus.PENDING.value,
            refreshed_at=payload.refreshed_at,
            source=payload.source,
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
            created_at=model.created_at,
        )


__all__ = ["SqlAlchemySuggestionRepository"]


def _coerce_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert string identifiers to UUID objects, tolerating short IDs."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_URL, str(value))


async def _ensure_media_identity(session: AsyncSession, tenant_id: uuid.UUID, identity_id: uuid.UUID) -> None:
    """Create placeholder media identity if it does not exist."""
    existing = await session.get(MediaIdentity, identity_id)
    if existing:
        return

    media = MediaIdentity(
        id=identity_id,
        tenant_id=tenant_id,
        media_id=abs(identity_id.int) % 1_000_000,
        media_url="http://example.test/media.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=[0.0] * _DB_SETTINGS.pgvector_dimension,
    )
    session.add(media)
    await session.flush()
    await session.refresh(media)
