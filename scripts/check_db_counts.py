import asyncio
import os
import sys
from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../apps/prototype-description-service")))

from db.settings import get_database_settings
from db.models import MediaIdentity, IdentityCluster, IdentityMember

async def main():
    settings = get_database_settings()
    print(f"Connecting to: {settings.postgres_dsn}")
    engine = create_async_engine(settings.postgres_dsn)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Bypass RLS
        await session.execute(text("SELECT set_config('app.bypass_rls', 'true', false)"))

        # Count Clusters
        result = await session.execute(select(func.count(IdentityCluster.id)))
        cluster_count = result.scalar()
        print(f"Total Clusters: {cluster_count}")

        # Count Identities
        result = await session.execute(select(func.count(MediaIdentity.id)))
        identity_count = result.scalar()
        print(f"Total Identities: {identity_count}")

        # Count Members
        result = await session.execute(select(func.count(IdentityMember.identity_id)))
        member_count = result.scalar()
        print(f"Total Members: {member_count}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
