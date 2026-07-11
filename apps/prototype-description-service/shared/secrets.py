"""SecretProvider port, env adapter, and OCI Vault adapter (SECRETS-P2/P3).

Ports & adapters (REF-15): consumers depend on ``SecretProvider.get_secret``;
``EnvSecretProvider`` reads process environment; ``OciVaultSecretProvider``
fetches secret bundles via instance principals. Backend selected by
``RECOGNITION_SECRET_BACKEND`` (default ``env``).

Minimal port (REF-18): one abstract method; optional/defaulted reads are a
concrete base method so adapters implement exactly one method.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from typing import Any

# Bounded Vault client timeouts (RES-02). Defaults mirror common OCI SDK
# connect default (10s) with a tighter read for boot-path secret fetch.
_DEFAULT_CONNECT_TIMEOUT_S = 5.0
_DEFAULT_READ_TIMEOUT_S = 10.0
# Bounded retry: transport / 5xx only (RES-06). Never on 4xx not-found/auth.
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BACKOFF_BASE_S = 0.25

_KNOWN_SECRET_BACKENDS = frozenset({"env", "oci_vault"})
_SECRET_BACKEND_ENV = "RECOGNITION_SECRET_BACKEND"
_VAULT_SECRET_MAP_ENV = "RECOGNITION_VAULT_SECRET_MAP"

# Required Vault secrets, keyed by the LOGICAL env-var name that consumers pass
# to get_secret(...) — the same keys used in RECOGNITION_VAULT_SECRET_MAP (the
# namespaced secret/<domain>/<name> is only the Vault-side path, not the map
# key). Fetched eagerly at boot under oci_vault so a missing/unreachable secret
# fails before the process serves (RES-13). These two are always needed: the DB
# password (rendered into the DSN when POSTGRES_DSN is not itself mapped) and the
# /admin root-of-trust token. POSTGRES_DSN/POSTGRES_SYNC_DSN and the ACX_*_API_KEY
# secrets are OPTIONAL — read via get_secret_optional with a fallback — so they
# are not boot-required.
REQUIRED_OCI_VAULT_SECRET_NAMES: tuple[str, ...] = (
    "PGPASSWORD",
    "RECOGNITION_ADMIN_TOKEN",
)

logger = logging.getLogger(__name__)


class SecretNotFound(Exception):  # noqa: N818 — port name fixed by SECRETS-P2 plan
    """Raised when a required secret name is not available from the provider."""


class VaultBootError(RuntimeError):
    """Raised when the oci_vault backend cannot satisfy required secrets at boot.

    RES-13: unreachable Vault, auth failure, or a missing required secret must
    refuse to serve — never fall back to process env under oci_vault.
    """


class SecretProvider(ABC):
    """Port for fetching secrets by name."""

    @abstractmethod
    def get_secret(self, name: str) -> str:
        """Return the secret value for ``name``.

        Raises:
            SecretNotFound: when the secret is absent from the backend.
        """

    def get_secret_optional(self, name: str, default: str | None = None) -> str | None:
        """Return the secret for ``name``, or ``default`` when genuinely ABSENT.

        Matches ``os.getenv`` semantics for the env adapter: a set-but-empty
        value is present (returns ``""``), not treated as missing. Only a
        missing secret (``SecretNotFound``) yields ``default``; a real backend
        error (e.g. Vault unreachable under ``oci_vault``) PROPAGATES — a
        transient failure must fail loud, never silently substitute a default
        for a configured secret ([RES-13]/[SEC-06]).
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


class OciVaultSecretProvider(SecretProvider):
    """OCI Vault adapter: instance-principal signer + secret-bundle fetch.

    Logical secret names — the env-var name the app requests (e.g.
    ``PGPASSWORD``, ``RECOGNITION_ADMIN_TOKEN``) — resolve to Vault secret OCIDs
    via a non-secret config map (``RECOGNITION_VAULT_SECRET_MAP``; the map KEY is
    the logical name, NOT the Vault-side ``secret/<domain>/<name>`` path, per
    decision #1882). Fetched values are cached for the process lifetime (rotation
    = restart, per ADR-013). All ``oci`` SDK usage stays inside this adapter
    (REF-15).
    """

    def __init__(
        self,
        secret_ocid_map: Mapping[str, str],
        *,
        secrets_client: Any | None = None,
        connect_timeout_s: float = _DEFAULT_CONNECT_TIMEOUT_S,
        read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        backoff_base_s: float = _DEFAULT_BACKOFF_BASE_S,
        sleeper: Callable[[float], None] = time.sleep,
        client_factory: Callable[..., Any] | None = None,
        signer_factory: Callable[[], Any] | None = None,
    ) -> None:
        if not secret_ocid_map:
            raise ValueError("OciVaultSecretProvider requires a non-empty secret_ocid_map")
        cleaned: dict[str, str] = {}
        for key, value in secret_ocid_map.items():
            if not isinstance(key, str) or not key:
                raise ValueError("secret_ocid_map keys must be non-empty strings")
            if not isinstance(value, str) or not value:
                raise ValueError(f"secret_ocid_map[{key!r}] must be a non-empty OCID string")
            cleaned[key] = value
        self._secret_ocid_map = cleaned
        self._connect_timeout_s = connect_timeout_s
        self._read_timeout_s = read_timeout_s
        self._max_attempts = max(1, max_attempts)
        self._backoff_base_s = backoff_base_s
        self._sleeper = sleeper
        self._client = secrets_client
        self._client_factory = client_factory
        self._signer_factory = signer_factory
        # Secrets are immutable for the process lifetime (rotation = restart, per
        # ADR-013), so cache each fetched value. Without this, get_security_settings()
        # — which rebuilds SecuritySettings() on every request — would fire a
        # blocking Vault get_secret_bundle round-trip (with retries) inside the
        # async request path per authenticated call (CON-01/RES-12/PERF-07).
        self._cache: dict[str, str] = {}

    @classmethod
    def from_env(cls) -> OciVaultSecretProvider:
        """Build from ``RECOGNITION_VAULT_SECRET_MAP`` JSON name→OCID map."""
        raw = os.environ.get(_VAULT_SECRET_MAP_ENV, "").strip()
        if not raw:
            raise ValueError(
                f"{_VAULT_SECRET_MAP_ENV} is required when {_SECRET_BACKEND_ENV}=oci_vault"
            )
        try:
            mapping = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{_VAULT_SECRET_MAP_ENV} must be a JSON object of path→OCID strings"
            ) from exc
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError(
                f"{_VAULT_SECRET_MAP_ENV} must be a non-empty JSON object of path→OCID strings"
            )
        return cls(mapping)

    def get_secret(self, name: str) -> str:
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        ocid = self._secret_ocid_map.get(name)
        if ocid is None:
            raise SecretNotFound(f"Secret not found: {name}")
        value = self._fetch_bundle_plaintext(ocid=ocid, name=name)
        self._cache[name] = value
        return value

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        import oci

        signer_factory = self._signer_factory or (
            lambda: oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        )
        signer = signer_factory()
        timeout = (self._connect_timeout_s, self._read_timeout_s)
        if self._client_factory is not None:
            self._client = self._client_factory(config={}, signer=signer, timeout=timeout)
        else:
            self._client = oci.secrets.SecretsClient(config={}, signer=signer, timeout=timeout)
        return self._client

    def _fetch_bundle_plaintext(self, *, ocid: str, name: str) -> str:
        from oci.exceptions import ConnectTimeout, RequestException, ServiceError

        last_error: BaseException | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._get_client().get_secret_bundle(secret_id=ocid)
                return self._decode_bundle_response(response, name=name)
            except ServiceError as exc:
                if exc.status == 404:
                    raise SecretNotFound(f"Secret not found: {name}") from exc
                # 4xx (auth, bad request, etc.) — no retry (RES-06).
                if exc.status is not None and 400 <= int(exc.status) < 500:
                    raise
                last_error = exc
            except (RequestException, ConnectTimeout, ConnectionError, TimeoutError, OSError) as exc:
                last_error = exc

            if attempt < self._max_attempts:
                self._sleeper(self._backoff_base_s * (2 ** (attempt - 1)))
                continue
            if last_error is None:
                raise RuntimeError("vault fetch exhausted without recording an error")
            raise last_error

        raise RuntimeError("unreachable vault fetch loop exit")  # pragma: no cover

    @staticmethod
    def _decode_bundle_response(response: Any, *, name: str) -> str:
        """Decode ``get_secret_bundle`` Response → plaintext string.

        Real OCI shape (oci 2.181.x):
        ``response.data.secret_bundle_content.content`` is a base64 string
        (``Base64SecretBundleContentDetails``).
        """
        data = getattr(response, "data", None)
        content_details = getattr(data, "secret_bundle_content", None) if data is not None else None
        content_b64 = getattr(content_details, "content", None) if content_details is not None else None
        if content_b64 is None or content_b64 == "":
            raise SecretNotFound(f"Secret not found: {name}")
        try:
            return base64.b64decode(content_b64, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise SecretNotFound(f"Secret not found: {name}") from exc


def resolve_secret_backend(raw: str | None = None) -> str:
    """Validate and normalize ``RECOGNITION_SECRET_BACKEND`` (rg-008).

    Unknown values raise ``ValueError`` at load — never a silent default.
    Unset / empty → ``env`` (local/CI default).
    """
    value = (raw if raw is not None else os.environ.get(_SECRET_BACKEND_ENV, "env")).strip().lower()
    if not value:
        value = "env"
    if value not in _KNOWN_SECRET_BACKENDS:
        known = ", ".join(sorted(_KNOWN_SECRET_BACKENDS))
        raise ValueError(
            f"Unknown {_SECRET_BACKEND_ENV}={value!r}; expected one of: {known}"
        )
    return value


def build_secret_provider(backend: str | None = None) -> SecretProvider:
    """Construct the provider for ``backend`` (or the resolved env default)."""
    resolved = resolve_secret_backend(backend)
    if resolved == "oci_vault":
        return OciVaultSecretProvider.from_env()
    return EnvSecretProvider()


_secret_provider: SecretProvider | None = None


def get_secret_provider() -> SecretProvider:
    """Return the active secret provider (lazy; backend from env).

    Mirrors the module-level accessor convention used by
    ``get_security_settings`` / ``get_database_settings``: one entry point for
    the process, overridable in tests via ``set_secret_provider``.
    """
    global _secret_provider
    if _secret_provider is None:
        _secret_provider = build_secret_provider()
    return _secret_provider


def set_secret_provider(provider: SecretProvider) -> None:
    """Replace the active secret provider (tests / explicit wiring)."""
    global _secret_provider
    _secret_provider = provider


def reset_secret_provider() -> None:
    """Clear the active provider so the next get rebuilds from backend env."""
    global _secret_provider
    _secret_provider = None


def validate_oci_vault_boot(
    *,
    provider: SecretProvider | None = None,
    required_names: Sequence[str] | None = None,
) -> None:
    """Eagerly fetch required secrets when ``RECOGNITION_SECRET_BACKEND=oci_vault``.

    No-op for the env backend (local/CI unchanged). Under oci_vault, every
    required logical name is fetched before the caller may bind a port. On
    unreachable Vault, auth failure, or missing secret, raises
    :class:`VaultBootError` and logs a clear error — never falls back to env
    (RES-13).
    """
    backend = resolve_secret_backend()
    if backend != "oci_vault":
        return

    names = tuple(required_names) if required_names is not None else REQUIRED_OCI_VAULT_SECRET_NAMES
    try:
        active = provider if provider is not None else get_secret_provider()
    except ValueError as exc:
        message = f"OCI Vault boot failed: {exc}; refusing to serve"
        logger.error(message)
        raise VaultBootError(message) from exc

    if not isinstance(active, OciVaultSecretProvider):
        message = (
            "OCI Vault boot failed: RECOGNITION_SECRET_BACKEND=oci_vault but the active "
            f"provider is {type(active).__name__}, not OciVaultSecretProvider; "
            "refusing env fallback"
        )
        logger.error(message)
        raise VaultBootError(message)

    # Import oci exception types only on the vault boot path (REF-15).
    from oci.exceptions import ConnectTimeout, RequestException, ServiceError

    for name in names:
        try:
            value = active.get_secret(name)
        except SecretNotFound as exc:
            message = (
                f"OCI Vault boot failed: required secret {name!r} not found in Vault; "
                "refusing to serve"
            )
            logger.error(message)
            raise VaultBootError(message) from exc
        except ServiceError as exc:
            status = exc.status
            if status is not None and 400 <= int(status) < 500:
                message = (
                    f"OCI Vault boot failed: auth/authorization error fetching {name!r} "
                    f"(status={status}); refusing to serve"
                )
            else:
                message = (
                    f"OCI Vault boot failed: Vault service error fetching {name!r} "
                    f"(status={status}); refusing to serve"
                )
            logger.error(message)
            raise VaultBootError(message) from exc
        except (RequestException, ConnectTimeout, ConnectionError, TimeoutError, OSError) as exc:
            message = (
                f"OCI Vault boot failed: Vault unreachable while fetching {name!r} "
                f"({type(exc).__name__}: {exc}); refusing to serve"
            )
            logger.error(message)
            raise VaultBootError(message) from exc
        except VaultBootError:
            raise
        except Exception as exc:  # noqa: BLE001 — boot must never partially succeed
            message = (
                f"OCI Vault boot failed: unexpected error fetching {name!r} "
                f"({type(exc).__name__}: {exc}); refusing to serve"
            )
            logger.error(message)
            raise VaultBootError(message) from exc

        if not value:
            message = (
                f"OCI Vault boot failed: required secret {name!r} is empty; refusing to serve"
            )
            logger.error(message)
            raise VaultBootError(message)


__all__ = [
    "EnvSecretProvider",
    "OciVaultSecretProvider",
    "REQUIRED_OCI_VAULT_SECRET_NAMES",
    "SecretNotFound",
    "SecretProvider",
    "VaultBootError",
    "build_secret_provider",
    "get_secret_provider",
    "reset_secret_provider",
    "resolve_secret_backend",
    "set_secret_provider",
    "validate_oci_vault_boot",
]
