"""GPUFLOW-2 B2a: snapshot export of representative quality and undo receipt.

Wire shape for php-projection-ingest. Values are copied from the chosen
representative / receipt; nothing is recomputed here (rg-015, API-10, UXR-15).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from recognition.interface_adapters.http.routers.clusters_snapshot import _build_cluster_responses

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
CLUSTER_ID = UUID("6c1a2e32-31b2-4d54-a4de-98b1a73d77a1")
IDENTITY_ID = UUID("4b8f0a3e-3f1f-4f59-96f2-bfb6c8c1d3bb")
RECEIPT_NEW = UUID("b9e2c4a1-7d6f-4a8b-9c31-2e5f0a7b8d44")
RECEIPT_OLD = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

_QUALITY_COMPONENT_KEYS = ("confidence", "bbox_area", "sharpness", "occlusion_severity")


def _rep(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "identity_id": IDENTITY_ID,
        "is_user_selected": False,
        "media_id": 501,
        "quality_score": 0.82,
        "quality_components": {
            "confidence": 0.94,
            "bbox_area": 7680,
            "sharpness": 42.5,
            "occlusion_severity": 0.12,
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _receipt(
    *,
    receipt_id: UUID,
    created_at: datetime,
    sequence_no: int = 1,
    reverted_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        receipt_id=receipt_id,
        created_at=created_at,
        sequence_no=sequence_no,
        reverted_at=reverted_at,
        expires_at=expires_at if expires_at is not None else created_at + timedelta(days=7),
    )


def _cluster(
    *,
    representatives: list[SimpleNamespace] | None = None,
    merge_receipts: list[SimpleNamespace] | None = None,
    label: str | None = "Alice Example",
    user_confirmed: bool = True,
    dismissed_at: datetime | None = None,
    identity_count: int = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=CLUSTER_ID,
        label=label,
        user_confirmed=user_confirmed,
        dismissed_at=dismissed_at,
        identity_count=identity_count,
        representatives=representatives or [],
        merge_receipts=merge_receipts or [],
    )


def _dump(cluster: SimpleNamespace) -> dict[str, object]:
    [row] = _build_cluster_responses([cluster], now=NOW)
    return row.model_dump(mode="json")


def test_export_copies_quality_score_components_media_and_undoable_receipt() -> None:
    payload = _dump(
        _cluster(
            representatives=[_rep()],
            merge_receipts=[
                _receipt(receipt_id=RECEIPT_NEW, created_at=NOW - timedelta(hours=1), sequence_no=2),
            ],
        )
    )

    assert payload["representative_quality"] == 0.82
    assert payload["quality_components"] == {
        "confidence": 0.94,
        "bbox_area": 7680,
        "sharpness": 42.5,
        "occlusion_severity": 0.12,
    }
    assert payload["representative_media_id"] == 501
    assert payload["undoable_merge_receipt_id"] == str(RECEIPT_NEW)
    assert payload["representative_id"] == str(IDENTITY_ID)
    assert payload["representative_thumb_path"] == f"acx://cluster/{CLUSTER_ID}/media/501"


def test_export_includes_co_required_quality_keys_as_null_without_representative() -> None:
    payload = _dump(_cluster(representatives=[], merge_receipts=[]))

    assert payload["representative_quality"] is None
    assert payload["quality_components"] is None
    assert payload["representative_media_id"] is None
    assert payload["undoable_merge_receipt_id"] is None
    assert payload["representative_id"] is None


def test_export_does_not_invent_quality_components_from_identity_signals() -> None:
    identity = SimpleNamespace(confidence=0.99, bbox_width=80, bbox_height=96, media_id=777)
    payload = _dump(
        _cluster(
            representatives=[
                _rep(
                    quality_score=0.5,
                    quality_components=None,
                    media_id=None,
                    identity=identity,
                )
            ]
        )
    )

    assert payload["representative_quality"] == 0.5
    assert payload["quality_components"] is None
    assert payload["representative_media_id"] == 777


def test_export_fills_missing_component_keys_with_null_never_omits() -> None:
    payload = _dump(
        _cluster(
            representatives=[
                _rep(quality_components={"confidence": 0.4, "unknown_signal": 9.0}),
            ]
        )
    )

    components = payload["quality_components"]
    assert isinstance(components, dict)
    assert set(components) == set(_QUALITY_COMPONENT_KEYS)
    assert components["confidence"] == 0.4
    assert components["bbox_area"] is None
    assert components["sharpness"] is None
    assert components["occlusion_severity"] is None
    assert "unknown_signal" not in components


def test_export_uses_pinned_representative_not_highest_quality_score() -> None:
    pinned = _rep(
        id="rep-pinned",
        is_user_selected=True,
        quality_score=0.2,
        media_id=11,
        quality_components={"confidence": 0.2, "bbox_area": 1, "sharpness": 1.0, "occlusion_severity": 0.9},
    )
    higher = _rep(
        id="rep-higher",
        is_user_selected=False,
        quality_score=0.99,
        media_id=99,
        quality_components={"confidence": 0.99, "bbox_area": 9, "sharpness": 90.0, "occlusion_severity": 0.0},
    )
    payload = _dump(_cluster(representatives=[higher, pinned]))

    assert payload["representative_quality"] == 0.2
    assert payload["representative_media_id"] == 11
    assert payload["is_pinned"] is True


def test_undoable_receipt_is_newest_unreverted_unexpired() -> None:
    expired = _receipt(
        receipt_id=uuid4(),
        created_at=NOW - timedelta(days=10),
        sequence_no=3,
        expires_at=NOW - timedelta(seconds=1),
    )
    reverted = _receipt(
        receipt_id=uuid4(),
        created_at=NOW - timedelta(hours=1),
        sequence_no=4,
        reverted_at=NOW - timedelta(minutes=1),
    )
    older = _receipt(receipt_id=RECEIPT_OLD, created_at=NOW - timedelta(hours=3), sequence_no=1)
    newer_same_time = _receipt(receipt_id=RECEIPT_NEW, created_at=NOW - timedelta(hours=3), sequence_no=2)
    payload = _dump(
        _cluster(
            representatives=[_rep()],
            merge_receipts=[expired, reverted, older, newer_same_time],
        )
    )

    assert payload["undoable_merge_receipt_id"] == str(RECEIPT_NEW)


def test_expired_or_reverted_only_stack_exports_null_receipt() -> None:
    payload = _dump(
        _cluster(
            representatives=[_rep()],
            merge_receipts=[
                _receipt(
                    receipt_id=RECEIPT_NEW,
                    created_at=NOW - timedelta(days=8),
                    expires_at=NOW - timedelta(seconds=1),
                ),
                _receipt(
                    receipt_id=RECEIPT_OLD,
                    created_at=NOW - timedelta(hours=1),
                    reverted_at=NOW,
                ),
            ],
        )
    )

    assert payload["undoable_merge_receipt_id"] is None
