"""GPUFLOW-2 C2: pairwise recovery merge with receipts."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import numpy as np
import pytest
from pydantic import ValidationError

from db.models.identity import ClusterMergeKind, ClusterMergeReceipt
from recognition.application.orchestration.clustering.discovery_pipeline import run_singleton_hac_refinement
from recognition.application.orchestration.clustering.recovery_merge import (
    InMemoryReceiptStore,
    RecordingSuggestionEmitter,
    RecoveryAbstainClause,
    RecoveryCluster,
    RecoveryMergeResult,
    RecoveryMember,
    RECOVERY_REVERT_BLOCK_REASON,
    _clusters_from_identities,
    evaluate_residual_admission,
    run_recovery_merge,
    run_recovery_merge_on_clusters,
)
from recognition.application.settings import HACSettings
from recognition.application.settings.clustering import (
    CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK,
    CalibrationApplyMode,
    ClusteringSettings,
    EmbeddingSpaceBinding,
    calibration_policy_is_applicable,
    default_cluster_recovery_calibration_policy,
    load_cluster_recovery_calibration_policy,
)
from recognition.domain.identity import MediaIdentity


def _unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / float(np.linalg.norm(vector))


def _accepted_policy(*, model: str = "test-space", dims: int = 3):
    raw = copy.deepcopy(CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK)
    raw["status"] = "accepted"
    raw["apply_mode"] = "accepted"
    raw["binding"] = {
        "embedding_model_id": model,
        "embedding_model_revision": "rev-1",
        "embedding_dimensionality": dims,
        "distance_metric": "cosine",
        "dataset_manifest_digest": "manifest-1",
        "calibration_run_digest": "calib-1",
        "require_all_runtime_fields_match": True,
        "apply_only_when": CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK["binding"]["apply_only_when"],
    }
    raw["abstained_strata"] = {
        "key_format": "<quality_band>×<operating_condition>",
        "selection": "cartesian_product",
        "quality_bands": [],
        "operating_conditions": [],
    }
    return load_cluster_recovery_calibration_policy(raw)


def _binding(*, model: str = "test-space", dims: int = 3) -> EmbeddingSpaceBinding:
    return EmbeddingSpaceBinding(
        embedding_model_id=model,
        embedding_model_revision="rev-1",
        embedding_dimensionality=dims,
        distance_metric="cosine",
        dataset_manifest_digest="manifest-1",
        calibration_run_digest="calib-1",
    )


def _member(
    embedding: np.ndarray,
    *,
    cluster_id: str,
    media_id: str,
    identity_id: str | None = None,
    quality_score: float = 0.95,
    operating_condition: str = "clear",
    embedding_model: str = "test-space",
) -> RecoveryMember:
    return RecoveryMember(
        identity_id=identity_id or str(uuid4()),
        cluster_id=cluster_id,
        embedding=embedding,
        media_id=media_id,
        quality_score=quality_score,
        operating_condition=operating_condition,
        embedding_model=embedding_model,
    )


def _cluster(
    members: list[RecoveryMember],
    *,
    cluster_id: str | None = None,
    label: str | None = None,
    user_confirmed: bool = False,
) -> RecoveryCluster:
    return RecoveryCluster(
        cluster_id=cluster_id or str(uuid4()),
        members=members,
        label=label,
        user_confirmed=user_confirmed,
        embedding_model=members[0].embedding_model if members else None,
    )


def _enabled_settings() -> ClusteringSettings:
    return ClusteringSettings(recovery_merge_enabled=True)


def _recovery_clusters_for_revert(
    destination_id: str,
    residual_id: str,
    residual_identity_id: str,
) -> tuple[RecoveryCluster, RecoveryCluster]:
    destination = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id=destination_id, media_id="d1"),
            _member(_unit(0.99, 0.1, 0.0), cluster_id=destination_id, media_id="d2"),
        ],
        cluster_id=destination_id,
    )
    residual = _cluster(
        [
            _member(
                _unit(0.98, 0.2, 0.0),
                cluster_id=residual_id,
                media_id="r1",
                identity_id=residual_identity_id,
            )
        ],
        cluster_id=residual_id,
    )
    return destination, residual


class _FakeResult:
    def __init__(
        self,
        *,
        scalar: int | None = None,
        scalars: list[object] | None = None,
        rows: list[object] | None = None,
        rowcount: int | None = None,
    ) -> None:
        self._scalar = scalar
        self._scalars = scalars or []
        self._rows = rows or []
        self.rowcount = rowcount

    def scalars(self) -> _FakeResult:
        return self

    def scalar_one(self) -> int | None:
        return self._scalar

    def all(self) -> list[object]:
        return self._scalars if self._scalars else self._rows


class _FakeNestedTransaction:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self._events = events

    async def __aenter__(self) -> _FakeNestedTransaction:
        self._events.append(("begin_nested", None))
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self._events.append(("end_nested", None))


class _RecordingSession:
    def __init__(self, responses: list[tuple[str, _FakeResult]]) -> None:
        self._responses = responses
        self.events: list[tuple[str, object]] = []

    async def execute(self, _statement: object) -> _FakeResult:
        label, result = self._responses.pop(0)
        self.events.append(("execute", label))
        return result

    def begin_nested(self) -> _FakeNestedTransaction:
        return _FakeNestedTransaction(self.events)

    def add(self, model: object) -> None:
        self.events.append(("add", model))

    async def flush(self) -> None:
        self.events.append(("flush", None))


def _planned_receipt(
    *,
    tenant_id: str,
    survivor_id: str,
    source_id: str,
    identity_id: str,
) -> ClusterMergeReceipt:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    return ClusterMergeReceipt(
        receipt_id=uuid4(),
        tenant_id=UUID(tenant_id),
        survivor_cluster_id=UUID(survivor_id),
        source_cluster_id=UUID(source_id),
        source_label=None,
        moved_identity_ids=[UUID(identity_id)],
        rule_version="accepted-v1",
        kind=ClusterMergeKind.AUTO.value,
        created_at=now,
        expires_at=now + timedelta(days=7),
        sequence_no=1,
    )


@pytest.mark.asyncio
async def test_flag_off_is_noop() -> None:
    policy = _accepted_policy()
    dest = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id="d", media_id="m1"),
            _member(_unit(0.99, 0.1, 0.0), cluster_id="d", media_id="m2"),
        ],
        cluster_id="d",
    )
    residual = _cluster(
        [_member(_unit(0.98, 0.2, 0.0), cluster_id="r", media_id="m3")],
        cluster_id="r",
    )
    store = InMemoryReceiptStore()
    emitter = RecordingSuggestionEmitter()
    result = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
        clusters=[dest, residual],
        settings=ClusteringSettings(recovery_merge_enabled=False),
        policy=policy,
        runtime_binding=_binding(),
        receipt_store=store,
        suggestion_emitter=emitter,
    )
    assert result.merged == 0
    assert result.applied is False
    assert store.receipts == []
    assert emitter.calls == []
    assert residual.identity_count == 1


def test_default_policy_is_disabled_until_accepted() -> None:
    policy = default_cluster_recovery_calibration_policy()
    assert policy.apply_mode is CalibrationApplyMode.DISABLED_UNTIL_ACCEPTED
    assert policy.rule_version == CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK["rule_version"]
    assert policy.tau_pair == 0.55
    assert policy.min_agreeing_exemplars == 2
    assert ClusteringSettings().recovery_merge_enabled is False


def test_policy_loader_rejects_unknown_keys() -> None:
    raw = copy.deepcopy(CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK)
    raw["not_a_calibration_key"] = 1
    with pytest.raises(ValidationError):
        load_cluster_recovery_calibration_policy(raw)


def test_policy_refuses_thresholds_when_binding_differs() -> None:
    policy = _accepted_policy(model="space-a")
    runtime = _binding(model="space-b")
    assert calibration_policy_is_applicable(policy, runtime) is False
    default_policy = default_cluster_recovery_calibration_policy()
    assert calibration_policy_is_applicable(default_policy, _binding()) is False


def test_recovery_uses_persisted_quality_and_explicit_unknown_condition() -> None:
    cluster_id = str(uuid4())
    identity_id = str(uuid4())
    identity = MediaIdentity(
        id=identity_id,
        tenant_id=str(uuid4()),
        media_id="media-1",
        embedding=_unit(1.0, 0.0, 0.0),
        confidence=0.99,
        bbox_width=10,
        bbox_height=10,
        embedding_model="test-space",
    )
    cluster = SimpleNamespace(id=cluster_id, label=None, user_confirmed=False)

    without_persisted_fields = _clusters_from_identities([cluster], {cluster_id: [identity]})
    assert without_persisted_fields[0].members[0].quality_score is None
    assert without_persisted_fields[0].members[0].operating_condition == "unknown"

    persisted = {
        identity_id: (cluster_id, identity.embedding, "test-space", 0.1, "media-1"),
    }
    with_persisted_fields = _clusters_from_identities(
        [cluster],
        {cluster_id: [identity]},
        persisted,
    )
    member = with_persisted_fields[0].members[0]
    assert member.quality_score == 0.1
    assert member.operating_condition == "unknown"
    assert member.quality_score != identity.confidence


@pytest.mark.asyncio
async def test_foreign_destination_members_are_dropped_before_centroid_math() -> None:
    destination_id = str(uuid4())
    residual_id = str(uuid4())
    foreign_identity_id = str(uuid4())
    destination = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id=destination_id, media_id="d1"),
            _member(_unit(0.99, 0.1, 0.0), cluster_id=destination_id, media_id="d2"),
            _member(
                _unit(0.0, 0.0, 1.0),
                cluster_id=destination_id,
                media_id="foreign",
                identity_id=foreign_identity_id,
                embedding_model="foreign-space",
            ),
        ],
        cluster_id=destination_id,
    )
    residual = _cluster(
        [_member(_unit(0.98, 0.2, 0.0), cluster_id=residual_id, media_id="r1")],
        cluster_id=residual_id,
    )

    result = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
        clusters=[destination, residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=InMemoryReceiptStore(),
    )

    assert result.merged == 1
    assert foreign_identity_id not in {member.identity_id for member in destination.members}


@pytest.mark.asyncio
async def test_foreign_or_wrong_dimension_residual_abstains_without_cosine_error() -> None:
    destination_id = str(uuid4())
    residual_id = str(uuid4())
    destination = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id=destination_id, media_id="d1"),
            _member(_unit(0.99, 0.1, 0.0), cluster_id=destination_id, media_id="d2"),
        ],
        cluster_id=destination_id,
    )
    foreign = _member(
        _unit(0.98, 0.2, 0.0),
        cluster_id=residual_id,
        media_id="foreign",
        embedding_model="foreign-space",
    )
    wrong_dimension = _member(
        np.array([1.0, 0.0], dtype=np.float32),
        cluster_id=residual_id,
        media_id="wrong-dimension",
    )
    residual = _cluster([foreign, wrong_dimension], cluster_id=residual_id)

    result = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
        clusters=[destination, residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=InMemoryReceiptStore(),
    )

    assert result.merged == 0
    assert result.abstentions[0].failing_clause is RecoveryAbstainClause.EMBEDDING_SPACE_MISMATCH


@pytest.mark.asyncio
async def test_reverted_merge_block_survives_receipt_purge_and_membership_change() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    destination_id = str(uuid4())
    residual_id = str(uuid4())
    residual_identity_id = str(uuid4())
    tenant_id = str(uuid4())
    store = InMemoryReceiptStore()

    destination, residual = _recovery_clusters_for_revert(destination_id, residual_id, residual_identity_id)
    first = await run_recovery_merge_on_clusters(
        tenant_id=tenant_id,
        clusters=[destination, residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=store,
        now=now,
    )
    receipt = first.receipts[0]
    receipt.reverted_at = now
    await store.add(receipt)
    await store.add_block(
        tenant_id=tenant_id,
        identity_id=residual_identity_id,
        blocked_cluster_id=destination_id,
    )

    destination, residual = _recovery_clusters_for_revert(destination_id, residual_id, residual_identity_id)
    emitter = RecordingSuggestionEmitter()
    blocked = await run_recovery_merge_on_clusters(
        tenant_id=tenant_id,
        clusters=[destination, residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=store,
        suggestion_emitter=emitter,
        now=now + timedelta(hours=1),
    )
    assert blocked.merged == 0
    assert blocked.abstentions[0].failing_clause is RecoveryAbstainClause.REVERTED_MERGE_EXCLUDED
    assert RecoveryAbstainClause.REVERTED_MERGE_EXCLUDED in emitter.clauses
    assert emitter.calls
    assert store.receipts == []
    assert len(store.blocks) == 1
    assert store.blocks[0].reason == RECOVERY_REVERT_BLOCK_REASON

    new_identity_id = str(uuid4())
    destination, residual = _recovery_clusters_for_revert(destination_id, residual_id, residual_identity_id)
    residual.members.append(
        _member(
            _unit(0.97, 0.24, 0.0),
            cluster_id=residual_id,
            media_id="r2",
            identity_id=new_identity_id,
        )
    )
    destination.members.extend(
        [
            _member(
                _unit(0.98, 0.16, 0.0),
                cluster_id=destination_id,
                media_id="d3",
            ),
            _member(
                _unit(0.97, 0.2, 0.0),
                cluster_id=destination_id,
                media_id="d4",
            ),
        ]
    )
    after_membership_change = await run_recovery_merge_on_clusters(
        tenant_id=tenant_id,
        clusters=[destination, residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=store,
        now=now + timedelta(days=1),
    )
    assert after_membership_change.merged == 0
    assert after_membership_change.abstentions[0].failing_clause is RecoveryAbstainClause.REVERTED_MERGE_EXCLUDED
    assert store.receipts == []


@pytest.mark.asyncio
async def test_active_block_only_rejects_its_destination_and_expired_block_is_ignored() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    tenant_id = str(uuid4())
    blocked_destination_id = str(uuid4())
    allowed_destination_id = str(uuid4())
    residual_id = str(uuid4())
    residual_identity_id = str(uuid4())
    blocked_destination = _cluster(
        [
            _member(_unit(0.0, 1.0, 0.0), cluster_id=blocked_destination_id, media_id="b1"),
            _member(_unit(0.0, 0.99, 0.1), cluster_id=blocked_destination_id, media_id="b2"),
        ],
        cluster_id=blocked_destination_id,
    )
    allowed_destination = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id=allowed_destination_id, media_id="a1"),
            _member(_unit(0.99, 0.1, 0.0), cluster_id=allowed_destination_id, media_id="a2"),
        ],
        cluster_id=allowed_destination_id,
    )
    residual = _cluster(
        [
            _member(
                _unit(0.98, 0.2, 0.0),
                cluster_id=residual_id,
                media_id="r1",
                identity_id=residual_identity_id,
            )
        ],
        cluster_id=residual_id,
    )
    store = InMemoryReceiptStore()
    await store.add_block(
        tenant_id=tenant_id,
        identity_id=residual_identity_id,
        blocked_cluster_id=blocked_destination_id,
    )
    result = await run_recovery_merge_on_clusters(
        tenant_id=tenant_id,
        clusters=[blocked_destination, allowed_destination, residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=store,
        now=now,
    )
    assert result.merged == 1
    assert str(result.receipts[0].survivor_cluster_id) == allowed_destination_id

    expired_destination, expired_residual = _recovery_clusters_for_revert(
        allowed_destination_id,
        residual_id,
        residual_identity_id,
    )
    expired_store = InMemoryReceiptStore()
    await expired_store.add_block(
        tenant_id=tenant_id,
        identity_id=residual_identity_id,
        blocked_cluster_id=allowed_destination_id,
        expires_at=now - timedelta(seconds=1),
    )
    expired_result = await run_recovery_merge_on_clusters(
        tenant_id=tenant_id,
        clusters=[expired_destination, expired_residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=expired_store,
        now=now,
    )
    assert expired_result.merged == 1


@pytest.mark.asyncio
async def test_singleton_hac_runs_recovery_once_for_each_early_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.application.orchestration.clustering import recovery_merge

    recovery = AsyncMock()
    monkeypatch.setattr(recovery_merge, "run_recovery_merge", recovery)
    tenant_id = str(uuid4())

    await run_singleton_hac_refinement(
        tenant_id=tenant_id,
        constrained_hac=None,
        hac_settings=None,
        assignment_writer=SimpleNamespace(),
    )

    class OneSingletonRepository:
        async def get_singleton_identities(self, _tenant_id: str, *, limit: int) -> list[object]:
            return [object()]

    await run_singleton_hac_refinement(
        tenant_id=tenant_id,
        constrained_hac=object(),
        hac_settings=HACSettings(max_scope_size=10),
        assignment_writer=SimpleNamespace(
            cluster_repository=OneSingletonRepository(),
            member_repository=SimpleNamespace(),
        ),
    )

    class TwoUnusableSingletonRepository:
        async def get_singleton_identities(self, _tenant_id: str, *, limit: int) -> list[object]:
            return [SimpleNamespace(cluster_id=None), SimpleNamespace(cluster_id=None)]

    await run_singleton_hac_refinement(
        tenant_id=tenant_id,
        constrained_hac=object(),
        hac_settings=HACSettings(max_scope_size=10),
        assignment_writer=SimpleNamespace(
            cluster_repository=TwoUnusableSingletonRepository(),
            member_repository=SimpleNamespace(),
        ),
    )

    assert recovery.await_count == 3


@pytest.mark.asyncio
async def test_c1_fixture_replay_does_not_auto_merge() -> None:
    """Watson residues stay partitioned under the verbatim C1 policy (apply_mode disabled)."""
    w1 = _cluster([_member(_unit(1.0, 0.0, 0.0), cluster_id="w1", media_id="w-media-1")], cluster_id="w1")
    w2 = _cluster([_member(_unit(0.99, 0.1, 0.0), cluster_id="w2", media_id="w-media-2")], cluster_id="w2")
    w3 = _cluster([_member(_unit(0.98, 0.2, 0.0), cluster_id="w3", media_id="w-media-3")], cluster_id="w3")
    store = InMemoryReceiptStore()
    result = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
        clusters=[w1, w2, w3],
        settings=_enabled_settings(),
        policy=default_cluster_recovery_calibration_policy(),
        runtime_binding=_binding(),
        receipt_store=store,
        suggestion_emitter=RecordingSuggestionEmitter(),
    )
    assert result.merged == 0
    assert result.applied is False
    assert store.receipts == []
    assert w1.identity_count == w2.identity_count == w3.identity_count == 1


@pytest.mark.asyncio
async def test_mixed_unnamed_residual_is_abstained_naming_failing_member() -> None:
    perry_dest_id = str(uuid4())
    trudeau_dest_id = str(uuid4())
    residual_id = str(uuid4())
    perry_press_id = str(uuid4())
    trudeau_press_id = str(uuid4())
    perry = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id=perry_dest_id, media_id="perry-g1"),
            _member(_unit(0.99, 0.05, 0.0), cluster_id=perry_dest_id, media_id="perry-g2"),
            _member(_unit(0.98, 0.1, 0.0), cluster_id=perry_dest_id, media_id="perry-g3"),
            _member(_unit(0.97, 0.12, 0.0), cluster_id=perry_dest_id, media_id="perry-g4"),
        ],
        cluster_id=perry_dest_id,
        label="Katy Perry",
        user_confirmed=True,
    )
    trudeau = _cluster(
        [
            _member(_unit(0.0, 1.0, 0.0), cluster_id=trudeau_dest_id, media_id="trudeau-g1"),
            _member(_unit(0.05, 0.99, 0.0), cluster_id=trudeau_dest_id, media_id="trudeau-g2"),
            _member(_unit(0.1, 0.98, 0.0), cluster_id=trudeau_dest_id, media_id="trudeau-g3"),
            _member(_unit(0.12, 0.97, 0.0), cluster_id=trudeau_dest_id, media_id="trudeau-g4"),
        ],
        cluster_id=trudeau_dest_id,
        label="Justin Trudeau",
        user_confirmed=True,
    )
    mixed = _cluster(
        [
            _member(
                _unit(1.0, 0.0, 0.0),
                cluster_id=residual_id,
                media_id="press-right",
                identity_id=perry_press_id,
            ),
            _member(
                _unit(0.0, 1.0, 0.0),
                cluster_id=residual_id,
                media_id="press-left",
                identity_id=trudeau_press_id,
            ),
        ],
        cluster_id=residual_id,
    )
    emitter = RecordingSuggestionEmitter()
    store = InMemoryReceiptStore()
    result = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
        clusters=[perry, trudeau, mixed],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=store,
        suggestion_emitter=emitter,
    )
    assert result.merged == 0
    assert store.receipts == []
    assert mixed.identity_count == 2
    assert result.abstentions
    failing = result.abstentions[0]
    assert failing.residual_cluster_id == residual_id
    assert failing.failing_member_id == trudeau_press_id
    assert failing.failing_clause in {
        RecoveryAbstainClause.INTRA_INCOHERENT,
        RecoveryAbstainClause.INSUFFICIENT_EXEMPLARS,
        RecoveryAbstainClause.COMPETING_MARGIN,
    }
    assert emitter.failing_members == [trudeau_press_id]


@pytest.mark.asyncio
async def test_borderline_chain_is_abstained() -> None:
    """Best-edge bridge (A close to B only) does not admit A into {B, C}."""
    dest_id = str(uuid4())
    residual_id = str(uuid4())
    dest = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id=dest_id, media_id="b-media"),
            _member(_unit(0.0, 1.0, 0.0), cluster_id=dest_id, media_id="c-media"),
        ],
        cluster_id=dest_id,
    )
    residual = _cluster(
        [_member(_unit(0.98, 0.2, 0.0), cluster_id=residual_id, media_id="a-media")],
        cluster_id=residual_id,
    )
    emitter = RecordingSuggestionEmitter()
    result = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
        clusters=[dest, residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=InMemoryReceiptStore(),
        suggestion_emitter=emitter,
    )
    assert result.merged == 0
    assert residual.identity_count == 1
    assert result.abstentions[0].failing_clause is RecoveryAbstainClause.INSUFFICIENT_EXEMPLARS
    assert emitter.calls


@pytest.mark.asyncio
async def test_no_merge_across_two_named_persons() -> None:
    dest_id = str(uuid4())
    residual_id = str(uuid4())
    dest = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id=dest_id, media_id="d1"),
            _member(_unit(0.99, 0.1, 0.0), cluster_id=dest_id, media_id="d2"),
        ],
        cluster_id=dest_id,
        label="Ada",
        user_confirmed=True,
    )
    residual = _cluster(
        [_member(_unit(0.98, 0.2, 0.0), cluster_id=residual_id, media_id="r1")],
        cluster_id=residual_id,
        label="Bea",
        user_confirmed=True,
    )
    result = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
        clusters=[dest, residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=InMemoryReceiptStore(),
        suggestion_emitter=RecordingSuggestionEmitter(),
    )
    assert result.merged == 0
    assert result.abstentions[0].failing_clause is RecoveryAbstainClause.NAMED_PERSON_CONFLICT
    assert residual.identity_count == 1


@pytest.mark.asyncio
async def test_two_runs_into_one_survivor_plan_two_receipts() -> None:
    dest_id = str(uuid4())
    r1_id = str(uuid4())
    r2_id = str(uuid4())
    dest = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id=dest_id, media_id="d1"),
            _member(_unit(0.99, 0.1, 0.0), cluster_id=dest_id, media_id="d2"),
        ],
        cluster_id=dest_id,
    )
    r1 = _cluster(
        [_member(_unit(0.98, 0.2, 0.0), cluster_id=r1_id, media_id="r1-media")],
        cluster_id=r1_id,
    )
    r2 = _cluster(
        [_member(_unit(0.97, 0.24, 0.0), cluster_id=r2_id, media_id="r2-media")],
        cluster_id=r2_id,
    )
    store = InMemoryReceiptStore()
    settings = _enabled_settings()
    policy = _accepted_policy()
    binding = _binding()
    tenant_id = str(uuid4())
    first = await run_recovery_merge_on_clusters(
        tenant_id=tenant_id,
        clusters=[dest, r1],
        settings=settings,
        policy=policy,
        runtime_binding=binding,
        receipt_store=store,
    )
    assert first.merged == 1
    assert len(store.receipts) == 0
    assert first.receipts[0].kind == ClusterMergeKind.AUTO.value
    await store.add(first.receipts[0])
    second = await run_recovery_merge_on_clusters(
        tenant_id=tenant_id,
        clusters=[dest, r2],
        settings=settings,
        policy=policy,
        runtime_binding=binding,
        receipt_store=store,
    )
    assert second.merged == 1
    assert len(store.receipts) == 1
    assert {str(receipt.source_cluster_id) for receipt in (*store.receipts, second.receipts[0])} == {r1_id, r2_id}
    assert {str(receipt.survivor_cluster_id) for receipt in (*store.receipts, second.receipts[0])} == {dest_id}
    assert dest.identity_count == 4


@pytest.mark.asyncio
async def test_expired_and_reverted_receipts_are_purged() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    store = InMemoryReceiptStore()
    survivor = uuid4()
    tenant = uuid4()
    expired = ClusterMergeReceipt(
        receipt_id=uuid4(),
        tenant_id=tenant,
        survivor_cluster_id=survivor,
        source_cluster_id=uuid4(),
        source_label=None,
        moved_identity_ids=[uuid4()],
        rule_version="old",
        kind=ClusterMergeKind.AUTO.value,
        created_at=now - timedelta(days=10),
        expires_at=now - timedelta(days=3),
        sequence_no=1,
    )
    reverted = ClusterMergeReceipt(
        receipt_id=uuid4(),
        tenant_id=tenant,
        survivor_cluster_id=survivor,
        source_cluster_id=uuid4(),
        source_label=None,
        moved_identity_ids=[uuid4()],
        rule_version="old",
        kind=ClusterMergeKind.AUTO.value,
        created_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=6),
        reverted_at=now - timedelta(hours=1),
        sequence_no=2,
    )
    live = ClusterMergeReceipt(
        receipt_id=uuid4(),
        tenant_id=tenant,
        survivor_cluster_id=survivor,
        source_cluster_id=uuid4(),
        source_label=None,
        moved_identity_ids=[uuid4()],
        rule_version="old",
        kind=ClusterMergeKind.AUTO.value,
        created_at=now - timedelta(hours=2),
        expires_at=now + timedelta(days=6),
        sequence_no=3,
    )
    store.receipts.extend([expired, reverted, live])
    result = await run_recovery_merge_on_clusters(
        tenant_id=str(tenant),
        clusters=[],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=store,
        now=now,
    )
    assert result.purged_receipts == 2
    assert [receipt.receipt_id for receipt in store.receipts] == [live.receipt_id]


@pytest.mark.asyncio
async def test_admitted_merge_writes_auto_receipt() -> None:
    dest_id = str(uuid4())
    residual_id = str(uuid4())
    dest = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id=dest_id, media_id="d1"),
            _member(_unit(0.99, 0.1, 0.0), cluster_id=dest_id, media_id="d2"),
        ],
        cluster_id=dest_id,
        label="Ada",
        user_confirmed=True,
    )
    residual = _cluster(
        [_member(_unit(0.98, 0.2, 0.0), cluster_id=residual_id, media_id="r1")],
        cluster_id=residual_id,
    )
    store = InMemoryReceiptStore()
    now = datetime(2026, 9, 17, tzinfo=UTC)
    result = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
        clusters=[dest, residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=store,
        now=now,
    )
    assert result.merged == 1
    assert residual.identity_count == 0
    assert dest.identity_count == 3
    receipt = result.receipts[0]
    assert receipt.kind == ClusterMergeKind.AUTO.value
    assert str(receipt.survivor_cluster_id) == dest_id
    assert str(receipt.source_cluster_id) == residual_id
    assert receipt.expires_at == now + timedelta(days=7)
    assert receipt.rule_version == _accepted_policy().rule_version


def _durable_apply_fixture(
    *,
    session: _RecordingSession,
    destination_id: str,
) -> SimpleNamespace:
    cluster_repository = SimpleNamespace(
        get_by_tenant=AsyncMock(
            return_value=[SimpleNamespace(id=destination_id, label=None, user_confirmed=False)]
        )
    )
    assignment_writer = SimpleNamespace(
        _session=session,
        cluster_repository=cluster_repository,
        recompute_representatives=AsyncMock(),
        recompute_centroid=AsyncMock(),
        refresh_centroids_view=AsyncMock(),
    )
    return assignment_writer


@pytest.mark.asyncio
async def test_durable_apply_orders_lock_count_exact_move_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from recognition.application.orchestration.clustering import recovery_merge

    tenant_id = str(uuid4())
    destination_id = str(uuid4())
    source_id = str(uuid4())
    identity_id = str(uuid4())
    receipt = _planned_receipt(
        tenant_id=tenant_id,
        survivor_id=destination_id,
        source_id=source_id,
        identity_id=identity_id,
    )
    session = _RecordingSession(
        [
            ("reverted_receipts", _FakeResult()),
            (
                "lock",
                _FakeResult(
                    scalars=[
                        SimpleNamespace(id=UUID(source_id)),
                        SimpleNamespace(id=UUID(destination_id)),
                    ]
                ),
            ),
            ("source_count", _FakeResult(scalar=1)),
            ("move", _FakeResult(rowcount=1)),
            ("remaining", _FakeResult(scalar=0)),
            ("siblings", _FakeResult()),
            ("destination_update", _FakeResult(rowcount=1)),
            ("source_delete", _FakeResult(rowcount=1)),
        ]
    )
    assignment_writer = _durable_apply_fixture(
        session=session,
        destination_id=destination_id,
    )
    monkeypatch.setattr(
        recovery_merge,
        "_load_persisted_recovery_fields",
        AsyncMock(
            return_value={
                identity_id: (
                    destination_id,
                    _unit(1.0, 0.0, 0.0),
                    "test-space",
                    0.95,
                    "media-1",
                )
            }
        ),
    )
    monkeypatch.setattr(
        recovery_merge,
        "run_recovery_merge_on_clusters",
        AsyncMock(return_value=RecoveryMergeResult(merged=1, receipts=(receipt,), applied=True)),
    )

    result = await run_recovery_merge(
        tenant_id=tenant_id,
        assignment_writer=assignment_writer,
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
    )

    assert result.merged == 1
    execute_labels = [value for kind, value in session.events if kind == "execute"]
    assert execute_labels == [
        "reverted_receipts",
        "lock",
        "source_count",
        "move",
        "remaining",
        "siblings",
        "destination_update",
        "source_delete",
    ]
    move_index = session.events.index(("execute", "move"))
    receipt_add_index = next(index for index, event in enumerate(session.events) if event[0] == "add")
    assert session.events.index(("execute", "lock")) < session.events.index(("execute", "source_count"))
    assert session.events.index(("execute", "source_count")) < move_index < receipt_add_index
    assert sum(kind == "add" for kind, _value in session.events) == 1


@pytest.mark.asyncio
async def test_durable_apply_cas_miss_retains_source_and_writes_no_receipt(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from recognition.application.orchestration.clustering import recovery_merge

    tenant_id = str(uuid4())
    destination_id = str(uuid4())
    source_id = str(uuid4())
    identity_id = str(uuid4())
    receipt = _planned_receipt(
        tenant_id=tenant_id,
        survivor_id=destination_id,
        source_id=source_id,
        identity_id=identity_id,
    )
    session = _RecordingSession(
        [
            ("reverted_receipts", _FakeResult()),
            (
                "lock",
                _FakeResult(
                    scalars=[
                        SimpleNamespace(id=UUID(source_id)),
                        SimpleNamespace(id=UUID(destination_id)),
                    ]
                ),
            ),
            ("source_count", _FakeResult(scalar=2)),
        ]
    )
    assignment_writer = _durable_apply_fixture(
        session=session,
        destination_id=destination_id,
    )
    monkeypatch.setattr(
        recovery_merge,
        "_load_persisted_recovery_fields",
        AsyncMock(
            return_value={
                identity_id: (
                    destination_id,
                    _unit(1.0, 0.0, 0.0),
                    "test-space",
                    0.95,
                    "media-1",
                )
            }
        ),
    )
    monkeypatch.setattr(
        recovery_merge,
        "run_recovery_merge_on_clusters",
        AsyncMock(return_value=RecoveryMergeResult(merged=1, receipts=(receipt,), applied=True)),
    )

    with caplog.at_level("INFO", logger=recovery_merge.__name__):
        result = await run_recovery_merge(
            tenant_id=tenant_id,
            assignment_writer=assignment_writer,
            settings=_enabled_settings(),
            policy=_accepted_policy(),
            runtime_binding=_binding(),
        )

    assert result.merged == 0
    assert result.receipts == ()
    assert "recovery_merge_cas_miss" in caplog.text
    execute_labels = [value for kind, value in session.events if kind == "execute"]
    assert execute_labels == ["reverted_receipts", "lock", "source_count"]
    assert not any(kind == "add" for kind, _value in session.events)


@pytest.mark.asyncio
async def test_durable_run_materializes_revert_block_before_planning_and_purges_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid4())
    destination_id = str(uuid4())
    residual_id = str(uuid4())
    blocked_identity_id = str(uuid4())
    now = datetime(2026, 9, 17, tzinfo=UTC)
    reverted_receipt = ClusterMergeReceipt(
        receipt_id=uuid4(),
        tenant_id=UUID(tenant_id),
        survivor_cluster_id=UUID(destination_id),
        source_cluster_id=UUID(residual_id),
        source_label=None,
        moved_identity_ids=[UUID(blocked_identity_id)],
        rule_version="accepted-v1",
        kind=ClusterMergeKind.AUTO.value,
        created_at=now - timedelta(hours=1),
        expires_at=now + timedelta(days=6),
        reverted_at=now - timedelta(minutes=1),
        sequence_no=1,
    )
    destination_identity_ids = [str(uuid4()), str(uuid4())]
    session = _RecordingSession(
        [
            ("reverted_receipts", _FakeResult(scalars=[reverted_receipt])),
            ("identity_rows", _FakeResult(scalars=[UUID(blocked_identity_id)])),
            ("existing_blocks", _FakeResult()),
            ("destination_siblings", _FakeResult()),
            ("residual_siblings", _FakeResult()),
            (
                "active_blocks",
                _FakeResult(rows=[(UUID(blocked_identity_id), UUID(destination_id))]),
            ),
            ("purge", _FakeResult(rowcount=1)),
        ]
    )
    cluster_repository = SimpleNamespace(
        get_by_tenant=AsyncMock(
            return_value=[
                SimpleNamespace(id=destination_id, label=None, user_confirmed=False),
                SimpleNamespace(id=residual_id, label=None, user_confirmed=False),
            ]
        )
    )
    assignment_writer = SimpleNamespace(
        _session=session,
        cluster_repository=cluster_repository,
        recompute_representatives=AsyncMock(),
        recompute_centroid=AsyncMock(),
        refresh_centroids_view=AsyncMock(),
    )

    persisted_fields = {
        destination_identity_ids[0]: (
            destination_id,
            _unit(1.0, 0.0, 0.0),
            "test-space",
            0.95,
            "d1",
        ),
        destination_identity_ids[1]: (
            destination_id,
            _unit(0.99, 0.1, 0.0),
            "test-space",
            0.95,
            "d2",
        ),
        blocked_identity_id: (
            residual_id,
            _unit(0.98, 0.2, 0.0),
            "test-space",
            0.95,
            "r1",
        ),
    }
    monkeypatch.setattr(
        "recognition.application.orchestration.clustering.recovery_merge._load_persisted_recovery_fields",
        AsyncMock(return_value=persisted_fields),
    )

    result = await run_recovery_merge(
        tenant_id=tenant_id,
        assignment_writer=assignment_writer,
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        now=now,
    )

    assert result.merged == 0
    assert result.purged_receipts == 1
    assert result.abstentions[0].failing_clause is RecoveryAbstainClause.REVERTED_MERGE_EXCLUDED
    added_blocks = [model for kind, model in session.events if kind == "add"]
    assert len(added_blocks) == 1
    assert str(added_blocks[0].identity_id) == blocked_identity_id
    assert str(added_blocks[0].blocked_cluster_id) == destination_id
    assert added_blocks[0].reason == RECOVERY_REVERT_BLOCK_REASON
    assert added_blocks[0].expires_at is None
    execute_labels = [value for kind, value in session.events if kind == "execute"]
    assert execute_labels[:3] == ["reverted_receipts", "identity_rows", "existing_blocks"]
    assert execute_labels[-1] == "purge"


def test_evaluate_residual_names_intra_failing_member() -> None:
    dest = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id="d", media_id="d1"),
            _member(_unit(0.99, 0.1, 0.0), cluster_id="d", media_id="d2"),
        ],
        cluster_id="d",
    )
    left_id = str(uuid4())
    right_id = str(uuid4())
    residual = _cluster(
        [
            _member(_unit(1.0, 0.0, 0.0), cluster_id="r", media_id="r1", identity_id=left_id),
            _member(_unit(0.0, 1.0, 0.0), cluster_id="r", media_id="r2", identity_id=right_id),
        ],
        cluster_id="r",
    )
    abstention = evaluate_residual_admission(residual, dest, None, _accepted_policy())
    assert abstention is not None
    assert abstention.failing_member_id == right_id
    assert abstention.failing_clause is RecoveryAbstainClause.INTRA_INCOHERENT
