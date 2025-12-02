"""Tenant context management for clustering operations.

Provides utilities for setting tenant context, managing RLS bypass,
and refreshing materialized views.
"""

from __future__ import annotations

import logging
import os
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.tenant_context import set_tenant_context

logger = logging.getLogger(__name__)


class TenantContextManager:
    """Manages tenant context and database session state for clustering."""

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def ensure_context(self) -> None:
        """Set tenant context and optional debugging flags."""
        await set_tenant_context(self.session, self.tenant_id)

        # Enable per-statement logging when explicitly requested
        if os.getenv("CLUSTERING_SQL_DEBUG") in {"1", "true", "True"}:
            try:
                await self.session.execute(text("SET LOCAL log_min_duration_statement = 0"))
            except Exception as exc:  # pragma: no cover
                logger.debug("Skipping log_min_duration_statement due to permissions: %s", exc)
                await self.session.rollback()
                await set_tenant_context(self.session, self.tenant_id)

        if os.getenv("ALLOW_RLS_BYPASS_FOR_TESTS") == "1":
            from asyncpg.exceptions import InFailedSQLTransactionError
            from sqlalchemy.exc import DBAPIError

            try:
                await self.session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            except DBAPIError as e:
                if e.orig and isinstance(e.orig.__cause__, InFailedSQLTransactionError):
                    await self.session.rollback()
                    await self.session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
                else:
                    raise

    async def refresh_centroid_view(self) -> None:
        """Refresh the materialized view for cluster centroids."""
        try:
            await self.session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            await self.session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to refresh centroid view: %s", exc)
        finally:
            await self.session.execute(text("RESET app.bypass_rls"))
