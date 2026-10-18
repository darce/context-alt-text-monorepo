from __future__ import annotations

import uuid
from collections.abc import Sequence

import numpy as np
import pytest
from sqlalchemy import select

from db.models import RecognitionEvent
from recognition.application.discovery.graph import GraphAlgorithm, GraphDiscovery
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.observability.recognition_runs import create_recognition_run


class StubGraphAlgorithm(GraphAlgorithm):
    def __init__(self) -> None:
        self.param_a = 1

    def cluster(self, embeddings: Sequence[np.ndarray], identities: Sequence[MediaIdentity] | None = None) -> list[int]:
        return [0] * len(embeddings)


@pytest.mark.asyncio
async def test_graph_discovery_emits_graph_run_event(db_session, tenant) -> None:
    run_ctx = await create_recognition_run(db_session, tenant_id=tenant.id, source="test")
    discovery = GraphDiscovery(
        settings=ClusteringSettings(similarity_threshold=0.85),
        algorithm=StubGraphAlgorithm(),
        run_context=run_ctx,
    )

    identities = [
        MediaIdentity(
            id=str(uuid.uuid4()),
            tenant_id=str(tenant.id),
            media_id="101",
            embedding=np.array([1.0] + [0.0] * 511, dtype=np.float32),
            confidence=0.99,
            bbox_width=10,
            bbox_height=10,
            bbox_x=1,
            bbox_y=2,
        ),
        MediaIdentity(
            id=str(uuid.uuid4()),
            tenant_id=str(tenant.id),
            media_id="102",
            embedding=np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32),
            confidence=0.98,
            bbox_width=10,
            bbox_height=10,
            bbox_x=3,
            bbox_y=4,
        ),
    ]

    await discovery.discover(identities, anchor_embeddings={})
    await db_session.commit()

    events = (await db_session.execute(select(RecognitionEvent))).scalars().all()
    graph_events = [event for event in events if event.event_type == "graph_run"]
    assert len(graph_events) == 1

    payload = graph_events[0].payload
    assert payload.get("algorithm") == "StubGraphAlgorithm"
    assert payload.get("params") == {"param_a": 1}
    assert payload.get("anchor_count") == 0

    embedding_stats = payload.get("embedding_stats")
    assert isinstance(embedding_stats, dict)
    assert embedding_stats.get("count") == 2
    assert embedding_stats.get("dimension") == 512
