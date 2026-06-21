"""Tenant resolution dependencies."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
from recognition.interface_adapters.http.deps.tenant_common import (
    get_tenant_id,
    get_tenant_id_optional,
    normalize_tenant_id,
)


async def get_authenticated_tenant_id(
    auth: AuthContext = Depends(require_auth),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> str:
    """Resolve tenant ID from the authenticated context for sensitive routes.

    Tenant-scoped API keys always win. Admin keys may override via ``X-Tenant-ID``.
    Query parameters are intentionally ignored for this dependency.
    """
    if not getattr(auth, "enabled", False):
        if not x_tenant_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-ID header required")
        return normalize_tenant_id(x_tenant_id)

    tenant_claim = getattr(auth, "tenant_claim", None)
    if tenant_claim:
        return normalize_tenant_id(str(tenant_claim))

    if getattr(auth, "is_admin", False):
        if not x_tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="X-Tenant-ID header required")
        return normalize_tenant_id(x_tenant_id)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="tenant-scoped API key or admin override required",
    )


__all__ = ["get_tenant_id", "get_tenant_id_optional", "get_authenticated_tenant_id"]
