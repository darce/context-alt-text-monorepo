"""GPUFLOW-2 C3: LIFO cluster-merge revert and undo HTTP surface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError
from starlette.testclient import TestClient

from db.models.identity import ClusterMergeKind, ClusterMergeReceipt, ReceiptExpiredError, ReceiptNotTopError
from recognition.application.orchestration.cluster_merge import (
    MergeReceiptNotFoundError,
    MergeReceiptStaleError,
    revert_merge,
)
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import IdentityMember
from recognition.domain.representative import ClusterRepresentative
from recognition.interface_adapters.http.deps import (
    get_cluster_service_builder,
    get_session,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.routers import cluster_revert as cluster_revert_module
from recognition.interface_adapters.http.routers.cluster_revert import router as revert_router

NOW = datetime(2026, 9, 17, tzinfo=UTC)


class FakeClusterRepo:
    def __init__(self) -> None:
        self.clusters: dict[str, IdentityCluster] = {}

    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None:
        return self.clusters.get(str(cluster_id).lower())

    async def save(self, cluster: IdentityCluster) -> IdentityCluster:
        if cluster.id is None:
            cluster.id = str(uuid4())
        cluster.id = str(cluster.id).lower()
        self.clusters[cluster.id] = cluster
        return cluster

    async def update(self, cluster: IdentityCluster) -> IdentityCluster:
        if cluster.id is None:
            raise ValueError("cluster id required")
        cluster.id = str(cluster.id).lower()
        self.clusters[cluster.id] = cluster
        return cluster


class FakeMemberRepo:
    def __init__(self) -> None:
        self.by_identity: dict[str, IdentityMember] = {}

    async def get_by_cluster(self, cluster_id: str) -> list[IdentityMember]:
        key = str(cluster_id).lower()
        return [member for member in self.by_identity.values() if member.cluster_id == key]

    async def add_member(self, cluster_id: str, identity_id: str, similarity: float) -> IdentityMember:
        member = IdentityMember(
            id=str(uuid4()),
            cluster_id=str(cluster_id).lower(),
            identity_id=str(identity_id).lower(),
            similarity=similarity,
        )
        self.by_identity[member.identity_id] = member
        return member

    async def remove_by_identity_id(self, identity_id: str) -> bool:
        return self.by_identity.pop(str(identity_id).lower(), None) is not None


class FakeWriter:
    def __init__(self, cluster_repo: FakeClusterRepo, member_repo: FakeMemberRepo) -> None:
        self.cluster_repository = cluster_repo
        self.member_repository = member_repo
        self.refresh_centroids_view = AsyncMock()
        self.recompute_calls: list[tuple[str, str]] = []

    async def recompute_representatives(self, cluster_id: str) -> None:
        self.recompute_calls.append(("representatives", cluster_id))
        await self._apply_recompute(cluster_id)

    async def recompute_centroid(self, cluster_id: str) -> None:
        self.recompute_calls.append(("centroid", cluster_id))
        await self._apply_recompute(cluster_id)

    async def _apply_recompute(self, cluster_id: str) -> None:
        cluster = await self.cluster_repository.get_by_id(cluster_id)
        if cluster is None:
            return
        members = await self.member_repository.get_by_cluster(cluster_id)
        identity_ids = tuple(sorted(member.identity_id for member in members))
        cluster.centroid = identity_ids
        cluster.representatives = tuple(
            ClusterRepresentative(
                id=f"rep:{identity_id}",
                cluster_id=str(cluster_id).lower(),
                identity_id=identity_id,
                embedding=np.zeros(2),
                created_at=NOW,
            )
            for identity_id in identity_ids
        )


class FakeMergeSuggestions:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
        self.deleted.append((tenant_id, cluster_id))
        return 1


class FakeSession:
    def __init__(self, *, receipt_update_rowcount: int = 1) -> None:
        self.statements: list[object] = []
        self.receipt_update_rowcount = receipt_update_rowcount
        self.rollback_calls = 0

    async def execute(self, stmt: object) -> object:
        self.statements.append(stmt)
        rendered = str(stmt).lower()
        if rendered.startswith("update") and "cluster_merge_receipts" in rendered:
            return SimpleNamespace(rowcount=self.receipt_update_rowcount)
        return SimpleNamespace(scalar_one_or_none=lambda: None, scalars=lambda: SimpleNamespace(all=list))

    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        self.rollback_calls += 1


def _receipt(
    *,
    tenant_id: UUID,
    survivor_id: UUID,
    source_id: UUID,
    moved: list[UUID],
    sequence_no: int,
    created_at: datetime,
    source_label: str | None = "Source",
    reverted_at: datetime | None = None,
    expires_at: datetime | None = None,
    receipt_id: UUID | None = None,
) -> ClusterMergeReceipt:
    return ClusterMergeReceipt(
        receipt_id=receipt_id or uuid4(),
        tenant_id=tenant_id,
        survivor_cluster_id=survivor_id,
        source_cluster_id=source_id,
        source_label=source_label,
        moved_identity_ids=moved,
        rule_version="c1-policy-v1",
        kind=ClusterMergeKind.AUTO.value,
        created_at=created_at,
        expires_at=expires_at or created_at + timedelta(days=7),
        reverted_at=reverted_at,
        sequence_no=sequence_no,
    )


def _snapshot(cluster: IdentityCluster) -> tuple[int, object, tuple[str, ...]]:
    reps = tuple(rep.identity_id for rep in (cluster.representatives or ()))
    return (cluster.identity_count, cluster.centroid, reps)


def _cleared_moved_by_merge(session: FakeSession) -> bool:
    for stmt in session.statements:
        values = getattr(stmt, "_values", None) or {}
        for column, value in values.items():
            name = getattr(column, "key", None) or getattr(column, "name", None)
            bound = getattr(value, "value", value)
            if name == "moved_by_merge_id" and bound is None:
                return True
        rendered = str(stmt).lower()
        if "moved_by_merge_id" in rendered:
            return True
    return False


def _install_receipt_loaders(
    monkeypatch: pytest.MonkeyPatch,
    receipts: list[ClusterMergeReceipt],
) -> list[tuple[str, UUID, UUID]]:
    lookups: list[tuple[str, UUID, UUID]] = []

    async def load_receipt(session: object, *, tenant_id: UUID, receipt_id: UUID) -> ClusterMergeReceipt | None:
        lookups.append(("receipt", tenant_id, receipt_id))
        for receipt in receipts:
            if receipt.tenant_id == tenant_id and receipt.receipt_id == receipt_id:
                return receipt
        return None

    async def load_siblings(
        session: object, *, tenant_id: UUID, survivor_cluster_id: UUID
    ) -> list[ClusterMergeReceipt]:
        lookups.append(("siblings", tenant_id, survivor_cluster_id))
        return [
            receipt
            for receipt in receipts
            if receipt.tenant_id == tenant_id and receipt.survivor_cluster_id == survivor_cluster_id
        ]

    monkeypatch.setattr(
        "recognition.application.orchestration.cluster_merge._load_receipt",
        load_receipt,
    )
    monkeypatch.setattr(
        "recognition.application.orchestration.cluster_merge._load_sibling_receipts",
        load_siblings,
    )
    return lookups


@pytest.fixture
def revert_world(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    tenant_id = uuid4()
    survivor_id = uuid4()
    source_id = uuid4()
    kept = uuid4()
    moved_a = uuid4()
    moved_b = uuid4()
    cluster_repo = FakeClusterRepo()
    member_repo = FakeMemberRepo()
    survivor = IdentityCluster(
        id=str(survivor_id),
        tenant_id=str(tenant_id),
        is_labeled=True,
        identity_count=3,
        label="Ada",
        clustering_algorithm="graph",
    )
    cluster_repo.clusters[str(survivor_id)] = survivor
    for identity_id, similarity in ((kept, 0.9), (moved_a, 0.8), (moved_b, 0.7)):
        member_repo.by_identity[str(identity_id)] = IdentityMember(
            id=str(uuid4()),
            cluster_id=str(survivor_id),
            identity_id=str(identity_id),
            similarity=similarity,
        )
    receipt = _receipt(
        tenant_id=tenant_id,
        survivor_id=survivor_id,
        source_id=source_id,
        moved=[moved_a, moved_b],
        sequence_no=1,
        created_at=NOW - timedelta(hours=1),
    )
    lookups = _install_receipt_loaders(monkeypatch, [receipt])
    broadcaster = SimpleNamespace(broadcast=AsyncMock(return_value=0))
    monkeypatch.setattr(
        "recognition.application.orchestration.cluster_merge.get_event_broadcaster",
        lambda: broadcaster,
    )
    writer = FakeWriter(cluster_repo, member_repo)
    merge_suggestions = FakeMergeSuggestions()
    session = FakeSession()
    return {
        "tenant_id": tenant_id,
        "survivor_id": survivor_id,
        "source_id": source_id,
        "kept": kept,
        "moved": (moved_a, moved_b),
        "receipt": receipt,
        "cluster_repo": cluster_repo,
        "member_repo": member_repo,
        "writer": writer,
        "session": session,
        "merge_suggestions": merge_suggestions,
        "broadcaster": broadcaster,
        "lookups": lookups,
    }


async def _run_revert(world: dict[str, object], **overrides: object) -> IdentityCluster:
    kwargs = {
        "tenant_id": str(world["tenant_id"]),
        "receipt_id": str(world["receipt"].receipt_id),
        "path_cluster_id": str(world["survivor_id"]),
        "assignment_writer": world["writer"],
        "session": world["session"],
        "merge_suggestion_service": world["merge_suggestions"],
        "now": NOW,
    }
    kwargs.update(overrides)
    return await revert_merge(**kwargs)


@pytest.mark.asyncio
async def test_revert_restores_partition_and_matches_fresh_recompute(revert_world: dict[str, object]) -> None:
    restored = await _run_revert(revert_world)
    source_id = str(revert_world["source_id"])
    survivor_id = str(revert_world["survivor_id"])
    kept = str(revert_world["kept"])
    moved_a, moved_b = (str(item) for item in revert_world["moved"])
    member_repo: FakeMemberRepo = revert_world["member_repo"]
    cluster_repo: FakeClusterRepo = revert_world["cluster_repo"]

    assert restored.id == source_id
    restored_ids = {member.identity_id for member in await member_repo.get_by_cluster(source_id)}
    survivor_ids = {member.identity_id for member in await member_repo.get_by_cluster(survivor_id)}
    assert restored_ids == {moved_a, moved_b}
    assert survivor_ids == {kept}

    survivor = await cluster_repo.get_by_id(survivor_id)
    assert survivor is not None
    before = (_snapshot(restored), _snapshot(survivor))
    writer: FakeWriter = revert_world["writer"]
    await writer.recompute_representatives(source_id)
    await writer.recompute_centroid(source_id)
    await writer.recompute_representatives(survivor_id)
    await writer.recompute_centroid(survivor_id)
    restored_after = await cluster_repo.get_by_id(source_id)
    survivor_after = await cluster_repo.get_by_id(survivor_id)
    assert restored_after is not None and survivor_after is not None
    assert (_snapshot(restored_after), _snapshot(survivor_after)) == before
    assert restored.identity_count == len(restored_ids)
    assert survivor.identity_count == len(survivor_ids)
    assert revert_world["receipt"].reverted_at == NOW
    assert revert_world["merge_suggestions"].deleted == [
        (str(revert_world["tenant_id"]), source_id),
        (str(revert_world["tenant_id"]), survivor_id),
    ]
    revert_world["broadcaster"].broadcast.assert_not_awaited()
    lookups: list[tuple[str, UUID, UUID]] = revert_world["lookups"]
    assert lookups[0][0] == "receipt"
    assert lookups[0][1] == revert_world["tenant_id"]
    assert lookups[0][2] == revert_world["receipt"].receipt_id


@pytest.mark.asyncio
async def test_mv_refresh_failure_leaves_revert_committed(revert_world: dict[str, object]) -> None:
    writer: FakeWriter = revert_world["writer"]
    writer.refresh_centroids_view = AsyncMock(side_effect=RuntimeError("transient MV refresh failure"))
    restored = await _run_revert(revert_world)
    source_id = str(revert_world["source_id"])
    member_repo: FakeMemberRepo = revert_world["member_repo"]
    assert restored.id == source_id
    restored_ids = {member.identity_id for member in await member_repo.get_by_cluster(source_id)}
    assert restored_ids == {str(item) for item in revert_world["moved"]}
    assert revert_world["receipt"].reverted_at == NOW
    writer.refresh_centroids_view.assert_awaited_once()


@pytest.mark.asyncio
async def test_conditional_receipt_claim_refuses_when_row_was_already_claimed(
    revert_world: dict[str, object],
) -> None:
    session: FakeSession = revert_world["session"]
    session.receipt_update_rowcount = 0

    with pytest.raises(ReceiptNotTopError):
        await _run_revert(revert_world)

    assert str(revert_world["source_id"]) not in revert_world["cluster_repo"].clusters
    assert revert_world["receipt"].reverted_at is None


@pytest.mark.asyncio
async def test_source_insert_integrity_error_is_a_deterministic_refusal(
    revert_world: dict[str, object],
) -> None:
    duplicate = IntegrityError("insert", {}, RuntimeError("duplicate source cluster"))
    revert_world["cluster_repo"].save = AsyncMock(side_effect=duplicate)

    with pytest.raises(ReceiptNotTopError):
        await _run_revert(revert_world)

    assert revert_world["session"].rollback_calls == 1
    assert revert_world["receipt"].reverted_at is None
    revert_world["broadcaster"].broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_revert_clears_provenance_so_recovery_cannot_reattach(revert_world: dict[str, object]) -> None:
    await _run_revert(revert_world)
    survivor_ids = {
        member.identity_id
        for member in await revert_world["member_repo"].get_by_cluster(str(revert_world["survivor_id"]))
    }
    restored_ids = {
        member.identity_id
        for member in await revert_world["member_repo"].get_by_cluster(str(revert_world["source_id"]))
    }
    assert restored_ids.isdisjoint(survivor_ids)
    assert _cleared_moved_by_merge(revert_world["session"])
    # A later recovery pass cannot key off moved_by_merge_id to glue the restored cluster back.


@pytest.mark.asyncio
async def test_lifo_two_merges_undo_in_order_and_refuse_non_top(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    survivor_id = uuid4()
    source_a = uuid4()
    source_b = uuid4()
    kept = uuid4()
    moved_a = uuid4()
    moved_b = uuid4()
    cluster_repo = FakeClusterRepo()
    member_repo = FakeMemberRepo()
    cluster_repo.clusters[str(survivor_id)] = IdentityCluster(
        id=str(survivor_id),
        tenant_id=str(tenant_id),
        is_labeled=True,
        identity_count=3,
        label="Ada",
    )
    for identity_id in (kept, moved_a, moved_b):
        member_repo.by_identity[str(identity_id)] = IdentityMember(
            id=str(uuid4()),
            cluster_id=str(survivor_id),
            identity_id=str(identity_id),
            similarity=0.8,
        )
    receipt_a = _receipt(
        tenant_id=tenant_id,
        survivor_id=survivor_id,
        source_id=source_a,
        moved=[moved_a],
        sequence_no=1,
        created_at=NOW - timedelta(hours=2),
        source_label="A",
    )
    receipt_b = _receipt(
        tenant_id=tenant_id,
        survivor_id=survivor_id,
        source_id=source_b,
        moved=[moved_b],
        sequence_no=2,
        created_at=NOW - timedelta(hours=1),
        source_label="B",
    )
    _install_receipt_loaders(monkeypatch, [receipt_a, receipt_b])
    monkeypatch.setattr(
        "recognition.application.orchestration.cluster_merge.get_event_broadcaster",
        lambda: SimpleNamespace(broadcast=AsyncMock(return_value=0)),
    )
    writer = FakeWriter(cluster_repo, member_repo)
    session = FakeSession()

    with pytest.raises(ReceiptNotTopError) as not_top:
        await revert_merge(
            tenant_id=str(tenant_id),
            receipt_id=str(receipt_a.receipt_id),
            path_cluster_id=str(survivor_id),
            assignment_writer=writer,
            session=session,
            now=NOW,
        )
    assert not_top.value.code == "receipt_not_top"

    restored_b = await revert_merge(
        tenant_id=str(tenant_id),
        receipt_id=str(receipt_b.receipt_id),
        path_cluster_id=str(survivor_id),
        assignment_writer=writer,
        session=session,
        now=NOW,
    )
    assert restored_b.id == str(source_b)
    assert {m.identity_id for m in await member_repo.get_by_cluster(str(source_b))} == {str(moved_b)}

    restored_a = await revert_merge(
        tenant_id=str(tenant_id),
        receipt_id=str(receipt_a.receipt_id),
        path_cluster_id=str(survivor_id),
        assignment_writer=writer,
        session=session,
        now=NOW,
    )
    assert restored_a.id == str(source_a)
    assert {m.identity_id for m in await member_repo.get_by_cluster(str(source_a))} == {str(moved_a)}
    assert {m.identity_id for m in await member_repo.get_by_cluster(str(survivor_id))} == {str(kept)}


@pytest.mark.asyncio
async def test_cross_tenant_receipt_lookup_is_not_found(revert_world: dict[str, object]) -> None:
    other_tenant = uuid4()
    with pytest.raises(MergeReceiptNotFoundError):
        await _run_revert(revert_world, tenant_id=str(other_tenant))


@pytest.mark.asyncio
async def test_expired_receipt_is_refused(revert_world: dict[str, object]) -> None:
    revert_world["receipt"].expires_at = NOW - timedelta(seconds=1)
    with pytest.raises(ReceiptExpiredError) as exc:
        await _run_revert(revert_world)
    assert exc.value.code == "receipt_expired"


@pytest.mark.asyncio
async def test_path_mismatch_and_missing_member_and_occupied_source_are_stale(
    revert_world: dict[str, object],
) -> None:
    with pytest.raises(MergeReceiptStaleError):
        await _run_revert(revert_world, path_cluster_id=str(uuid4()))

    member_repo: FakeMemberRepo = revert_world["member_repo"]
    del member_repo.by_identity[str(revert_world["moved"][0])]
    with pytest.raises(MergeReceiptStaleError):
        await _run_revert(revert_world)

    member_repo.by_identity[str(revert_world["moved"][0])] = IdentityMember(
        id=str(uuid4()),
        cluster_id=str(revert_world["survivor_id"]),
        identity_id=str(revert_world["moved"][0]),
        similarity=0.8,
    )
    cluster_repo: FakeClusterRepo = revert_world["cluster_repo"]
    cluster_repo.clusters[str(revert_world["source_id"])] = IdentityCluster(
        id=str(revert_world["source_id"]),
        tenant_id=str(revert_world["tenant_id"]),
        is_labeled=True,
        identity_count=1,
        label="occupied",
    )
    with pytest.raises(MergeReceiptStaleError):
        await _run_revert(revert_world)


@pytest.mark.asyncio
async def test_restored_label_uses_source_or_survivor_name(revert_world: dict[str, object]) -> None:
    revert_world["receipt"].source_label = "Perry"
    restored = await _run_revert(revert_world)
    assert restored.label == "Perry"

    # Second restore path: empty source_label → "<survivor> (restored)"
    revert_world["cluster_repo"].clusters.pop(str(revert_world["source_id"]))
    for identity_id in revert_world["moved"]:
        revert_world["member_repo"].by_identity[str(identity_id)] = IdentityMember(
            id=str(uuid4()),
            cluster_id=str(revert_world["survivor_id"]),
            identity_id=str(identity_id),
            similarity=0.8,
        )
    revert_world["receipt"].source_label = None
    revert_world["receipt"].reverted_at = None
    restored = await _run_revert(revert_world)
    assert restored.label == "Ada (restored)"


def _revert_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenant_id: str,
    impl,
    resolved_tenant_id: str | None = None,
    builder=None,
    session: SimpleNamespace | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(revert_router, prefix="/recognition")
    auth = AuthContext(token=None, tenant_claim=tenant_id, enabled=False)
    app.dependency_overrides[require_auth] = lambda: auth
    app.dependency_overrides[require_write_access] = lambda: auth
    app.dependency_overrides[enforce_rate_limit] = lambda: auth
    app.dependency_overrides[get_tenant_id] = lambda: resolved_tenant_id or tenant_id

    session = session or SimpleNamespace(flush=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session

    async def _builder(_tid: str) -> SimpleNamespace:
        return SimpleNamespace(assignment_writer=object(), merge_suggestion_service=None)

    app.dependency_overrides[get_cluster_service_builder] = lambda: builder or _builder
    monkeypatch.setattr(cluster_revert_module, "revert_merge", impl)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_revert_route_is_post_on_cluster_id_not_legacy_collection() -> None:
    routes = {(frozenset(route.methods or ()), route.path) for route in revert_router.routes}
    assert (frozenset({"POST"}), "/clusters/{cluster_id}/revert-merge") in routes
    assert (frozenset({"POST"}), "/clusters/revert-merge") not in routes


def test_revert_route_returns_source_cluster_id(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid4())
    cluster_id = uuid4()
    source_id = uuid4()
    receipt_id = uuid4()
    seen: dict[str, object] = {}

    async def impl(**kwargs: object) -> IdentityCluster:
        seen.update(kwargs)
        return IdentityCluster(
            id=str(source_id),
            tenant_id=tenant_id,
            is_labeled=True,
            identity_count=2,
            label="Source",
        )

    client = _revert_client(monkeypatch, tenant_id=tenant_id, impl=impl)
    response = client.post(
        f"/recognition/clusters/{cluster_id}/revert-merge",
        json={"receipt_id": str(receipt_id)},
    )
    assert response.status_code == 200
    assert response.json() == {"source_cluster_id": str(source_id)}
    assert seen["tenant_id"] == tenant_id
    assert seen["receipt_id"] == str(receipt_id)
    assert seen["path_cluster_id"] == str(cluster_id)


def test_revert_route_rejects_auth_tenant_mismatch_before_building_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_tenant_id = str(uuid4())
    requested_tenant_id = str(uuid4())
    builder_called = False

    async def builder(_tid: str) -> SimpleNamespace:
        nonlocal builder_called
        builder_called = True
        return SimpleNamespace(assignment_writer=object(), merge_suggestion_service=None)

    async def impl(**kwargs: object) -> IdentityCluster:
        pytest.fail("revert service must not be built for an auth tenant mismatch")

    client = _revert_client(
        monkeypatch,
        tenant_id=auth_tenant_id,
        resolved_tenant_id=requested_tenant_id,
        builder=builder,
        impl=impl,
    )
    response = client.post(
        f"/recognition/clusters/{uuid4()}/revert-merge?tenant_id={requested_tenant_id}",
        json={"receipt_id": str(uuid4())},
    )

    assert response.status_code == 403
    assert not builder_called


def test_revert_route_broadcasts_only_after_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid4())
    source_id = uuid4()
    order: list[str] = []
    session = SimpleNamespace(
        flush=AsyncMock(side_effect=lambda: order.append("flush")),
        commit=AsyncMock(side_effect=lambda: order.append("commit")),
        rollback=AsyncMock(),
    )
    broadcaster = SimpleNamespace(
        broadcast=AsyncMock(side_effect=lambda *args, **kwargs: order.append("broadcast")),
    )
    monkeypatch.setattr(cluster_revert_module, "get_event_broadcaster", lambda: broadcaster)

    async def impl(**kwargs: object) -> tuple[IdentityCluster, dict[str, object]]:
        order.append("service")
        return (
            IdentityCluster(
                id=str(source_id),
                tenant_id=tenant_id,
                is_labeled=True,
                identity_count=2,
                label="Source",
            ),
            {"source_cluster_id": str(source_id), "moved_count": 2},
        )

    client = _revert_client(monkeypatch, tenant_id=tenant_id, impl=impl, session=session)
    response = client.post(
        f"/recognition/clusters/{uuid4()}/revert-merge",
        json={"receipt_id": str(uuid4())},
    )

    assert response.status_code == 200
    assert order == ["service", "flush", "commit", "broadcast"]
    broadcaster.broadcast.assert_awaited_once()


def test_revert_route_does_not_broadcast_when_commit_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid4())
    broadcaster = SimpleNamespace(broadcast=AsyncMock())
    monkeypatch.setattr(cluster_revert_module, "get_event_broadcaster", lambda: broadcaster)
    session = SimpleNamespace(
        flush=AsyncMock(),
        commit=AsyncMock(side_effect=RuntimeError("commit failed")),
        rollback=AsyncMock(),
    )

    async def impl(**kwargs: object) -> IdentityCluster:
        return IdentityCluster(
            id=str(uuid4()),
            tenant_id=tenant_id,
            is_labeled=True,
            identity_count=2,
            label="Source",
        )

    client = _revert_client(
        monkeypatch,
        tenant_id=tenant_id,
        impl=impl,
        session=session,
        raise_server_exceptions=False,
    )
    response = client.post(
        f"/recognition/clusters/{uuid4()}/revert-merge",
        json={"receipt_id": str(uuid4())},
    )

    assert response.status_code == 500
    broadcaster.broadcast.assert_not_awaited()


@pytest.mark.parametrize(
    ("exc", "code", "slug"),
    [
        (ReceiptNotTopError(uuid4()), "receipt_not_top", "receipt-not-top"),
        (ReceiptExpiredError(uuid4()), "receipt_expired", "receipt-expired"),
        (MergeReceiptStaleError(uuid4()), "merge_receipt_stale", "merge-receipt-stale"),
    ],
)
def test_revert_route_maps_refusals_to_problem_details(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    code: str,
    slug: str,
) -> None:
    tenant_id = str(uuid4())
    cluster_id = uuid4()

    async def impl(**kwargs: object) -> IdentityCluster:
        raise exc

    client = _revert_client(monkeypatch, tenant_id=tenant_id, impl=impl)
    response = client.post(
        f"/recognition/clusters/{cluster_id}/revert-merge",
        json={"receipt_id": str(uuid4())},
    )
    assert response.status_code == 409
    assert "application/problem+json" in response.headers.get("content-type", "")
    body = response.json()
    assert body == {
        "type": f"https://context-alt-text.dev/problems/{slug}",
        "title": body["title"],
        "status": 409,
        "code": code,
    }
    assert set(body.keys()) == {"type", "title", "status", "code"}


def test_revert_route_hides_cross_tenant_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid4())
    receipt_id = uuid4()

    async def impl(**kwargs: object) -> IdentityCluster:
        raise MergeReceiptNotFoundError(receipt_id)

    client = _revert_client(monkeypatch, tenant_id=tenant_id, impl=impl)
    response = client.post(
        f"/recognition/clusters/{uuid4()}/revert-merge",
        json={"receipt_id": str(receipt_id)},
    )
    assert response.status_code == 404
    assert str(receipt_id) not in response.text
