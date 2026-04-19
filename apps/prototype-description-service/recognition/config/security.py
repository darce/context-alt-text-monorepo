"""Security settings for recognition HTTP layer."""

from __future__ import annotations

import os
from enum import StrEnum

from pydantic import BaseModel, Field


class RateLimitTier(StrEnum):
    """Per-key rate-limit tier. Values are the stored DB strings."""

    STANDARD = "STANDARD"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


_TIER_MULTIPLIERS: dict[RateLimitTier, int] = {
    RateLimitTier.STANDARD: 1,
    RateLimitTier.PRO: 3,
    RateLimitTier.ENTERPRISE: 10,
}


def tier_rpm(tier: RateLimitTier | str | None, settings: SecuritySettings) -> int:
    """Return the per-minute request budget for ``tier`` given ``settings``.

    STANDARD uses ``rate_limit_requests_per_minute`` as the baseline; PRO = 3x,
    ENTERPRISE = 10x. Unknown / None tier strings reconcile to STANDARD.
    """
    if tier is None:
        resolved = RateLimitTier.STANDARD
    elif isinstance(tier, RateLimitTier):
        resolved = tier
    else:
        try:
            resolved = RateLimitTier(tier.upper() if isinstance(tier, str) else tier)
        except ValueError:
            resolved = RateLimitTier.STANDARD
    return settings.rate_limit_requests_per_minute * _TIER_MULTIPLIERS[resolved]


def _bool_env(name: str, default: bool = False) -> bool:
    """Parse boolean-ish environment variables."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


class SecuritySettings(BaseModel):
    """Runtime-configurable security flags."""

    auth_enabled: bool = Field(default_factory=lambda: _bool_env("RECOGNITION_AUTH_ENABLED", True))
    api_key_header: str = Field(default_factory=lambda: os.getenv("RECOGNITION_API_KEY_HEADER", "Authorization"))
    api_key_hash_algorithm: str = Field(
        default_factory=lambda: os.getenv("RECOGNITION_API_KEY_HASH_ALGORITHM", "sha256")
    )
    dev_api_keys: list[str] = Field(
        default_factory=lambda: [t for t in os.getenv("RECOGNITION_ALLOWED_API_KEYS", "").split(",") if t.strip()]
    )
    rate_limit_requests_per_minute: int = Field(
        default_factory=lambda: int(os.getenv("RECOGNITION_RATE_LIMIT_RPM", "60"))
    )
    rate_limit_burst: int = Field(default_factory=lambda: int(os.getenv("RECOGNITION_RATE_LIMIT_BURST", "10")))
    max_page_size: int = Field(default_factory=lambda: int(os.getenv("RECOGNITION_MAX_PAGE_SIZE", "500")))


def get_security_settings() -> SecuritySettings:
    """Return security settings (evaluated from current environment)."""
    return SecuritySettings()


__all__ = ["RateLimitTier", "SecuritySettings", "get_security_settings", "tier_rpm"]
