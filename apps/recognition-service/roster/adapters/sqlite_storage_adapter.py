"""SQLite-backed roster storage adapter."""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from .database_storage_base import DEFAULT_TENANT_ID, DatabaseRosterStorageAdapter

logger = logging.getLogger(__name__)


class SQLiteStorageAdapter(DatabaseRosterStorageAdapter):
    """SQLite implementation of the roster storage port."""

    def __init__(
        self,
        database_url: str,
        tenant_id: Optional[Any] = None,
        *,
        echo: bool = False,
    ) -> None:
        if not database_url:
            raise ValueError("database_url must be provided for SQLite storage")

        tenant = tenant_id or DEFAULT_TENANT_ID
        super().__init__(
            database_url=database_url,
            tenant_id=tenant,
            echo=echo,
            create_schema=True,
        )
        logger.info("SQLite roster storage adapter initialised (tenant=%s)", self.tenant_id)

    def _create_engine(self, database_url: str, *, echo: bool) -> Engine:
        """Create SQLite engine with suitable defaults for local development."""

        return create_engine(
            database_url,
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False},
        )

    def load_roster_entries(self, model: str) -> List[RosterEntry]:
        return super().load_roster_entries(model)

    def get_roster_entry(self, unique_id: str, model: str) -> Optional[RosterEntry]:
        return super().get_roster_entry(unique_id, model)
