"""Stage-1 visual prior in isolation (E20-FUSION S1, shared with VLM-4).

Extracts structured visual facts without ``ContextPack`` so fusion reconciliation
has an uncontaminated anchor. On the fast Florence tier the prior is derived from
the single caption pass (FUSION-PA-01) — never a second adapter invocation.
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
    """Structured visual facts for Stage-2 reconciliation (no ``ContextPack``)."""

    model_config = ConfigDict(extra="forbid")

    caption: str
    objects: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    spatial: list[str] = Field(default_factory=list)
    text: str | None = None
    source: VisualFactsPriorSource = VisualFactsPriorSource.ISOLATION_PASS


_FAST_TIER_PROFILES = frozenset({DescriptionProfile.FLORENCE_SMALL})


def is_fast_tier_profile(profile: DescriptionProfile) -> bool:
    """True when Stage-1 must be caption-derived (no second adapter pass)."""
    return profile in _FAST_TIER_PROFILES


class VisualFactsPass:
    """Stage-1 visual-facts extraction — isolation pass or caption-derived."""

    @staticmethod
    def describe(*, adapter: DescriptionAdapter, image_bytes: bytes) -> VisualFactsPrior:
        """Run the adapter without ``ContextPack`` and map to a visual prior."""
        result = adapter.describe(image_bytes=image_bytes, context=None)
        return VisualFactsPass._from_adapter_result(result, source=VisualFactsPriorSource.ISOLATION_PASS)

    @staticmethod
    def from_caption(*, result: AdapterResult) -> VisualFactsPrior:
        """Derive the prior from an existing caption pass (fast-tier path)."""
        return VisualFactsPass._from_adapter_result(result, source=VisualFactsPriorSource.CAPTION_DERIVED)

    @staticmethod
    def obtain(
        *,
        adapter: DescriptionAdapter,
        image_bytes: bytes,
        profile: DescriptionProfile,
        adapter_result: AdapterResult | None = None,
    ) -> VisualFactsPrior:
        """Tier-shaped Stage-1: caption-derived on fast Florence, isolation elsewhere."""
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
            attributes=[],
            spatial=[],
            text=result.ocr_text,
            source=source,
        )
