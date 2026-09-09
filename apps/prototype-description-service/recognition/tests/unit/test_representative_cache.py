import numpy as np
import pytest

from recognition.application.similarity import RepresentativeCache


class ClusterRepoStub:
    def __init__(self, reps_by_cluster: dict[str, list[object]]) -> None:
        self._reps_by_cluster = reps_by_cluster

    async def get_all_representatives(self, cluster_id: str):
        return self._reps_by_cluster.get(cluster_id, [])


@pytest.mark.asyncio
async def test_load_normalizes_and_stacks_embeddings() -> None:
    rep = type("Rep", (), {"embedding": np.array([3.0, 4.0], dtype=np.float32)})()
    repo = ClusterRepoStub({"cluster-a": [rep]})

    cache = await RepresentativeCache.load(["cluster-a"], repo)
    reps = cache.get_representatives("cluster-a")

    assert reps is not None
    assert reps.shape == (1, 2)
    assert np.linalg.norm(reps[0]) == pytest.approx(1.0)
    assert reps[0][0] == pytest.approx(0.6)
    assert reps[0][1] == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_load_skips_clusters_with_no_representatives() -> None:
    repo = ClusterRepoStub({"cluster-a": []})

    cache = await RepresentativeCache.load(["cluster-a"], repo)

    assert cache.get_representatives("cluster-a") is None


@pytest.mark.asyncio
async def test_load_excludes_foreign_embedding_model_reps() -> None:
    same = type(
        "Rep",
        (),
        {"embedding": np.array([3.0, 4.0], dtype=np.float32), "embedding_model": "space-a"},
    )()
    foreign = type(
        "Rep",
        (),
        {"embedding": np.array([0.0, 1.0], dtype=np.float32), "embedding_model": "space-b"},
    )()
    repo = ClusterRepoStub({"cluster-a": [same, foreign]})

    cache = await RepresentativeCache.load(["cluster-a"], repo)
    reps = cache.get_representatives("cluster-a")

    assert reps is not None
    assert reps.shape == (1, 2)
    assert reps[0][0] == pytest.approx(0.6)
    assert reps[0][1] == pytest.approx(0.8)
