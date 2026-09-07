"""
Tenant identity routes for pairing and provisioning visibility.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from db.tenant_context import get_tenant_record, tenant_not_provisioned_detail, set_tenant_context
from recognition.infrastructure.repositories.tenant_repository import SqlAlchemyTenantRepository
from recognition.interface_adapters.http.deps import get_optional_session, require_auth, require_auth_key_only, require_write_access
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.shared.db.dialect import is_postgres


# enforce_rate_limit defaults to Depends(require_auth), which re-runs strict
# tenant matching. Wire it after key-only auth so whoami stays header-tolerant.
async def _enforce_rate_limit_key_only(
    auth: AuthContext = Depends(require_auth_key_only),
) -> AuthContext:
    return await enforce_rate_limit(auth)


router = APIRouter(
    tags=["tenant"],
    dependencies=[Depends(require_auth_key_only), Depends(_enforce_rate_limit_key_only)],
)


class NamingAgreementRequest(BaseModel):
    """Strict wire body for the tenant naming authority mutation."""

    enabled: StrictBool


class NamingAgreementResponse(BaseModel):
    enabled: bool


def _tenant_uuid_for_naming(auth: AuthContext) -> uuid.UUID:
    """Resolve a tenant API key claim and reject demo/admin-only identities."""
    tier = str(getattr(auth, "rate_limit_tier", "") or "").lower()
    if tier == "demo" or bool(getattr(auth, "is_demo", False)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="naming agreement unavailable for demo tier")
    if not auth.tenant_claim:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Naming agreement requires a tenant-scoped API key",
        )
    try:
        return uuid.UUID(str(auth.tenant_claim))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid tenant claim") from exc


async def get_naming_agreement_repository(
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession | None = Depends(get_optional_session),
) -> SqlAlchemyTenantRepository:
    """Build a tenant repository scoped to the authenticated API-key claim."""
    tenant_id = _tenant_uuid_for_naming(auth)
    if session is None or not hasattr(session, "get"):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")
    if is_postgres(session):
        await set_tenant_context(session, tenant_id)
    return SqlAlchemyTenantRepository(session)


def _missing_tenant(tenant_id: uuid.UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=tenant_not_provisioned_detail(tenant_id),
    )


@router.get("/tenant/whoami")
async def tenant_whoami(
    auth: AuthContext = Depends(require_auth_key_only),
    session: AsyncSession | None = Depends(get_optional_session),
) -> dict[str, str]:
    """Return the canonical tenant bound to the presented API key."""
    if not auth.tenant_claim:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no tenant claim")

    if session is None or not hasattr(session, "execute"):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    tenant_uuid = uuid.UUID(str(auth.tenant_claim))
    tenant = await get_tenant_record(session, tenant_uuid)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "tenant_not_found",
                "tenant_id": str(tenant_uuid),
                "detail": "Tenant bound to the presented API key no longer exists.",
            },
        )

    return {
        "tenant_id": str(tenant.id),
        "site_url": tenant.site_url,
    }


@router.get("/tenant/naming-agreement", response_model=NamingAgreementResponse)
async def get_naming_agreement(
    auth: AuthContext = Depends(require_auth),
    repository: SqlAlchemyTenantRepository = Depends(get_naming_agreement_repository),
) -> NamingAgreementResponse:
    """Read the naming authority flag for the calling tenant."""
    tenant_id = _tenant_uuid_for_naming(auth)
    enabled = await repository.get_naming_agreement_enabled(tenant_id)
    if enabled is None:
        raise _missing_tenant(tenant_id)
    return NamingAgreementResponse(enabled=enabled)


@router.put("/tenant/naming-agreement", response_model=NamingAgreementResponse)
async def update_naming_agreement(
    body: NamingAgreementRequest,
    auth: AuthContext = Depends(require_auth),
    _: AuthContext = Depends(require_write_access),
    repository: SqlAlchemyTenantRepository = Depends(get_naming_agreement_repository),
) -> NamingAgreementResponse:
    """Update the naming authority flag for the calling tenant."""
    tenant_id = _tenant_uuid_for_naming(auth)
    enabled = await repository.update_naming_agreement_enabled(tenant_id, body.enabled)
    if enabled is None:
        raise _missing_tenant(tenant_id)
    return NamingAgreementResponse(enabled=enabled)
