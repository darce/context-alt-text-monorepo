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
from sqlalchemy import delete, func, or_, select, update

from db.models.constraints import IdentityClusterBlock

from db.models.identity import (
    ClusterMergeKind,
    ClusterMergeReceipt,
)
from db.models.identity import (
    IdentityCluster as IdentityClusterModel,
)
from db.models.identity import (
    IdentityMember as IdentityMemberModel,
)
from db.models.identity import (
    MediaIdentity as MediaIdentityModel,
)
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

RECOVERY_UNKNOWN_OPERATING_CONDITION = "unknown"
RECOVERY_REVERT_BLOCK_REASON = "merge_reverted"


class RecoveryAbstainClause(StrEnum):
    """Why a residual was kept out of automatic merge (sr-007)."""

    POLICY_NOT_APPLICABLE = "policy_not_applicable"
    INTRA_INCOHERENT = "intra_incoherent"
    INSUFFICIENT_EXEMPLARS = "insufficient_exemplars"
    COMPETING_MARGIN = "competing_margin"
    NAMED_PERSON_CONFLICT = "named_person_conflict"
    QUALITY_STRATUM_ABSTAINED = "quality_stratum_abstained"
    MISSING_EVIDENCE = "missing_evidence"
    EMBEDDING_SPACE_MISMATCH = "embedding_space_mismatch"
    REVERTED_MERGE_EXCLUDED = "reverted_merge_excluded"
    NO_DESTINATION = "no_destination"


@dataclass(frozen=True, slots=True)
class RecoveryMember:
    identity_id: str
    cluster_id: str
    embedding: np.ndarray
    media_id: str
    quality_score: float | None = None
    operating_condition: str = RECOVERY_UNKNOWN_OPERATING_CONDITION
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
    skip_reason: str | None = None


class RecoveryReceiptStore(Protocol):
    async def add(self, receipt: ClusterMergeReceipt) -> None: ...

    async def siblings(self, survivor_cluster_id: str) -> Sequence[ClusterMergeReceipt]: ...

    async def active_block_pairs(
        self,
        identity_ids: Sequence[str],
        *,
        tenant_id: str | None = None,
        now: datetime,
    ) -> set[tuple[str, str]]: ...

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
    blocks: list[IdentityClusterBlock] = field(default_factory=list)

    async def add(self, receipt: ClusterMergeReceipt) -> None:
        self.receipts.append(receipt)

    async def siblings(self, survivor_cluster_id: str) -> Sequence[ClusterMergeReceipt]:
        survivor = str(survivor_cluster_id)
        return [receipt for receipt in self.receipts if str(receipt.survivor_cluster_id) == survivor]

    async def add_block(
        self,
        *,
        tenant_id: str,
        identity_id: str,
        blocked_cluster_id: str,
        reason: str = RECOVERY_REVERT_BLOCK_REASON,
        expires_at: datetime | None = None,
    ) -> IdentityClusterBlock:
        tenant_uuid = uuid.UUID(str(tenant_id))
        identity_uuid = uuid.UUID(str(identity_id))
        blocked_cluster_uuid = uuid.UUID(str(blocked_cluster_id))
        for block in self.blocks:
            if (
                block.tenant_id == tenant_uuid
                and block.identity_id == identity_uuid
                and block.blocked_cluster_id == blocked_cluster_uuid
            ):
                block.reason = reason
                block.expires_at = expires_at
                return block
        block = IdentityClusterBlock(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            identity_id=identity_uuid,
            blocked_cluster_id=blocked_cluster_uuid,
            reason=reason,
            expires_at=expires_at,
        )
        self.blocks.append(block)
        return block

    async def active_block_pairs(
        self,
        identity_ids: Sequence[str],
        *,
        tenant_id: str | None = None,
        now: datetime,
    ) -> set[tuple[str, str]]:
        identity_keys = {str(identity_id) for identity_id in identity_ids}
        tenant_key = str(tenant_id) if tenant_id is not None else None
        return {
            (str(block.identity_id), str(block.blocked_cluster_id))
            for block in self.blocks
            if str(block.identity_id) in identity_keys
            and (tenant_key is None or str(block.tenant_id) == tenant_key)
            and (block.expires_at is None or block.expires_at > now)
        }

    async def purge_expired_or_reverted(self, *, now: datetime) -> int:
        kept: list[ClusterMergeReceipt] = []
        purged = 0
        for receipt in self.receipts:
            if receipt.reverted_at is not None or receipt.expires_at <= now:
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
        ranked.append((pairwise_cosine(residual_centroid, dest_centroid), destination))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def _member_matches_runtime_binding(
    member: RecoveryMember,
    runtime_binding: EmbeddingSpaceBinding,
) -> bool:
    """Return whether a member can safely participate in runtime-space math."""
    vector = np.asarray(member.embedding)
    return bool(
        member.embedding_model == runtime_binding.embedding_model_id
        and vector.ndim == 1
        and vector.shape[0] == runtime_binding.embedding_dimensionality
    )


def _prepare_runtime_space_clusters(
    clusters: Sequence[RecoveryCluster],
    runtime_binding: EmbeddingSpaceBinding,
) -> tuple[dict[str, RecoveryCluster], dict[str, tuple[RecoveryMember, ...]], dict[str, int]]:
    """Filter every cluster before any centroid or cosine calculation.

    Destination clusters may retain their accepted-space members after foreign
    rows are dropped. A residual containing even one rejected member is tracked
    separately and is handled as a fail-closed abstention by the planner.
    """
    live: dict[str, RecoveryCluster] = {}
    rejected_by_cluster: dict[str, tuple[RecoveryMember, ...]] = {}
    original_counts: dict[str, int] = {}
    for cluster in clusters:
        original_counts[cluster.cluster_id] = len(cluster.members)
        accepted: list[RecoveryMember] = []
        rejected: list[RecoveryMember] = []
        for member in cluster.members:
            if _member_matches_runtime_binding(member, runtime_binding):
                accepted.append(member)
            else:
                rejected.append(member)
        cluster.members = accepted
        if rejected:
            rejected_by_cluster[cluster.cluster_id] = tuple(rejected)
        if accepted:
            live[cluster.cluster_id] = cluster
    return live, rejected_by_cluster, original_counts


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
    """Plan constrained pairwise recovery over an in-memory cluster snapshot.

    This function deliberately does not persist receipts or membership changes;
    the session-backed entry point applies the returned plans with a CAS guard.
    """
    clock = now or datetime.now(tz=UTC)
    if not settings.recovery_merge_enabled:
        return RecoveryMergeResult()

    if not calibration_policy_is_applicable(policy, runtime_binding):
        logger.info(
            "[clustering] recovery_merge_skip reason=policy_not_applicable apply_mode=%s",
            policy.apply_mode.value,
        )
        purged = await receipt_store.purge_expired_or_reverted(now=clock)
        return RecoveryMergeResult(purged_receipts=purged, applied=False)

    sibling_cache = {cluster.cluster_id: list(await receipt_store.siblings(cluster.cluster_id)) for cluster in clusters}
    max_residual = settings.recovery_max_residual_size
    candidate_identity_ids = tuple(
        member.identity_id
        for cluster in clusters
        if len(cluster.members) <= max_residual
        for member in cluster.members
    )
    active_block_pairs: set[tuple[str, str]] = set()
    load_active_blocks = getattr(receipt_store, "active_block_pairs", None)
    if callable(load_active_blocks) and candidate_identity_ids:
        active_block_pairs = set(
            await load_active_blocks(
                candidate_identity_ids,
                tenant_id=tenant_id,
                now=clock,
            )
        )
    live, rejected_by_cluster, original_counts = _prepare_runtime_space_clusters(clusters, runtime_binding)
    residuals = [
        cluster
        for cluster in clusters
        if 0 < original_counts.get(cluster.cluster_id, 0) <= max_residual
        and (cluster.members or cluster.cluster_id in rejected_by_cluster)
    ]
    residuals.sort(key=lambda cluster: (cluster.identity_count, cluster.cluster_id))

    planned: list[ClusterMergeReceipt] = []
    abstentions: list[ResidualAbstention] = []
    suggestions = 0
    merged = 0
    absorbed: set[str] = set()

    for residual in residuals:
        if residual.cluster_id in absorbed or residual.cluster_id not in live:
            if residual.cluster_id in rejected_by_cluster and residual.cluster_id not in absorbed:
                failing_member = rejected_by_cluster[residual.cluster_id][0]
                abstentions.append(
                    ResidualAbstention(
                        residual_cluster_id=residual.cluster_id,
                        destination_cluster_id=None,
                        failing_member_id=failing_member.identity_id,
                        failing_clause=RecoveryAbstainClause.EMBEDDING_SPACE_MISMATCH,
                    )
                )
            continue
        rejected = rejected_by_cluster.get(residual.cluster_id)
        if rejected:
            abstentions.append(
                ResidualAbstention(
                    residual_cluster_id=residual.cluster_id,
                    destination_cluster_id=None,
                    failing_member_id=rejected[0].identity_id,
                    failing_clause=RecoveryAbstainClause.EMBEDDING_SPACE_MISMATCH,
                )
            )
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
        if any(
            (member.identity_id, destination.cluster_id) in active_block_pairs
            for member in residual.members
        ):
            abstention = ResidualAbstention(
                residual_cluster_id=residual.cluster_id,
                destination_cluster_id=destination.cluster_id,
                failing_member_id=residual.members[0].identity_id if residual.members else None,
                failing_clause=RecoveryAbstainClause.REVERTED_MERGE_EXCLUDED,
                similarity=dest_similarity,
            )
            abstentions.append(abstention)
            if suggestion_emitter is not None:
                await suggestion_emitter.emit_pair(
                    tenant_id,
                    residual.cluster_id,
                    destination.cluster_id,
                    similarity=dest_similarity,
                    failing_member_id=abstention.failing_member_id,
                    failing_clause=abstention.failing_clause,
                )
                suggestions += 1
            continue
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

        siblings = sibling_cache.setdefault(destination.cluster_id, [])
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
        siblings.append(receipt)
        planned.append(receipt)
        merged += 1

    purged = await receipt_store.purge_expired_or_reverted(now=clock)
    return RecoveryMergeResult(
        merged=merged,
        receipt_ids=tuple(receipt.receipt_id for receipt in planned),
        receipts=tuple(planned),
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
        result = await self._session.execute(
            select(ClusterMergeReceipt).where(
                ClusterMergeReceipt.tenant_id == self._tenant_id,
                ClusterMergeReceipt.survivor_cluster_id == uuid.UUID(str(survivor_cluster_id)),
            )
        )
        return list(result.scalars().all())

    async def active_block_pairs(
        self,
        identity_ids: Sequence[str],
        *,
        tenant_id: str | None = None,
        now: datetime,
    ) -> set[tuple[str, str]]:
        del tenant_id
        if not identity_ids:
            return set()
        identity_uuids = [uuid.UUID(str(identity_id)) for identity_id in identity_ids]
        result = await self._session.execute(
            select(
                IdentityClusterBlock.identity_id,
                IdentityClusterBlock.blocked_cluster_id,
            ).where(
                IdentityClusterBlock.tenant_id == self._tenant_id,
                IdentityClusterBlock.identity_id.in_(identity_uuids),
                or_(
                    IdentityClusterBlock.expires_at.is_(None),
                    IdentityClusterBlock.expires_at > now,
                ),
            )
        )
        return {(str(identity_id), str(cluster_id)) for identity_id, cluster_id in result.all()}

    async def purge_expired_or_reverted(self, *, now: datetime) -> int:
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


async def _persist_reverted_receipt_blocks(
    *,
    session: Any,
    tenant_id: str,
    now: datetime,
    settings: ClusteringSettings | None = None,
) -> int:
    """Carry reverted receipts into durable identity-to-cluster blocks.

    Receipts are intentionally purged later in the recovery run, so this
    bridge must execute first. Identity rows are checked before inserts because
    receipt history can outlive an identity and the block table has an FK.
    """
    tenant_uuid = uuid.UUID(str(tenant_id))
    receipt_result = await session.execute(
        select(ClusterMergeReceipt)
        .where(
            ClusterMergeReceipt.tenant_id == tenant_uuid,
            ClusterMergeReceipt.reverted_at.is_not(None),
        )
    )
    reverted_receipts = list(receipt_result.scalars().all())
    if not reverted_receipts:
        return 0

    receipt_pairs: dict[uuid.UUID, set[uuid.UUID]] = {}
    moved_ids = {
        uuid.UUID(str(identity_id))
        for receipt in reverted_receipts
        for identity_id in receipt.moved_identity_ids
    }
    for receipt in reverted_receipts:
        survivor_id = uuid.UUID(str(receipt.survivor_cluster_id))
        receipt_pairs.setdefault(survivor_id, set()).update(
            uuid.UUID(str(identity_id)) for identity_id in receipt.moved_identity_ids
        )
    if not moved_ids:
        return 0

    identity_result = await session.execute(
        select(MediaIdentityModel.id).where(
            MediaIdentityModel.tenant_id == tenant_uuid,
            MediaIdentityModel.id.in_(moved_ids),
        )
    )
    existing_identity_ids = {
        uuid.UUID(str(identity_id)) for identity_id in identity_result.scalars().all()
    }
    if not existing_identity_ids:
        return 0

    survivor_ids = tuple(receipt_pairs)
    existing_block_result = await session.execute(
        select(IdentityClusterBlock)
        .where(
            IdentityClusterBlock.tenant_id == tenant_uuid,
            IdentityClusterBlock.identity_id.in_(existing_identity_ids),
            IdentityClusterBlock.blocked_cluster_id.in_(survivor_ids),
        )
    )
    existing_blocks = {
        (uuid.UUID(str(block.identity_id)), uuid.UUID(str(block.blocked_cluster_id))): block
        for block in existing_block_result.scalars().all()
    }

    persisted = 0
    retention_days = (settings or ClusteringSettings()).revert_block_retention_window_days
    expires_at = now + timedelta(days=retention_days)
    for survivor_id, receipt_identity_ids in receipt_pairs.items():
        for identity_id in receipt_identity_ids & existing_identity_ids:
            block = existing_blocks.get((identity_id, survivor_id))
            if block is None:
                session.add(
                    IdentityClusterBlock(
                        id=uuid.uuid4(),
                        tenant_id=tenant_uuid,
                        identity_id=identity_id,
                        blocked_cluster_id=survivor_id,
                        reason=RECOVERY_REVERT_BLOCK_REASON,
                        expires_at=expires_at,
                    )
                )
                persisted += 1
                continue
            if block.reason == RECOVERY_REVERT_BLOCK_REASON:
                continue
            if block.expires_at is None or block.expires_at > now:
                continue
            await session.delete(block)
            await session.flush()
            session.add(
                IdentityClusterBlock(
                    id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    identity_id=identity_id,
                    blocked_cluster_id=survivor_id,
                    reason=RECOVERY_REVERT_BLOCK_REASON,
                    expires_at=expires_at,
                )
            )
            persisted += 1
    return persisted


_PersistedRecoveryFields = tuple[str, np.ndarray, str | None, float | None, str]


async def _load_persisted_recovery_fields(
    *,
    session: Any,
    tenant_id: str,
    cluster_ids: Sequence[str],
) -> dict[str, _PersistedRecoveryFields]:
    """Load the persisted recovery fields omitted by the domain member loader."""
    if not cluster_ids:
        return {}
    tenant_uuid = uuid.UUID(str(tenant_id))
    cluster_uuids = [uuid.UUID(str(cluster_id)) for cluster_id in cluster_ids]
    stmt = (
        select(
            MediaIdentityModel.id,
            IdentityMemberModel.cluster_id,
            MediaIdentityModel.embedding,
            MediaIdentityModel.embedding_model,
            MediaIdentityModel.quality_score,
            MediaIdentityModel.media_id,
        )
        .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentityModel.id)
        .where(
            MediaIdentityModel.tenant_id == tenant_uuid,
            IdentityMemberModel.tenant_id == tenant_uuid,
            IdentityMemberModel.cluster_id.in_(cluster_uuids),
        )
    )
    result = await session.execute(stmt)
    fields: dict[str, _PersistedRecoveryFields] = {}
    for row in result.all():
        if len(row) == 5:
            identity_id, cluster_id, embedding, embedding_model, quality_score = row
            media_id = identity_id
        else:
            identity_id, cluster_id, embedding, embedding_model, quality_score, media_id = row
        if embedding is None:
            continue
        fields[str(identity_id)] = (
            str(cluster_id),
            np.asarray(embedding, dtype=np.float32),
            str(embedding_model) if embedding_model is not None else None,
            float(quality_score) if quality_score is not None else None,
            str(media_id),
        )
    return fields


def _clusters_from_persisted_fields(
    clusters: Sequence[Any],
    persisted_fields: Mapping[str, _PersistedRecoveryFields],
) -> list[RecoveryCluster]:
    """Build recovery members directly from the narrow persisted-member query."""
    recovered: list[RecoveryCluster] = []
    for cluster in clusters:
        cluster_id = getattr(cluster, "id", None)
        if not cluster_id:
            continue
        members: list[RecoveryMember] = []
        for identity_id, (
            persisted_cluster_id,
            embedding,
            embedding_model,
            quality_score,
            media_id,
        ) in persisted_fields.items():
            if persisted_cluster_id != str(cluster_id):
                continue
            members.append(
                RecoveryMember(
                    identity_id=identity_id,
                    cluster_id=str(cluster_id),
                    embedding=embedding,
                    media_id=media_id,
                    quality_score=quality_score,
                    operating_condition=RECOVERY_UNKNOWN_OPERATING_CONDITION,
                    embedding_model=embedding_model,
                )
            )
        if not members:
            continue
        recovered.append(
            RecoveryCluster(
                cluster_id=str(cluster_id),
                members=members,
                label=getattr(cluster, "label", None),
                user_confirmed=bool(getattr(cluster, "user_confirmed", False)),
                embedding_model=None,
            )
        )
    return recovered


def _clusters_from_identities(
    clusters: Sequence[Any],
    members_by_cluster: Mapping[str, Sequence[MediaIdentity]],
    persisted_fields: Mapping[str, _PersistedRecoveryFields] | None = None,
) -> list[RecoveryCluster]:
    persisted = persisted_fields or {}
    recovered: list[RecoveryCluster] = []
    for cluster in clusters:
        cluster_id = getattr(cluster, "id", None)
        if not cluster_id:
            continue
        identities = members_by_cluster.get(str(cluster_id), ())
        members: list[RecoveryMember] = []
        for identity in identities:
            if identity.embedding is None:
                continue
            fields = persisted.get(str(identity.id))
            if fields is None:
                embedding = np.asarray(identity.embedding, dtype=np.float32)
                embedding_model = identity.embedding_model
                quality_score = None
            else:
                persisted_cluster_id, embedding, embedding_model, quality_score, _media_id = fields
                if persisted_cluster_id != str(cluster_id):
                    continue
            members.append(
                RecoveryMember(
                    identity_id=str(identity.id),
                    cluster_id=str(cluster_id),
                    embedding=embedding,
                    media_id=str(identity.media_id),
                    quality_score=quality_score,
                    operating_condition=RECOVERY_UNKNOWN_OPERATING_CONDITION,
                    embedding_model=embedding_model,
                )
            )
        if not members:
            continue
        recovered.append(
            RecoveryCluster(
                cluster_id=str(cluster_id),
                members=members,
                label=getattr(cluster, "label", None),
                user_confirmed=bool(getattr(cluster, "user_confirmed", False)),
                # Member-level provenance is authoritative; no cluster-level
                # fallback may license cross-space centroid comparisons.
                embedding_model=None,
            )
        )
    return recovered


class _RecoveryCasMissError(RuntimeError):
    """The planned source membership no longer matches the database snapshot."""


async def _apply_recovery_receipt(
    *,
    session: Any,
    receipt_store: RecoveryReceiptStore,
    receipt: ClusterMergeReceipt,
    tenant_id: str,
) -> bool:
    """Apply one planned merge under row locks and a member-set CAS guard."""
    tenant_uuid = uuid.UUID(str(tenant_id))
    source_uuid = uuid.UUID(str(receipt.source_cluster_id))
    destination_uuid = uuid.UUID(str(receipt.survivor_cluster_id))
    moved_ids = tuple(uuid.UUID(str(identity_id)) for identity_id in receipt.moved_identity_ids)
    if not moved_ids:
        return False

    try:
        async with session.begin_nested():
            locked = await session.execute(
                select(IdentityClusterModel)
                .where(
                    IdentityClusterModel.tenant_id == tenant_uuid,
                    IdentityClusterModel.id.in_((source_uuid, destination_uuid)),
                )
                .order_by(IdentityClusterModel.id)
                .with_for_update()
            )
            locked_ids = {model.id for model in locked.scalars().all()}
            if source_uuid not in locked_ids or destination_uuid not in locked_ids:
                raise _RecoveryCasMissError

            source_count_result = await session.execute(
                select(func.count(IdentityMemberModel.id)).where(
                    IdentityMemberModel.tenant_id == tenant_uuid,
                    IdentityMemberModel.cluster_id == source_uuid,
                )
            )
            if int(source_count_result.scalar_one() or 0) != len(moved_ids):
                raise _RecoveryCasMissError

            moved = await session.execute(
                update(IdentityMemberModel)
                .where(
                    IdentityMemberModel.tenant_id == tenant_uuid,
                    IdentityMemberModel.cluster_id == source_uuid,
                    IdentityMemberModel.identity_id.in_(moved_ids),
                )
                .values(cluster_id=destination_uuid)
            )
            if int(moved.rowcount or 0) != len(moved_ids):
                raise _RecoveryCasMissError

            moved_identity_stamp = await session.execute(
                update(MediaIdentityModel)
                .where(
                    MediaIdentityModel.tenant_id == tenant_uuid,
                    MediaIdentityModel.id.in_(moved_ids),
                )
                .values(moved_by_merge_id=receipt.receipt_id)
            )
            if int(moved_identity_stamp.rowcount or 0) != len(moved_ids):
                raise _RecoveryCasMissError

            remaining = await session.execute(
                select(func.count(IdentityMemberModel.id)).where(
                    IdentityMemberModel.tenant_id == tenant_uuid,
                    IdentityMemberModel.cluster_id == source_uuid,
                )
            )
            if int(remaining.scalar_one() or 0) != 0:
                raise _RecoveryCasMissError

            siblings = await receipt_store.siblings(str(destination_uuid))
            receipt.sequence_no = ClusterMergeReceipt.next_sequence_no(siblings)
            destination_update = await session.execute(
                update(IdentityClusterModel)
                .where(
                    IdentityClusterModel.tenant_id == tenant_uuid,
                    IdentityClusterModel.id == destination_uuid,
                )
                .values(identity_count=IdentityClusterModel.identity_count + len(moved_ids))
            )
            if int(destination_update.rowcount or 0) != 1:
                raise _RecoveryCasMissError

            source_delete = await session.execute(
                delete(IdentityClusterModel).where(
                    IdentityClusterModel.tenant_id == tenant_uuid,
                    IdentityClusterModel.id == source_uuid,
                )
            )
            if int(source_delete.rowcount or 0) != 1:
                raise _RecoveryCasMissError

            # The receipt is durable only after the exact member move and
            # source deletion have succeeded inside this savepoint.
            await receipt_store.add(receipt)
            await session.flush()
    except _RecoveryCasMissError:
        logger.info(
            "recovery_merge_cas_miss tenant_id=%s source_cluster_id=%s destination_cluster_id=%s",
            tenant_id,
            receipt.source_cluster_id,
            receipt.survivor_cluster_id,
        )
        return False
    return True


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
    clock = now or datetime.now(tz=UTC)

    cluster_repo = assignment_writer.cluster_repository
    session = getattr(assignment_writer, "_session", None) or getattr(cluster_repo, "_session", None)
    store = receipt_store
    if store is None:
        store = _SessionReceiptStore(session, tenant_id) if session is not None else InMemoryReceiptStore()
    if session is not None:
        await _persist_reverted_receipt_blocks(
            session=session,
            tenant_id=tenant_id,
            now=clock,
            settings=clustering,
        )

    if runtime_binding is None:
        logger.warning(
            "[clustering] recovery_merge_skip reason=runtime_binding_unavailable tenant_id=%s",
            tenant_id,
        )
        purged = await store.purge_expired_or_reverted(now=clock)
        return RecoveryMergeResult(
            purged_receipts=purged,
            applied=False,
            skip_reason="runtime_binding_unavailable",
        )

    domain_clusters = await cluster_repo.get_by_tenant(tenant_id, limit=1000)
    cluster_ids = [str(cluster.id) for cluster in domain_clusters if cluster.id is not None]
    if session is not None:
        persisted_fields = await _load_persisted_recovery_fields(
            session=session,
            tenant_id=tenant_id,
            cluster_ids=cluster_ids,
        )
        recovered = _clusters_from_persisted_fields(domain_clusters, persisted_fields)
    else:
        members_by_cluster: dict[str, Sequence[MediaIdentity]] = {}
        if cluster_ids:
            loaded = await cluster_repo.get_member_identities_for_clusters(cluster_ids)
            members_by_cluster = {str(key): value for key, value in loaded.items()}
        recovered = _clusters_from_identities(domain_clusters, members_by_cluster)
    typed_policy = policy or default_cluster_recovery_calibration_policy()

    emitter = suggestion_emitter
    if emitter is None and merge_suggestion_service is not None:
        emitter = _ServiceSuggestionEmitter(merge_suggestion_service)

    snapshot = {cluster.cluster_id: cluster for cluster in recovered}
    result = await run_recovery_merge_on_clusters(
        tenant_id=tenant_id,
        clusters=list(snapshot.values()),
        settings=clustering,
        policy=typed_policy,
        runtime_binding=runtime_binding,
        receipt_store=store,
        suggestion_emitter=emitter,
        now=clock,
    )

    if not result.receipts:
        return result
    if session is None:
        logger.warning(
            "[clustering] recovery_merge_skip reason=no_session_for_apply tenant_id=%s",
            tenant_id,
        )
        return RecoveryMergeResult(
            abstentions=result.abstentions,
            purged_receipts=result.purged_receipts,
            suggestions_emitted=result.suggestions_emitted,
            applied=False,
        )

    applied_receipts: list[ClusterMergeReceipt] = []
    for receipt in result.receipts:
        if not await _apply_recovery_receipt(
            session=session,
            receipt_store=store,
            receipt=receipt,
            tenant_id=tenant_id,
        ):
            continue
        applied_receipts.append(receipt)
        destination_id = str(receipt.survivor_cluster_id)
        await assignment_writer.recompute_representatives(destination_id)
        await assignment_writer.recompute_centroid(destination_id)
        if merge_suggestion_service is not None:
            await merge_suggestion_service.delete_by_cluster(tenant_id, str(receipt.source_cluster_id))
            await merge_suggestion_service.delete_by_cluster(tenant_id, destination_id)

    if applied_receipts:
        try:
            await assignment_writer.refresh_centroids_view()
        except Exception:
            logger.warning(
                "[clustering] recovery_merge MV refresh failed tenant_id=%s",
                tenant_id,
                exc_info=True,
            )

    return RecoveryMergeResult(
        merged=len(applied_receipts),
        receipt_ids=tuple(receipt.receipt_id for receipt in applied_receipts),
        receipts=tuple(applied_receipts),
        abstentions=result.abstentions,
        purged_receipts=result.purged_receipts,
        suggestions_emitted=result.suggestions_emitted,
        applied=result.applied and (bool(applied_receipts) or not result.receipts),
    )
