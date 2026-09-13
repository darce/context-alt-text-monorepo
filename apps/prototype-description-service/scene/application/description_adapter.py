"""The DescriptionAdapter seam: one protocol, many implementations.

Both the seeded adapter (S2) and the later local-CPU VLM adapter (S9) implement
this protocol, so the route/service depend on the abstraction and the model is a
swap, never a contract change. Mirrors the recognition ``ObjectStore`` Protocol
seam. Pure application layer — no HTTP/DB imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from scene.application.identity_merge.merge import PhraseBox
from scene.domain.description import DescriptionAdapterKind


@dataclass(frozen=True)
class AdapterResult:
    """Adapter output, mapped to the wire ``VisualFactsResponse`` by the service."""

    caption: str
    objects: tuple[str, ...]
    ocr_text: str | None
    alt_text_draft: str
    context_sources: tuple[str, ...]
    context_applied: bool
    # E19-4a S4: caption phrase-grounding boxes ([0,1] top-left frame, the
    # VLM-2C phrase_boxes.json shape). Default empty — E19-1 callers unaffected.
    phrase_boxes: tuple[PhraseBox, ...] = field(default_factory=tuple)
    # ALTQ-1: optional long-form surface from dual-length prompting. None when
    # the adapter produces only the short draft — existing adapters unaffected.
    alt_text_long: str | None = None


@runtime_checkable
class DescriptionAdapter(Protocol):
    """Produces visual facts for one image. Identity fields are cache-key inputs."""

    @property
    def kind(self) -> DescriptionAdapterKind: ...

    @property
    def model_id(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    @property
    def prompt_or_task_version(self) -> str: ...

    def describe(self, *, image_bytes: bytes, context: Mapping[str, Any] | None) -> AdapterResult: ...
