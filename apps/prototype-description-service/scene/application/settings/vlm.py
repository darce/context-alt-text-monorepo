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
    # Pin the trust_remote_code model + remote code to the tested commit
    # (supply-chain reproducibility); override via env to upgrade deliberately.
    model_revision: str = Field(
        default_factory=lambda: os.environ.get(
            "ACX_VLM_MODEL_REVISION", "f6c1a25888ffc1d945ee8a1a77ac833c7303d46e"
        )
    )
    max_image_edge_px: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_MAX_IMAGE_EDGE_PX", "1024")))
    num_beams: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_NUM_BEAMS", "3")))
    max_new_tokens: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_MAX_NEW_TOKENS", "512")))
    inference_timeout_seconds: float = Field(
        default_factory=lambda: float(os.environ.get("ACX_VLM_TIMEOUT_SECONDS", "20"))
    )
    max_rss_mb: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_MAX_RSS_MB", "6144")))
    worker_concurrency: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_WORKER_CONCURRENCY", "1")))
    async_inline: bool = Field(
        default_factory=lambda: os.environ.get("ACX_VLM_ASYNC_INLINE", "false").lower() == "true"
    )
