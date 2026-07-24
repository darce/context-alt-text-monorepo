"""FIR-6 wave-0: insightface characterization golden (shared by all lanes).

Drives a multi-face chunk through discovery → gate → partition → persist under
the insightface profile. Decision / membership / representative output must stay
field-identical after S1–S3 shared-module changes ([TEST-15]).

Discrimination (M-01): similarities straddle discovery/threshold edges; fixture
includes accept + suggest + no-candidate; threshold metadata + curriculum_t are
pinned so arithmetic drifts go red. Order-independent compare (M-04). Full float
similarity equality (M-08). Representative admission recorded (M-02).

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


def _float(value: float) -> float:
    """Canonicalize float32→python float without decimal truncation (M-08)."""
    return float(value)


def _threshold_meta(metadata: dict[str, Any] | None) -> dict[str, Any]:
    md = metadata or {}
    return {
        "base_threshold": md.get("base_threshold"),
        "final_threshold": md.get("final_threshold"),
        "suggestion_floor": md.get("suggestion_floor"),
        "suggestion_ceiling": md.get("suggestion_ceiling"),
        "maturity_adj": md.get("maturity_adj"),
        "quality_adj": md.get("quality_adj"),
        "curriculum_t": md.get("curriculum_t"),
        "curriculum_adj": md.get("curriculum_adj"),
    }


def _canonicalize_expected(payload: dict[str, Any]) -> dict[str, Any]:
    """Order-independent projection for field-identical compare (M-04 / TEST-15)."""
    candidates = sorted(
        payload["candidates"],
        key=lambda row: (row["identity_id"], row["cluster_id"], row["discovery_method"]),
    )
    decisions = sorted(
        payload["decisions"],
        key=lambda row: (row["identity_id"], row["cluster_id"], row["outcome"]),
    )
    gate = dict(payload["gate_counts"])
    gate["accepted_ids"] = sorted(gate["accepted_ids"])
    gate["suggested_ids"] = sorted(gate["suggested_ids"])
    gate["rejected_ids"] = sorted(gate["rejected_ids"])

    partition = {
        "still_unclustered_ids": sorted(payload["partition"]["still_unclustered_ids"]),
        "no_candidates_ids": sorted(payload["partition"]["no_candidates_ids"]),
    }

    bulk = []
    for entry in payload["persist"]["bulk_memberships"]:
        members = sorted(
            ([pair[0], pair[1]] for pair in entry["members"]),
            key=lambda pair: pair[0],
        )
        bulk.append({"cluster_id": entry["cluster_id"], "members": members})
    bulk.sort(key=lambda entry: entry["cluster_id"])

    reps = sorted(
        payload["persist"]["representatives_added"],
        key=lambda row: (row["cluster_id"], row["identity_id"]),
    )

    return {
        "threshold_context": payload["threshold_context"],
        "candidates": candidates,
        "decisions": decisions,
        "gate_counts": gate,
        "partition": partition,
        "persist": {
            "persisted": payload["persist"]["persisted"],
            "skipped": payload["persist"]["skipped"],
            "reps_added": payload["persist"]["reps_added"],
            "bulk_memberships": bulk,
            "representatives_added": reps,
        },
    }


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
        # Full float precision — do not round before recording (M-08).
        self.bulk_calls.append(
            (cluster_id, [(m.identity_id, _float(m.similarity)) for m in members])
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


def _settings_from_fixture(fixture: dict[str, Any]) -> ClusteringSettings:
    ctx = fixture["threshold_context"]
    return ClusteringSettings(
        similarity_threshold=float(ctx["similarity_threshold"]),
        suggestion_floor=float(ctx["suggestion_floor"]),
        suggestion_ceiling=float(ctx["suggestion_ceiling"]),
        curriculum_coefficient=float(ctx["curriculum_coefficient"]),
    )


async def _run_characterization(
    fixture: dict[str, Any],
    *,
    settings: ClusteringSettings | None = None,
) -> dict[str, Any]:
    """Execute discovery→gate→partition→persist and project comparable fields.

    Uses evaluate_chunk_candidates + persist_assignments_chunk (the bulk path S2
    rebinds). Full orchestrator/chunker integration is S2-owned; a return-arity
    change on persist_assignments_chunk still breaks the 3-tuple unpack here (M-03).
    """
    settings = settings or _settings_from_fixture(fixture)
    chunk = _build_chunk(fixture)
    reps = {
        cluster["id"]: [_norm(cluster["representative"])] for cluster in fixture["clusters"]
    }
    labeled = set(reps)

    discovery = RepresentativeDiscovery(settings=settings)
    candidates = await discovery.discover(chunk, reps, labeled_cluster_ids=labeled)

    repo = _build_repo(fixture)
    curriculum_t = float(fixture["threshold_context"]["curriculum_t"])
    for cluster in fixture["clusters"]:
        await repo.set_curriculum_t(cluster["id"], curriculum_t)

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
    # Capture ALL decision outcomes (accept/suggest/reject) with threshold meta.
    all_decisions = [await gate.evaluate(candidate) for candidate in candidates]

    persisted, skipped, reps_added, _guard_rejected = await writer.persist_assignments_chunk(
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

    representatives_added: list[dict[str, str]] = []
    for cluster in fixture["clusters"]:
        for rep in await repo.get_all_representatives(cluster["id"]):
            representatives_added.append(
                {
                    "cluster_id": cluster["id"],
                    "identity_id": rep.identity_id,
                }
            )

    return {
        "threshold_context": {
            "similarity_threshold": float(settings.similarity_threshold),
            "suggestion_floor": float(settings.suggestion_floor),
            "suggestion_ceiling": float(settings.suggestion_ceiling),
            "curriculum_coefficient": float(settings.curriculum_coefficient),
            "curriculum_t": curriculum_t,
        },
        "candidates": [
            {
                "identity_id": c.identity.id,
                "cluster_id": c.cluster_id,
                "discovery_method": c.discovery_method.value,
                "discovery_similarity": _float(c.discovery_similarity),
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
                "discovery_similarity": _float(d.candidate.discovery_similarity),
                "threshold_meta": _threshold_meta(d.metadata),
            }
            for d in all_decisions
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
            "reps_added": reps_added,
            "bulk_memberships": [
                {
                    "cluster_id": cluster_id,
                    "members": [list(pair) for pair in member_pairs],
                }
                for cluster_id, member_pairs in members.bulk_calls
            ],
            "representatives_added": representatives_added,
        },
    }


@pytest.mark.asyncio
async def test_insightface_characterization_golden_field_identical() -> None:
    """Pin discovery→gate→partition→persist outputs under insightface defaults."""
    fixture = _load_fixture()
    assert fixture["profile"] == "insightface"
    assert FacePipelineSettings().profile == "insightface"

    actual = await _run_characterization(fixture)
    assert _canonicalize_expected(actual) == _canonicalize_expected(fixture["expected"])


@pytest.mark.asyncio
async def test_characterization_discriminates_similarity_threshold_drift() -> None:
    """+0.30 discovery threshold must drop the near-threshold face (M-01)."""
    fixture = _load_fixture()
    settings = _settings_from_fixture(fixture)
    drifted = settings.model_copy(
        update={"similarity_threshold": settings.similarity_threshold + 0.30}
    )
    actual = await _run_characterization(fixture, settings=drifted)
    assert _canonicalize_expected(actual) != _canonicalize_expected(fixture["expected"])
    # Near-threshold bob match must leave the candidate set.
    assert "identity-face-b" not in {
        row["identity_id"] for row in actual["candidates"]
    }


@pytest.mark.asyncio
async def test_characterization_discriminates_curriculum_coefficient_drift() -> None:
    """10x curriculum coefficient must move threshold_meta (M-01)."""
    fixture = _load_fixture()
    settings = _settings_from_fixture(fixture)
    drifted = settings.model_copy(
        update={"curriculum_coefficient": settings.curriculum_coefficient * 10.0}
    )
    actual = await _run_characterization(fixture, settings=drifted)
    assert _canonicalize_expected(actual) != _canonicalize_expected(fixture["expected"])
    # At least one accept/suggest decision carries a different curriculum_adj.
    expected_adj = {
        (row["identity_id"], row["threshold_meta"]["curriculum_adj"])
        for row in fixture["expected"]["decisions"]
    }
    actual_adj = {
        (row["identity_id"], row["threshold_meta"]["curriculum_adj"])
        for row in actual["decisions"]
    }
    assert actual_adj != expected_adj


def test_insightface_characterization_fixture_is_committed() -> None:
    """Guard: golden fixture exists; multi-face single media_id; outcome diversity."""
    assert FIXTURE_PATH.is_file()
    fixture = _load_fixture()
    assert len(fixture["chunk"]) >= 3
    # All faces share one media_id (photo-atomic multi-face chunk).
    media_ids = {row.get("media_id", fixture["media_id"]) for row in fixture["chunk"]}
    assert media_ids == {fixture["media_id"]}
    chunk = _build_chunk(fixture)
    assert len({i.media_id for i in chunk}) == 1
    assert len(chunk) >= 3

    outcomes = {row["outcome"] for row in fixture["expected"]["decisions"]}
    assert "accept" in outcomes
    assert "suggest" in outcomes
    assert fixture["expected"]["gate_counts"]["suggest_count"] >= 1
    assert fixture["expected"]["persist"]["reps_added"] >= 1
    assert len(fixture["expected"]["partition"]["no_candidates_ids"]) >= 1
