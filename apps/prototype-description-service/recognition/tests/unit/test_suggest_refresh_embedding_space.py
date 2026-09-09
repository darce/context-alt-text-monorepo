"""CVUP1-R3-15: suggestion refresh must not cosine across embedding spaces."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.refresh_service import (
    SuggestionRefreshService,
    _gallery_vector_for_probe,
)
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.representative import ClusterRepresentative


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


def test_gallery_vector_excludes_foreign_space_when_probe_is_stamped() -> None:
    probe_model = "space-a"
    same = SimpleNamespace(embedding=_normalize(np.array([1.0, 0.0])), embedding_model="space-a")
    foreign = SimpleNamespace(embedding=_normalize(np.array([0.0, 1.0])), embedding_model="space-b")

    assert _gallery_vector_for_probe(same, probe_model) is not None
    assert _gallery_vector_for_probe(foreign, probe_model) is None


def test_gallery_vector_excludes_stamped_gallery_when_probe_is_unstamped() -> None:
    unstamped = SimpleNamespace(embedding=_normalize(np.array([1.0, 0.0])), embedding_model=None)
    stamped = SimpleNamespace(embedding=_normalize(np.array([0.0, 1.0])), embedding_model="space-b")

    assert _gallery_vector_for_probe(unstamped, None) is not None
    assert _gallery_vector_for_probe(stamped, None) is None


@pytest.mark.asyncio
async def test_find_best_cluster_match_skips_foreign_space_gallery() -> None:
    tenant_id = str(uuid4())
    same_cluster_id = str(uuid4())
    foreign_cluster_id = str(uuid4())
    probe_model = "space-a"

    identity = MediaIdentity(
        id=str(uuid4()),
        tenant_id=tenant_id,
        media_id="1",
        embedding=_normalize(np.array([1.0, 0.0, 0.0])),
        confidence=0.9,
        bbox_width=10,
        bbox_height=10,
        embedding_model=probe_model,
    )
    same_rep = ClusterRepresentative(
        id="r-same",
        cluster_id=same_cluster_id,
        identity_id="i-same",
        embedding=_normalize(np.array([0.8, 0.2, 0.0])),
        created_at=datetime.now(tz=UTC),
        embedding_model=probe_model,
    )
    foreign_rep = ClusterRepresentative(
        id="r-foreign",
        cluster_id=foreign_cluster_id,
        identity_id="i-foreign",
        embedding=_normalize(np.array([0.99, 0.01, 0.0])),
        created_at=datetime.now(tz=UTC),
        embedding_model="space-b",
    )
    same_cluster = IdentityCluster(
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=1,
        id=same_cluster_id,
        label="Same",
        user_confirmed=True,
        representatives=[same_rep],
    )
    foreign_cluster = IdentityCluster(
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=1,
        id=foreign_cluster_id,
        label="Foreign",
        user_confirmed=True,
        representatives=[foreign_rep],
    )

    cluster_repo = AsyncMock()
    cluster_repo.get_labeled_with_representatives = AsyncMock(
        return_value=[(same_cluster, [same_rep]), (foreign_cluster, [foreign_rep])]
    )
    service = SuggestionRefreshService(
        repository=AsyncMock(),
        tenant_id=tenant_id,
        cluster_repository=cluster_repo,
        settings=ClusteringSettings(similarity_threshold=0.3, suggestion_floor=0.3),
    )

    match = await service._find_best_cluster_match(identity)

    assert match is not None
    assert match[0] == same_cluster_id
