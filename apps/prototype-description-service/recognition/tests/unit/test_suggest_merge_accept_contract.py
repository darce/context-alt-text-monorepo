"""FEBT1-LD-01: atomic merge-accept returns revert ids and honours operator target."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from recognition.domain.cluster import IdentityCluster
from recognition.interface_adapters.http.routers.suggestions import (
    AcceptMergeSuggestionRequest,
    AcceptMergeSuggestionResponse,
    _resolve_merge_pair,
    _to_accept_merge_response,
)
from recognition.interface_adapters.http.schemas.responses import MergeSuggestionResponse


def _cluster(cluster_id: str, *, identity_count: int = 1) -> IdentityCluster:
    return IdentityCluster(
        tenant_id=str(uuid4()),
        is_labeled=False,
        identity_count=identity_count,
        id=cluster_id,
        user_confirmed=False,
    )


def test_accept_merge_response_includes_moved_identity_ids() -> None:
    assert "moved_identity_ids" in AcceptMergeSuggestionResponse.model_fields
    assert "target_cluster_id" in AcceptMergeSuggestionRequest.model_fields
    payload = _to_accept_merge_response(
        MergeSuggestionResponse(
            id=str(uuid4()),
            cluster_a_id=str(uuid4()),
            cluster_b_id=str(uuid4()),
            similarity=0.7,
            status="accepted",
        ),
        moved_identity_ids=["id-1", "id-2"],
    )
    assert payload.moved_identity_ids == ["id-1", "id-2"]


def test_resolve_merge_pair_honours_operator_target() -> None:
    smaller = _cluster("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", identity_count=1)
    larger = _cluster("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", identity_count=9)

    source_id, target_id, _label = _resolve_merge_pair(
        smaller,
        larger,
        requested_target_cluster_id=smaller.id,
    )

    assert target_id == smaller.id
    assert source_id == larger.id


def test_resolve_merge_pair_rejects_unrelated_target() -> None:
    cluster_a = _cluster("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    cluster_b = _cluster("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    with pytest.raises(HTTPException) as exc:
        _resolve_merge_pair(
            cluster_a,
            cluster_b,
            requested_target_cluster_id=str(uuid4()),
        )

    assert exc.value.status_code == 422
