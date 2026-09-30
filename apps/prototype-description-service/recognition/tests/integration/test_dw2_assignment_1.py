from __future__ import annotations

import uuid

import numpy as np
import pytest

from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import ClusteringSettings, QualitySettings
from recognition.domain.identity import MediaIdentity


@pytest.mark.asyncio
async def test_persist_new_cluster_uses_runtime_quality_settings_for_seed_selection(
    monkeypatch,
) -> None:
    class ClusterRepositoryStub:
        def __init__(self) -> None:
            self.representatives = []

        async def save(self, cluster):
            return cluster

        async def add_representative(self, representative) -> None:
            self.representatives.append(representative)

    class MemberRepositoryStub:
        async def bulk_add_members_if_not_exists(self, _cluster_id, member_data):
            return member_data, False

    tenant_id = str(uuid.uuid4())
    cluster_repo = ClusterRepositoryStub()
    member_repo = MemberRepositoryStub()
    settings = ClusteringSettings(
        quality=QualitySettings(
            representative_quality_composite_enabled=True,
            factor_floor_sharpness=10.0,
        ),
        max_representatives_per_cluster=1,
    )
    writer = AssignmentWriter(settings, cluster_repo, member_repo)

    async def no_centroid(_cluster_id):
        return None

    monkeypatch.setattr(writer, "recompute_centroid", no_centroid)

    embedding = np.zeros(512, dtype=np.float32)
    embedding[0] = 1.0
    configured_winner = MediaIdentity(
        id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        tenant_id=tenant_id,
        media_id=str(uuid.uuid4()),
        embedding=embedding,
        confidence=0.95,
        bbox_width=10,
        bbox_height=10,
        sharpness=20.0,
    )
    default_winner = MediaIdentity(
        id="00000000-0000-0000-0000-000000000001",
        tenant_id=tenant_id,
        media_id=str(uuid.uuid4()),
        embedding=embedding,
        confidence=0.95,
        bbox_width=10,
        bbox_height=10,
        sharpness=10.0,
    )
    identities = [configured_winner, default_winner]

    await writer.persist_new_cluster(
        tenant_id=tenant_id,
        identities=identities,
        similarities=[0.93, 0.93],
        algorithm="graph",
        cluster_id=str(uuid.uuid4()),
    )

    assert len(cluster_repo.representatives) == 1
    assert cluster_repo.representatives[0].identity_id == configured_winner.id
