"""Integration tests for SqlAlchemyConstraintRepository."""

import uuid

import pytest
from sqlalchemy import select

from db.models import MediaIdentity, Tenant
from recognition.domain.constraints import ConstraintSource, ConstraintType, canonical_order
from recognition.infrastructure.repositories import SqlAlchemyConstraintRepository


async def ensure_tenant(session, tenant_id: str):
    t_uuid = uuid.UUID(tenant_id)
    tenant = await session.get(Tenant, t_uuid)
    if not tenant:
        tenant = Tenant(id=t_uuid, site_url=f"http://example-{tenant_id}.com")
        session.add(tenant)
        await session.flush()


async def create_identity(session, tenant_id: str, media_id: int = 1) -> str:
    await ensure_tenant(session, tenant_id)
    identity_id = uuid.uuid4()
    identity = MediaIdentity(
        id=identity_id,
        tenant_id=uuid.UUID(tenant_id),
        media_id=media_id,
        embedding=[0.1] * 512,
        confidence=0.9,
        media_url="http://example.com/test.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=100,
        bbox_height=100,
    )
    session.add(identity)
    await session.flush()
    return str(identity_id)


@pytest.mark.asyncio
@pytest.mark.integration
class TestConstraintRepository:
    """Integration tests with real PostgreSQL."""

    async def test_create_and_retrieve(self, db_session):
        """Constraint round-trips through database."""
        repo = SqlAlchemyConstraintRepository(db_session)
        tenant_id = str(uuid.uuid4())

        # Setup identities
        id_a = await create_identity(db_session, tenant_id, 1)
        id_b = await create_identity(db_session, tenant_id, 2)

        # Create constraint
        constraint = await repo.create(
            tenant_id=tenant_id,
            identity_a=id_a,
            identity_b=id_b,
            constraint_type=ConstraintType.MUST_LINK.value,
            source=ConstraintSource.MERGE.value,
        )

        assert constraint.id is not None
        assert constraint.tenant_id == uuid.UUID(tenant_id)
        assert constraint.constraint_type == ConstraintType.MUST_LINK

        # Retrieve by get
        retrieved = await repo.get(tenant_id, id_a, id_b)
        assert retrieved is not None
        assert retrieved.id == constraint.id

        # Retrieve reverse order (should work due to canonical lookup)
        retrieved_rev = await repo.get(tenant_id, id_b, id_a)
        assert retrieved_rev is not None
        assert retrieved_rev.id == constraint.id

    async def test_canonical_ordering_on_insert(self, db_session):
        """Repository enforces canonical ordering regardless of input order."""
        repo = SqlAlchemyConstraintRepository(db_session)
        tenant_id = str(uuid.uuid4())

        id_a = await create_identity(db_session, tenant_id, 1)
        id_b = await create_identity(db_session, tenant_id, 2)

        # Ensure we pass them in non-canonical order (larger first)
        u_a = uuid.UUID(id_a)
        u_b = uuid.UUID(id_b)
        first, second = (id_a, id_b) if u_a > u_b else (id_b, id_a)

        constraint = await repo.create(
            tenant_id=tenant_id, identity_a=first, identity_b=second, constraint_type="cannot_link", source="split"
        )

        # Check domain object
        expected_first, expected_second = canonical_order(u_a, u_b)
        assert constraint.identity_a == expected_first
        assert constraint.identity_b == expected_second

        # Check DB directly
        # Actually easier to use get()
        stored = await repo.get(tenant_id, id_a, id_b)
        assert stored is not None
        assert stored.identity_a == expected_first

    async def test_has_cannot_link(self, db_session):
        """Verify has_cannot_link logic."""
        repo = SqlAlchemyConstraintRepository(db_session)
        tenant_id = str(uuid.uuid4())

        id_main = await create_identity(db_session, tenant_id, 1)
        id_blocked = await create_identity(db_session, tenant_id, 2)
        id_allowed = await create_identity(db_session, tenant_id, 3)

        # Create CANNOT_LINK between main and blocked
        await repo.create(
            tenant_id=tenant_id,
            identity_a=id_main,
            identity_b=id_blocked,
            constraint_type="cannot_link",
            source="wrong_person",
        )

        # Check blocked
        assert await repo.has_cannot_link(tenant_id, id_main, [id_blocked, id_allowed]) is True

        # Check allowed
        assert await repo.has_cannot_link(tenant_id, id_main, [id_allowed]) is False

        # Check when main is not involved
        assert await repo.has_cannot_link(tenant_id, id_allowed, [id_blocked]) is False

    async def test_tenant_isolation(self, db_session):
        """Constraints are isolated by tenant."""
        repo = SqlAlchemyConstraintRepository(db_session)
        t1 = str(uuid.uuid4())
        t2 = str(uuid.uuid4())

        # Create identity in t1
        id_a = await create_identity(db_session, t1, 1)
        id_b = await create_identity(db_session, t1, 2)

        await repo.create(t1, id_a, id_b, "must_link", "merge")

        # Create identity in t2 with same IDs? No, IDs are UUIDs.
        # But even if we query with t2, we shouldn't find it.
        assert await repo.get(t2, id_a, id_b) is None
