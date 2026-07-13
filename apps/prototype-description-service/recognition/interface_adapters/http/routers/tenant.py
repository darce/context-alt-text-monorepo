"""
Tenant identity routes for pairing and provisioning visibility.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.tenant_context import get_tenant_record
from recognition.interface_adapters.http.deps import get_optional_session, require_auth_key_only
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit

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
