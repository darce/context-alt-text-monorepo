"""Response schema for the describe route — the visual-facts Core Contract.

All 15 fields are declared and required so model/provider provenance and
retention state are unavoidable on the wire; future adapters (local_cpu,
hosted_provider) never change the shape (roadmap "Core Contract"). The seeded
adapter fills expansion fields (``context_used``, ``provider_disclosure``) with
typed placeholders rather than nulls.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from scene.application.gpu_state import GpuState
from scene.application.identity_merge import NamingRealizer
from scene.application.identity_merge import NamingStatus as NamingProvenanceStatus
from scene.domain.describe_run import DescribeItemStatus, DescribeRunPhase, DescribeRunStatus
from scene.domain.description import DescriptionAdapterKind, DescriptionResultTier, ProviderMode, RetentionClass


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
    # C7 fields: typed, contract-locked naming outcome and realization.
    status: NamingProvenanceStatus = NamingProvenanceStatus.NO_FACES
    realizer: NamingRealizer | None = None
    names_applied: list[str] = Field(default_factory=list)


class AttachmentFactProvenance(BaseModel):
    """One ContextPack fact's Stage-2 attachment decision (E20-FUSION)."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str
    fact_source: str
    fact_label: str
    decision: str
    altitude: str
    target_evidence: str | None = None
    review_reason: str | None = None
    visible: bool = False


class AttachmentProvenance(BaseModel):
    """E20-FUSION per-fact attachment provenance from Stage-2 reconciliation.

    Mirrors the ``NamingProvenance`` additive-optional pattern: declared on the
    response, never required, ``extra="forbid"`` preserved.
    """

    model_config = ConfigDict(extra="forbid")

    facts: list[AttachmentFactProvenance] = Field(default_factory=list)


class VisualFactsResponse(BaseModel):
    """The 15 contract-locked core fields plus additive optional preview /
    fusion fields (``generic_draft``/``named_draft``/``naming_provenance``/
    ``attachment_provenance``).

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
    tier: DescriptionResultTier = DescriptionResultTier.PROVISIONAL_CPU
    result_generation: int = Field(default=1, ge=1)
    # E19-4a additive optional preview fields (never in the schema `required`).
    generic_draft: str | None = None
    named_draft: str | None = None
    naming_provenance: NamingProvenance | None = None
    # E20-FUSION additive optional Stage-2 attachment provenance.
    attachment_provenance: AttachmentProvenance | None = None
    # ALTQ-1 additive optional long-form surface (dual-length prompting).
    # None when the adapter produces only the short draft; never required.
    alt_text_long: str | None = None


class DescribeJobResult(BaseModel):
    """Async describe job poll result."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    tier: DescriptionResultTier | None = None
    result_generation: int = Field(default=0, ge=0)
    visual_facts: dict | None = None
    error: str | None = None


class DescribeRunResponse(BaseModel):
    """Async describe-run status returned by submit/status endpoints."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    run_id: str
    status: DescribeRunStatus
    phase: DescribeRunPhase
    completed: int
    failed: int
    skipped: int
    total: int
    cancel_requested: bool = False
    # WBUX-3 (S7-01): honest remaining-time estimate; null unless the run is
    # in-flight with measured progress.
    eta_seconds: float | None = None
    gpu_state: GpuState = GpuState.UNKNOWN
    # HARM-F1: snapshot of recognition_enabled at submit. Default True so
    # omitted payloads keep today's naming-on behaviour.
    recognition_enabled: bool = True
    # GUIDEDFIX-2 [RES-02] / [S01]: the server's own end-to-end GENERATION budget
    # for this whole accepted run — the budget the worker actually enforces,
    # summed across the run's items. It explicitly does NOT include GPU warm-up /
    # cold-start; the client adds that leg itself. Derived at accept from the
    # per-item timeout the worker is handed times the run's item count, and
    # snapshotted, so a later config change never moves an accepted run's number.
    # Null only for runs created outside the submit route (never via POST).
    deadline_seconds: float | None = None


class DescribeRunItemResponse(BaseModel):
    """One item's persisted describe output. WBUX-4 INT-01a: the read path that
    surfaces per-item drafts to the operator. Draft/caption/provenance are null
    until the worker describes the item; never fabricated."""

    model_config = ConfigDict(extra="forbid")

    media_id: int
    status: DescribeItemStatus
    alt_text_draft: str | None = None
    caption: str | None = None
    provenance: dict | None = None
    tier: DescriptionResultTier | None = None
    result_generation: int = Field(default=0, ge=0)


class DescribeRunItemsResponse(BaseModel):
    """Per-item drafts for one run, media-id ordered."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    run_id: str
    items: list[DescribeRunItemResponse]
