"""FIR23-01: embedding_model enforcement on read paths + fail-closed readiness.

Unclustered rows fail closed to the active runtime id. All-unstamped batches
remain the legacy no-op; mixed or foreign stamps never pass through.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.embedding.manifest import (
    active_embedding_model_id,
    incumbent_embedding_model_manifest,
)
from recognition.application.health import check_active_embedding_model
from recognition.infrastructure.repositories.cluster_repository import (
    _choose_embedding_model,
    _filter_embedding_pairs_to_single_model,
    _filter_identity_models_to_single_embedding_model,
    _filter_rows_to_single_embedding_model,
)
from shared.health import HealthStatus


def test_active_embedding_model_id_insightface_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "production")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "insightface")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        model_id = active_embedding_model_id()
        assert model_id == incumbent_embedding_model_manifest().model_id
        assert "@" in model_id
    finally:
        get_settings.cache_clear()


def test_active_embedding_model_id_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        assert active_embedding_model_id() == "stub-detector@test"
    finally:
        get_settings.cache_clear()


def test_check_active_embedding_model_ok() -> None:
    result = check_active_embedding_model()
    assert result.name == "embedding_model"
    assert result.status is HealthStatus.OK
    assert result.detail.startswith("active_space=")


def test_check_active_embedding_model_public_detail_hides_model_id() -> None:
    """Unauthenticated /ready must not disclose the toolchain-bearing model_id.

    CVUP1-GR-15: ``space_token`` folds the resolved OpenCV and onnxruntime
    versions into ``model_id``, so echoing it on the public probe is version
    disclosure. The coarse form must still discriminate — two different active
    model_ids must not collapse to the same ``active_space``.
    """
    model_id = active_embedding_model_id()
    public = check_active_embedding_model()
    assert model_id not in public.detail

    with patch(
        "recognition.application.embedding.manifest.active_embedding_model_id",
        return_value=model_id + "-other",
    ):
        other = check_active_embedding_model()
    assert other.detail != public.detail


def test_check_active_embedding_model_verbose_keeps_model_id() -> None:
    verbose = check_active_embedding_model(verbose=True)
    assert verbose.status is HealthStatus.OK
    assert verbose.detail == f"active={active_embedding_model_id()}"


def test_check_active_embedding_model_fail_closed() -> None:
    with patch(
        "recognition.application.embedding.manifest.active_embedding_model_id",
        side_effect=RuntimeError("boom"),
    ):
        result = check_active_embedding_model()
    assert result.status is HealthStatus.UNHEALTHY
    assert "unresolved" in result.detail


def test_choose_embedding_model_majority_and_lex_tie() -> None:
    assert _choose_embedding_model(["b", "a", "b"]) == "b"
    # equal counts → lex min
    assert _choose_embedding_model(["b", "a"]) == "a"
    assert _choose_embedding_model([None, ""]) is None


def test_filter_embedding_pairs_single_model_is_noop() -> None:
    emb = np.ones(4, dtype=np.float32)
    rows = [(emb, "m1"), (emb * 2, "m1")]
    assert _filter_embedding_pairs_to_single_model(rows) == rows


def test_filter_embedding_pairs_mixed_keeps_majority() -> None:
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    rows = [(a, "keep"), (a, "keep"), (b, "drop")]
    kept = _filter_embedding_pairs_to_single_model(rows)
    assert len(kept) == 2
    assert all(model == "keep" for _, model in kept)


def test_filter_identity_models_single_model_noop() -> None:
    rows = [
        SimpleNamespace(embedding_model="m1", id="1"),
        SimpleNamespace(embedding_model="m1", id="2"),
    ]
    # helper expects MediaIdentity-like; attribute access only.
    assert _filter_identity_models_to_single_embedding_model(rows) == rows  # type: ignore[arg-type]


def test_filter_identity_models_mixed_majority() -> None:
    rows = [
        SimpleNamespace(embedding_model="keep"),
        SimpleNamespace(embedding_model="keep"),
        SimpleNamespace(embedding_model="drop"),
    ]
    kept = _filter_identity_models_to_single_embedding_model(rows)  # type: ignore[arg-type]
    assert len(kept) == 2
    assert all(r.embedding_model == "keep" for r in kept)


def test_filter_identity_models_drops_unstamped_when_stamp_exists() -> None:
    """One stamp plus unstamped/empty rows is mixed provenance, not a no-op."""
    stamped = SimpleNamespace(embedding_model="keep")
    unstamped = SimpleNamespace(embedding_model=None)
    empty = SimpleNamespace(embedding_model="")
    kept = _filter_identity_models_to_single_embedding_model([unstamped, stamped, empty])  # type: ignore[arg-type]
    assert kept == [stamped]


def test_filter_embedding_pairs_drops_unstamped_when_stamp_exists() -> None:
    stamped = np.array([1.0, 0.0], dtype=np.float32)
    unstamped = np.array([0.0, 1.0], dtype=np.float32)
    rows = [(unstamped, None), (stamped, "keep"), (unstamped, "")]
    kept = _filter_embedding_pairs_to_single_model(rows)
    assert len(kept) == 1
    assert kept[0][1] == "keep"


def test_filter_rows_unclustered_mixed_prefers_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        rows = [
            SimpleNamespace(embedding_model="stub-detector@test"),
            SimpleNamespace(embedding_model="other-model"),
            SimpleNamespace(embedding_model="other-model"),
        ]
        kept = _filter_rows_to_single_embedding_model(rows)  # type: ignore[arg-type]
        assert len(kept) == 1
        assert kept[0].embedding_model == "stub-detector@test"
    finally:
        get_settings.cache_clear()


def test_filter_rows_unclustered_single_foreign_model_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        rows = [
            SimpleNamespace(embedding_model="legacy-seed"),
            SimpleNamespace(embedding_model="legacy-seed"),
        ]
        assert _filter_rows_to_single_embedding_model(rows) == []  # type: ignore[arg-type]
    finally:
        get_settings.cache_clear()


def test_filter_rows_unclustered_active_model_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        rows = [
            SimpleNamespace(embedding_model="stub-detector@test"),
            SimpleNamespace(embedding_model="stub-detector@test"),
        ]
        assert _filter_rows_to_single_embedding_model(rows) == rows  # type: ignore[arg-type]
    finally:
        get_settings.cache_clear()


def test_filter_rows_unclustered_unstamped_mixed_with_stamp_keeps_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        unstamped = SimpleNamespace(embedding_model=None)
        active = SimpleNamespace(embedding_model="stub-detector@test")
        foreign = SimpleNamespace(embedding_model="legacy-seed")
        kept = _filter_rows_to_single_embedding_model([unstamped, active, foreign])  # type: ignore[arg-type]
        assert kept == [active]
    finally:
        get_settings.cache_clear()


def test_filter_rows_unclustered_all_unstamped_is_legacy_noop() -> None:
    rows = [
        SimpleNamespace(embedding_model=None),
        SimpleNamespace(embedding_model=None),
    ]
    assert _filter_rows_to_single_embedding_model(rows) == rows  # type: ignore[arg-type]


def _batch_member_model(*, embedding_model: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        media_id=1,
        embedding=np.array([1.0, 0.0], dtype=np.float32),
        confidence=0.99,
        bbox_width=10,
        bbox_height=10,
        bbox_x=0,
        bbox_y=0,
        pose_pitch=None,
        pose_yaw=None,
        pose_roll=None,
        image_phash=None,
        sharpness=None,
        embedding_norm=None,
        occlusion_severity=None,
        moved_by_merge_id=None,
        embedding_model=embedding_model,
    )


@pytest.mark.asyncio
async def test_get_member_identities_for_clusters_keeps_same_space_minority() -> None:
    """Batch member load must not majority-drop a same-space identity."""
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

    cluster_uuid = uuid4()
    cluster_id = str(cluster_uuid)
    gallery = _batch_member_model(embedding_model="space-a")
    foreign = [_batch_member_model(embedding_model="space-b") for _ in range(3)]
    result = MagicMock()
    result.all.return_value = [(model, cluster_uuid) for model in [*foreign, gallery]]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    repo = SqlAlchemyClusterRepository(session)

    grouped = await repo.get_member_identities_for_clusters([cluster_id])

    identities = grouped[cluster_id]
    assert len(identities) == 4
    assert {identity.embedding_model for identity in identities} == {"space-a", "space-b"}
    assert sum(1 for identity in identities if identity.embedding_model == "space-a") == 1


def test_centroid_mv_sql_frames_by_embedding_model() -> None:
    """Migration MV definition must majority-frame by embedding_model (FIR23-01)."""
    from pathlib import Path

    migration = Path(__file__).resolve().parents[3] / "db" / "migrations" / "versions" / "001_identity_schema.py"
    text = migration.read_text(encoding="utf-8")
    assert "chosen_model" in text
    assert "embedding_model" in text
    assert "ORDER BY cluster_id, n DESC, embedding_model ASC" in text


@pytest.mark.asyncio
async def test_sqlite_refresh_counts_majority_stamp_and_drops_unstamped() -> None:
    """SQLite centroid refresh must ignore unstamped rows and minority stamps."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("CREATE TABLE identity_clusters (id TEXT PRIMARY KEY, tenant_id TEXT, updated_at TIMESTAMP)")
            )
            await conn.execute(
                text(
                    "CREATE TABLE media_identities ("
                    "id TEXT PRIMARY KEY, embedding BLOB, embedding_model TEXT, updated_at TIMESTAMP)"
                )
            )
            await conn.execute(text("CREATE TABLE identity_members (identity_id TEXT, cluster_id TEXT)"))
            await conn.execute(
                text(
                    "CREATE TABLE mv_identity_cluster_centroids ("
                    "cluster_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, "
                    "identity_count INTEGER NOT NULL DEFAULT 0, centroid BLOB, refreshed_at TIMESTAMP)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO identity_clusters (id, tenant_id, updated_at) VALUES "
                    "('c-mixed', 't1', CURRENT_TIMESTAMP), ('c-unstamped', 't1', CURRENT_TIMESTAMP)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO media_identities (id, embedding, embedding_model, updated_at) VALUES "
                    "('m-keep-1', X'00', 'keep', CURRENT_TIMESTAMP), "
                    "('m-keep-2', X'00', 'keep', CURRENT_TIMESTAMP), "
                    "('m-drop', X'00', 'drop', CURRENT_TIMESTAMP), "
                    "('m-null', X'00', NULL, CURRENT_TIMESTAMP), "
                    "('m-only-null', X'00', NULL, CURRENT_TIMESTAMP)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO identity_members (identity_id, cluster_id) VALUES "
                    "('m-keep-1', 'c-mixed'), ('m-keep-2', 'c-mixed'), "
                    "('m-drop', 'c-mixed'), ('m-null', 'c-mixed'), "
                    "('m-only-null', 'c-unstamped')"
                )
            )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            await SqlAlchemyClusterRepository(session).refresh_centroids_view()
            rows = {
                str(row[0]): int(row[1])
                for row in (
                    await session.execute(text("SELECT cluster_id, identity_count FROM mv_identity_cluster_centroids"))
                ).all()
            }
        assert rows.get("c-mixed") == 2
        assert "c-unstamped" not in rows
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_orchestrator_fetch_keeps_only_active_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mixed unclustered ORM rows must keep the active runtime model only."""
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4

    from recognition.application.orchestration.clustering.orchestrator import IncrementalClusteringRunner
    from recognition.config import get_settings

    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    get_settings.cache_clear()
    try:
        active = SimpleNamespace(embedding_model="stub-detector@test")
        foreign = SimpleNamespace(embedding_model="legacy-seed")
        unstamped = SimpleNamespace(embedding_model=None)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [unstamped, foreign, active]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        runner = IncrementalClusteringRunner.__new__(IncrementalClusteringRunner)
        runner._session = session
        kept, skip_payload = await runner._fetch_unclustered_identities(uuid4())
        assert kept == [active]
        assert skip_payload["active_embedding_model"] == "stub-detector@test"
        assert skip_payload["skipped_models"] == ["legacy-seed", "unstamped"]
        assert skip_payload["skipped_count"] == 2
        assert skip_payload["kept_count"] == 1
        assert skip_payload["total_count"] == 3
    finally:
        get_settings.cache_clear()


def test_probe_space_skip_payload_shape() -> None:
    """B-05: job payload names active model, skipped models, and counts."""
    from recognition.application.orchestration.clustering.orchestrator import probe_space_skip_payload

    active = SimpleNamespace(embedding_model="stub-detector@test")
    foreign = SimpleNamespace(embedding_model="legacy-seed")
    unstamped = SimpleNamespace(embedding_model=None)
    payload = probe_space_skip_payload(
        [unstamped, foreign, active],
        [active],
        active_model="stub-detector@test",
    )
    assert payload == {
        "active_embedding_model": "stub-detector@test",
        "skipped_models": ["legacy-seed", "unstamped"],
        "skipped_count": 2,
        "kept_count": 1,
        "total_count": 3,
    }


def test_unstamped_gallery_with_known_active_model_does_not_abort() -> None:
    """Unstamped reps + known active model must proceed rather than fail the job."""
    from recognition.application.orchestration.clustering.discovery_pipeline import GalleryProvenanceStats

    stats = GalleryProvenanceStats(
        active_embedding_model="opencv-sface+cv5@128d/l2/cosine",
        provenance_loaded=True,
        representatives_excluded_unresolvable=12,
        clusters_excluded_unresolvable=5,
        centroids_excluded_untrusted=4,
        gallery_wiped=True,
    )
    assert stats.abort_reason() is None


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self):
        return list(self._rows)

    def scalars(self):
        return self


@pytest.mark.asyncio
async def test_with_model_loaders_keep_all_unstamped_cluster() -> None:
    """All-null embedding_model rows must survive Python majority filter (legacy no-op)."""
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

    emb_a = np.array([1.0, 0.0], dtype=np.float32)
    emb_b = np.array([0.0, 1.0], dtype=np.float32)
    rows = [(emb_a, None), (emb_b, None)]
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult(rows))
    repo = SqlAlchemyClusterRepository(session)

    embeddings, chosen = await repo.get_representative_embeddings_with_model("cluster-1")

    assert chosen is None
    assert len(embeddings) == 2
    np.testing.assert_array_equal(embeddings[0], emb_a)
    np.testing.assert_array_equal(embeddings[1], emb_b)


@pytest.mark.asyncio
async def test_list_identity_ids_moved_by_merge_reads_stamped_rows() -> None:
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

    tenant_id = str(uuid4())
    merge_id = str(uuid4())
    moved = [uuid4(), uuid4()]
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult(moved))
    repo = SqlAlchemyClusterRepository(session)

    found = await repo.list_identity_ids_moved_by_merge(tenant_id, merge_id)

    assert found == [str(identity_id) for identity_id in moved]
    session.execute.assert_awaited_once()
    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()
    assert "moved_by_merge_id" in sql
