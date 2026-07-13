"""Stage-1 visual prior in isolation (E20-FUSION S1, shared with VLM-4).

Extracts structured visual facts without ``ContextPack`` so fusion reconciliation
has an uncontaminated anchor. A separate isolation adapter pass runs ONLY on the
async isolation tiers (``ASYNC_ISOLATION_PROFILES``); every other profile —
interactive Florence, seeded, hosted — derives the prior from the single caption
pass (FUSION-PA-01: never double inference, cost, or image egress).

This module is the single source of tier truth: callers (including
``visual_facts_service``) must import ``ASYNC_ISOLATION_PROFILES`` /
``is_fast_tier_profile`` from here rather than maintaining their own sets.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.config.profiles import DescriptionProfile


class VisualFactsPriorSource(StrEnum):
    """How the prior was produced — isolation pass vs caption-derived fast tier."""

    ISOLATION_PASS = "isolation_pass"
    CAPTION_DERIVED = "caption_derived"


class VisualFactsPrior(BaseModel):
    """Structured visual facts for Stage-2 reconciliation (no ``ContextPack``).

    ``derived_from_context_applied_caption`` is the contamination signal: True
    when the prior was derived from a caption pass that had a ``ContextPack``
    applied, so Stage-2 must not treat context-echoed facts as independent
    visual evidence. An isolation pass is always uncontaminated (False).
    """

    model_config = ConfigDict(extra="forbid")

    caption: str
    objects: list[str] = Field(default_factory=list)
    text: str | None = None
    source: VisualFactsPriorSource = VisualFactsPriorSource.ISOLATION_PASS
    derived_from_context_applied_caption: bool = False


# Profiles whose Stage-1 runs as a separate isolation adapter pass. Only true
# async/GPU tiers belong here: a second pass on SEEDED/FLORENCE_SMALL doubles
# interactive latency, and on HOSTED_GPT4O it doubles paid API cost AND image
# egress to a third party (E20-11). Canonical set — the service imports this.
ASYNC_ISOLATION_PROFILES = frozenset(
    {
        DescriptionProfile.FLORENCE_LARGE,
        DescriptionProfile.GPU_PHI4,
        DescriptionProfile.GPU_QWEN30B,
    }
)


def is_fast_tier_profile(profile: DescriptionProfile) -> bool:
    """True when Stage-1 must be caption-derived (no second adapter pass)."""
    return profile not in ASYNC_ISOLATION_PROFILES


class VisualFactsPass:
    """Stage-1 visual-facts extraction — isolation pass or caption-derived."""

    @staticmethod
    def describe(*, adapter: DescriptionAdapter, image_bytes: bytes) -> VisualFactsPrior:
        """Run the adapter without ``ContextPack`` and map to a visual prior."""
        result = adapter.describe(image_bytes=image_bytes, context=None)
        return VisualFactsPass._from_adapter_result(result, source=VisualFactsPriorSource.ISOLATION_PASS)

    @staticmethod
    def from_caption(*, result: AdapterResult) -> VisualFactsPrior:
        """Derive the prior from an existing caption pass (fast-tier path).

        Carries ``result.context_applied`` through as the contamination flag so
        downstream can distinguish a clean prior from a context-derived one.
        """
        return VisualFactsPass._from_adapter_result(result, source=VisualFactsPriorSource.CAPTION_DERIVED)

    @staticmethod
    def obtain(
        *,
        adapter: DescriptionAdapter,
        image_bytes: bytes,
        profile: DescriptionProfile,
        adapter_result: AdapterResult | None = None,
    ) -> VisualFactsPrior:
        """Tier-shaped Stage-1: isolation pass only on async tiers, caption-derived elsewhere."""
        if is_fast_tier_profile(profile):
            if adapter_result is None:
                raise ValueError("fast-tier profile requires adapter_result from the single caption pass")
            return VisualFactsPass.from_caption(result=adapter_result)
        return VisualFactsPass.describe(adapter=adapter, image_bytes=image_bytes)

    @staticmethod
    def _from_adapter_result(result: AdapterResult, *, source: VisualFactsPriorSource) -> VisualFactsPrior:
        return VisualFactsPrior(
            caption=result.caption,
            objects=list(result.objects),
            text=result.ocr_text,
            source=source,
            derived_from_context_applied_caption=(
                source is VisualFactsPriorSource.CAPTION_DERIVED and result.context_applied
            ),
        )
