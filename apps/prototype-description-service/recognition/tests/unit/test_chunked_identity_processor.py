"""Unit tests for ChunkedIdentityProcessor."""

from __future__ import annotations

import numpy as np

from recognition.application.orchestration.clustering.chunked_processor import ChunkedIdentityProcessor
from recognition.domain.identity import MediaIdentity


def _make_identity(idx: int, confidence: float) -> MediaIdentity:
    return MediaIdentity(
        id=str(idx),
        tenant_id="tenant-1",
        media_id=str(idx),
        embedding=np.zeros(2, dtype=np.float32),
        confidence=confidence,
        bbox_width=1,
        bbox_height=1,
    )


def test_iter_chunks_sorts_by_confidence() -> None:
    identities = [
        _make_identity(1, 0.2),
        _make_identity(2, 0.9),
        _make_identity(3, 0.5),
    ]
    processor = ChunkedIdentityProcessor(identities)

    chunk, processed_before = next(processor.iter_chunks())

    assert processed_before == 0
    assert [identity.id for identity in chunk] == ["2", "3", "1"]


def test_iter_chunks_tracks_processed_counts_and_sizes() -> None:
    identities = [_make_identity(idx, 1.0) for idx in range(30)]
    processor = ChunkedIdentityProcessor(identities)

    sizes: list[int] = []
    processed_counts: list[int] = []

    for chunk, processed_before in processor.iter_chunks():
        sizes.append(len(chunk))
        processed_counts.append(processed_before)

    assert sizes == [5, 5, 5, 5, 10]
    assert processed_counts == [0, 5, 10, 15, 20]
    assert processor.processed_count == 30
    assert processor.total_count == 30
