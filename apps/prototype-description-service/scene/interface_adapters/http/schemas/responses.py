"""Response schema for the describe route — the visual-facts Core Contract.

All 15 fields are declared and required so model/provider provenance and
retention state are unavoidable on the wire; future adapters (local_cpu,
hosted_provider) never change the shape (roadmap "Core Contract"). The seeded
adapter fills expansion fields (``context_used``, ``provider_disclosure``) with
typed placeholders rather than nulls.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from scene.domain.description import DescriptionAdapterKind, ProviderMode, RetentionClass


class VisualFacts(BaseModel):
    """Structured, inspectable observations returned before final prose."""

    model_config = ConfigDict(extra="forbid")

    caption: str
    objects: list[str] = Field(default_factory=list)
    ocr_text: str | None = None


class ContextUsed(BaseModel):
    """Typed echo of the context the adapter actually consumed.

    The seeded adapter returns ``sources=[], applied=False`` (empty-but-typed) in
    Phase 1; distinct from the request's ``wp_context`` input.
    """

    model_config = ConfigDict(extra="forbid")

    sources: list[str] = Field(default_factory=list)
    applied: bool = False


class ProviderDisclosure(BaseModel):
    """Whether/where image bytes left the Alt Context service boundary."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderMode = ProviderMode.NONE
    left_service_boundary: bool = False


class VisualFactsResponse(BaseModel):
    """The 15-field describe response. Field set is contract-locked."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    media_id: int
    image_hash: str
    context_hash: str
    adapter: DescriptionAdapterKind
    model_id: str
    model_version: str
    prompt_or_task_version: str
    visual_facts: VisualFacts
    alt_text_draft: str
    context_used: ContextUsed
    provider_disclosure: ProviderDisclosure
    cached: bool
    duration_ms: int = Field(ge=0)
    retention_class: RetentionClass
