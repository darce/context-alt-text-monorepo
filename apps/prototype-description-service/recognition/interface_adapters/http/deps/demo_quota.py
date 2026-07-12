"""Demo-tenant recognition quota guard (DS3-BR-02 / DS-2).

For authenticated requests whose API key maps to a ``demo_instances`` row,
atomically increments ``recognition_used`` and rejects at quota. Non-demo keys
are unaffected (no registry row → no enforcement).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.demo_provisioning_service import (
    DemoQuotaExceededError,
    try_consume_demo_quota,
)
from recognition.config.security import get_security_settings
from recognition.interface_adapters.http.deps.auth import (
    AuthContext,
    _hash_api_key,
    require_auth,
)
from recognition.interface_adapters.http.deps.session import get_optional_session


async def consume_demo_quota_units(
    session: AsyncSession,
    *,
    api_key_hash: str,
    units: int,
) -> None:
    """Consume ``units`` demo compute quota; raise 429 when exceeded."""
    try:
        await try_consume_demo_quota(session, api_key_hash=api_key_hash, units=units)
    except DemoQuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "demo_quota_exceeded",
                "message": "demo recognition quota exceeded",
                "quota_remaining": exc.remaining,
            },
        ) from exc


async def enforce_demo_quota(
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession | None = Depends(get_optional_session),
) -> AuthContext:
    """Consume one demo recognition unit when the caller is a demo tenant key.

    Skips when auth is disabled, session is unavailable, or the key is not a
    demo registry key. Raises 429 with ``demo_quota_exceeded`` at cap.
    """
    if not auth.enabled:
        return auth
    if session is None:
        return auth
    if not auth.token:
        return auth

    settings = get_security_settings()
    key_hash = _hash_api_key(auth.token, settings.api_key_hash_algorithm)
    await consume_demo_quota_units(session, api_key_hash=key_hash, units=1)
    return auth


__all__ = ["consume_demo_quota_units", "enforce_demo_quota"]
