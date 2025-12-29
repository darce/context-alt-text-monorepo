"""
SQLAlchemy implementation of IdentityConstraintRepository.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import insert, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Insert

from db.models import IdentityConstraint as ConstraintModel
from recognition.domain.constraints import (
    ConstraintSource,
    ConstraintType,
    IdentityConstraint,
    canonical_order,
)
from recognition.domain.repositories import IdentityConstraintRepository


class SqlAlchemyConstraintRepository(IdentityConstraintRepository):
    """PostgreSQL implementation of identity constraints using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _to_domain(self, model: ConstraintModel) -> IdentityConstraint:
        return IdentityConstraint(
            id=model.id,
            tenant_id=model.tenant_id,
            identity_a=model.identity_a,
            identity_b=model.identity_b,
            constraint_type=ConstraintType(model.constraint_type),
            source=ConstraintSource(model.source),
            created_at=model.created_at,
            created_by_user_id=model.created_by_user_id,
        )

    async def create_cannot_link(
        self,
        tenant_id: str,
        identity_a: str,
        identity_b: str,
        source: str,
        created_by_user_id: int | None = None,
    ) -> IdentityConstraint:
        """Create a new pairwise CANNOT_LINK constraint."""
        return await self.create(
            tenant_id=tenant_id,
            identity_a=identity_a,
            identity_b=identity_b,
            constraint_type=ConstraintType.CANNOT_LINK.value,
            source=source,
            created_by_user_id=created_by_user_id,
        )

    async def create(
        self,
        tenant_id: str,
        identity_a: str,
        identity_b: str,
        constraint_type: str,
        source: str,
        created_by_user_id: int | None = None,
    ) -> IdentityConstraint:
        id_a, id_b = canonical_order(uuid.UUID(identity_a), uuid.UUID(identity_b))
        if id_a == id_b:
            raise ValueError("Cannot create constraint between identical identity IDs")
        constraint_id = uuid.uuid4()
        values = {
            "id": constraint_id,
            "tenant_id": uuid.UUID(tenant_id),
            "identity_a": id_a,
            "identity_b": id_b,
            "constraint_type": constraint_type,
            "source": source,
            "created_at": datetime.now(tz=UTC),
            "created_by_user_id": created_by_user_id,
        }

        bind = self.session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else None

        stmt: Insert
        if dialect_name == "postgresql":
            stmt = pg_insert(ConstraintModel).values(**values).on_conflict_do_nothing()
        elif dialect_name == "sqlite":
            stmt = sqlite_insert(ConstraintModel).values(**values).on_conflict_do_nothing()
        else:
            stmt = insert(ConstraintModel).values(**values)

        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount == 0:
            existing = await self.get(tenant_id, str(id_a), str(id_b))
            if existing:
                return existing
            raise ValueError("Constraint insert skipped but existing row not found")

        model = await self.session.get(ConstraintModel, constraint_id)
        if model is None:
            existing = await self.get(tenant_id, str(id_a), str(id_b))
            if existing:
                return existing
            raise ValueError("Constraint insert failed to load created row")
        return self._to_domain(model)

    async def get(
        self,
        tenant_id: str,
        identity_a: str,
        identity_b: str,
    ) -> IdentityConstraint | None:
        id_a, id_b = canonical_order(uuid.UUID(identity_a), uuid.UUID(identity_b))
        stmt = select(ConstraintModel).where(
            ConstraintModel.tenant_id == uuid.UUID(tenant_id),
            ConstraintModel.identity_a == id_a,
            ConstraintModel.identity_b == id_b,
        )
        result = await self.session.execute(stmt)
        model = result.scalars().one_or_none()
        return self._to_domain(model) if model else None

    async def get_all_for_identity(
        self,
        tenant_id: str,
        identity_id: str,
    ) -> list[IdentityConstraint]:
        uid = uuid.UUID(identity_id)
        stmt = select(ConstraintModel).where(
            ConstraintModel.tenant_id == uuid.UUID(tenant_id),
            or_(ConstraintModel.identity_a == uid, ConstraintModel.identity_b == uid),
        )
        result = await self.session.execute(stmt)
        return [self._to_domain(m) for m in result.scalars().all()]

    async def get_all(self, tenant_id: str) -> list[IdentityConstraint]:
        stmt = select(ConstraintModel).where(ConstraintModel.tenant_id == uuid.UUID(tenant_id))
        result = await self.session.execute(stmt)
        return [self._to_domain(m) for m in result.scalars().all()]

    async def has_cannot_link(
        self,
        tenant_id: str,
        identity_id: str,
        cluster_member_ids: list[str],
    ) -> bool:
        if not cluster_member_ids:
            return False

        uid = uuid.UUID(identity_id)
        member_uuids = [uuid.UUID(mid) for mid in cluster_member_ids if mid != identity_id]
        if not member_uuids:
            return False

        # Check for any constraint where:
        # (identity_a = uid AND identity_b IN members) OR (identity_b = uid AND identity_a IN members)
        # AND type = CANNOT_LINK
        stmt = (
            select(ConstraintModel.id)
            .where(
                ConstraintModel.tenant_id == uuid.UUID(tenant_id),
                ConstraintModel.constraint_type == ConstraintType.CANNOT_LINK.value,
                or_(
                    ConstraintModel.identity_a == uid,
                    ConstraintModel.identity_b == uid,
                ),
                or_(
                    ConstraintModel.identity_a.in_(member_uuids),
                    ConstraintModel.identity_b.in_(member_uuids),
                ),
            )
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar() is not None
