"""Test doubles shared across recognition tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Sequence
from uuid import UUID, uuid4

from db.models import MediaIdentity


class DummySession:
    """Lightweight stand-in for an AsyncSession."""

    def __init__(self, existing_identity_keys: list[tuple[int, int]] | None = None) -> None:
        self.added: List[Any] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.committed = False
        self.refreshed: List[Any] = []
        self._existing_identity_keys = existing_identity_keys or []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1
        self.committed = True

    async def refresh(self, instance: Any) -> None:  # noqa: ARG002
        self.refreshed.append(instance)

    async def rollback(self) -> None:
        return

    async def execute(self, stmt):  # noqa: ARG002
        return FakeResult(list(self._existing_identity_keys))


class FakeResult:
    """Mimics SQLAlchemy AsyncResult for deterministic tests."""

    def __init__(self, rows: Sequence[Any]) -> None:
        self._rows = list(rows)

    def all(self) -> List[Any]:
        return list(self._rows)

    def scalars(self) -> "FakeResult":
        return self

    def __iter__(self):
        return iter(self._rows)


@dataclass(frozen=True)
class SimpleIdentity:
    id: UUID
    confidence: float = 0.9


def make_simple_identity(confidence: float = 0.9) -> SimpleIdentity:
    return SimpleIdentity(id=uuid4(), confidence=confidence)


def make_media_identity(
    tenant_id: UUID,
    media_id: int,
    confidence: float = 0.9,
    embedding: Iterable[float] | None = None,
) -> MediaIdentity:
    base_embedding = list(embedding) if embedding is not None else [0.0] * 1024
    identity = MediaIdentity(
        tenant_id=tenant_id,
        media_id=media_id,
        media_url=f"https://example.com/{media_id}.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=confidence,
        embedding=base_embedding,
    )
    if getattr(identity, "id", None) is None:
        identity.id = uuid4()
    return identity
__all__ = ["DummySession", "FakeResult", "SimpleIdentity", "make_simple_identity", "make_media_identity"]
