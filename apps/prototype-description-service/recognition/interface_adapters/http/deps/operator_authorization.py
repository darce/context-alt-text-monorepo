"""Authoritative operator-control entitlement gate.

AuthContext carries tenant_claim and rate_limit_tier only. Marker copies of
beta/plan/email/token are not entitlement authority. This dependency loads the
tenant-scoped TenantEntitlement row for auth.tenant_claim before GPU intent,
clustering admission/recovery, or cluster revert.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.params import Depends as DependsMarker
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import clustering_async_session_factory
from db.tenant_context import set_tenant_context
from recognition.domain.portal_contracts import EntitlementStatus, PortalPrincipal
from recognition.infrastructure.repositories.tenant_entitlement_repository import (
    SqlAlchemyTenantEntitlementRepository,
    TenantEntitlementTimeoutError,
)
from recognition.interface_adapters.http.deps.auth import require_write_access
from recognition.interface_adapters.http.deps.session import get_optional_session

OPERATOR_FORBIDDEN_DETAIL = "operator_control_forbidden"
OPERATOR_UNAVAILABLE_DETAIL = "operator_authorization_unavailable"
GPU_FORBIDDEN_DETAIL = "gpu_control_forbidden"
_READ_TIMEOUT_S = 5.0
_GET_ONLY_PLAN_ALLOWANCES = {"paid": 0}
_ALLOWED_OPERATOR_STATUSES = frozenset({EntitlementStatus.PAID_ACTIVE})
_DENIED_OPERATOR_STATUSES = frozenset(
    {
        EntitlementStatus.BETA_ACTIVE,
        EntitlementStatus.PAST_DUE,
        EntitlementStatus.EXPIRED,
        EntitlementStatus.REVOKED,
    }
)


async def get_operator_entitlement_repository(
    session: AsyncSession | None = Depends(get_optional_session),
) -> AsyncIterator[Any]:
    """Yield the entitlement repository on the business session."""
    if session is None or isinstance(session, DependsMarker):
        yield None
        return
    yield _repository_from_session(session)


class _ClusteringOperatorEntitlementRepository:
    """Read an entitlement on a short-lived clustering-pool session."""

    async def get(self, tenant_id: UUID, *, for_update: bool = False) -> Any:
        session = clustering_async_session_factory()
        try:
            await asyncio.wait_for(
                set_tenant_context(session, tenant_id),
                timeout=_READ_TIMEOUT_S,
            )
            repository = _repository_from_session(session)
            row = await repository.get(tenant_id, for_update=for_update)
            await session.commit()
            return row
        except TimeoutError as exc:
            await _rollback(session)
            raise _unavailable() from exc
        except BaseException:
            await _rollback(session)
            raise
        finally:
            await session.close()


async def get_clustering_operator_entitlement_repository() -> Any:
    """Yield a repository that releases its clustering connection after each read."""
    return _ClusteringOperatorEntitlementRepository()


def _unavailable(*, detail: str = OPERATOR_UNAVAILABLE_DETAIL) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


def _forbidden(*, detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _is_portal_principal(auth: Any) -> bool:
    """PortalPrincipal, or the same trusted issuer/subject shape. Never request body."""
    if isinstance(auth, PortalPrincipal):
        return True
    issuer = getattr(auth, "issuer", None)
    subject = getattr(auth, "subject", None)
    return isinstance(issuer, str) and bool(issuer.strip()) and isinstance(subject, str) and bool(subject.strip())


def _tenant_uuid(auth: Any) -> UUID | None:
    raw = getattr(auth, "tenant_claim", None)
    if raw is None:
        return None
    if isinstance(raw, UUID):
        return raw
    try:
        return UUID(str(raw))
    except (TypeError, ValueError, AttributeError):
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _period_current(row: Any, *, now: datetime) -> bool:
    try:
        period_start = _as_utc(row.period_start)
        period_end = _as_utc(row.period_end)
    except (AttributeError, TypeError, ValueError):
        return False
    return period_start <= now < period_end


def _entitlement_status(value: object) -> EntitlementStatus | None:
    if isinstance(value, EntitlementStatus):
        return value
    try:
        return EntitlementStatus(value)
    except (TypeError, ValueError):
        return None


async def _rollback(session: Any) -> None:
    rollback = getattr(session, "rollback", None)
    if not callable(rollback):
        return
    result = rollback()
    if hasattr(result, "__await__"):
        await result


def _resolve_session(session: Any, repository: Any) -> Any:
    if session is not None and not isinstance(session, DependsMarker):
        return session
    return getattr(repository, "session", None)


def _repository_from_session(session: AsyncSession) -> SqlAlchemyTenantEntitlementRepository:
    return SqlAlchemyTenantEntitlementRepository(
        session,
        timeout_s=_READ_TIMEOUT_S,
        plan_allowances=_GET_ONLY_PLAN_ALLOWANCES,
    )


async def authorize_operator_control(
    auth: Any,
    *,
    session: Any | None = None,
    repository: Any | None = None,
    forbidden_detail: str = OPERATOR_FORBIDDEN_DETAIL,
) -> None:
    """Deny portal callers and tenants whose durable entitlement is not paid_active.

    Existing write/admin/demo checks stay with the caller. Paid status does not
    set is_admin. Auth disabled is unchanged. [DATA-03] [RES-05]
    """
    if auth is None:
        return
    if _is_portal_principal(auth):
        raise _forbidden(detail=forbidden_detail)
    if not getattr(auth, "enabled", False):
        return

    tenant_uuid = _tenant_uuid(auth)
    if tenant_uuid is None:
        if getattr(auth, "is_admin", False):
            return
        raise _unavailable()

    if isinstance(repository, DependsMarker):
        repository = None
    resolved_session = _resolve_session(session, repository)
    if repository is None:
        if resolved_session is None:
            raise _unavailable()
        repository = _repository_from_session(resolved_session)

    getter = getattr(repository, "get", None)
    if not callable(getter):
        raise _unavailable()

    lookup_session = getattr(repository, "session", None)
    if lookup_session is None:
        lookup_session = resolved_session

    try:
        if lookup_session is not None:
            await asyncio.wait_for(
                set_tenant_context(lookup_session, tenant_uuid),
                timeout=_READ_TIMEOUT_S,
            )
        row = await getter(tenant_uuid)
    except HTTPException:
        raise
    except TimeoutError as exc:
        await _rollback(lookup_session)
        raise _unavailable() from exc
    except TenantEntitlementTimeoutError as exc:
        await _rollback(lookup_session)
        raise _unavailable() from exc
    except Exception as exc:
        await _rollback(lookup_session)
        raise _unavailable() from exc

    if row is None:
        raise _unavailable()

    row_tenant = getattr(row, "tenant_id", None)
    if row_tenant is not None and _tenant_uuid_value(row_tenant) != tenant_uuid:
        raise _unavailable()

    entitlement_status = _entitlement_status(getattr(row, "status", None))
    if entitlement_status is None:
        raise _unavailable()
    if entitlement_status in _DENIED_OPERATOR_STATUSES or not _period_current(row, now=datetime.now(tz=UTC)):
        raise _forbidden(detail=forbidden_detail)
    if entitlement_status not in _ALLOWED_OPERATOR_STATUSES:
        raise _unavailable()


def _tenant_uuid_value(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


async def require_operator_authorization(
    auth: Any = Depends(require_write_access),
    session: AsyncSession | None = Depends(get_optional_session),
    repository: Any = Depends(get_operator_entitlement_repository),
) -> Any:
    """FastAPI dependency form. Routes with existing session signatures should call authorize_operator_control."""
    await authorize_operator_control(auth, session=session, repository=repository)
    return auth


__all__ = [
    "GPU_FORBIDDEN_DETAIL",
    "OPERATOR_FORBIDDEN_DETAIL",
    "OPERATOR_UNAVAILABLE_DETAIL",
    "authorize_operator_control",
    "get_clustering_operator_entitlement_repository",
    "get_operator_entitlement_repository",
    "require_operator_authorization",
]
