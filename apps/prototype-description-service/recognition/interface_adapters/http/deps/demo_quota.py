"""Demo-tenant recognition quota guard (DS3-BR-02 / DS-2 / DS-2C).

For authenticated requests whose API key maps to a ``demo_instances`` row,
atomically increments ``recognition_used`` and rejects at quota. Non-demo keys
are unaffected (no registry row → no enforcement).

Consumption is committed in its own short step at consume time (no-refund):
later request failures (415/422/502/504) must not roll back a spent unit.

After a durable mid-request commit, transaction-scoped ``SET LOCAL`` guards
(``app.current_tenant``, statement/idle timeouts) are re-applied on the same
request-cached session so metered routes never continue RLS-unscoped.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DemoInstance
from db.tenant_context import set_tenant_context
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
from recognition.interface_adapters.http.deps.session import (
    _apply_postgres_session_safety_settings,
    get_optional_session,
)
from recognition.shared.db.dialect import is_postgres


def hash_api_key_for_quota(raw_key: str) -> str:
    """Public API-key hash helper shared by the dep and inline consume paths."""
    settings = get_security_settings()
    return _hash_api_key(raw_key, settings.api_key_hash_algorithm)


def _invalid_units_http(units: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "invalid_demo_quota_units",
            "message": f"units must be an integer in 1..{MAX_DEMO_QUOTA_UNITS}",
            "units": units,
        },
    )


def _validate_units_floor(units: int) -> None:
    """Reject non-integers and non-positive units before any demo lookup."""
    if not isinstance(units, int) or isinstance(units, bool) or units < 1:
        raise _invalid_units_http(units)


async def _demo_registry_key_exists(session: AsyncSession, api_key_hash: str) -> bool:
    """Return True when ``api_key_hash`` matches any demo_instances row."""
    cleaned = (api_key_hash or "").strip()
    if not cleaned:
        return False
    result = await session.execute(
        select(DemoInstance.api_key_ref).where(DemoInstance.api_key_ref == cleaned).limit(1)
    )
    return result.first() is not None


async def _capture_app_current_tenant(session: AsyncSession) -> str | None:
    """Read transaction-local app.current_tenant when set (Postgres only)."""
    if not is_postgres(session):
        return None
    try:
        result = await session.execute(text("SELECT current_setting('app.current_tenant', true)"))
    except Exception:
        return None
    value = result.scalar() if result is not None else None
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


async def _restore_session_guards_after_durable_commit(
    session: AsyncSession,
    *,
    tenant_id: str | uuid.UUID | None,
) -> None:
    """Re-apply SET LOCAL safety settings + tenant context after mid-request commit.

    ``session.commit()`` ends the transaction that carried ``SET LOCAL`` values,
    so every durable quota charge must re-establish them before later route SQL.
    """
    await _apply_postgres_session_safety_settings(session)
    if tenant_id is None:
        return
    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except (TypeError, ValueError):
        return
    await set_tenant_context(session, tenant_uuid)


async def consume_demo_quota_units(
    session: AsyncSession,
    *,
    api_key_hash: str,
    units: int,
    durable: bool = True,
    tenant_id: str | uuid.UUID | None = None,
) -> bool:
    """Consume ``units`` demo compute quota.

    Returns:
        True when units were consumed for a demo key.
        False when the hash is not a demo registry key (caller proceeds).

    Raises:
        HTTPException 422 for invalid ``units`` (demo keys only for the ceiling).
        HTTPException 429 with ``demo_quota_exceeded`` when the demo cap is hit.
    """
    _validate_units_floor(units)

    # Ceiling is demo-key only: non-demo keys must not get a demo-branded 422
    # (main accepted large multi-unit batches for non-demo callers).
    if units > MAX_DEMO_QUOTA_UNITS:
        if not await _demo_registry_key_exists(session, api_key_hash):
            return False
        raise _invalid_units_http(units)

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
        # Capture tenant before commit ends the SET LOCAL transaction.
        prior_tenant = await _capture_app_current_tenant(session)
        restore_tenant = prior_tenant or (str(tenant_id) if tenant_id is not None else None)
        # Commit in its own step so later route errors cannot refund the charge.
        await session.commit()
        await _restore_session_guards_after_durable_commit(session, tenant_id=restore_tenant)
    return consumed


async def maybe_consume_demo_quota(
    auth: AuthContext,
    session: AsyncSession | None,
    *,
    units: int = 1,
    durable: bool = True,
) -> bool:
    """Shared gate used by the FastAPI dep and inline route paths.

    Skips when auth is disabled, there is no token, or the session is unavailable.
    Without a session we cannot know if the key is a demo registry key, so the
    general path restores main behavior (skip) rather than 503 for every
    authenticated token. Demo-slug entry routes carry their own gating; residual
    risk for metered compute without a DB is noted in the DS-2C report.

    Returns:
        True if demo units were consumed, False if not a demo key / skipped.
    """
    if not getattr(auth, "enabled", False):
        return False
    token = getattr(auth, "token", None)
    if not token:
        return False
    if session is None:
        # Main-compatible: skip metering when session is unavailable.
        return False

    key_hash = hash_api_key_for_quota(token)
    tenant_id = getattr(auth, "tenant_claim", None) or getattr(auth, "tenant_id", None)
    return await consume_demo_quota_units(
        session,
        api_key_hash=key_hash,
        units=units,
        durable=durable,
        tenant_id=tenant_id,
    )


async def enforce_demo_quota(
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession | None = Depends(get_optional_session),
) -> AuthContext:
    """Consume one demo recognition unit when the caller is a demo tenant key.

    Skips when auth is disabled, session is unavailable, or the key is not a
    demo registry key. Raises 429 with ``demo_quota_exceeded`` at cap.
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
