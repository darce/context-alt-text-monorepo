"""SQLAlchemy repository for tenant-level settings."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant


class SqlAlchemyTenantRepository:
    """Persist tenant settings through a request-scoped async session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        """Return one tenant, or ``None`` when it has not been provisioned."""
        return await self.session.get(Tenant, tenant_id)

    async def get_naming_agreement_enabled(self, tenant_id: uuid.UUID) -> bool | None:
        """Return the tenant naming flag without applying a local default."""
        tenant = await self.get(tenant_id)
        if tenant is None:
            return None
        return bool(tenant.naming_agreement_enabled)

    async def update_naming_agreement_enabled(
        self,
        tenant_id: uuid.UUID,
        enabled: bool,
    ) -> bool | None:
        """Update and flush the tenant naming flag, or return ``None`` if absent."""
        tenant = await self.get(tenant_id)
        if tenant is None:
            return None
        tenant.naming_agreement_enabled = enabled
        await self.session.flush()
        return bool(tenant.naming_agreement_enabled)

