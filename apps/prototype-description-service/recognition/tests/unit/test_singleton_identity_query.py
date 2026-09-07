"""Regression coverage for the singleton identity membership join invariant."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Table, create_engine, text
from sqlalchemy.orm import Session

from db.base import Base
from db.models import IdentityCluster, MediaIdentity, Tenant
from db.settings import get_database_settings
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository


@pytest.mark.asyncio
async def test_singleton_query_excludes_members_with_null_cluster_id() -> None:
    """A NULL membership key cannot survive the INNER JOIN into singleton rows."""
    # The production schema declares this key NOT NULL. Make the test table
    # nullable so the join invariant is exercised independently of that DDL.
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(
            engine,
            tables=[
                Table("tenants", Base.metadata),
                Table("identity_clusters", Base.metadata),
                Table("media_identities", Base.metadata),
            ],
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE identity_members (
                        identity_id CHAR(32) NOT NULL,
                        cluster_id CHAR(32)
                    )
                    """
                )
            )

        tenant = Tenant(site_url="http://example.test")
        cluster_id = uuid.uuid4()
        valid_identity_id = uuid.uuid4()
        null_identity_id = uuid.uuid4()
        embedding = [0.0] * int(get_database_settings().pgvector_dimension)
        with Session(engine) as session:
            session.add(tenant)
            session.flush()
            session.add(
                IdentityCluster(
                    id=cluster_id,
                    tenant_id=tenant.id,
                    identity_count=1,
                    user_confirmed=False,
                )
            )
            session.add_all(
                [
                    MediaIdentity(
                        id=valid_identity_id,
                        tenant_id=tenant.id,
                        media_id=1,
                        media_url="http://example.test/valid.jpg",
                        bbox_x=0,
                        bbox_y=0,
                        bbox_width=1,
                        bbox_height=1,
                        confidence=1.0,
                        embedding=embedding,
                        embedding_model="test-model",
                    ),
                    MediaIdentity(
                        id=null_identity_id,
                        tenant_id=tenant.id,
                        media_id=2,
                        media_url="http://example.test/null-cluster.jpg",
                        bbox_x=0,
                        bbox_y=0,
                        bbox_width=1,
                        bbox_height=1,
                        confidence=1.0,
                        embedding=embedding,
                        embedding_model="test-model",
                    ),
                ]
            )
            session.flush()
            session.execute(
                text(
                    "INSERT INTO identity_members (identity_id, cluster_id) VALUES "
                    "(:valid_identity_id, :cluster_id), (:null_identity_id, NULL)"
                ),
                {
                    "valid_identity_id": valid_identity_id.hex,
                    "cluster_id": cluster_id.hex,
                    "null_identity_id": null_identity_id.hex,
                },
            )

            class _AsyncSessionAdapter:
                async def execute(self, statement):
                    return session.execute(statement)

            identities = await SqlAlchemyClusterRepository(_AsyncSessionAdapter()).get_singleton_identities(
                str(tenant.id)
            )

        assert [identity.id for identity in identities] == [str(valid_identity_id)]
    finally:
        engine.dispose()
