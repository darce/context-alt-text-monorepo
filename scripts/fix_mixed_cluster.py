
import asyncio
import os
import sys
import uuid
import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "apps/prototype-description-service")))

from db.settings import get_database_settings
from db.models import MediaIdentity, IdentityCluster, IdentityMember

async def main():
    if len(sys.argv) < 2:
        print("Usage: python fix_mixed_cluster.py <cluster_id>")
        return

    cluster_id = uuid.UUID(sys.argv[1])
    settings = get_database_settings()
    engine = create_async_engine(settings.postgres_dsn)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Bypass RLS
        await session.execute(text("SELECT set_config('app.bypass_rls', 'true', false)"))

        # 1. Fetch all identities in the cluster
        print(f"Fetching identities for cluster {cluster_id}...")
        stmt = (
            select(MediaIdentity)
            .join(IdentityMember, MediaIdentity.id == IdentityMember.identity_id)
            .where(IdentityMember.cluster_id == cluster_id)
        )
        result = await session.execute(stmt)
        identities = result.scalars().all()
        
        if not identities:
            print("No identities found in cluster.")
            return

        print(f"Found {len(identities)} identities.")
        
        # 2. Prepare embeddings
        embeddings = np.array([id.embedding for id in identities])
        ids = [id.id for id in identities]
        media_ids = [id.media_id for id in identities]

        # 3. Run DBSCAN to find sub-clusters
        # eps=0.4 corresponds to cosine similarity of ~0.6 (distance = 1 - sim)
        # If distance is cosine distance, 0.4 distance = 0.6 similarity.
        # We need to compute distance matrix first or use metric='cosine'
        
        print("Running clustering analysis...")
        clustering = DBSCAN(eps=0.35, min_samples=2, metric='cosine').fit(embeddings)
        labels = clustering.labels_

        unique_labels = set(labels)
        print(f"Found {len(unique_labels)} sub-groups (including noise -1): {unique_labels}")

        for label in unique_labels:
            if label == -1:
                print(f"\nGroup Noise (Label -1):")
            else:
                print(f"\nGroup {label}:")
            
            group_indices = [i for i, l in enumerate(labels) if l == label]
            for i in group_indices:
                print(f"  - Media {media_ids[i]} (Identity {ids[i]})")

        # 4. Perform Split
        # We assume Group 0 stays in the original cluster, Group 1 moves to a new one.
        # If Group 1 is larger, we could swap, but let's just move Group 1.
        
        group_1_indices = [i for i, l in enumerate(labels) if l == 1]
        if not group_1_indices:
            print("No Group 1 found. Nothing to split.")
            return

        print(f"\nMoving {len(group_1_indices)} identities from Group 1 to a new cluster...")
        
        # Create new cluster
        new_cluster_id = uuid.uuid4()
        # Get tenant_id from one of the identities
        tenant_id = identities[0].tenant_id
        
        new_cluster = IdentityCluster(
            id=new_cluster_id,
            tenant_id=tenant_id,
            label="Split Cluster (Maya Pettersen?)",
            identity_count=len(group_1_indices),
            clustering_algorithm="cosine_similarity",
        )
        session.add(new_cluster)
        await session.flush()
        print(f"Created new cluster {new_cluster_id}")

        # Move members
        group_1_identity_ids = [ids[i] for i in group_1_indices]
        stmt = (
            text("UPDATE identity_members SET cluster_id = :new_cluster_id WHERE identity_id = ANY(:identity_ids)")
            .bindparams(new_cluster_id=new_cluster_id, identity_ids=group_1_identity_ids)
        )
        await session.execute(stmt)
        
        # Move representatives if they exist
        stmt = (
            text("UPDATE identity_cluster_representatives SET cluster_id = :new_cluster_id WHERE identity_id = ANY(:identity_ids)")
            .bindparams(new_cluster_id=new_cluster_id, identity_ids=group_1_identity_ids)
        )
        await session.execute(stmt)

        # Update counts
        remaining_count = len(identities) - len(group_1_indices)
        stmt = (
            text("UPDATE identity_clusters SET identity_count = :count WHERE id = :cluster_id")
            .bindparams(count=remaining_count, cluster_id=cluster_id)
        )
        await session.execute(stmt)

        # Refresh Materialized View
        print("Refreshing centroid view...")
        await session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
        
        await session.commit()
        print("Split complete.")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
