import asyncio
import os
import sys
import uuid
from pathlib import Path

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add app to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT / "apps" / "prototype-description-service"))

from db.models import MediaIdentity, Tenant
from db.settings import get_database_settings
from recognition.application.identity_clustering_service import IdentityClusteringService
from recognition.application.clustering_settings import ClusteringSettings

async def main():
    settings = get_database_settings()
    engine = create_async_engine(settings.postgres_dsn, future=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    tenant_id = uuid.uuid4()
    
    async with async_session() as session:
        # Bypass RLS
        await session.execute(text("SET app.bypass_rls = 'true'"))

        # Setup Tenant
        tenant = Tenant(id=tenant_id, site_url=f"https://test-{tenant_id}.local")
        session.add(tenant)
        await session.commit()
        
        # Create Service
        service = IdentityClusteringService(session, tenant_id)
        
        # Create Dummy Identity
        # Create a random vector and normalize it
        raw_embedding = np.random.rand(1024).astype(np.float32)
        norm = np.linalg.norm(raw_embedding)
        embedding = (raw_embedding / norm).tolist()
        
        identity = MediaIdentity(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            media_id=12345,
            media_url="http://example.com/1.jpg",
            bbox_x=0, bbox_y=0, bbox_width=100, bbox_height=100,
            confidence=0.99,
            embedding=embedding,
            created_by_user_id=1
        )
        session.add(identity)
        await session.commit()
        
        print(f"Created identity {identity.id}")
        
        # Create Cluster using Factory (simulating what happens in the app)
        # We need to use the service's callback
        cluster, entry = await service.factory.create_cluster_with_centroid(
            [identity],
            add_representative_callback=service._add_representative_embedding
        )
        
        await session.commit()
        print(f"Created cluster {cluster.id}")
        
        # Verify Representative
        result = await session.execute(
            text("SELECT count(*) FROM identity_cluster_representatives WHERE cluster_id = :cid"),
            {"cid": cluster.id}
        )
        count = result.scalar()
        print(f"Representative count for cluster: {count}")
        
        if count == 1:
            print("SUCCESS: Representative created.")
        else:
            print("FAILURE: Representative NOT created.")

if __name__ == "__main__":
    asyncio.run(main())
