"""Tenant ID utilities."""

from __future__ import annotations

import uuid


def coerce_tenant_uuid(tenant_id: str | uuid.UUID) -> uuid.UUID:
    """Convert tenant IDs to UUID, handling 32-hex format without dashes."""
    if isinstance(tenant_id, uuid.UUID):
        return tenant_id
    tenant_str = str(tenant_id).replace("-", "")
    if len(tenant_str) == 32:
        formatted = f"{tenant_str[:8]}-{tenant_str[8:12]}-{tenant_str[12:16]}-{tenant_str[16:20]}-{tenant_str[20:]}"
        return uuid.UUID(formatted)
    return uuid.UUID(str(tenant_id))
