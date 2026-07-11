"""Security settings for recognition HTTP layer."""

from __future__ import annotations

import os
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from shared.secrets import get_secret_provider


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
    rate_limit_requests_per_minute: int = Field(
        default_factory=lambda: int(os.getenv("RECOGNITION_RATE_LIMIT_RPM", "60"))
    )
    rate_limit_burst: int = Field(default_factory=lambda: int(os.getenv("RECOGNITION_RATE_LIMIT_BURST", "10")))
    max_page_size: int = Field(default_factory=lambda: int(os.getenv("RECOGNITION_MAX_PAGE_SIZE", "500")))
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            o.strip() for o in os.getenv("RECOGNITION_ALLOWED_ORIGINS", "").split(",") if o.strip()
        ],
        validate_default=True,
    )
    admin_enabled: bool = Field(default_factory=lambda: _bool_env("RECOGNITION_ADMIN_ENABLED", False))
    admin_token: str = Field(
        default_factory=lambda: get_secret_provider().get_secret_optional("RECOGNITION_ADMIN_TOKEN", "") or ""
    )
    admin_header: str = Field(default_factory=lambda: os.getenv("RECOGNITION_ADMIN_TOKEN_HEADER", "X-Admin-Token"))

    @field_validator("allowed_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        """Wildcard '*' in allowed_origins defeats the allowlist — explicit listing only."""
        for origin in value:
            if origin.strip() == "*":
                raise ValueError("RECOGNITION_ALLOWED_ORIGINS must not contain '*'; list explicit origins only.")
        return value


def get_security_settings() -> SecuritySettings:
    """Return security settings (evaluated from current environment)."""
    return SecuritySettings()


class InsecureProductionConfigError(RuntimeError):
    """Raised at startup when production config contains insecure credentials."""


_ADMIN_TOKEN_MIN_LENGTH = 32


def validate_required_secrets(runtime_mode: str | None = None) -> None:
    """Fail closed when production is missing a non-default DB password.

    Mirrors ``db.settings.get_database_settings`` resolution: when
    ``POSTGRES_DSN`` is set, the password is taken from that DSN; otherwise the
    process falls back to ``PGPASSWORD`` (defaulting to the shared local
    ``context`` value). Production must never boot on that silent default
    (rg-008). Callers invoke this at app startup so the process refuses to
    serve traffic rather than connecting with a known-weak credential.
    """
    runtime_mode = runtime_mode or os.environ.get("RECOGNITION_RUNTIME_MODE", "production")
    if runtime_mode != "production":
        return

    # Import here to keep security.py free of package-level db coupling and to
    # read the live default from its producer (db/settings.py).
    from urllib.parse import unquote, urlparse

    from db.settings import DEFAULT_PGPASSWORD

    # Secret reads go through SecretProvider (SECRETS-P2); non-secret runtime_mode stays on os.
    postgres_dsn = get_secret_provider().get_secret_optional("POSTGRES_DSN")
    if postgres_dsn:
        # Same precedence as get_database_settings: explicit DSN wins over PG*.
        password = urlparse(postgres_dsn).password
        if password is not None:
            password = unquote(password)
        if password is None or password == "" or password == DEFAULT_PGPASSWORD:
            raise InsecureProductionConfigError(
                "POSTGRES_DSN is set in production with an empty or development-default "
                "password (RECOGNITION_RUNTIME_MODE=production). Use a non-default password "
                "in POSTGRES_DSN before serving traffic."
            )
        return

    password = get_secret_provider().get_secret_optional("PGPASSWORD")
    if password is None or password == "" or password == DEFAULT_PGPASSWORD:
        raise InsecureProductionConfigError(
            "PGPASSWORD is unset, empty, or set to the development default in production "
            "(RECOGNITION_RUNTIME_MODE=production). Set a non-default PGPASSWORD before "
            "serving traffic."
        )


def validate_admin_config(
    settings: SecuritySettings | None = None,
    *,
    runtime_mode: str | None = None,
) -> None:
    """Fail closed when the admin surface is enabled with an insecure config.

    The ``/admin`` surface is reachable only over the tailnet, but the shared
    admin token is the in-app authority that must hold even on that path. This
    refuses to start when admin is enabled and the token is missing or too short
    to resist guessing. In production it additionally requires an explicit
    ``RECOGNITION_ADMIN_TAILNET_BOUND=1`` acknowledgement so the operator cannot
    expose the surface on the public vhost by accident. No-op when admin is off.
    """
    settings = settings or get_security_settings()
    if not settings.admin_enabled:
        return

    token = settings.admin_token
    if not token or len(token) < _ADMIN_TOKEN_MIN_LENGTH:
        raise InsecureProductionConfigError(
            "RECOGNITION_ADMIN_ENABLED is set but RECOGNITION_ADMIN_TOKEN is empty or shorter than "
            f"{_ADMIN_TOKEN_MIN_LENGTH} characters. Generate a strong token with: "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )

    runtime_mode = runtime_mode or os.environ.get("RECOGNITION_RUNTIME_MODE", "production")
    if runtime_mode == "production" and os.environ.get("RECOGNITION_ADMIN_TAILNET_BOUND") != "1":
        raise InsecureProductionConfigError(
            "RECOGNITION_ADMIN_ENABLED is set in production (RECOGNITION_RUNTIME_MODE=production) without "
            "RECOGNITION_ADMIN_TAILNET_BOUND=1. The /admin surface must be bound to the tailnet and denied on "
            "the public vhost; set RECOGNITION_ADMIN_TAILNET_BOUND=1 to acknowledge the surface is tailnet-bound."
        )


__all__ = [
    "InsecureProductionConfigError",
    "RateLimitTier",
    "SecuritySettings",
    "get_security_settings",
    "tier_rpm",
    "validate_admin_config",
    "validate_required_secrets",
]
