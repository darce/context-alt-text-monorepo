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
from sqlalchemy.orm import joinedload

from db.models import IdentityCluster, IdentityMember, MediaIdentity
from db.models import IdentitySuggestion as SuggestionModel
from db.settings import get_database_settings
from recognition.application.suggestions.label_inference import infer_suggested_label
from recognition.domain.repositories import SuggestionCreateData, SuggestionRepository
from recognition.domain.suggestion import (
    AssignmentSuggestion,
    FaceBox,
    SuggestionDetails,
    SuggestionStatus,
)

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
            cluster_label=cluster.label if cluster else None,
            cluster_identity_count=int(cluster.identity_count)
            if cluster and cluster.identity_count is not None
            else None,
            identity_media_id=int(identity.media_id) if identity and identity.media_id is not None else None,
            identity_media_url=identity.media_url if identity else None,
            identity_thumbnail_url=identity.thumbnail_url if identity else None,
            identity_bbox=self._build_bbox(identity),
            representative_media_id=int(representative.media_id)
            if representative and representative.media_id is not None
            else None,
            representative_media_url=representative.media_url if representative else None,
            representative_thumbnail_url=representative.thumbnail_url if representative else None,
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

        Returns suggestions for both labeled and unlabeled clusters. Unlabeled clusters
        remain actionable because callers can compute a best-effort suggested label
        (with provenance) at read time for UI copy.
        """
        stmt: Select[tuple[SuggestionModel]] = (
            select(SuggestionModel)
            .join(SuggestionModel.suggested_cluster)
            .where(SuggestionModel.tenant_id == _coerce_uuid(tenant_id))
            .where(SuggestionModel.resolution == SuggestionStatus.PENDING.value)
            .order_by(SuggestionModel.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(
                joinedload(SuggestionModel.identity),
                joinedload(SuggestionModel.suggested_cluster).joinedload(IdentityCluster.representative_identity),
            )
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().unique().all()

        # Collect cluster IDs to fetch thumbnails
        cluster_ids = [row.suggested_cluster_id for row in rows]
        thumbnails_map: dict[uuid.UUID, list[str]] = {}

        if cluster_ids:
            # Fetch up to 4 thumbnails per cluster
            # Using rank/partition is expensive/complex in ORM, so we fetch a few more and filter in Python
            # or simplify: just fetch random 4 per cluster?
            # Better: fetch last 4 added members with thumbnails
            # Since we iterate clusters, let's do a loop if it's small (50), or a window query.
            # Window query example:
            from sqlalchemy import func

            # Simple approach: Fetch all members for these clusters with limit? complex.
            # Let's execute one query per cluster? 50 queries is bad.
            # Let's try to fetch recent members for these clusters.
            # Optimization: User requested "Face Grid".
            # We can use a window function request or just fetch ALL members for these 50 clusters if they are small.
            # Clusters can be large.
            # Let's use a LATERAL JOIN equivalent or a simple IN query limited by total count?
            # Or just fetch representative + 3 random members?
            # Let's assume fetching `limit=4` members per cluster is desired.
            pass

            # Efficient approach: Use SQL partition/row_number
            # But for MVP speed, and since limit is 50, let's just fetch IDs and thumbnails in one IN query
            # and limit 9 per cluster?
            # We can define a helper or just query:
            # SELECT cluster_id, thumbnail_url FROM ... WHERE cluster_id IN (...) AND thumbnail_url IS NOT NULL
            # Then group in python. If a cluster has 1000 members, querying all is bad.
            # So we SHOULD use partitioning.

            # SQLite (test env) supports window functions. Postgres does too.
            subq = (
                select(
                    IdentityMember.cluster_id,
                    MediaIdentity.thumbnail_url,
                    func.row_number()
                    .over(partition_by=IdentityMember.cluster_id, order_by=MediaIdentity.created_at.desc())
                    .label("rn"),
                )
                .join(MediaIdentity, IdentityMember.identity_id == MediaIdentity.id)
                .where(IdentityMember.cluster_id.in_(cluster_ids))
                .where(MediaIdentity.thumbnail_url.isnot(None))
            ).subquery()

            thumb_stmt = (
                select(subq.c.cluster_id, subq.c.thumbnail_url).where(
                    subq.c.rn <= 9
                )  # Fetch 9 for 3x3 grid or just 4 for 2x2. let's get 9.
            )
            thumb_res = await self._session.execute(thumb_stmt)
            for cid, url in thumb_res.all():
                if cid not in thumbnails_map:
                    thumbnails_map[cid] = []
                thumbnails_map[cid].append(url)

        details_list = []
        for model in rows:
            details = self._to_details(model)
            if details.cluster_id:
                # Add thumbnails (filter out representative if desired, or keep all)
                # Ensure UUID string key matching
                cid_uuid = uuid.UUID(details.cluster_id)
                details.cluster_thumbnails = thumbnails_map.get(cid_uuid, [])

            # If cluster is unlabeled, try to infer a label
            if not details.cluster_label:
                inferred = await infer_suggested_label(
                    tenant_id=tenant_id, cluster_id=details.cluster_id, session=self._session
                )
                if inferred:
                    details.suggested_label = inferred.label
                    details.suggested_label_source = inferred.source
                    details.suggested_label_confidence = inferred.confidence

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
