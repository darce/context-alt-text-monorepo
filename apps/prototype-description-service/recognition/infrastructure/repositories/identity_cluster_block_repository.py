"""
SQLAlchemy-backed implementation of IdentityClusterBlockRepository.

Scaffolded for curation block persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusterBlock as IdentityClusterBlockModel
from recognition.domain.repositories import IdentityClusterBlock, IdentityClusterBlockRepository
from recognition.infrastructure.repositories._helpers import coerce_uuid as _coerce_uuid


class SqlAlchemyIdentityClusterBlockRepository(IdentityClusterBlockRepository):
    """Persist identity-cluster blocks using an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def add_block(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        blocked_cluster_id: str,
        reason: str | None = None,
        created_by_user_id: int | None = None,
        expires_at: datetime | None = None,
    ) -> IdentityClusterBlock:
        """Persist a new block preventing auto-assignment."""
        tenant_uuid = _coerce_uuid(tenant_id)
        identity_uuid = _coerce_uuid(identity_id)
        blocked_uuid = _coerce_uuid(blocked_cluster_id)
        if not tenant_uuid or not identity_uuid or not blocked_uuid:
            raise ValueError("tenant_id, identity_id, and blocked_cluster_id must be valid UUID-compatible strings")

        # Type narrowing for mypy
        assert tenant_uuid is not None and identity_uuid is not None and blocked_uuid is not None

        now = datetime.now(tz=UTC)
        stmt = (
            select(IdentityClusterBlockModel)
            .where(IdentityClusterBlockModel.tenant_id == tenant_uuid)
            .where(IdentityClusterBlockModel.identity_id == identity_uuid)
            .where(IdentityClusterBlockModel.blocked_cluster_id == blocked_uuid)
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            if existing.expires_at and existing.expires_at <= now:
                await self._session.delete(existing)
                await self._session.flush()
            else:
                return self._to_domain(existing)

        model = IdentityClusterBlockModel(
            tenant_id=tenant_uuid,
            identity_id=identity_uuid,
            blocked_cluster_id=blocked_uuid,
            reason=reason or "manual_removal",
            created_by_user_id=created_by_user_id,
            expires_at=expires_at,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def remove_block(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        blocked_cluster_id: str,
    ) -> bool:
        """Remove a block. Returns True if a block was removed."""
        tenant_uuid = _coerce_uuid(tenant_id)
        identity_uuid = _coerce_uuid(identity_id)
        blocked_uuid = _coerce_uuid(blocked_cluster_id)
        if not tenant_uuid or not identity_uuid or not blocked_uuid:
            return False

        stmt: Select[tuple[IdentityClusterBlockModel]] = (
            select(IdentityClusterBlockModel)
            .where(IdentityClusterBlockModel.tenant_id == tenant_uuid)
            .where(IdentityClusterBlockModel.identity_id == identity_uuid)
            .where(IdentityClusterBlockModel.blocked_cluster_id == blocked_uuid)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    async def get_blocks_for_identity(
        self,
        *,
        tenant_id: str,
        identity_id: str,
    ) -> list[IdentityClusterBlock]:
        """List all blocks for an identity in a tenant."""
        tenant_uuid = _coerce_uuid(tenant_id)
        identity_uuid = _coerce_uuid(identity_id)
        if not tenant_uuid or not identity_uuid:
            return []

        now = datetime.now(tz=UTC)
        stmt: Select[tuple[IdentityClusterBlockModel]] = (
            select(IdentityClusterBlockModel)
            .where(IdentityClusterBlockModel.tenant_id == tenant_uuid)
            .where(IdentityClusterBlockModel.identity_id == identity_uuid)
            .where((IdentityClusterBlockModel.expires_at.is_(None)) | (IdentityClusterBlockModel.expires_at > now))
            .order_by(IdentityClusterBlockModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(model) for model in result.scalars().all()]

    async def is_blocked(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        cluster_id: str,
    ) -> bool:
        """Return True if the identity is blocked from the given cluster."""
        tenant_uuid = _coerce_uuid(tenant_id)
        identity_uuid = _coerce_uuid(identity_id)
        cluster_uuid = _coerce_uuid(cluster_id)
        if not tenant_uuid or not identity_uuid or not cluster_uuid:
            return False

        now = datetime.now(tz=UTC)
        stmt = (
            select(IdentityClusterBlockModel.id)
            .where(IdentityClusterBlockModel.tenant_id == tenant_uuid)
            .where(IdentityClusterBlockModel.identity_id == identity_uuid)
            .where(IdentityClusterBlockModel.blocked_cluster_id == cluster_uuid)
            .where((IdentityClusterBlockModel.expires_at.is_(None)) | (IdentityClusterBlockModel.expires_at > now))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    def _to_domain(self, model: IdentityClusterBlockModel) -> IdentityClusterBlock:
        """Convert ORM model to domain object."""
        return IdentityClusterBlock(
            id=str(model.id),
            tenant_id=str(model.tenant_id),
            identity_id=str(model.identity_id),
            blocked_cluster_id=str(model.blocked_cluster_id),
            reason=model.reason,
            created_at=model.created_at,
            created_by_user_id=model.created_by_user_id,
            expires_at=model.expires_at,
        )


__all__ = ["SqlAlchemyIdentityClusterBlockRepository"]
