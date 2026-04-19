"""
Authentication and authorization dependencies for recognition HTTP API.

This module provides FastAPI dependencies for API key validation and access control.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import BackgroundTasks, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import async_session_factory
from recognition.config.security import SecuritySettings, get_security_settings
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository
from recognition.interface_adapters.http.deps.session import get_optional_session
from recognition.interface_adapters.http.deps.tenant_common import normalize_tenant_id
from recognition.observability.auth_audit import emit_auth_event

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class _AuthLookupFailure:
    """Normalized auth-store lookup failure details for policy translation."""

    kind: str
    sqlstate: str | None


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


def _extract_sqlstate(exc: BaseException) -> str | None:
    """Return a best-effort SQLSTATE/pgcode from nested DB exceptions."""
    for candidate in (
        exc,
        getattr(exc, "orig", None),
        getattr(exc, "__cause__", None),
        getattr(getattr(exc, "orig", None), "__cause__", None),
    ):
        if candidate is None:
            continue
        for attr_name in ("sqlstate", "pgcode"):
            value = getattr(candidate, attr_name, None)
            if isinstance(value, str) and value:
                return value
    return None


def _classify_auth_lookup_failure(exc: Exception) -> _AuthLookupFailure:
    """Classify auth lookup failures with SQLSTATE-first semantics."""
    sqlstate = _extract_sqlstate(exc)
    if sqlstate == "42P01" or _table_missing(exc):
        return _AuthLookupFailure(kind="table_missing", sqlstate=sqlstate or "42P01")
    if sqlstate == "25P02":
        return _AuthLookupFailure(kind="transaction_aborted", sqlstate=sqlstate)
    return _AuthLookupFailure(kind="lookup_failed", sqlstate=sqlstate)


def _translate_auth_lookup_failure(failure: _AuthLookupFailure) -> HTTPException:
    """Map an auth-store failure into an auth-boundary HTTP response."""
    if failure.kind == "table_missing":
        return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="api key store unavailable")
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="api key lookup failed")


async def record_api_key_use(
    api_key_id: str,
    *,
    session_factory: Callable[[], AsyncSession] = async_session_factory,
) -> None:
    """Best-effort telemetry update for successful API-key auth."""
    session = session_factory()
    try:
        repo = SqlAlchemyApiKeyRepository(session)
        await repo.touch_by_id(api_key_id)
        await session.commit()
    except Exception:
        logger.exception("api key telemetry update failed", extra={"api_key_id": api_key_id})
        await session.rollback()
    finally:
        await session.close()


def _enqueue_api_key_telemetry(background_tasks: BackgroundTasks | None, api_key_id: str | None) -> None:
    """Schedule telemetry bookkeeping when the dependency has a background task sink."""
    if background_tasks is None or api_key_id is None:
        return
    background_tasks.add_task(record_api_key_use, api_key_id=api_key_id, session_factory=async_session_factory)


async def _require_auth_impl(
    *,
    authorization: str | None,
    x_tenant_id: str | None,
    api_key_header_value: str | None,
    background_tasks: BackgroundTasks | None,
    session: AsyncSession | None,
) -> AuthContext:
    """Shared auth implementation that keeps the direct-call test seam explicit."""
    settings = get_security_settings()
    if not settings.auth_enabled:
        return AuthContext(token=None, tenant_claim=None, api_key_id=None, is_admin=False, enabled=False)

    configured_header = settings.api_key_header.strip().lower()
    api_key: str | None

    if configured_header == "authorization":
        if authorization:
            api_key = _extract_authorization_api_key(authorization)
        elif api_key_header_value:
            api_key = _extract_api_key_header_value(api_key_header_value)
        else:
            api_key = None
    else:
        if api_key_header_value:
            api_key = _extract_api_key_header_value(api_key_header_value)
        elif authorization:
            api_key = _extract_authorization_api_key(authorization)
        else:
            api_key = None

    if not api_key:
        emit_auth_event(
            "invalid_key",
            api_key_id=None,
            key_hash=None,
            tenant_claim=x_tenant_id,
            trace_id=None,
        )
        if authorization or api_key_header_value:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authorization scheme")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header required")

    hashed_for_audit = _hash_api_key(api_key, settings.api_key_hash_algorithm)
    try:
        tenant_claim, api_key_id, rate_limit_tier, is_admin = await _lookup_api_key(api_key, settings, session)
    except HTTPException as exc:
        outcome: str
        if exc.detail == "api key expired":
            outcome = "expired"
        elif exc.detail == "api key revoked":
            outcome = "revoked"
        elif exc.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            outcome = "invalid_key"
        else:
            outcome = None  # type: ignore[assignment]
        if outcome is not None:
            emit_auth_event(
                outcome,  # type: ignore[arg-type]
                api_key_id=None,
                key_hash=hashed_for_audit,
                tenant_claim=x_tenant_id,
                trace_id=None,
            )
        raise
    if tenant_claim and x_tenant_id:
        provided = normalize_tenant_id(x_tenant_id)
        if tenant_claim != provided:
            emit_auth_event(
                "tenant_mismatch",
                api_key_id=api_key_id,
                key_hash=hashed_for_audit,
                tenant_claim=x_tenant_id,
                trace_id=None,
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    _enqueue_api_key_telemetry(background_tasks, api_key_id)

    emit_auth_event(
        "success",
        api_key_id=api_key_id,
        key_hash=hashed_for_audit,
        tenant_claim=tenant_claim,
        trace_id=None,
    )

    return AuthContext(
        token=api_key,
        tenant_claim=tenant_claim,
        api_key_id=api_key_id,
        rate_limit_tier=rate_limit_tier,
        is_admin=is_admin,
        enabled=True,
    )


async def _lookup_api_key(
    api_key: str,
    settings: SecuritySettings,
    session: AsyncSession | None,
) -> tuple[str | None, str | None, str | None, bool]:
    """Validate API key and return (tenant_id, api_key_id, rate_limit_tier, is_admin).

    Returns the raw hash as a trailing tuple entry when available so the caller
    can pass a non-reversible fingerprint to the audit emitter. Dev-key fallback
    carries `hashed=None` since the dev path never touches the DB row.
    """
    hashed = _hash_api_key(api_key, settings.api_key_hash_algorithm)
    if session is None or not hasattr(session, "execute"):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    repo = SqlAlchemyApiKeyRepository(session)
    try:
        async with session.begin_nested():
            record = await repo.get_by_hash(hashed)
    except Exception as exc:
        failure = _classify_auth_lookup_failure(exc)
        logger.error(
            "api key lookup failed",
            extra={"auth_failure_kind": failure.kind, "sqlstate": failure.sqlstate},
            exc_info=True,
        )
        raise _translate_auth_lookup_failure(failure) from exc

    if record:
        return str(record.tenant_id), str(record.id), record.rate_limit_tier, False

    if api_key in settings.dev_api_keys:
        return None, None, "enterprise", True

    # Distinguish expired/revoked from truly unknown so the 401 detail can tell
    # operators what happened. classify_by_hash is a separate query and is only
    # executed when the first lookup returned nothing.
    try:
        classification = await repo.classify_by_hash(hashed)
    except Exception:  # pragma: no cover - defensive; treated as unknown
        classification = "unknown"
    if classification == "expired":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="api key expired")
    if classification == "revoked":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="api key revoked")

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid or missing API key")


def _extract_authorization_api_key(header_value: str) -> str:
    """Extract a bearer token from the Authorization header."""
    scheme, _, token = header_value.partition(" ")
    normalized_token = token.strip()
    if scheme.lower() != "bearer" or not normalized_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authorization scheme")
    return normalized_token


def _extract_api_key_header_value(header_value: str) -> str | None:
    """Extract an API key from X-Api-Key, tolerating optional Bearer formatting."""
    normalized_header = header_value.strip()
    if not normalized_header:
        return None
    scheme, _, token = normalized_header.partition(" ")
    if scheme.lower() == "bearer":
        normalized_header = token.strip()
    return normalized_header or None


async def require_auth(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    api_key_header_value: str | None = Header(default=None, alias="X-Api-Key"),
    session: AsyncSession | None = Depends(get_optional_session),
) -> AuthContext:
    """Enforce bearer auth when enabled via settings."""
    return await _require_auth_impl(
        authorization=authorization,
        x_tenant_id=x_tenant_id,
        api_key_header_value=api_key_header_value,
        background_tasks=background_tasks,
        session=session,
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
    "record_api_key_use",
    "require_auth",
    "get_current_tenant",
    "require_write_access",
]
