"""Unit tests for the chunk gate-evaluation and unclustered-partition seams.

ORCH-4: these pin the two pure-logic phases extracted from the 233-line
``IncrementalClusteringRunner._process_chunks`` god-method so they can be
tested in isolation (previously only reachable through the integration path).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from recognition.application.assignment import AssignmentOutcome
from recognition.application.orchestration.clustering.discovery_pipeline import (
    ChunkGateResult,
    ChunkPartition,
    evaluate_chunk_candidates,
    partition_unclustered,
)
from recognition.domain.identity import MediaIdentity


def _candidate(identity_id: str, cluster_id: str | None = "c1") -> SimpleNamespace:
    return SimpleNamespace(identity=SimpleNamespace(id=identity_id, media_id=f"m-{identity_id}"), cluster_id=cluster_id)


class _FakeDecisionHandler:
    """Returns a pre-mapped outcome per candidate identity id and records calls."""

    def __init__(self, outcomes: dict[str, AssignmentOutcome]) -> None:
        self._outcomes = outcomes
        self.calls: list[tuple[str, str, str, bool]] = []

    async def evaluate_only(
        self, candidate: object, *, job_id: str, job_label: str, verbose: bool = True
    ) -> SimpleNamespace:
        identity_id = candidate.identity.id  # type: ignore[attr-defined]
        self.calls.append((identity_id, job_id, job_label, verbose))
        return SimpleNamespace(outcome=self._outcomes[identity_id], candidate=candidate)


@pytest.mark.asyncio
async def test_evaluate_chunk_candidates_partitions_by_outcome() -> None:
    handler = _FakeDecisionHandler(
        {
            "a1": AssignmentOutcome.ACCEPT,
            "s1": AssignmentOutcome.SUGGEST,
            "r1": AssignmentOutcome.REJECT,
            "a2": AssignmentOutcome.ACCEPT,
        }
    )
    candidates = [_candidate("a1"), _candidate("s1"), _candidate("r1"), _candidate("a2")]

    result = await evaluate_chunk_candidates(
        all_candidates=candidates, decision_handler=handler, job_id="job-1", job_label="L", verbose=True
    )

    assert isinstance(result, ChunkGateResult)
    assert (result.accept_count, result.suggest_count, result.reject_count) == (2, 1, 1)
    assert result.accepted_ids == {"a1", "a2"}
    assert result.suggested_ids == {"s1"}
    assert result.rejected_ids == {"r1"}
    # accepted_decisions preserves order and carries the original candidate.
    assert [d.candidate.identity.id for d in result.accepted_decisions] == ["a1", "a2"]
    # kwargs are passed through verbatim to the decision handler.
    assert handler.calls[0] == ("a1", "job-1", "L", True)


@pytest.mark.asyncio
async def test_evaluate_chunk_candidates_empty_returns_zeroed_result() -> None:
    handler = _FakeDecisionHandler({})

    result = await evaluate_chunk_candidates(
        all_candidates=[], decision_handler=handler, job_id="job-1", job_label="L", verbose=False
    )

    assert result == ChunkGateResult(
        accepted_decisions=[],
        accepted_ids=set(),
        suggested_ids=set(),
        rejected_ids=set(),
        accept_count=0,
        suggest_count=0,
        reject_count=0,
    )
    assert handler.calls == []


@pytest.mark.asyncio
async def test_evaluate_chunk_candidates_counts_decisions_not_unique_ids() -> None:
    """accept_count counts decisions; accepted_ids dedupes by identity id."""
    handler = _FakeDecisionHandler({"dup": AssignmentOutcome.ACCEPT})
    candidates = [_candidate("dup", cluster_id="c1"), _candidate("dup", cluster_id="c2")]

    result = await evaluate_chunk_candidates(
        all_candidates=candidates, decision_handler=handler, job_id="j", job_label="L", verbose=False
    )

    assert result.accept_count == 2
    assert result.accepted_ids == {"dup"}
    assert len(result.accepted_decisions) == 2


def _identity(identity_id: str) -> MediaIdentity:
    # Duck-typed stand-in: partition_unclustered only reads ``.id``.
    return cast(MediaIdentity, SimpleNamespace(id=identity_id))


def test_partition_unclustered_combines_no_candidate_rejected_suggested() -> None:
    chunk = [_identity("a1"), _identity("s1"), _identity("r1"), _identity("n1"), _identity("p1")]
    proposals = [([_identity("p1")], [0.9])]

    part = partition_unclustered(
        chunk=chunk,
        accepted_ids={"a1"},
        suggested_ids={"s1"},
        rejected_ids={"r1"},
        new_cluster_proposals=proposals,
    )

    assert isinstance(part, ChunkPartition)
    assert [i.id for i in part.no_candidates] == ["n1"]
    assert [i.id for i in part.rejected_identities] == ["r1"]
    assert [i.id for i in part.suggested_identities] == ["s1"]
    # Ordering is no_candidates ++ rejected ++ suggested (behaviour-preserving).
    assert [i.id for i in part.still_unclustered] == ["n1", "r1", "s1"]


def test_partition_unclustered_excludes_accepted_and_new_cluster_members() -> None:
    chunk = [_identity("a1"), _identity("p1")]
    part = partition_unclustered(
        chunk=chunk,
        accepted_ids={"a1"},
        suggested_ids=set(),
        rejected_ids=set(),
        new_cluster_proposals=[([_identity("p1")], [1.0])],
    )

    assert part.still_unclustered == []


def test_partition_unclustered_flattens_members_across_proposals() -> None:
    """already_in_new_clusters must flatten across MULTIPLE proposals AND multiple
    members per proposal — every new-cluster member is excluded from still_unclustered."""
    chunk = [_identity("p1"), _identity("p2"), _identity("p3"), _identity("n1")]
    part = partition_unclustered(
        chunk=chunk,
        accepted_ids=set(),
        suggested_ids=set(),
        rejected_ids=set(),
        new_cluster_proposals=[
            ([_identity("p1"), _identity("p2")], [0.9, 0.8]),
            ([_identity("p3")], [0.7]),
        ],
    )

    # p1/p2 (proposal 1) and p3 (proposal 2) are all new-cluster members -> excluded.
    assert [i.id for i in part.still_unclustered] == ["n1"]
    assert [i.id for i in part.no_candidates] == ["n1"]
