#!/usr/bin/env python3
import asyncio
import uuid

import numpy as np
from sqlalchemy import select

from db.models import IdentityClusterRepresentative, Tenant
from db.session import async_session_factory
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository


def make_identity(tenant_id):
    return MediaIdentity(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        media_id="123",
        embedding=np.random.rand(512).astype(np.float32),
        confidence=0.99,
        bbox_width=100,
        bbox_height=100,
    )


async def test():
    async with async_session_factory() as session:
        tenant = (await session.execute(select(Tenant).limit(1))).scalar_one_or_none()
        if not tenant:
            print("No tenant found")
            return

        print(f"Using tenant: {tenant.id}")

        cluster_repo = SqlAlchemyClusterRepository(session)
        member_repo = SqlAlchemyMemberRepository(session, tenant_id=str(tenant.id))
        writer = AssignmentWriter(ClusteringSettings(), cluster_repo, member_repo)

        identities = [make_identity(str(tenant.id)), make_identity(str(tenant.id))]
        similarities = [0.93, 0.94]

        cluster = await writer.persist_new_cluster(
            tenant_id=str(tenant.id),
            identities=identities,
            similarities=similarities,
            algorithm="graph",
        )

        print(f"Created cluster: {cluster.id}")

        reps = (
            (
                await session.execute(
                    select(IdentityClusterRepresentative).where(IdentityClusterRepresentative.cluster_id == cluster.id)
                )
            )
            .scalars()
            .all()
        )

        print(f"Representatives created: {len(reps)}")
        for r in reps:
            print(f"  Rep: {r.id}, identity: {r.identity_id}")

        await session.rollback()


if __name__ == "__main__":
    asyncio.run(test())
