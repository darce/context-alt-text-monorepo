"""Authoritative survivor/retired ids on merge-suggestion accept responses.

``_select_merge_target`` ranks by (user_confirmed, meaningful_label, identity_count, id).
Accept responses must return those ids as ``source_cluster_id`` (retired) /
``target_cluster_id`` (survivor) so clients do not re-rank presentation fields.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from recognition.domain.cluster import IdentityCluster
from recognition.domain.suggestion import SuggestionStatus
from recognition.interface_adapters.http.routers.suggestions import (
    _is_meaningful_label,
    _select_merge_target,
    _to_merge_response,
)
from recognition.interface_adapters.http.schemas.responses import MergeSuggestionResponse


def _cluster(
    *,
    cluster_id: str,
    user_confirmed: bool = False,
    label: str | None = None,
    identity_count: int = 1,
) -> IdentityCluster:
    return IdentityCluster(
        tenant_id=str(uuid4()),
        is_labeled=bool(label),
        identity_count=identity_count,
        label=label,
        id=cluster_id,
        user_confirmed=user_confirmed,
    )


def test_select_merge_target_placeholder_labels_return_none_target_label() -> None:
    """E21-17-R1-PY47-3: cluster-* survivor labels must not flow into merge guard."""
    larger = _cluster(
        cluster_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        label="cluster-aaa",
        identity_count=5,
    )
    smaller = _cluster(
        cluster_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        label="cluster-bbb",
        identity_count=2,
    )

    source_id, target_id, target_label = _select_merge_target(larger, smaller)

    assert source_id == smaller.id
    assert target_id == larger.id
    assert target_label is None


@pytest.mark.parametrize(
    "label",
    [" CLUSTER-9 ", "cluster_9", "CLUSTER-A"],
)
def test_is_meaningful_label_rejects_reserved_variants(label: str) -> None:
    """E21-17-R2-PY-N2: canonical reserved predicate covers case/underscore/whitespace."""
    assert _is_meaningful_label(label) is False


@pytest.mark.parametrize("label", ["Alice", "Person 2"])
def test_is_meaningful_label_accepts_operator_labels(label: str) -> None:
    assert _is_meaningful_label(label) is True


@pytest.mark.parametrize("label", ["", None, "   "])
def test_is_meaningful_label_rejects_empty(label: str | None) -> None:
    assert _is_meaningful_label(label) is False


def test_select_merge_target_whitespace_reserved_label_returns_none() -> None:
    """E21-17-R2-PY-N2: ' CLUSTER-9 ' survivor must select target_label=None (no 400)."""
    larger = _cluster(
        cluster_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        label=" CLUSTER-9 ",
        identity_count=5,
    )
    smaller = _cluster(
        cluster_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        label="cluster-bbb",
        identity_count=2,
    )

    source_id, target_id, target_label = _select_merge_target(larger, smaller)

    assert source_id == smaller.id
    assert target_id == larger.id
    assert target_label is None


def test_select_merge_target_meaningful_label_unchanged() -> None:
    named = _cluster(
        cluster_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        label="Alice",
        identity_count=2,
    )
    placeholder = _cluster(
        cluster_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        label="cluster-bbb",
        identity_count=50,
    )

    source_id, target_id, target_label = _select_merge_target(named, placeholder)

    assert source_id == placeholder.id
    assert target_id == named.id
    assert target_label == "Alice"


def test_select_merge_target_user_confirmed_flips_survivor_over_larger_count() -> None:
    """user_confirmed is the SOLE discriminator: labels/counts favor the loser."""
    # E215-BR-03: larger unconfirmed has equal-or-better label + higher count;
    # only user_confirmed flips the survivor to the smaller confirmed side.
    larger_unconfirmed = _cluster(
        cluster_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        user_confirmed=False,
        label="Alice",
        identity_count=50,
    )
    smaller_confirmed = _cluster(
        cluster_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        user_confirmed=True,
        label="Bob",
        identity_count=2,
    )

    source_id, target_id, target_label = _select_merge_target(larger_unconfirmed, smaller_confirmed)

    assert source_id == larger_unconfirmed.id  # retired (loser despite better count)
    assert target_id == smaller_confirmed.id  # survivor solely via user_confirmed
    assert target_label == "Bob"


def test_select_merge_target_user_confirmed_flip_when_confirmed_is_cluster_a() -> None:
    """Same ranking with sides swapped — confirmed still survives as sole flip."""
    confirmed_a = _cluster(
        cluster_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        user_confirmed=True,
        label="Ada",
        identity_count=1,
    )
    larger_b = _cluster(
        cluster_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        user_confirmed=False,
        label="Bea",  # equal meaningful label rank; higher count favors loser B
        identity_count=99,
    )

    source_id, target_id, target_label = _select_merge_target(confirmed_a, larger_b)

    assert source_id == larger_b.id
    assert target_id == confirmed_a.id
    assert target_label == "Ada"


def test_to_merge_response_old_shape_omits_authoritative_ids() -> None:
    """Pending/list path (no accept kwargs) leaves source/target null — old shape."""
    suggestion = SimpleNamespace(
        id=str(uuid4()),
        cluster_a_id=str(uuid4()),
        cluster_b_id=str(uuid4()),
        similarity=0.91,
        status=SuggestionStatus.PENDING,
        confidence_score=0.91,
        expires_at=None,
        source_job_id=None,
    )

    response = _to_merge_response(suggestion)

    assert response.source_cluster_id is None
    assert response.target_cluster_id is None
    dumped = response.model_dump()
    # Fields exist on the schema (red against a model that never declared them).
    assert "source_cluster_id" in dumped
    assert "target_cluster_id" in dumped


def test_to_merge_response_accept_shape_carries_select_merge_target_ids() -> None:
    """Accept path must stamp authoritative survivor/retired ids onto the response."""
    cluster_a_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    cluster_b_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    # user_confirmed sole discriminator (labels equal-rank, count favors loser A).
    a = _cluster(cluster_id=cluster_a_id, user_confirmed=False, label="Alice", identity_count=50)
    b = _cluster(cluster_id=cluster_b_id, user_confirmed=True, label="Bob", identity_count=2)
    source_id, target_id, _ = _select_merge_target(a, b)

    suggestion = SimpleNamespace(
        id=str(uuid4()),
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        similarity=0.88,
        status=SuggestionStatus.ACCEPTED,
        confidence_score=0.88,
        expires_at=None,
        source_job_id=None,
    )

    response = _to_merge_response(
        suggestion,
        source_cluster_id=source_id,
        target_cluster_id=target_id,
    )

    assert isinstance(response, MergeSuggestionResponse)
    assert response.status == "accepted"
    assert response.source_cluster_id == source_id == cluster_a_id
    assert response.target_cluster_id == target_id == cluster_b_id
    # Presentation pair is unordered relative to survivor; authoritative fields are ordered.
    assert {response.cluster_a_id, response.cluster_b_id} == {cluster_a_id, cluster_b_id}
    assert response.source_cluster_id != response.target_cluster_id


@pytest.mark.asyncio
async def test_resolve_accepted_merge_ids_via_existence() -> None:
    """ACCEPTED replay: missing side is retired, remaining side is survivor."""
    from recognition.interface_adapters.http.routers.suggestions import _resolve_accepted_merge_ids

    cluster_a_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    cluster_b_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    survivor = _cluster(cluster_id=cluster_b_id, user_confirmed=True, label="Bob", identity_count=2)
    suggestion = SimpleNamespace(
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        status=SuggestionStatus.ACCEPTED,
    )

    class _Repo:
        async def get_by_id(self, cluster_id: str):  # noqa: ANN001
            return survivor if cluster_id == cluster_b_id else None

    source_id, target_id = await _resolve_accepted_merge_ids(suggestion, _Repo())
    assert source_id == cluster_a_id
    assert target_id == cluster_b_id
