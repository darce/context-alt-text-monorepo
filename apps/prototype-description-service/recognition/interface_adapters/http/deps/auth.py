"""
Authentication and authorization dependencies for recognition HTTP API.

This module provides FastAPI dependencies for API key validation and access control.
"""

from __future__ import annotations

import hashlib
from contextlib import suppress

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.config.security import SecuritySettings, get_security_settings
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository
from recognition.interface_adapters.http.deps.session import get_optional_session
from recognition.interface_adapters.http.deps.tenant_common import normalize_tenant_id


class AuthContext:
    """Simple auth context returned by require_auth."""

    def __init__(
        self,
        token: str | None,
        tenant_claim: str | None,
        api_key_id: str | None = None,
        rate_limit_tier: str | None = None,
        is_admin: bool = False,
        enabled: bool = False,
    ) -> None:
        self.token = token
        self.tenant_claim = tenant_claim
        self.tenant_id = tenant_claim
        self.api_key_id = api_key_id
        self.rate_limit_tier = rate_limit_tier
        self.is_admin = is_admin
        self.enabled = enabled


def _hash_api_key(raw_key: str, algorithm: str) -> str:
    """Return a hex digest for the provided API key."""
    try:
        digest = hashlib.new(algorithm)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="unsupported api key hash algorithm"
        ) from exc
    digest.update(raw_key.encode("utf-8"))
    return digest.hexdigest()


def _table_missing(exc: Exception) -> bool:
    """Detect missing api_keys table errors to allow graceful fallback."""
    message = str(exc).lower()
    return "no such table: api_keys" in message or 'relation "api_keys" does not exist' in message


async def _lookup_api_key(
    api_key: str,
    settings: SecuritySettings,
    session: AsyncSession | None,
) -> tuple[str | None, str | None, str | None, bool]:
    """Validate API key and return (tenant_id, api_key_id, rate_limit_tier, is_admin)."""
    hashed = _hash_api_key(api_key, settings.api_key_hash_algorithm)
    if session is not None and hasattr(session, "execute"):
        repo = SqlAlchemyApiKeyRepository(session)
        try:
            record = await repo.get_by_hash(hashed)
        except Exception as exc:
            if not _table_missing(exc):
                raise
            record = None
        if record:
            with suppress(Exception):
                await repo.touch(record)
            return str(record.tenant_id), str(record.id), record.rate_limit_tier, False

    if api_key in settings.dev_api_keys:
        return None, None, "enterprise", True

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid or missing API key")


async def require_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    api_key_header_value: str | None = Header(default=None, alias="X-Api-Key"),
    session: AsyncSession | None = Depends(get_optional_session),
) -> AuthContext:
    """Enforce bearer auth when enabled via settings."""
    settings = get_security_settings()
    if not settings.auth_enabled:
        return AuthContext(token=None, tenant_claim=None, api_key_id=None, is_admin=False, enabled=False)

    header_value = authorization
    if settings.api_key_header.lower() != "authorization":
        header_value = api_key_header_value or authorization

    if not header_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header required")

    scheme, _, token = header_value.partition(" ")
    api_key = token if scheme.lower() == "bearer" else None
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authorization scheme")

    tenant_claim, api_key_id, rate_limit_tier, is_admin = await _lookup_api_key(api_key, settings, session)
    if tenant_claim and x_tenant_id:
        provided = normalize_tenant_id(x_tenant_id)
        if tenant_claim != provided:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    return AuthContext(
        token=api_key,
        tenant_claim=tenant_claim,
        api_key_id=api_key_id,
        rate_limit_tier=rate_limit_tier,
        is_admin=is_admin,
        enabled=True,
    )


async def get_current_tenant(auth: AuthContext = Depends(require_auth)) -> str | None:
    """Resolve tenant from validated API key (None when auth is disabled)."""
    return auth.tenant_claim


async def require_write_access(auth: AuthContext = Depends(require_auth)) -> AuthContext:
    """Enforce write access for mutate endpoints (analyze, clustering, merges).

    Currently, all authenticated requests with a valid tenant are allowed to write.
    In the future, this can be extended to check for specific scopes or roles.

    Returns:
        The validated AuthContext.

    Raises:
        HTTPException: 403 if the user lacks write permissions.
    """
    if not auth.enabled:
        # Auth disabled - allow all operations
        return auth
    if auth.tenant_claim is None and not auth.is_admin:
        # No tenant claim and not an admin - deny write access
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access requires a tenant-scoped API key or admin privileges",
        )
    return auth


__all__ = [
    "AuthContext",
    "require_auth",
    "get_current_tenant",
    "require_write_access",
]
