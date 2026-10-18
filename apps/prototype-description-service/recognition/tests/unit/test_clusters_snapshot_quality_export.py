"""GPUFLOW-2 B2a: snapshot export of representative quality and undo receipt.

Wire shape for php-projection-ingest. Values are copied from the chosen
representative / receipt; nothing is recomputed here (rg-015, API-10, UXR-15).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import jsonschema
import pytest
from sqlalchemy.orm.attributes import set_committed_value

from db.models.identity import (
    ClusterMergeReceipt,
    IdentityClusterRepresentative,
    MediaIdentity,
)
from db.models.identity import IdentityCluster as ClusterModel
from recognition.domain.cluster import IdentityCluster
from recognition.domain.job import JobStatus, JobType
from recognition.domain.representative import ClusterRepresentative
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.interface_adapters.http.routers.clusters_snapshot import (
    _build_cluster_responses,
    _export_representative_quality,
)
from recognition.interface_adapters.http.schemas.responses import (
    ClusterDeltaResponse,
    JobProgressResponse,
    JobStatusResponse,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
TENANT_ID = UUID("f1a2b3c4-d5e6-47f8-9012-3456789abcde")
CLUSTER_ID = UUID("6c1a2e32-31b2-4d54-a4de-98b1a73d77a1")
IDENTITY_ID = UUID("4b8f0a3e-3f1f-4f59-96f2-bfb6c8c1d3bb")
REPRESENTATIVE_ID = UUID("d7c6b5a4-9382-41f0-b1e2-3d4c5b6a7980")
RECEIPT_NEW = UUID("b9e2c4a1-7d6f-4a8b-9c31-2e5f0a7b8d44")
RECEIPT_OLD = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

_QUALITY_COMPONENT_KEYS = ("confidence", "bbox_area", "sharpness", "occlusion_severity")


def _identity(*, media_id: int = 501, identity_id: UUID = IDENTITY_ID) -> MediaIdentity:
    return MediaIdentity(
        id=identity_id,
        tenant_id=TENANT_ID,
        media_id=media_id,
        media_url="https://example.test/face.jpg",
        bbox_x=10,
        bbox_y=20,
        bbox_width=80,
        bbox_height=96,
        confidence=0.94,
        embedding=[1.0, 0.0, 0.0, 0.0],
        embedding_model="test-model",
        pose_pitch=0.0,
        pose_yaw=0.0,
        pose_roll=0.0,
        quality_score=0.9,
    )


def _representative(
    *,
    representative_id: UUID = REPRESENTATIVE_ID,
    identity_id: UUID = IDENTITY_ID,
    quality_score: float = 0.82,
    quality_components: dict[str, Any] | None = None,
    is_user_selected: bool = False,
) -> IdentityClusterRepresentative:
    return IdentityClusterRepresentative(
        id=representative_id,
        tenant_id=TENANT_ID,
        cluster_id=CLUSTER_ID,
        identity_id=identity_id,
        embedding=[1.0, 0.0, 0.0, 0.0],
        quality_score=quality_score,
        quality_components=(
            quality_components
            if quality_components is not None
            else {
                "confidence": 0.94,
                "bbox_area": 7680,
                "sharpness": 42.5,
                "occlusion_severity": 0.12,
            }
        ),
        diversity_score=None,
        is_user_selected=is_user_selected,
        is_provisional=False,
        created_at=NOW - timedelta(days=1),
    )


def _receipt(
    *,
    receipt_id: UUID,
    sequence_no: int,
    created_at: datetime = NOW - timedelta(hours=1),
    reverted_at: datetime | None = None,
    expires_at: datetime = datetime(2099, 1, 1, tzinfo=UTC),
) -> ClusterMergeReceipt:
    return ClusterMergeReceipt(
        receipt_id=receipt_id,
        tenant_id=TENANT_ID,
        survivor_cluster_id=CLUSTER_ID,
        source_cluster_id=uuid4(),
        source_label="Source cluster",
        moved_identity_ids=[IDENTITY_ID],
        rule_version="test-policy-v1",
        kind="auto",
        created_at=created_at,
        expires_at=expires_at,
        reverted_at=reverted_at,
        sequence_no=sequence_no,
    )


def _cluster_model(
    *,
    representatives: list[IdentityClusterRepresentative] | None = None,
    identities: list[MediaIdentity] | None = None,
    merge_receipts: list[ClusterMergeReceipt] | None = None,
    load_representatives: bool = True,
    load_merge_receipts: bool = True,
    label: str | None = "Alice Example",
    user_confirmed: bool = True,
    dismissed_at: datetime | None = None,
    identity_count: int = 2,
) -> ClusterModel:
    representatives = representatives if representatives is not None else [_representative()]
    identities = identities if identities is not None else [_identity()]
    merge_receipts = merge_receipts if merge_receipts is not None else []
    model = ClusterModel(
        id=CLUSTER_ID,
        tenant_id=TENANT_ID,
        label=label,
        representative_identity_id=IDENTITY_ID,
        identity_count=identity_count,
        clustering_algorithm="graph",
        user_confirmed=user_confirmed,
        dismissed_at=dismissed_at,
        created_at=NOW - timedelta(days=2),
        updated_at=NOW - timedelta(minutes=1),
    )

    if load_representatives:
        for representative, identity in zip(representatives, identities, strict=True):
            set_committed_value(representative, "identity", identity)
        set_committed_value(model, "representatives", representatives)
    if load_merge_receipts:
        set_committed_value(model, "merge_receipts", merge_receipts)
    return model


def _domain_cluster(**kwargs: Any) -> IdentityCluster:
    model = _cluster_model(**kwargs)
    return SqlAlchemyClusterRepository(MagicMock())._to_domain(model)


def _dump(cluster: IdentityCluster) -> dict[str, object]:
    [row] = _build_cluster_responses([cluster], now=NOW)
    return row.model_dump(mode="json")


def test_to_domain_carries_quality_components_and_undoable_receipt() -> None:
    model = _cluster_model(
        merge_receipts=[
            _receipt(receipt_id=RECEIPT_NEW, sequence_no=2),
        ],
    )

    domain = SqlAlchemyClusterRepository(MagicMock())._to_domain(model)

    assert isinstance(domain.representatives[0], ClusterRepresentative)
    assert domain.representatives[0].quality_components == {
        "confidence": 0.94,
        "bbox_area": 7680,
        "sharpness": 42.5,
        "occlusion_severity": 0.12,
    }
    assert domain.undoable_merge_receipt_id == str(RECEIPT_NEW)


def test_to_domain_leaves_undoable_receipt_null_when_stack_is_not_loaded() -> None:
    model = _cluster_model(load_merge_receipts=False)

    domain = SqlAlchemyClusterRepository(MagicMock())._to_domain(model)

    assert domain.undoable_merge_receipt_id is None


def test_export_copies_quality_score_components_media_and_undoable_receipt() -> None:
    payload = _dump(
        _domain_cluster(
            merge_receipts=[
                _receipt(receipt_id=RECEIPT_NEW, sequence_no=2),
            ],
        )
    )

    assert payload["representative_quality"] == 0.82
    assert payload["quality_components"] == {
        "confidence": 0.94,
        "bbox_area": 7680.0,
        "sharpness": 42.5,
        "occlusion_severity": 0.12,
    }
    assert payload["representative_media_id"] == 501
    assert payload["undoable_merge_receipt_id"] == str(RECEIPT_NEW)
    assert payload["representative_id"] == str(IDENTITY_ID)
    assert payload["representative_thumb_path"] == f"acx://cluster/{CLUSTER_ID}/media/501"


def test_job_status_projection_preserves_quality_fields_and_matches_contract() -> None:
    [cluster_row] = _build_cluster_responses(
        [
            _domain_cluster(
                merge_receipts=[
                    _receipt(receipt_id=RECEIPT_NEW, sequence_no=2),
                ],
            )
        ],
        now=NOW,
    )
    projection = ClusterDeltaResponse(
        tenant_id=str(TENANT_ID),
        snapshot_version=105,
        generated_at=NOW,
        clusters=[cluster_row],
        members=[],
    )
    response = JobStatusResponse(
        id=str(RECEIPT_NEW),
        type=JobType.CLUSTERING,
        status=JobStatus.COMPLETED,
        progress=JobProgressResponse(completed=1, total=1),
        started_at=NOW,
        finished_at=NOW,
        projection_payload=projection,
    )

    payload = response.model_dump(mode="json")
    projected_cluster = payload["projection_payload"]["clusters"][0]

    assert projected_cluster["representative_quality"] == 0.82
    assert projected_cluster["quality_components"] == {
        "confidence": 0.94,
        "bbox_area": 7680.0,
        "sharpness": 42.5,
        "occlusion_severity": 0.12,
    }
    assert projected_cluster["representative_media_id"] == 501
    assert projected_cluster["undoable_merge_receipt_id"] == str(RECEIPT_NEW)

    schema_path = (
        Path(__file__).resolve().parents[5]
        / "packages"
        / "shared-contracts"
        / "schemas"
        / "recognition-cluster-snapshot.schema.json"
    )
    jsonschema.validate(payload["projection_payload"], json.loads(schema_path.read_text()))


def test_export_includes_co_required_quality_keys_as_null_without_representative() -> None:
    payload = _dump(_domain_cluster(representatives=[], identities=[]))

    assert payload["representative_quality"] is None
    assert payload["quality_components"] is None
    assert payload["representative_media_id"] is None
    assert payload["undoable_merge_receipt_id"] is None
    assert payload["representative_id"] is None


def test_export_rejects_score_without_components() -> None:
    cluster = _domain_cluster(
        representatives=[_representative(quality_components={})],
        identities=[_identity()],
    )

    payload = _dump(cluster)

    assert payload["representative_quality"] is None
    assert payload["quality_components"] is None


def test_export_rejects_components_without_score() -> None:
    cluster = _domain_cluster()
    representative = cluster.representatives[0]
    assert isinstance(representative, ClusterRepresentative)
    cluster.representatives = [replace(representative, quality_score=None)]

    payload = _dump(cluster)

    assert payload["representative_quality"] is None
    assert payload["quality_components"] is None


def test_export_rejects_nonfinite_score_or_components() -> None:
    for score in (float("nan"), float("inf"), float("-inf")):
        cluster = _domain_cluster(
            representatives=[_representative(quality_score=score)],
            identities=[_identity()],
        )
        payload = _dump(cluster)
        assert payload["representative_quality"] is None
        assert payload["quality_components"] is None

    cluster = _domain_cluster(
        representatives=[
            _representative(
                quality_components={
                    "confidence": 0.94,
                    "bbox_area": float("nan"),
                }
            )
        ],
        identities=[_identity()],
    )
    payload = _dump(cluster)
    assert payload["representative_quality"] is None
    assert payload["quality_components"] is None


def test_export_fills_missing_component_keys_with_null_never_omits() -> None:
    cluster = _domain_cluster(
        representatives=[
            _representative(quality_components={"confidence": 0.4, "unknown_signal": 9.0}),
        ],
        identities=[_identity()],
    )

    components = _dump(cluster)["quality_components"]
    assert isinstance(components, dict)
    assert set(components) == set(_QUALITY_COMPONENT_KEYS)
    assert components["confidence"] == 0.4
    assert components["bbox_area"] is None
    assert components["sharpness"] is None
    assert components["occlusion_severity"] is None
    assert "unknown_signal" not in components


def test_export_uses_pinned_representative_not_highest_quality_score() -> None:
    higher_identity = _identity(media_id=99)
    pinned_identity = _identity(media_id=11, identity_id=uuid4())
    pinned = _representative(
        representative_id=UUID("00000000-0000-0000-0000-000000000001"),
        identity_id=pinned_identity.id,
        is_user_selected=True,
        quality_score=0.2,
        quality_components={"confidence": 0.2, "bbox_area": 1, "sharpness": 1.0, "occlusion_severity": 0.9},
    )
    higher = _representative(
        representative_id=UUID("00000000-0000-0000-0000-000000000002"),
        identity_id=higher_identity.id,
        is_user_selected=False,
        quality_score=0.99,
        quality_components={"confidence": 0.99, "bbox_area": 9, "sharpness": 90.0, "occlusion_severity": 0.0},
    )
    cluster = _domain_cluster(
        representatives=[higher, pinned],
        identities=[higher_identity, pinned_identity],
    )

    payload = _dump(cluster)

    assert payload["representative_quality"] == 0.2
    assert payload["representative_media_id"] == 11
    assert payload["is_pinned"] is True


def test_export_uses_highest_quality_representative_not_lexicographically_first() -> None:
    lower_identity = _identity(media_id=101, identity_id=UUID("11111111-1111-1111-1111-111111111111"))
    higher_identity = _identity(media_id=202, identity_id=UUID("22222222-2222-2222-2222-222222222222"))
    lower = _representative(
        representative_id=UUID("00000000-0000-0000-0000-000000000001"),
        identity_id=lower_identity.id,
        quality_score=0.2,
    )
    higher = _representative(
        representative_id=UUID("00000000-0000-0000-0000-000000000002"),
        identity_id=higher_identity.id,
        quality_score=0.9,
    )

    payload = _dump(
        _domain_cluster(
            representatives=[lower, higher],
            identities=[lower_identity, higher_identity],
        )
    )

    assert payload["representative_id"] == str(higher_identity.id)
    assert payload["representative_thumb_path"] == f"acx://cluster/{CLUSTER_ID}/media/202"
    assert payload["representative_media_id"] == 202
    assert payload["representative_quality"] == 0.9


def test_export_prefers_measured_quality_components_over_defaulted_score() -> None:
    default_identity = _identity(media_id=303, identity_id=UUID("33333333-3333-3333-3333-333333333333"))
    measured_identity = _identity(media_id=404, identity_id=UUID("44444444-4444-4444-4444-444444444444"))
    defaulted = _representative(
        representative_id=UUID("00000000-0000-0000-0000-000000000003"),
        identity_id=default_identity.id,
        quality_score=1.0,
        quality_components={},
    )
    measured = _representative(
        representative_id=UUID("00000000-0000-0000-0000-000000000004"),
        identity_id=measured_identity.id,
        quality_score=0.4,
    )
    cluster = _domain_cluster(
        representatives=[defaulted, measured],
        identities=[default_identity, measured_identity],
    )
    defaulted_domain, measured_domain = cluster.representatives
    cluster.representatives = [
        replace(defaulted_domain, quality_score=1.0, quality_components=None),
        measured_domain,
    ]

    payload = _dump(cluster)

    assert payload["representative_id"] == str(measured_identity.id)
    assert payload["representative_media_id"] == 404
    assert payload["representative_quality"] == 0.4


def test_export_breaks_equal_quality_scores_by_representative_id() -> None:
    lower_rep_id = UUID("00000000-0000-0000-0000-000000000005")
    higher_rep_id = UUID("00000000-0000-0000-0000-000000000006")
    lower_identity = _identity(media_id=505, identity_id=UUID("55555555-5555-5555-5555-555555555555"))
    higher_identity = _identity(media_id=606, identity_id=UUID("66666666-6666-6666-6666-666666666666"))

    for representatives, identities in (
        (
            [
                _representative(
                    representative_id=higher_rep_id,
                    identity_id=higher_identity.id,
                    quality_score=0.7,
                ),
                _representative(
                    representative_id=lower_rep_id,
                    identity_id=lower_identity.id,
                    quality_score=0.7,
                ),
            ],
            [higher_identity, lower_identity],
        ),
        (
            [
                _representative(
                    representative_id=lower_rep_id,
                    identity_id=lower_identity.id,
                    quality_score=0.7,
                ),
                _representative(
                    representative_id=higher_rep_id,
                    identity_id=higher_identity.id,
                    quality_score=0.7,
                ),
            ],
            [lower_identity, higher_identity],
        ),
    ):
        payload = _dump(_domain_cluster(representatives=representatives, identities=identities))

        assert payload["representative_id"] == str(lower_identity.id)
        assert payload["representative_media_id"] == 505


def test_undoable_receipt_is_highest_sequence_unreverted_unexpired() -> None:
    expired = _receipt(
        receipt_id=uuid4(),
        sequence_no=5,
        expires_at=datetime.now(tz=UTC) - timedelta(seconds=1),
    )
    reverted = _receipt(
        receipt_id=uuid4(),
        sequence_no=4,
        reverted_at=NOW - timedelta(minutes=1),
    )
    older = _receipt(receipt_id=RECEIPT_OLD, sequence_no=1)
    newer = _receipt(receipt_id=RECEIPT_NEW, sequence_no=2)
    cluster = _domain_cluster(
        merge_receipts=[expired, reverted, older, newer],
    )

    assert _dump(cluster)["undoable_merge_receipt_id"] == str(RECEIPT_NEW)


def test_expired_or_reverted_only_stack_exports_null_receipt() -> None:
    cluster = _domain_cluster(
        merge_receipts=[
            _receipt(
                receipt_id=RECEIPT_NEW,
                sequence_no=1,
                expires_at=datetime.now(tz=UTC) - timedelta(seconds=1),
            ),
            _receipt(
                receipt_id=RECEIPT_OLD,
                sequence_no=2,
                reverted_at=NOW,
            ),
        ],
    )

    assert _dump(cluster)["undoable_merge_receipt_id"] is None


class _ScalarResult:
    def __init__(self, rows: list[ClusterModel]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[ClusterModel]:
        return list(self._rows)


@pytest.mark.asyncio
async def test_targeted_snapshot_builder_matches_full_snapshot_builder() -> None:
    model = _cluster_model(
        merge_receipts=[_receipt(receipt_id=RECEIPT_NEW, sequence_no=2)],
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_ScalarResult([model]))
    repo = SqlAlchemyClusterRepository(session)

    full_domain = repo._to_domain(model)

    # The targeted repository path uses the same conversion as a full snapshot.
    targeted_clusters = await repo.get_clusters_by_ids(str(TENANT_ID), [str(CLUSTER_ID)])
    full_payload = _dump(full_domain)
    targeted_payload = _dump(targeted_clusters[0])

    assert targeted_payload == full_payload
    statement = session.execute.await_args.args[0]
    assert len(statement._with_options) == 2


def test_export_representative_quality_returns_paired_values_for_valid_data() -> None:
    representative = _domain_cluster().representatives[0]
    assert isinstance(representative, ClusterRepresentative)

    score, components = _export_representative_quality(representative)

    assert score == 0.82
    assert components is not None
