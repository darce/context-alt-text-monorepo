"""
Tenant identity routes for pairing and provisioning visibility.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.tenant_context import get_tenant_record
from recognition.interface_adapters.http.dependencies import get_optional_session, require_auth
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit

router = APIRouter(tags=["tenant"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])


@router.get("/tenant/whoami")
async def tenant_whoami(
    auth: AuthContext = Depends(require_auth),
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
