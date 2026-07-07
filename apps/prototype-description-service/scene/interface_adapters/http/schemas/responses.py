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


class InjectedName(BaseModel):
    """One name injected into the named draft, with its curation source."""

    model_config = ConfigDict(extra="forbid")

    name: str
    cluster_id: str
    roster_id: str | None = None
    # The face detector's score for the matched region — not a face↔phrase
    # match strength.
    detection_confidence: float


class NamingProvenance(BaseModel):
    """E19-4a preview provenance: what was named, from where, or why not."""

    model_config = ConfigDict(extra="forbid")

    injected_names: list[InjectedName] = Field(default_factory=list)
    naming_allowed: bool = False
    reason: str | None = None
    # "grounded" (phrase-box span replacement) or "positional" (appended
    # left-to-right sentence); null when no naming occurred.
    mode: str | None = None


class VisualFactsResponse(BaseModel):
    """The 15 contract-locked core fields plus the E19-4a additive optional
    preview trio (``generic_draft``/``named_draft``/``naming_provenance``).

    Preview fields are draft-only: nothing here writes
    ``_wp_attachment_image_alt`` (that write path is E19-2).
    """

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
    # E19-4a additive optional preview fields (never in the schema `required`).
    generic_draft: str | None = None
    named_draft: str | None = None
    naming_provenance: NamingProvenance | None = None
