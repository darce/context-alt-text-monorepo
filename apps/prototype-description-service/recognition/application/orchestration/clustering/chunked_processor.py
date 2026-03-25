"""Chunking utilities for incremental clustering."""

from __future__ import annotations

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
    """

    def __init__(self, identities: Sequence[MediaIdentity]) -> None:
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
            chunk = self._remaining[:chunk_size]
            self._remaining = self._remaining[chunk_size:]
            self._processed += len(chunk)
            yield chunk, processed_before

    def __iter__(self) -> Iterator[tuple[list[MediaIdentity], int]]:
        return self.iter_chunks()
