"""SecretProvider port and default env adapter (SECRETS-P2 seam).

Ports & adapters (REF-15): consumers depend on ``SecretProvider.get_secret``;
the default ``EnvSecretProvider`` reads process environment. Phase 3 can swap
an OCI Vault adapter via ``set_secret_provider`` with zero consumer edits.

Minimal port (REF-18): one abstract method; optional/defaulted reads are a
concrete base method so adapters implement exactly one method.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class SecretNotFound(Exception):  # noqa: N818 — port name fixed by SECRETS-P2 plan
    """Raised when a required secret name is not available from the provider."""


class SecretProvider(ABC):
    """Port for fetching secrets by name."""

    @abstractmethod
    def get_secret(self, name: str) -> str:
        """Return the secret value for ``name``.

        Raises:
            SecretNotFound: when the secret is absent from the backend.
        """

    def get_secret_optional(self, name: str, default: str | None = None) -> str | None:
        """Return the secret for ``name``, or ``default`` when absent.

        Matches ``os.getenv`` semantics for the env adapter: a set-but-empty
        value is present (returns ``""``), not treated as missing.
        """
        try:
            return self.get_secret(name)
        except SecretNotFound:
            return default


class EnvSecretProvider(SecretProvider):
    """Default adapter: secrets come from ``os.environ``."""

    def get_secret(self, name: str) -> str:
        if name not in os.environ:
            raise SecretNotFound(f"Secret not found: {name}")
        return os.environ[name]


_secret_provider: SecretProvider | None = None


def get_secret_provider() -> SecretProvider:
    """Return the active secret provider (lazy default: EnvSecretProvider).

    Mirrors the module-level accessor convention used by
    ``get_security_settings`` / ``get_database_settings``: one entry point for
    the process, overridable in tests via ``set_secret_provider``.
    """
    global _secret_provider
    if _secret_provider is None:
        _secret_provider = EnvSecretProvider()
    return _secret_provider


def set_secret_provider(provider: SecretProvider) -> None:
    """Replace the active secret provider (tests / Phase 3 Vault wiring)."""
    global _secret_provider
    _secret_provider = provider


def reset_secret_provider() -> None:
    """Clear the active provider so the next get rebuilds the env default."""
    global _secret_provider
    _secret_provider = None


__all__ = [
    "EnvSecretProvider",
    "SecretNotFound",
    "SecretProvider",
    "get_secret_provider",
    "reset_secret_provider",
    "set_secret_provider",
]
