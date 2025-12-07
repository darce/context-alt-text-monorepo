"""Tenant resolution dependencies."""

from __future__ import annotations

from fastapi import Header, HTTPException, Query, status

from recognition.shared.ids import parse_id


def _normalize_tenant_id(value: str) -> str:
    """Validate tenant identifier and return a canonical UUID string."""
    try:
        parsed = parse_id(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid tenant_id format") from exc
    return str(parsed)


async def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    tenant_id: str | None = Query(default=None),
) -> str:
    """Resolve tenant ID from header or query and validate UUID format."""
    value = x_tenant_id or tenant_id
    if not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id is required")
    return _normalize_tenant_id(value)


async def get_tenant_id_optional(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    tenant_id: str | None = Query(default=None),
) -> str | None:
    """Best-effort tenant resolution; returns None when missing."""
    value = x_tenant_id or tenant_id
    if not value:
        return None
    return _normalize_tenant_id(value)


__all__ = ["get_tenant_id", "get_tenant_id_optional", "_normalize_tenant_id"]
