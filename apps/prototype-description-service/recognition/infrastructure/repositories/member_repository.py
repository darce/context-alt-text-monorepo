"""
SQLAlchemy-backed implementation of MemberRepository.

Scaffolded for Phase 5 persistence work.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity
from db.settings import get_database_settings
from recognition.domain.repositories import IdentityMember, MemberRepository

_DB_SETTINGS = get_database_settings()


def _clamp_similarity(value: float) -> float:
    """Clamp similarity to [0.0, 1.0] range to satisfy DB constraint.

    Floating-point operations can produce values slightly outside this range
    (e.g., 1.0000001 from cosine similarity), which violates the DB check constraint.
    """
    return max(0.0, min(1.0, value))


class SqlAlchemyMemberRepository(MemberRepository):
    """Persist cluster members using an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def get_by_cluster(self, cluster_id: str) -> list[IdentityMember]:
        """Fetch all members in a cluster."""
        stmt: Select[tuple[MemberModel]] = (
            select(MemberModel)
            .where(MemberModel.cluster_id == _coerce_uuid(cluster_id))
            .where(MemberModel.tenant_id == _coerce_uuid(self._tenant_id))
            .order_by(MemberModel.assigned_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(model) for model in result.scalars().all()]

    async def add_member(self, cluster_id: str, identity_id: str, similarity: float) -> IdentityMember:
        """Add a single cluster member."""
        tenant_uuid = _coerce_uuid(self._tenant_id)
        cluster_uuid = _coerce_uuid(cluster_id)
        identity_uuid = _coerce_uuid(identity_id)
        if tenant_uuid is None or cluster_uuid is None or identity_uuid is None:
            raise ValueError("tenant_id, cluster_id, and identity_id must be valid UUID-compatible strings")
        await _ensure_media_identity(self._session, tenant_uuid, identity_uuid)

        model = MemberModel(
            tenant_id=tenant_uuid,
            cluster_id=cluster_uuid,
            identity_id=identity_uuid,
            similarity=_clamp_similarity(similarity),
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def add_member_if_not_exists(
        self, cluster_id: str, identity_id: str, similarity: float
    ) -> IdentityMember | None:
        """Add a member only if not already in this cluster.

        Returns the member if created, None if already exists.
        This prevents duplicate key errors when retrying assignments.
        """
        tenant_uuid = _coerce_uuid(self._tenant_id)
        cluster_uuid = _coerce_uuid(cluster_id)
        identity_uuid = _coerce_uuid(identity_id)
        if tenant_uuid is None or cluster_uuid is None or identity_uuid is None:
            raise ValueError("tenant_id, cluster_id, and identity_id must be valid UUID-compatible strings")

        # Check if already a member of this specific cluster
        stmt = (
            select(MemberModel)
            .where(MemberModel.tenant_id == tenant_uuid)
            .where(MemberModel.cluster_id == cluster_uuid)
            .where(MemberModel.identity_id == identity_uuid)
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            return None  # Already a member

        return await self.add_member(cluster_id, identity_id, similarity)

    async def bulk_add_members(self, cluster_id: str, members) -> list[IdentityMember]:
        """Bulk insert members."""
        if not members:
            return []

        tenant_uuid = _coerce_uuid(self._tenant_id)
        cluster_uuid = _coerce_uuid(cluster_id)
        if tenant_uuid is None or cluster_uuid is None:
            raise ValueError("tenant_id and cluster_id must be valid UUID-compatible strings")

        for member in members:
            identity_uuid = _coerce_uuid(member.identity_id)
            if identity_uuid is None:
                raise ValueError("identity_id must be a valid UUID-compatible string")
            await _ensure_media_identity(self._session, tenant_uuid, identity_uuid)

        models = [
            MemberModel(
                tenant_id=tenant_uuid,
                cluster_id=cluster_uuid,
                identity_id=_coerce_uuid(member.identity_id),
                similarity=_clamp_similarity(member.similarity),
            )
            for member in members
        ]
        self._session.add_all(models)
        await self._session.flush()
        for model in models:
            await self._session.refresh(model)
        return [self._to_domain(model) for model in models]

    async def move_members(self, source_cluster_id: str, target_cluster_id: str) -> int:
        """Reassign all members from a source cluster to a target cluster.

        Uses a single bulk UPDATE statement to prevent deadlocks when
        concurrent merges affect overlapping members.
        """
        from sqlalchemy import update

        tenant_uuid = _coerce_uuid(self._tenant_id)
        source_uuid = _coerce_uuid(source_cluster_id)
        target_uuid = _coerce_uuid(target_cluster_id)
        if tenant_uuid is None or source_uuid is None or target_uuid is None:
            raise ValueError("tenant_id, source_cluster_id, and target_cluster_id must be valid UUIDs")

        # Use a single UPDATE statement for atomicity and deadlock prevention
        stmt = (
            update(MemberModel)
            .where(MemberModel.cluster_id == source_uuid)
            .where(MemberModel.tenant_id == tenant_uuid)
            .values(cluster_id=target_uuid)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount)  # type: ignore[attr-defined]

    async def remove_member(self, member_id: str) -> None:
        """Remove a member."""
        stmt = select(MemberModel).where(MemberModel.id == _coerce_uuid(member_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()

    async def get_by_identity_id(self, identity_id: str) -> list[IdentityMember]:
        """Fetch all member records for an identity (usually 0 or 1)."""
        tenant_uuid = _coerce_uuid(self._tenant_id)
        identity_uuid = _coerce_uuid(identity_id)
        if tenant_uuid is None or identity_uuid is None:
            return []

        stmt: Select[tuple[MemberModel]] = (
            select(MemberModel)
            .where(MemberModel.identity_id == identity_uuid)
            .where(MemberModel.tenant_id == tenant_uuid)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(m) for m in result.scalars().all()]

    async def remove_by_identity_id(self, identity_id: str) -> bool:
        """Remove member record(s) for an identity. Returns True if any were removed."""
        tenant_uuid = _coerce_uuid(self._tenant_id)
        identity_uuid = _coerce_uuid(identity_id)
        if tenant_uuid is None or identity_uuid is None:
            return False

        stmt: Select[tuple[MemberModel]] = (
            select(MemberModel)
            .where(MemberModel.identity_id == identity_uuid)
            .where(MemberModel.tenant_id == tenant_uuid)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        removed = False
        for model in models:
            await self._session.delete(model)
            removed = True
        if removed:
            await self._session.flush()
        return removed

    def _to_domain(self, model: MemberModel) -> IdentityMember:
        return IdentityMember(
            id=str(model.id),
            cluster_id=str(model.cluster_id),
            identity_id=str(model.identity_id),
            similarity=model.similarity,
            tenant_id=str(model.tenant_id) if model.tenant_id else None,
            assigned_at=model.assigned_at if isinstance(model.assigned_at, datetime) else None,
        )


def _coerce_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert string identifiers to UUID objects."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_URL, str(value))


async def _ensure_media_identity(session: AsyncSession, tenant_id: uuid.UUID, identity_id: uuid.UUID) -> None:
    """Create a placeholder media identity if one doesn't exist."""
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
