"""Demo-tenant recognition quota guard (DS3-BR-02 / DS-2 / DS-2C).

For authenticated requests whose API key maps to a ``demo_instances`` row,
atomically increments ``recognition_used`` and rejects at quota. Non-demo keys
are unaffected (no registry row → no enforcement).

Consumption is committed in its own short step at consume time (no-refund):
later request failures (415/422/502/504) must not roll back a spent unit.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.demo_provisioning_service import (
    MAX_DEMO_QUOTA_UNITS,
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


def hash_api_key_for_quota(raw_key: str) -> str:
    """Public API-key hash helper shared by the dep and inline consume paths."""
    settings = get_security_settings()
    return _hash_api_key(raw_key, settings.api_key_hash_algorithm)


def _validate_units(units: int) -> None:
    if not isinstance(units, int) or isinstance(units, bool) or units < 1 or units > MAX_DEMO_QUOTA_UNITS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_demo_quota_units",
                "message": f"units must be an integer in 1..{MAX_DEMO_QUOTA_UNITS}",
                "units": units,
            },
        )


async def consume_demo_quota_units(
    session: AsyncSession,
    *,
    api_key_hash: str,
    units: int,
    durable: bool = True,
) -> bool:
    """Consume ``units`` demo compute quota.

    Returns:
        True when units were consumed for a demo key.
        False when the hash is not a demo registry key (caller proceeds).

    Raises:
        HTTPException 422 for invalid ``units``.
        HTTPException 429 with ``demo_quota_exceeded`` when the demo cap is hit.
    """
    _validate_units(units)
    try:
        consumed = await try_consume_demo_quota(session, api_key_hash=api_key_hash, units=units)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_demo_quota_units",
                "message": str(exc),
                "units": units,
            },
        ) from exc
    except DemoQuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "demo_quota_exceeded",
                "message": "demo recognition quota exceeded",
                "quota_remaining": exc.remaining,
            },
        ) from exc

    if consumed and durable:
        # Commit in its own step so later route errors cannot refund the charge.
        await session.commit()
    return consumed


async def maybe_consume_demo_quota(
    auth: AuthContext,
    session: AsyncSession | None,
    *,
    units: int = 1,
    durable: bool = True,
) -> bool:
    """Shared gate used by the FastAPI dep and inline route paths.

    Skips when auth is disabled or there is no token. When auth is enabled with
    a token but the session is unavailable, fail-closed with 503 (never run
    unmetered VLM work for a potentially-demo key).

    Returns:
        True if demo units were consumed, False if not a demo key / skipped.
    """
    if not getattr(auth, "enabled", False):
        return False
    token = getattr(auth, "token", None)
    if not token:
        return False
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database session unavailable",
        )

    key_hash = hash_api_key_for_quota(token)
    return await consume_demo_quota_units(
        session,
        api_key_hash=key_hash,
        units=units,
        durable=durable,
    )


async def enforce_demo_quota(
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession | None = Depends(get_optional_session),
) -> AuthContext:
    """Consume one demo recognition unit when the caller is a demo tenant key.

    Skips when auth is disabled or the key is not a demo registry key.
    Raises 503 when the session is unavailable for an authenticated request.
    Raises 429 with ``demo_quota_exceeded`` at cap.
    """
    await maybe_consume_demo_quota(auth, session, units=1)
    return auth


__all__ = [
    "MAX_DEMO_QUOTA_UNITS",
    "consume_demo_quota_units",
    "enforce_demo_quota",
    "hash_api_key_for_quota",
    "maybe_consume_demo_quota",
]
