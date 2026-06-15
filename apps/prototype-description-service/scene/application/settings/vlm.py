"""Local-CPU VLM *host runtime caps*. Defaults keep inference bounded on the A1.

Model selection (id / revision / version / decode params) lives in the profile
registry (``scene/config/profiles.py``), which is the single source of truth for
the ``ACX_DESCRIPTION_ADAPTER`` switch. These caps are deployment-host knobs that
apply to whichever local-CPU Florence profile is active; they exist independently
of whether the ``[vlm]`` extra (torch/transformers) is installed — the model is
never imported here. ``async_inline=False`` plus ``worker_concurrency=1`` keep
inference off the HTTP request path and bounded on the OCI A1 host.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


class VlmSettings(BaseModel):
    """Runtime caps for the local-CPU Florence adapter (S9; host knobs only)."""

    model_config = ConfigDict(frozen=True)

    max_image_edge_px: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_MAX_IMAGE_EDGE_PX", "1024")))
    inference_timeout_seconds: float = Field(
        default_factory=lambda: float(os.environ.get("ACX_VLM_TIMEOUT_SECONDS", "20"))
    )
    max_rss_mb: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_MAX_RSS_MB", "6144")))
    worker_concurrency: int = Field(default_factory=lambda: int(os.environ.get("ACX_VLM_WORKER_CONCURRENCY", "1")))
    async_inline: bool = Field(
        default_factory=lambda: os.environ.get("ACX_VLM_ASYNC_INLINE", "false").lower() == "true"
    )
