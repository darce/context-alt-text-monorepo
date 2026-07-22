"""Chunking utilities for incremental clustering."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence

from recognition.domain.identity import MediaIdentity

# Target latency per chunk (ms). Adaptive sizing scales toward this budget.
_TARGET_CHUNK_MS = 500.0
# Clamp chunk size within [_MIN_CHUNK, _MAX_CHUNK] regardless of feedback.
_MIN_CHUNK = 5
_MAX_CHUNK = 100


def get_chunk_size(total_processed: int) -> int:
    """Return baseline chunk size for incremental cold-start clustering.

    The step function biases toward small chunks early in a job when the
    cluster graph is sparse and each identity is more expensive to place.
    """
    if total_processed < 20:
        return 5
    if total_processed < 50:
        return 10
    if total_processed < 200:
        return 25
    return 50


class ChunkedIdentityProcessor:
    """Yield identities in adaptive chunks, highest confidence first.

    On each iteration the processor optionally receives feedback from the
    orchestrator about how long the previous chunk took (``record_chunk_ms``).
    It uses an exponential moving average of observed latency to scale the
    next chunk size toward ``_TARGET_CHUNK_MS`` (default 500 ms), while
    staying within ``[_MIN_CHUNK, _MAX_CHUNK]``.

    When ``photo_atomic`` is True (face_pipeline joint assignment), identities
    that share a ``media_id`` are never split across chunks. The insightface
    path keeps ``photo_atomic=False`` for bit-identical slicing.
    """

    def __init__(
        self,
        identities: Sequence[MediaIdentity],
        *,
        photo_atomic: bool = False,
    ) -> None:
        self._photo_atomic = photo_atomic
        if photo_atomic:
            self._remaining = _order_photo_atomic(identities)
        else:
            self._remaining = sorted(identities, key=lambda identity: identity.confidence, reverse=True)
        self._processed = 0
        self._total = len(self._remaining)
        # Latency EMA state: None until the first chunk result is recorded.
        self._ema_ms: float | None = None
        self._adaptive_size: int | None = None

    @property
    def total_count(self) -> int:
        """Return the total number of identities to process."""
        return self._total

    @property
    def processed_count(self) -> int:
        """Return the number of identities already processed."""
        return self._processed

    def record_chunk_ms(self, elapsed_ms: float, chunk_size: int) -> None:
        """Feed back observed chunk latency to tune the next chunk size.

        Estimates per-identity cost via an EMA, then scales the next chunk
        to hit ``_TARGET_CHUNK_MS``.  Results are clamped to ``[_MIN_CHUNK,
        _MAX_CHUNK]`` and the update is a no-op when ``elapsed_ms`` or
        ``chunk_size`` are non-positive.
        """
        if elapsed_ms <= 0 or chunk_size <= 0:
            return
        per_identity_ms = elapsed_ms / chunk_size
        alpha = 0.3
        if self._ema_ms is None:
            self._ema_ms = per_identity_ms
        else:
            self._ema_ms = alpha * per_identity_ms + (1.0 - alpha) * self._ema_ms
        if self._ema_ms > 0:
            target = max(_MIN_CHUNK, min(_MAX_CHUNK, int(_TARGET_CHUNK_MS / self._ema_ms)))
            self._adaptive_size = target

    def iter_chunks(self) -> Iterator[tuple[list[MediaIdentity], int]]:
        """Yield a chunk of identities and the processed count before the chunk."""
        while self._remaining:
            processed_before = self._processed
            if self._adaptive_size is not None:
                chunk_size = self._adaptive_size
            else:
                chunk_size = get_chunk_size(processed_before)
            if self._photo_atomic:
                chunk = self._take_photo_atomic_chunk(chunk_size)
            else:
                chunk = self._remaining[:chunk_size]
                self._remaining = self._remaining[chunk_size:]
            self._processed += len(chunk)
            yield chunk, processed_before

    def _take_photo_atomic_chunk(self, chunk_size: int) -> list[MediaIdentity]:
        """Take up to ``chunk_size`` identities without splitting a media_id group.

        A single photo that alone exceeds ``chunk_size`` is still emitted whole.
        """
        if not self._remaining:
            return []
        chunk: list[MediaIdentity] = []
        while self._remaining:
            media_id = str(self._remaining[0].media_id)
            group: list[MediaIdentity] = []
            while self._remaining and str(self._remaining[0].media_id) == media_id:
                group.append(self._remaining.pop(0))
            if chunk and len(chunk) + len(group) > chunk_size:
                # Put the group back and stop; never split it.
                self._remaining = group + self._remaining
                break
            chunk.extend(group)
            if len(chunk) >= chunk_size:
                break
        return chunk

    def __iter__(self) -> Iterator[tuple[list[MediaIdentity], int]]:
        return self.iter_chunks()


def _order_photo_atomic(identities: Sequence[MediaIdentity]) -> list[MediaIdentity]:
    """Group by media_id, order groups by max confidence, preserve face order within group."""
    groups: dict[str, list[MediaIdentity]] = defaultdict(list)
    group_max_confidence: dict[str, float] = {}
    media_order: list[str] = []
    for identity in identities:
        media_id = str(identity.media_id)
        if media_id not in group_max_confidence:
            media_order.append(media_id)
            group_max_confidence[media_id] = identity.confidence
        else:
            group_max_confidence[media_id] = max(group_max_confidence[media_id], identity.confidence)
        groups[media_id].append(identity)

    ordered_media = sorted(
        media_order,
        key=lambda mid: (-group_max_confidence[mid], mid),
    )
    ordered: list[MediaIdentity] = []
    for media_id in ordered_media:
        # Within a photo keep higher-confidence faces first.
        ordered.extend(sorted(groups[media_id], key=lambda identity: identity.confidence, reverse=True))
    return ordered
