"""Description-specific settings, kept separate from RecognitionSettings.

Env-driven via ``default_factory`` so a deployment can flip the adapter or caps
without touching the recognition-only configuration surface. Defaults keep the
service on the seeded adapter.
"""

from __future__ import annotations

import math
import os

from pydantic import BaseModel, ConfigDict, Field

from scene.config.profiles import DescriptionProfile
from shared.secrets import get_secret_provider

_DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024  # 25 MiB, matches recognition multipart cap.
# Covers one complete 30-second start-timer interval beyond the measured p95
# composition of detection, snapshot freshness, GPU boot, and response read.
DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS = 510.0
_MAX_GPU_WARMUP_TIMEOUT_SECONDS = 3600.0


def _parse_gpu_warmup_timeout(raw: str | None) -> float:
    """Fail fast at settings load: a typo'd or non-finite warmup timeout must
    not surface as a per-run FAILED inside the worker (rg-008)."""
    if raw is None or raw == "":
        return DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError as exc:
        raise ValueError(f"ACX_GPU_WARMUP_TIMEOUT_SECONDS={raw!r} is not a number") from exc
    if not math.isfinite(seconds) or seconds <= 0 or seconds > _MAX_GPU_WARMUP_TIMEOUT_SECONDS:
        raise ValueError(
            f"ACX_GPU_WARMUP_TIMEOUT_SECONDS={raw!r} must be a finite value in "
            f"(0, {_MAX_GPU_WARMUP_TIMEOUT_SECONDS:g}] seconds"
        )
    return seconds


def _parse_allowlist(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


class DescriptionSettings(BaseModel):
    """Adapter selection and request caps for the describe route."""

    model_config = ConfigDict(frozen=True)

    # The operator switch: seeded | florence_small | florence_large | gpu_phi4.
    profile: DescriptionProfile = Field(
        default_factory=lambda: DescriptionProfile(os.environ.get("ACX_DESCRIPTION_ADAPTER", "seeded"))
    )
    max_description_image_bytes: int = Field(
        default_factory=lambda: int(os.environ.get("ACX_DESCRIPTION_MAX_IMAGE_BYTES", _DEFAULT_MAX_IMAGE_BYTES))
    )
    allowed_description_mime_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp")
    prompt_or_task_version: str = Field(default_factory=lambda: os.environ.get("ACX_DESCRIPTION_PROMPT_VERSION", "1"))
    gpu_prompt_or_task_version: str = Field(default_factory=lambda: os.environ.get("ACX_GPU_PROMPT_VERSION", "3"))
    model_version: str = Field(default_factory=lambda: os.environ.get("ACX_DESCRIPTION_MODEL_VERSION", "1"))
    # Generous default so the slow local_cpu (Florence) inline POC is not prematurely
    # 504'd (~30-95s incl. cold load); seeded never approaches it. Tune via env for prod.
    generation_timeout_seconds: float = Field(
        default_factory=lambda: float(os.environ.get("ACX_DESCRIPTION_TIMEOUT_SECONDS", "180"))
    )
    gpu_connect_timeout_seconds: float = Field(
        default_factory=lambda: float(os.environ.get("ACX_GPU_CONNECT_TIMEOUT_SECONDS", "5"))
    )
    gpu_read_timeout_seconds: float = Field(
        default_factory=lambda: float(os.environ.get("ACX_GPU_READ_TIMEOUT_SECONDS", "175"))
    )
    gpu_max_concurrent_calls: int = Field(
        default_factory=lambda: int(os.environ.get("ACX_GPU_MAX_CONCURRENT_CALLS", "4"))
    )
    gpu_warmup_timeout_seconds: float = Field(
        default_factory=lambda: _parse_gpu_warmup_timeout(os.environ.get("ACX_GPU_WARMUP_TIMEOUT_SECONDS"))
    )
    gpu_endpoint_url: str | None = Field(default_factory=lambda: os.environ.get("ACX_GPU_ENDPOINT_URL") or None)
    gpu_endpoint_api_key: str | None = Field(
        default_factory=lambda: get_secret_provider().get_secret_optional("ACX_GPU_ENDPOINT_API_KEY") or None
    )
    gpu_endpoint_allowlist: tuple[str, ...] = Field(
        default_factory=lambda: _parse_allowlist(os.environ.get("ACX_GPU_ENDPOINT_ALLOWLIST"))
    )
