"""Pairwise recovery merge after conservative core formation (GRPH-22).

Never merges by best edge. Complete-link HAC stays intact; this pass only
admits a residual when every member clears every clause, then writes one
``cluster_merge_receipts`` row so LIFO revert can undo the move.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

import numpy as np

from db.models.identity import ClusterMergeKind, ClusterMergeReceipt
from recognition.application.settings.clustering import (
    ClusteringSettings,
    ClusterRecoveryCalibrationPolicy,
    EmbeddingSpaceBinding,
    calibration_policy_is_applicable,
    default_cluster_recovery_calibration_policy,
    quality_band_for_score,
    stratum_is_abstained,
    stratum_pair_floor,
)
from recognition.domain.cluster import is_reserved_label_shape
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import MergeSuggestionCreateData

logger = logging.getLogger(__name__)


class RecoveryAbstainClause(StrEnum):
    """Why a residual was kept out of automatic merge (sr-007)."""

    POLICY_NOT_APPLICABLE = "policy_not_applicable"
    INTRA_INCOHERENT = "intra_incoherent"
    INSUFFICIENT_EXEMPLARS = "insufficient_exemplars"
    COMPETING_MARGIN = "competing_margin"
    NAMED_PERSON_CONFLICT = "named_person_conflict"
    QUALITY_STRATUM_ABSTAINED = "quality_stratum_abstained"
    MISSING_EVIDENCE = "missing_evidence"
    NO_DESTINATION = "no_destination"


@dataclass(frozen=True, slots=True)
class RecoveryMember:
    identity_id: str
    cluster_id: str
    embedding: np.ndarray
    media_id: str
    quality_score: float | None = None
    operating_condition: str = "unknown"
    embedding_model: str | None = None


@dataclass(slots=True)
class RecoveryCluster:
    cluster_id: str
    members: list[RecoveryMember]
    label: str | None = None
    user_confirmed: bool = False
    embedding_model: str | None = None

    @property
    def identity_count(self) -> int:
        return len(self.members)

    @property
    def named_person_key(self) -> str | None:
        label = self.label
        if not (self.user_confirmed and label and not is_reserved_label_shape(label)):
            return None
        return label.strip().lower()

    @property
    def centroid(self) -> np.ndarray | None:
        if not self.members:
            return None
        stacked = np.stack(
            [_unit(member.embedding) for member in self.members],
            axis=0,
        )
        return _unit(np.mean(stacked, axis=0))


@dataclass(frozen=True, slots=True)
class ResidualAbstention:
    residual_cluster_id: str
    destination_cluster_id: str | None
    failing_member_id: str | None
    failing_clause: RecoveryAbstainClause
    similarity: float | None = None


@dataclass(frozen=True, slots=True)
class RecoveryMergeResult:
    merged: int = 0
    receipt_ids: tuple[uuid.UUID, ...] = ()
    receipts: tuple[ClusterMergeReceipt, ...] = ()
    abstentions: tuple[ResidualAbstention, ...] = ()
    purged_receipts: int = 0
    suggestions_emitted: int = 0
    applied: bool = False


class RecoveryReceiptStore(Protocol):
    async def add(self, receipt: ClusterMergeReceipt) -> None: ...

    async def siblings(self, survivor_cluster_id: str) -> Sequence[ClusterMergeReceipt]: ...

    async def purge_expired_or_reverted(self, *, now: datetime) -> int: ...


class RecoverySuggestionEmitter(Protocol):
    async def emit_pair(
        self,
        tenant_id: str,
        residual_cluster_id: str,
        destination_cluster_id: str,
        *,
        similarity: float,
        failing_member_id: str | None,
        failing_clause: RecoveryAbstainClause,
    ) -> None: ...


@dataclass
class InMemoryReceiptStore:
    receipts: list[ClusterMergeReceipt] = field(default_factory=list)

    async def add(self, receipt: ClusterMergeReceipt) -> None:
        self.receipts.append(receipt)

    async def siblings(self, survivor_cluster_id: str) -> Sequence[ClusterMergeReceipt]:
        survivor = str(survivor_cluster_id)
        return [receipt for receipt in self.receipts if str(receipt.survivor_cluster_id) == survivor]

    async def purge_expired_or_reverted(self, *, now: datetime) -> int:
        kept: list[ClusterMergeReceipt] = []
        purged = 0
        for receipt in self.receipts:
            expired = receipt.expires_at <= now
            reverted = receipt.reverted_at is not None
            if expired or reverted:
                purged += 1
                continue
            kept.append(receipt)
        self.receipts = kept
        return purged


@dataclass
class RecordingSuggestionEmitter:
    calls: list[MergeSuggestionCreateData] = field(default_factory=list)
    failing_members: list[str | None] = field(default_factory=list)
    clauses: list[RecoveryAbstainClause] = field(default_factory=list)

    async def emit_pair(
        self,
        tenant_id: str,
        residual_cluster_id: str,
        destination_cluster_id: str,
        *,
        similarity: float,
        failing_member_id: str | None,
        failing_clause: RecoveryAbstainClause,
    ) -> None:
        del tenant_id
        self.calls.append(
            MergeSuggestionCreateData(
                cluster_a_id=destination_cluster_id,
                cluster_b_id=residual_cluster_id,
                similarity=similarity,
                source="recovery_merge",
                survivor_cluster_id=destination_cluster_id,
            )
        )
        self.failing_members.append(failing_member_id)
        self.clauses.append(failing_clause)


def _unit(vector: np.ndarray) -> np.ndarray:
    values = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(values))
    if norm == 0.0:
        return values
    return values / norm


def pairwise_cosine(left: np.ndarray, right: np.ndarray) -> float:
    """Raw cosine in the supplied space. Not a best-edge merge score."""
    return float(np.dot(_unit(left), _unit(right)))


def _named_person_conflict(residual: RecoveryCluster, destination: RecoveryCluster) -> bool:
    residual_name = residual.named_person_key
    destination_name = destination.named_person_key
    if residual_name is None or destination_name is None:
        return False
    return residual_name != destination_name


def _member_tau_pair(
    member: RecoveryMember, policy: ClusterRecoveryCalibrationPolicy
) -> tuple[float | None, RecoveryAbstainClause | None]:
    if member.quality_score is None:
        return None, RecoveryAbstainClause.MISSING_EVIDENCE
    band = quality_band_for_score(member.quality_score, policy)
    if band is None:
        return None, RecoveryAbstainClause.QUALITY_STRATUM_ABSTAINED
    if stratum_is_abstained(band, member.operating_condition, policy):
        return None, RecoveryAbstainClause.QUALITY_STRATUM_ABSTAINED
    floor = stratum_pair_floor(band, member.operating_condition, policy)
    return max(policy.tau_pair, floor), None


def _intra_coherent(
    residual: RecoveryCluster,
    policy: ClusterRecoveryCalibrationPolicy,
) -> ResidualAbstention | None:
    members = residual.members
    for index, left in enumerate(members):
        for right in members[index + 1 :]:
            cosine = pairwise_cosine(left.embedding, right.embedding)
            if cosine < policy.tau_intra:
                return ResidualAbstention(
                    residual_cluster_id=residual.cluster_id,
                    destination_cluster_id=None,
                    failing_member_id=right.identity_id,
                    failing_clause=RecoveryAbstainClause.INTRA_INCOHERENT,
                    similarity=cosine,
                )
    return None


def _agreeing_distinct_media(
    member: RecoveryMember,
    destination: RecoveryCluster,
    *,
    tau_pair: float,
) -> set[str]:
    media_ids: set[str] = set()
    for exemplar in destination.members:
        if exemplar.media_id == member.media_id:
            continue
        if pairwise_cosine(member.embedding, exemplar.embedding) >= tau_pair:
            media_ids.add(exemplar.media_id)
    return media_ids


def _best_pairwise(member: RecoveryMember, cluster: RecoveryCluster) -> float:
    if not cluster.members:
        return float("-inf")
    return max(pairwise_cosine(member.embedding, exemplar.embedding) for exemplar in cluster.members)


def evaluate_residual_admission(
    residual: RecoveryCluster,
    destination: RecoveryCluster,
    runner_up: RecoveryCluster | None,
    policy: ClusterRecoveryCalibrationPolicy,
) -> ResidualAbstention | None:
    """Return an abstention if any member fails any clause; else None (admit).

    GRPH-22: every clause for every moved member. No partial move.
    """
    if _named_person_conflict(residual, destination):
        failing = residual.members[0].identity_id if residual.members else None
        return ResidualAbstention(
            residual_cluster_id=residual.cluster_id,
            destination_cluster_id=destination.cluster_id,
            failing_member_id=failing,
            failing_clause=RecoveryAbstainClause.NAMED_PERSON_CONFLICT,
            similarity=None,
        )

    intra = _intra_coherent(residual, policy)
    if intra is not None:
        return ResidualAbstention(
            residual_cluster_id=intra.residual_cluster_id,
            destination_cluster_id=destination.cluster_id,
            failing_member_id=intra.failing_member_id,
            failing_clause=intra.failing_clause,
            similarity=intra.similarity,
        )

    required = max(policy.k, policy.min_agreeing_exemplars)
    margin = policy.delta
    for member in residual.members:
        tau_pair, clause = _member_tau_pair(member, policy)
        if tau_pair is None:
            return ResidualAbstention(
                residual_cluster_id=residual.cluster_id,
                destination_cluster_id=destination.cluster_id,
                failing_member_id=member.identity_id,
                failing_clause=clause or RecoveryAbstainClause.MISSING_EVIDENCE,
            )
        agreeing = _agreeing_distinct_media(member, destination, tau_pair=tau_pair)
        if len(agreeing) < required:
            return ResidualAbstention(
                residual_cluster_id=residual.cluster_id,
                destination_cluster_id=destination.cluster_id,
                failing_member_id=member.identity_id,
                failing_clause=RecoveryAbstainClause.INSUFFICIENT_EXEMPLARS,
            )
        if runner_up is not None:
            best = _best_pairwise(member, destination)
            second = _best_pairwise(member, runner_up)
            if best - second < margin:
                return ResidualAbstention(
                    residual_cluster_id=residual.cluster_id,
                    destination_cluster_id=destination.cluster_id,
                    failing_member_id=member.identity_id,
                    failing_clause=RecoveryAbstainClause.COMPETING_MARGIN,
                    similarity=best,
                )
    return None


def _rank_destinations(
    residual: RecoveryCluster,
    destinations: Sequence[RecoveryCluster],
) -> list[tuple[float, RecoveryCluster]]:
    residual_centroid = residual.centroid
    if residual_centroid is None:
        return []
    ranked: list[tuple[float, RecoveryCluster]] = []
    for destination in destinations:
        if destination.cluster_id == residual.cluster_id:
            continue
        dest_centroid = destination.centroid
        if dest_centroid is None:
            continue
        if (
            residual.embedding_model
            and destination.embedding_model
            and residual.embedding_model != destination.embedding_model
        ):
            continue
        ranked.append((pairwise_cosine(residual_centroid, dest_centroid), destination))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def _new_receipt(
    *,
    tenant_id: str,
    residual: RecoveryCluster,
    destination: RecoveryCluster,
    policy: ClusterRecoveryCalibrationPolicy,
    settings: ClusteringSettings,
    now: datetime,
    siblings: Sequence[ClusterMergeReceipt],
) -> ClusterMergeReceipt:
    return ClusterMergeReceipt(
        receipt_id=uuid.uuid4(),
        tenant_id=uuid.UUID(str(tenant_id)),
        survivor_cluster_id=uuid.UUID(str(destination.cluster_id)),
        source_cluster_id=uuid.UUID(str(residual.cluster_id)),
        source_label=residual.label,
        moved_identity_ids=[uuid.UUID(str(member.identity_id)) for member in residual.members],
        rule_version=policy.rule_version,
        kind=ClusterMergeKind.AUTO.value,
        created_at=now,
        expires_at=now + timedelta(days=settings.merge_undo_window_days),
        sequence_no=ClusterMergeReceipt.next_sequence_no(siblings),
    )


async def run_recovery_merge_on_clusters(
    *,
    tenant_id: str,
    clusters: Sequence[RecoveryCluster],
    settings: ClusteringSettings,
    policy: ClusterRecoveryCalibrationPolicy,
    runtime_binding: EmbeddingSpaceBinding,
    receipt_store: RecoveryReceiptStore,
    suggestion_emitter: RecoverySuggestionEmitter | None = None,
    now: datetime | None = None,
) -> RecoveryMergeResult:
    """Constrained pairwise recovery over an in-memory cluster snapshot."""
    clock = now or datetime.now(tz=UTC)
    if not settings.recovery_merge_enabled:
        return RecoveryMergeResult()

    purged = await receipt_store.purge_expired_or_reverted(now=clock)

    if not calibration_policy_is_applicable(policy, runtime_binding):
        logger.info(
            "[clustering] recovery_merge_skip reason=policy_not_applicable apply_mode=%s",
            policy.apply_mode.value,
        )
        return RecoveryMergeResult(purged_receipts=purged, applied=False)

    live = {cluster.cluster_id: cluster for cluster in clusters if cluster.members}
    max_residual = settings.recovery_max_residual_size
    residuals = [cluster for cluster in live.values() if cluster.identity_count <= max_residual]
    residuals.sort(key=lambda cluster: (cluster.identity_count, cluster.cluster_id))

    written: list[ClusterMergeReceipt] = []
    abstentions: list[ResidualAbstention] = []
    suggestions = 0
    merged = 0
    absorbed: set[str] = set()

    for residual in residuals:
        if residual.cluster_id in absorbed or residual.cluster_id not in live:
            continue
        ranked = _rank_destinations(
            residual,
            [cluster for cluster_id, cluster in live.items() if cluster_id not in absorbed],
        )
        if not ranked:
            abstentions.append(
                ResidualAbstention(
                    residual_cluster_id=residual.cluster_id,
                    destination_cluster_id=None,
                    failing_member_id=residual.members[0].identity_id if residual.members else None,
                    failing_clause=RecoveryAbstainClause.NO_DESTINATION,
                )
            )
            continue
        dest_similarity, destination = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else None
        abstention = evaluate_residual_admission(residual, destination, runner_up, policy)
        if abstention is not None:
            filled = ResidualAbstention(
                residual_cluster_id=abstention.residual_cluster_id,
                destination_cluster_id=destination.cluster_id,
                failing_member_id=abstention.failing_member_id,
                failing_clause=abstention.failing_clause,
                similarity=abstention.similarity if abstention.similarity is not None else dest_similarity,
            )
            abstentions.append(filled)
            if suggestion_emitter is not None:
                await suggestion_emitter.emit_pair(
                    tenant_id,
                    residual.cluster_id,
                    destination.cluster_id,
                    similarity=filled.similarity or dest_similarity,
                    failing_member_id=filled.failing_member_id,
                    failing_clause=filled.failing_clause,
                )
                suggestions += 1
            continue

        siblings = await receipt_store.siblings(destination.cluster_id)
        receipt = _new_receipt(
            tenant_id=tenant_id,
            residual=residual,
            destination=destination,
            policy=policy,
            settings=settings,
            now=clock,
            siblings=siblings,
        )
        destination.members.extend(residual.members)
        residual.members = []
        live.pop(residual.cluster_id, None)
        absorbed.add(residual.cluster_id)
        await receipt_store.add(receipt)
        written.append(receipt)
        merged += 1

    return RecoveryMergeResult(
        merged=merged,
        receipt_ids=tuple(receipt.receipt_id for receipt in written),
        receipts=tuple(written),
        abstentions=tuple(abstentions),
        purged_receipts=purged,
        suggestions_emitted=suggestions,
        applied=True,
    )


class _ServiceSuggestionEmitter:
    def __init__(self, service: Any) -> None:
        self._service = service

    async def emit_pair(
        self,
        tenant_id: str,
        residual_cluster_id: str,
        destination_cluster_id: str,
        *,
        similarity: float,
        failing_member_id: str | None,
        failing_clause: RecoveryAbstainClause,
    ) -> None:
        del failing_member_id, failing_clause
        repository = getattr(self._service, "_repository", None)
        upsert = getattr(repository, "upsert_pending", None)
        if not callable(upsert):
            return
        await upsert(
            tenant_id,
            MergeSuggestionCreateData(
                cluster_a_id=destination_cluster_id,
                cluster_b_id=residual_cluster_id,
                similarity=similarity,
                source="recovery_merge",
                survivor_cluster_id=destination_cluster_id,
            ),
        )


class _SessionReceiptStore:
    def __init__(self, session: Any, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = uuid.UUID(str(tenant_id))

    async def add(self, receipt: ClusterMergeReceipt) -> None:
        self._session.add(receipt)

    async def siblings(self, survivor_cluster_id: str) -> Sequence[ClusterMergeReceipt]:
        from sqlalchemy import select

        result = await self._session.execute(
            select(ClusterMergeReceipt).where(
                ClusterMergeReceipt.tenant_id == self._tenant_id,
                ClusterMergeReceipt.survivor_cluster_id == uuid.UUID(str(survivor_cluster_id)),
            )
        )
        return list(result.scalars().all())

    async def purge_expired_or_reverted(self, *, now: datetime) -> int:
        from sqlalchemy import delete, or_

        result = await self._session.execute(
            delete(ClusterMergeReceipt).where(
                ClusterMergeReceipt.tenant_id == self._tenant_id,
                or_(
                    ClusterMergeReceipt.reverted_at.is_not(None),
                    ClusterMergeReceipt.expires_at <= now,
                ),
            )
        )
        return int(result.rowcount or 0)


def _quality_score_from_identity(identity: MediaIdentity) -> float | None:
    metadata = identity.metadata or {}
    raw = metadata.get("quality_score")
    if isinstance(raw, (int, float)):
        return float(raw)
    if identity.confidence is not None:
        return float(identity.confidence)
    return None


def _operating_condition_from_identity(identity: MediaIdentity) -> str:
    metadata = identity.metadata or {}
    raw = metadata.get("operating_condition")
    if isinstance(raw, str) and raw:
        return raw
    return "unknown"


def _clusters_from_identities(
    clusters: Sequence[Any],
    members_by_cluster: Mapping[str, Sequence[MediaIdentity]],
) -> list[RecoveryCluster]:
    recovered: list[RecoveryCluster] = []
    for cluster in clusters:
        cluster_id = getattr(cluster, "id", None)
        if not cluster_id:
            continue
        identities = members_by_cluster.get(str(cluster_id), ())
        members = [
            RecoveryMember(
                identity_id=str(identity.id),
                cluster_id=str(cluster_id),
                embedding=np.asarray(identity.embedding, dtype=np.float32),
                media_id=str(identity.media_id),
                quality_score=_quality_score_from_identity(identity),
                operating_condition=_operating_condition_from_identity(identity),
                embedding_model=identity.embedding_model,
            )
            for identity in identities
            if identity.embedding is not None
        ]
        if not members:
            continue
        recovered.append(
            RecoveryCluster(
                cluster_id=str(cluster_id),
                members=members,
                label=getattr(cluster, "label", None),
                user_confirmed=bool(getattr(cluster, "user_confirmed", False)),
                embedding_model=getattr(cluster, "embedding_model", None) or members[0].embedding_model,
            )
        )
    return recovered


def _binding_from_clusters(
    clusters: Sequence[RecoveryCluster],
    fallback: EmbeddingSpaceBinding | None,
) -> EmbeddingSpaceBinding | None:
    if fallback is not None:
        return fallback
    for cluster in clusters:
        for member in cluster.members:
            if not member.embedding_model:
                continue
            return EmbeddingSpaceBinding(
                embedding_model_id=member.embedding_model,
                embedding_model_revision="unbound",
                embedding_dimensionality=int(np.asarray(member.embedding).shape[-1]),
                distance_metric="cosine",
                dataset_manifest_digest="unbound",
                calibration_run_digest="unbound",
            )
    return None


async def run_recovery_merge(
    *,
    tenant_id: str,
    assignment_writer: Any,
    merge_suggestion_service: Any | None = None,
    settings: ClusteringSettings | None = None,
    policy: ClusterRecoveryCalibrationPolicy | None = None,
    runtime_binding: EmbeddingSpaceBinding | None = None,
    receipt_store: RecoveryReceiptStore | None = None,
    suggestion_emitter: RecoverySuggestionEmitter | None = None,
    now: datetime | None = None,
) -> RecoveryMergeResult:
    """Pipeline entry: load clusters from the assignment writer, then recover."""
    clustering = settings or getattr(assignment_writer, "_settings", None) or ClusteringSettings()
    if not clustering.recovery_merge_enabled:
        return RecoveryMergeResult()

    cluster_repo = getattr(assignment_writer, "cluster_repository", None)
    member_repo = getattr(assignment_writer, "member_repository", None)
    if cluster_repo is None:
        return RecoveryMergeResult()

    get_by_tenant = getattr(cluster_repo, "get_by_tenant", None)
    if not callable(get_by_tenant):
        return RecoveryMergeResult()

    domain_clusters = await get_by_tenant(tenant_id, limit=1000)
    cluster_ids = [str(cluster.id) for cluster in domain_clusters if getattr(cluster, "id", None)]
    members_by_cluster: dict[str, Sequence[MediaIdentity]] = {}
    loader = getattr(cluster_repo, "get_member_identities_for_clusters", None)
    if callable(loader) and cluster_ids:
        loaded = await loader(cluster_ids)
        members_by_cluster = {str(key): value for key, value in loaded.items()}
    else:
        get_members = getattr(cluster_repo, "get_member_identities", None)
        if callable(get_members):
            for cluster_id in cluster_ids:
                members_by_cluster[cluster_id] = await get_members(cluster_id)

    recovered = _clusters_from_identities(domain_clusters, members_by_cluster)
    typed_policy = policy or default_cluster_recovery_calibration_policy()
    binding = _binding_from_clusters(recovered, runtime_binding)
    if binding is None:
        logger.info("[clustering] recovery_merge_skip reason=unbound_runtime_embedding_space")
        store = receipt_store or InMemoryReceiptStore()
        purged = await store.purge_expired_or_reverted(now=now or datetime.now(tz=UTC))
        return RecoveryMergeResult(purged_receipts=purged, applied=False)

    store = receipt_store
    if store is None:
        session = getattr(assignment_writer, "_session", None)
        store = _SessionReceiptStore(session, tenant_id) if session is not None else InMemoryReceiptStore()

    emitter = suggestion_emitter
    if emitter is None and merge_suggestion_service is not None:
        emitter = _ServiceSuggestionEmitter(merge_suggestion_service)

    snapshot = {cluster.cluster_id: cluster for cluster in recovered}
    result = await run_recovery_merge_on_clusters(
        tenant_id=tenant_id,
        clusters=list(snapshot.values()),
        settings=clustering,
        policy=typed_policy,
        runtime_binding=binding,
        receipt_store=store,
        suggestion_emitter=emitter,
        now=now,
    )

    if result.merged and member_repo is not None:
        for receipt in result.receipts:
            source_id = str(receipt.source_cluster_id)
            dest_id = str(receipt.survivor_cluster_id)
            move = getattr(member_repo, "move_members", None)
            if callable(move):
                moved = await move(source_id, dest_id)
            else:
                moved = len(receipt.moved_identity_ids)
            delete_cluster = getattr(cluster_repo, "delete", None)
            if callable(delete_cluster):
                await delete_cluster(source_id)
            get_by_id = getattr(cluster_repo, "get_by_id", None)
            if callable(get_by_id):
                dest_cluster = await get_by_id(dest_id)
                if dest_cluster is not None:
                    dest_cluster.identity_count = (dest_cluster.identity_count or 0) + int(moved or 0)
                    updater = getattr(cluster_repo, "update", None)
                    if callable(updater):
                        await updater(dest_cluster)
            recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
            recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
            if callable(recompute_reps):
                await recompute_reps(dest_id)
            if callable(recompute_centroid):
                await recompute_centroid(dest_id)
            delete_suggestions = getattr(merge_suggestion_service, "delete_by_cluster", None)
            if callable(delete_suggestions):
                await delete_suggestions(tenant_id, source_id)
                await delete_suggestions(tenant_id, dest_id)

        refresh = getattr(assignment_writer, "refresh_centroids_view", None)
        if callable(refresh):
            try:
                await refresh()
            except Exception:
                logger.warning(
                    "[clustering] recovery_merge MV refresh failed tenant_id=%s",
                    tenant_id,
                    exc_info=True,
                )

    return result
