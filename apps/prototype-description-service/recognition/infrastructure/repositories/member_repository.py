"""
SQLAlchemy-backed implementation of MemberRepository.

Scaffolded for Phase 5 persistence work.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from sqlalchemy import Select, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Insert

from db.models import IdentityMember as MemberModel
from recognition.domain.repositories import IdentityMember, MemberRepository
from recognition.infrastructure.repositories._helpers import coerce_uuid as _coerce_uuid
from recognition.infrastructure.repositories._helpers import ensure_media_identity as _ensure_media_identity
from recognition.shared.db.helpers import execute_dml, get_rowcount


def _clamp_similarity(value: float) -> float:
    """Clamp similarity to [0.0, 1.0] range to satisfy DB constraint.

    Floating-point operations can produce values slightly outside this range
    (e.g., 1.0000001 from cosine similarity), which violates the DB check constraint.
    """
    return max(0.0, min(1.0, value))


def _is_deadlock_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    if "deadlock detected" in message:
        return True
    orig = getattr(exc, "orig", None)
    return orig is not None and orig.__class__.__name__ == "DeadlockDetectedError"


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

        await _ensure_media_identity(self._session, tenant_uuid, identity_uuid)

        member_id = uuid.uuid4()
        values = {
            "id": member_id,
            "tenant_id": tenant_uuid,
            "cluster_id": cluster_uuid,
            "identity_id": identity_uuid,
            "similarity": _clamp_similarity(similarity),
        }
        bind = self._session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else None

        stmt: Insert
        if dialect_name == "postgresql":
            stmt = pg_insert(MemberModel).values(**values).on_conflict_do_nothing()
        elif dialect_name == "sqlite":
            stmt = sqlite_insert(MemberModel).values(**values).on_conflict_do_nothing()
        else:
            stmt = insert(MemberModel).values(**values)

        result = await execute_dml(self._session, stmt)
        if get_rowcount(result) == 0:
            return None

        model = await self._session.get(MemberModel, member_id)
        if model is None:
            return None
        return self._to_domain(model)

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

        Uses a single bulk UPDATE statement and retries on deadlocks when
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
        max_attempts = 3
        last_error: DBAPIError | None = None
        for attempt in range(max_attempts):
            try:
                result = await execute_dml(self._session, stmt)
                await self._session.flush()
                return get_rowcount(result)
            except DBAPIError as exc:
                last_error = exc
                if _is_deadlock_error(exc) and attempt < max_attempts - 1:
                    await self._session.rollback()
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise
        if last_error:
            raise last_error
        raise RuntimeError("Failed to move members after retries.")

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
