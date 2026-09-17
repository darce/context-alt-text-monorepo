"""GPUFLOW-2 C2: pairwise recovery merge with receipts."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

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
    RecoveryMember,
    _clusters_from_identities,
    evaluate_residual_admission,
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
async def test_reverted_merge_is_excluded_until_expiry_then_can_be_replanned() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    destination_id = str(uuid4())
    residual_id = str(uuid4())
    residual_identity_id = str(uuid4())
    store = InMemoryReceiptStore()

    destination, residual = _recovery_clusters_for_revert(destination_id, residual_id, residual_identity_id)
    first = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
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

    destination, residual = _recovery_clusters_for_revert(destination_id, residual_id, residual_identity_id)
    emitter = RecordingSuggestionEmitter()
    blocked = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
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
    assert len(store.receipts) == 1

    destination, residual = _recovery_clusters_for_revert(destination_id, residual_id, residual_identity_id)
    after_expiry = await run_recovery_merge_on_clusters(
        tenant_id=str(uuid4()),
        clusters=[destination, residual],
        settings=_enabled_settings(),
        policy=_accepted_policy(),
        runtime_binding=_binding(),
        receipt_store=store,
        now=receipt.expires_at + timedelta(seconds=1),
    )
    assert after_expiry.merged == 1
    assert store.receipts == []


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
    assert result.purged_receipts == 1
    assert [receipt.receipt_id for receipt in store.receipts] == [reverted.receipt_id, live.receipt_id]


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
