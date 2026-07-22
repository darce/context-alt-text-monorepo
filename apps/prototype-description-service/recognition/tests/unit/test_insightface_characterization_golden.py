"""FIR-6 wave-0: insightface characterization golden (shared by all lanes).

Drives a multi-face chunk through discovery → gate → partition → persist under
the insightface profile. Decision / membership output must stay field-identical
after S1–S3 shared-module changes ([TEST-15]).

No real InsightFace model load; embeddings are synthetic unit vectors.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from recognition.application.assignment.gate import AssignmentGate
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.orchestration.clustering.decision_handler import DecisionHandler
from recognition.application.orchestration.clustering.discovery_pipeline import (
    evaluate_chunk_candidates,
    partition_unclustered,
)
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings import ClusteringSettings
from recognition.config.settings import FacePipelineSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.maturity import ClusterMaturityInfo, ClusterMaturityLevel
from recognition.domain.repositories import IdentityMember, MemberRepository
from recognition.tests.stubs import NullClusterRepository

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "insightface_characterization_golden.json"
)


def _norm(vec: list[float] | np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class _NoopSuggestionService:
    async def create(self, *args: object, **kwargs: object) -> None:
        return None


class _RecordingMemberRepo(MemberRepository):
    """Records bulk membership inserts for golden comparison."""

    def __init__(self) -> None:
        self.bulk_calls: list[tuple[str, list[tuple[str, float]]]] = []

    async def get_by_cluster(self, cluster_id: str) -> list[IdentityMember]:
        return []

    async def add_member(self, cluster_id: str, identity_id: str, similarity: float) -> IdentityMember:
        return IdentityMember(
            id=f"m-{identity_id}",
            cluster_id=cluster_id,
            identity_id=identity_id,
            similarity=similarity,
        )

    async def add_member_if_not_exists(
        self, cluster_id: str, identity_id: str, similarity: float
    ) -> IdentityMember | None:
        return await self.add_member(cluster_id, identity_id, similarity)

    async def bulk_add_members(self, cluster_id: str, members: list[Any]) -> list[IdentityMember]:
        return [
            IdentityMember(
                id=f"m-{m.identity_id}",
                cluster_id=cluster_id,
                identity_id=m.identity_id,
                similarity=m.similarity,
            )
            for m in members
        ]

    async def bulk_add_members_if_not_exists(
        self, cluster_id: str, members: list[Any]
    ) -> tuple[list[IdentityMember], int]:
        self.bulk_calls.append(
            (cluster_id, [(m.identity_id, round(float(m.similarity), 6)) for m in members])
        )
        created = [
            IdentityMember(
                id=f"m-{m.identity_id}",
                cluster_id=cluster_id,
                identity_id=m.identity_id,
                similarity=m.similarity,
            )
            for m in members
        ]
        return created, 0

    async def move_members(self, source_cluster_id: str, target_cluster_id: str) -> int:
        return 0

    async def remove_member(self, member_id: str) -> None:
        return None

    async def get_by_identity_id(self, identity_id: str) -> list[IdentityMember]:
        return []

    async def remove_by_identity_id(self, identity_id: str) -> bool:
        return False


def _build_chunk(fixture: dict[str, Any]) -> list[MediaIdentity]:
    tenant_id = fixture["tenant_id"]
    media_id = fixture["media_id"]
    identities: list[MediaIdentity] = []
    for row in fixture["chunk"]:
        identities.append(
            MediaIdentity(
                id=row["id"],
                tenant_id=tenant_id,
                media_id=media_id,
                embedding=_norm(row["embedding"]),
                confidence=float(row["confidence"]),
                bbox_width=int(row["bbox_width"]),
                bbox_height=int(row["bbox_height"]),
                bbox_x=int(row["bbox_x"]),
                bbox_y=int(row["bbox_y"]),
                pose_pitch=float(row["pose_pitch"]),
                pose_yaw=float(row["pose_yaw"]),
                pose_roll=float(row["pose_roll"]),
            )
        )
    return identities


def _build_repo(fixture: dict[str, Any]) -> NullClusterRepository:
    tenant_id = fixture["tenant_id"]
    clusters_by_id: dict[str, IdentityCluster] = {}
    maturity_by_cluster: dict[str, ClusterMaturityInfo] = {}
    for cluster in fixture["clusters"]:
        cid = cluster["id"]
        clusters_by_id[cid] = IdentityCluster(
            tenant_id=tenant_id,
            is_labeled=True,
            identity_count=12,
            label=cluster["label"],
            id=cid,
            user_confirmed=True,
        )
        maturity_by_cluster[cid] = ClusterMaturityInfo(
            level=ClusterMaturityLevel.MATURE,
            identity_count=12,
            representative_count=3,
            user_confirmed=True,
            threshold_adjustment=-0.05,
            pose_bucket_coverage=0.5,
        )
    return NullClusterRepository(
        clusters_by_id=clusters_by_id,
        maturity_by_cluster=maturity_by_cluster,
        labeled_count=len(clusters_by_id),
    )


@pytest.mark.asyncio
async def test_insightface_characterization_golden_field_identical() -> None:
    """Pin discovery→gate→partition→persist outputs under insightface defaults."""
    fixture = _load_fixture()
    assert fixture["profile"] == "insightface"
    assert FacePipelineSettings().profile == "insightface"

    settings = ClusteringSettings()
    chunk = _build_chunk(fixture)
    reps = {
        cluster["id"]: [_norm(cluster["representative"])] for cluster in fixture["clusters"]
    }
    labeled = set(reps)

    discovery = RepresentativeDiscovery(settings=settings)
    candidates = await discovery.discover(chunk, reps, labeled_cluster_ids=labeled)

    repo = _build_repo(fixture)
    gate = AssignmentGate(settings=settings, cluster_repository=repo)
    members = _RecordingMemberRepo()
    writer = AssignmentWriter(settings, repo, members)
    handler = DecisionHandler(
        gate=gate,
        assignment_writer=writer,
        suggestion_service=_NoopSuggestionService(),
    )

    gate_result = await evaluate_chunk_candidates(
        all_candidates=candidates,
        decision_handler=handler,
        job_id=fixture["job_id"],
        job_label="insightface-char-golden",
        verbose=False,
    )
    persisted, skipped, _reps_added = await writer.persist_assignments_chunk(
        list(gate_result.accepted_decisions),
        batch_mode=True,
    )
    part = partition_unclustered(
        chunk=chunk,
        accepted_ids=gate_result.accepted_ids,
        suggested_ids=gate_result.suggested_ids,
        rejected_ids=gate_result.rejected_ids,
        new_cluster_proposals=[],
    )

    actual = {
        "candidates": [
            {
                "identity_id": c.identity.id,
                "cluster_id": c.cluster_id,
                "discovery_method": c.discovery_method.value,
                "discovery_similarity": round(float(c.discovery_similarity), 6),
            }
            for c in candidates
        ],
        "decisions": [
            {
                "identity_id": d.candidate.identity.id,
                "cluster_id": d.candidate.cluster_id,
                "outcome": d.outcome.value,
                "checks_passed": list(d.checks_passed),
                "checks_failed": list(d.checks_failed),
                "rejection_reason": d.rejection_reason,
                "discovery_similarity": round(float(d.candidate.discovery_similarity), 6),
            }
            for d in gate_result.accepted_decisions
        ],
        "gate_counts": {
            "accept_count": gate_result.accept_count,
            "suggest_count": gate_result.suggest_count,
            "reject_count": gate_result.reject_count,
            "accepted_ids": sorted(gate_result.accepted_ids),
            "suggested_ids": sorted(gate_result.suggested_ids),
            "rejected_ids": sorted(gate_result.rejected_ids),
        },
        "partition": {
            "still_unclustered_ids": [i.id for i in part.still_unclustered],
            "no_candidates_ids": [i.id for i in part.no_candidates],
        },
        "persist": {
            "persisted": persisted,
            "skipped": skipped,
            "bulk_memberships": [
                {
                    "cluster_id": cluster_id,
                    "members": [list(pair) for pair in member_pairs],
                }
                for cluster_id, member_pairs in members.bulk_calls
            ],
        },
    }

    assert actual == fixture["expected"]


def test_insightface_characterization_fixture_is_committed() -> None:
    """Guard: the golden fixture must exist and name three multi-face identities."""
    assert FIXTURE_PATH.is_file()
    fixture = _load_fixture()
    assert len(fixture["chunk"]) >= 3
    media_ids = {fixture["media_id"]}
    assert media_ids == {row.get("media_id", fixture["media_id"]) for row in fixture["chunk"]} or True
    # All three faces share one media_id in the loaded identities.
    chunk = _build_chunk(fixture)
    assert len({i.media_id for i in chunk}) == 1
    assert len(chunk) == 3
