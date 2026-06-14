"""Description-specific settings, kept separate from RecognitionSettings.

Env-driven via ``default_factory`` so a deployment can flip the adapter or caps
without touching the recognition-only configuration surface. Defaults keep the
service on the seeded adapter.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from scene.domain.description import DescriptionAdapterKind

_DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024  # 25 MiB, matches recognition multipart cap.


class DescriptionSettings(BaseModel):
    """Adapter selection and request caps for the describe route."""

    model_config = ConfigDict(frozen=True)

    adapter_mode: DescriptionAdapterKind = Field(
        default_factory=lambda: DescriptionAdapterKind(os.environ.get("ACX_DESCRIPTION_ADAPTER", "seeded"))
    )
    max_description_image_bytes: int = Field(
        default_factory=lambda: int(os.environ.get("ACX_DESCRIPTION_MAX_IMAGE_BYTES", _DEFAULT_MAX_IMAGE_BYTES))
    )
    allowed_description_mime_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp")
    prompt_or_task_version: str = Field(
        default_factory=lambda: os.environ.get("ACX_DESCRIPTION_PROMPT_VERSION", "1")
    )
    model_version: str = Field(default_factory=lambda: os.environ.get("ACX_DESCRIPTION_MODEL_VERSION", "1"))
    # Generous default so the slow local_cpu (Florence) inline POC is not prematurely
    # 504'd (~30-95s incl. cold load); seeded never approaches it. Tune via env for prod.
    generation_timeout_seconds: float = Field(
        default_factory=lambda: float(os.environ.get("ACX_DESCRIPTION_TIMEOUT_SECONDS", "180"))
    )
