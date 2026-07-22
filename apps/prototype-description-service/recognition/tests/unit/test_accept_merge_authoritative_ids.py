"""Authoritative survivor/retired ids on merge-suggestion accept responses.

``_select_merge_target`` ranks by (user_confirmed, meaningful_label, identity_count, id).
Accept responses must return those ids as ``source_cluster_id`` (retired) /
``target_cluster_id`` (survivor) so clients do not re-rank presentation fields.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from recognition.domain.cluster import IdentityCluster
from recognition.domain.suggestion import SuggestionStatus
from recognition.interface_adapters.http.routers.suggestions import (
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


def test_select_merge_target_user_confirmed_flips_survivor_over_larger_count() -> None:
    """user_confirmed beats identity_count: smaller confirmed cluster is survivor."""
    larger_unconfirmed = _cluster(
        cluster_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        user_confirmed=False,
        label=None,
        identity_count=50,
    )
    smaller_confirmed = _cluster(
        cluster_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        user_confirmed=True,
        label="Named Person",
        identity_count=2,
    )

    source_id, target_id, target_label = _select_merge_target(larger_unconfirmed, smaller_confirmed)

    assert source_id == larger_unconfirmed.id  # retired
    assert target_id == smaller_confirmed.id  # survivor
    assert target_label == "Named Person"


def test_select_merge_target_user_confirmed_flip_when_confirmed_is_cluster_a() -> None:
    """Same ranking with sides swapped — confirmed still survives."""
    confirmed_a = _cluster(
        cluster_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        user_confirmed=True,
        label="Ada",
        identity_count=1,
    )
    larger_b = _cluster(
        cluster_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        user_confirmed=False,
        label=None,
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
    a = _cluster(cluster_id=cluster_a_id, user_confirmed=False, identity_count=50)
    b = _cluster(cluster_id=cluster_b_id, user_confirmed=True, label="Survivor", identity_count=2)
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
