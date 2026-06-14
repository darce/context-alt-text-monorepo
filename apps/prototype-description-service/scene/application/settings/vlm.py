"""Local-CPU VLM runtime caps. Defaults keep the model off (seeded) and inline-free.

These caps exist independently of whether the ``[vlm]`` extra (torch/transformers)
is installed — the model is never imported here. ``async_inline=False`` plus
``worker_concurrency=1`` keep inference off the HTTP request path and bounded on
the OCI A1 host.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from scene.domain.description import DescriptionAdapterKind


class VlmSettings(BaseModel):
    """Runtime caps for the local-CPU Florence-2 adapter (S9)."""

    model_config = ConfigDict(frozen=True)

    adapter_mode: DescriptionAdapterKind = Field(
        default_factory=lambda: DescriptionAdapterKind(os.environ.get("ACX_DESCRIPTION_ADAPTER", "seeded"))
    )
    florence_model_id: str = Field(
        default_factory=lambda: os.environ.get("ACX_VLM_MODEL_ID", "microsoft/Florence-2-base-ft")
    )
    max_image_edge_px: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_MAX_IMAGE_EDGE_PX", "1024")))
    inference_timeout_seconds: float = Field(
        default_factory=lambda: float(os.environ.get("ACX_VLM_TIMEOUT_SECONDS", "20"))
    )
    max_rss_mb: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_MAX_RSS_MB", "6144")))
    worker_concurrency: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_WORKER_CONCURRENCY", "1")))
    async_inline: bool = Field(
        default_factory=lambda: os.environ.get("ACX_VLM_ASYNC_INLINE", "false").lower() == "true"
    )
