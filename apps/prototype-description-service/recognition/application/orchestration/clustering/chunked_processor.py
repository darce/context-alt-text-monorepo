"""Chunking utilities for incremental clustering."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from recognition.domain.identity import MediaIdentity


def get_chunk_size(total_processed: int) -> int:
    """Return adaptive chunk size for incremental cold-start clustering."""
    if total_processed < 20:
        return 5
    if total_processed < 50:
        return 10
    if total_processed < 200:
        return 25
    return 50


class ChunkedIdentityProcessor:
    """Yield identities in adaptive chunks, highest confidence first."""

    def __init__(self, identities: Sequence[MediaIdentity]) -> None:
        self._remaining = sorted(identities, key=lambda identity: identity.confidence, reverse=True)
        self._processed = 0
        self._total = len(self._remaining)

    @property
    def total_count(self) -> int:
        """Return the total number of identities to process."""
        return self._total

    @property
    def processed_count(self) -> int:
        """Return the number of identities already processed."""
        return self._processed

    def iter_chunks(self) -> Iterator[tuple[list[MediaIdentity], int]]:
        """Yield a chunk of identities and the processed count before the chunk."""
        while self._remaining:
            processed_before = self._processed
            chunk_size = get_chunk_size(processed_before)
            chunk = self._remaining[:chunk_size]
            self._remaining = self._remaining[chunk_size:]
            self._processed += len(chunk)
            yield chunk, processed_before

    def __iter__(self) -> Iterator[tuple[list[MediaIdentity], int]]:
        return self.iter_chunks()
