"""Shared database-backed roster storage adapter logic."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.models import (
    AugmentedEmbedding as AugmentedEmbeddingModel,
    Base,
    ReferenceEmbedding as ReferenceEmbeddingModel,
    RosterEntry as RosterEntryModel,
    Tenant,
)
from roster.domain.entities import RosterEntry
from roster.domain.interfaces import RosterStoragePort

from .database_base_utils import (
    DEFAULT_TENANT_ID,
    coerce_datetime,
    ensure_tenant,
    normalize_entry_id,
    normalize_tenant_id,
)
from .roster_persistence import (
    hydrate_entry,
    load_augmented_embeddings,
    load_reference_embeddings,
    prepare_entry_metadata,
    replace_augmented_embeddings,
    replace_reference_embeddings,
)
from .sqlalchemy_session import create_default_engine, create_session_factory, session_scope

logger = logging.getLogger(__name__)


class DatabaseRosterStorageAdapter(RosterStoragePort):
    """Reusable database-backed storage implementation."""

    def __init__(
        self,
        database_url: str,
        tenant_id: Optional[Any],
        *,
        echo: bool = False,
        create_schema: bool = False,
    ) -> None:
        if not database_url:
            raise ValueError("database_url must be provided for database storage")

        self.database_url = database_url
        self._tenant_uuid = normalize_tenant_id(tenant_id)
        self.tenant_id = str(self._tenant_uuid)

        self._engine = self._create_engine(database_url, echo=echo)
        if create_schema:
            Base.metadata.create_all(self._engine)

        self._Session = create_session_factory(self._engine)

    # ------------------------------------------------------------------
    # Helper indirection for subclasses
    # ------------------------------------------------------------------
    def _prepare_entry_metadata(
        self, entry: RosterEntry, model: str
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]], str, str]:
        return prepare_entry_metadata(entry, model)

    def _replace_reference_embeddings(
        self, session: Session, entry_id: Any, reference_images: Any
    ) -> None:
        replace_reference_embeddings(session, entry_id, reference_images)

    def _replace_augmented_embeddings(
        self, session: Session, entry_id: Any, augmented_records: Any
    ) -> None:
        replace_augmented_embeddings(session, entry_id, augmented_records)

    def _load_reference_embeddings(
        self, session: Session, entry_ids: List[Any]
    ) -> Dict[Any, List[Dict[str, Any]]]:
        return load_reference_embeddings(session, entry_ids)

    def _load_augmented_embeddings(
        self, session: Session, entry_ids: List[Any]
    ) -> Dict[Any, List[Dict[str, Any]]]:
        return load_augmented_embeddings(session, entry_ids)

    def _hydrate_entry(
        self,
        row: RosterEntryModel,
        reference_images: List[Dict[str, Any]],
        augmented_embeddings: List[Dict[str, Any]],
    ) -> RosterEntry:
        return hydrate_entry(row, reference_images, augmented_embeddings)

    # ------------------------------------------------------------------
    # Engine helpers
    # ------------------------------------------------------------------
    def _create_engine(self, database_url: str, *, echo: bool) -> Engine:
        """Create the SQLAlchemy engine. Subclasses may override."""

        return create_default_engine(database_url, echo=echo)

    def _session(self) -> Session:
        """Context manager that yields a configured session and ensures cleanup."""

        return session_scope(self._Session, self._configure_session)

    def _configure_session(self, session: Session) -> None:  # pragma: no cover - hook for subclasses
        """Hook for subclasses to customise session state per transaction."""

    def close(self) -> None:
        """Dispose the underlying engine."""

        self._engine.dispose()

    # ------------------------------------------------------------------
    # Tenant helpers
    # ------------------------------------------------------------------
    def _ensure_tenant(self, session: Session) -> Tenant:
        return ensure_tenant(session, self._tenant_uuid)

    # ------------------------------------------------------------------
    # Port implementation
    # ------------------------------------------------------------------
    def save_roster_entry(self, entry: RosterEntry, model: str) -> bool:
        metadata, augmented_records, display_value, preferred_name = self._prepare_entry_metadata(entry, model)

        try:
            with self._session() as session:
                tenant = self._ensure_tenant(session)

                entry_pk = normalize_entry_id(entry.unique_id)
                row = session.get(RosterEntryModel, entry_pk)
                created_at = coerce_datetime(entry.created_timestamp) or datetime.utcnow()
                updated_at = coerce_datetime(entry.updated_timestamp) or datetime.utcnow()

                if row is None:
                    label_value = str(entry.unique_id or preferred_name or entry_pk)
                    row = RosterEntryModel(
                        id=entry_pk,
                        tenant_id=tenant.id,
                        label=label_value,
                        display_name=display_value,
                        model=model,
                        type=metadata.get("type", "person"),
                        meta=metadata,
                        aggregate_embedding=entry.aggregate_embedding,
                        created_at=created_at,
                        updated_at=updated_at,
                    )
                    session.add(row)
                else:
                    row.tenant_id = tenant.id
                    row.label = str(entry.unique_id or preferred_name or entry_pk)
                    row.display_name = display_value
                    row.model = model
                    row.type = metadata.get("type", row.type or "person")
                    row.meta = metadata
                    row.aggregate_embedding = entry.aggregate_embedding
                    row.updated_at = updated_at

                session.flush()

                self._replace_reference_embeddings(session, row.id, entry.reference_images)
                self._replace_augmented_embeddings(session, row.id, augmented_records)

                session.commit()
                return True

        except SQLAlchemyError:
            logger.exception("Failed to save roster entry '%s'", entry.unique_id)
            return False

    def load_roster_entries(self, model: str) -> List[RosterEntry]:
        try:
            with self._session() as session:
                self._ensure_tenant(session)
                
                stmt = select(RosterEntryModel).where(RosterEntryModel.tenant_id == self._tenant_uuid)
                if model not in ("all", None):
                    stmt = stmt.where(RosterEntryModel.model == model)

                rows = session.execute(stmt).scalars().all()

                if not rows:
                    return []

                entry_ids = [row.id for row in rows]
                reference_map = self._load_reference_embeddings(session, entry_ids)
                augmented_map = self._load_augmented_embeddings(session, entry_ids)

                return [
                    self._hydrate_entry(
                        db_entry,
                        reference_map.get(db_entry.id, []),
                        augmented_map.get(db_entry.id, []),
                    )
                    for db_entry in rows
                ]

        except SQLAlchemyError:
            logger.exception("Failed to load roster entries for model '%s'", model)
            return []

    def get_roster_entry(self, unique_id: str, model: str) -> Optional[RosterEntry]:
        try:
            with self._session() as session:
                self._ensure_tenant(session)
                
                stmt = select(RosterEntryModel).where(
                    RosterEntryModel.label == unique_id,
                    RosterEntryModel.tenant_id == self._tenant_uuid,
                )
                if model not in ("all", None):
                    stmt = stmt.where(RosterEntryModel.model == model)

                row = session.execute(stmt).scalar_one_or_none()

                if row is None:
                    return None

                reference_map = self._load_reference_embeddings(session, [row.id])
                augmented_map = self._load_augmented_embeddings(session, [row.id])

                return self._hydrate_entry(
                    row,
                    reference_map.get(row.id, []),
                    augmented_map.get(row.id, []),
                )

        except SQLAlchemyError:
            logger.exception("Failed to fetch roster entry '%s'", unique_id)
            return None

    def delete_roster_entry(self, unique_id: str, model: str) -> bool:  # noqa: ARG002
        try:
            with self._session() as session:
                self._ensure_tenant(session)
                delete_stmt = delete(RosterEntryModel).where(
                    RosterEntryModel.label == unique_id,
                    RosterEntryModel.tenant_id == self._tenant_uuid,
                )
                if model not in ("all", None):
                    delete_stmt = delete_stmt.where(RosterEntryModel.model == model)
                result = session.execute(delete_stmt)
                session.commit()
                return result.rowcount > 0

        except SQLAlchemyError:
            logger.exception("Failed to delete roster entry '%s'", unique_id)
            return False

    def roster_exists(self, model: str) -> bool:  # noqa: ARG002
        try:
            with self._session() as session:
                self._ensure_tenant(session)
                stmt = select(RosterEntryModel.id).where(RosterEntryModel.tenant_id == self._tenant_uuid)
                if model not in ("all", None):
                    stmt = stmt.where(RosterEntryModel.model == model)
                count = session.execute(stmt).first()
                return count is not None

        except SQLAlchemyError:
            logger.exception("Failed to check roster existence")
            return False

    def clear_roster(self, model: str) -> bool:  # noqa: ARG002
        try:
            with self._session() as session:
                self._ensure_tenant(session)
                stmt = select(RosterEntryModel.id).where(RosterEntryModel.tenant_id == self._tenant_uuid)
                if model not in ("all", None):
                    stmt = stmt.where(RosterEntryModel.model == model)
                entry_ids = session.execute(stmt).scalars().all()

                if not entry_ids:
                    return True

                session.execute(
                    delete(ReferenceEmbeddingModel).where(ReferenceEmbeddingModel.roster_entry_id.in_(entry_ids))
                )
                session.execute(
                    delete(AugmentedEmbeddingModel).where(AugmentedEmbeddingModel.roster_entry_id.in_(entry_ids))
                )
                session.execute(
                    delete(RosterEntryModel).where(RosterEntryModel.id.in_(entry_ids))
                )
                session.commit()
                return True

        except SQLAlchemyError:
            logger.exception("Failed to clear roster")
            return False

    def get_storage_info(self, model: str) -> Dict[str, Any]:  # noqa: ARG002
        try:
            with self._session() as session:
                self._ensure_tenant(session)
                info = self._build_storage_info(session, model)
        except SQLAlchemyError:
            logger.exception("Failed to collect storage info")
            info = self._fallback_storage_info()

        self._augment_storage_info(info)
        return info

    def get_storage_description(self) -> str:
        """Return the database URL as the storage description."""
        return self.database_url

    def _build_storage_info(self, session: Session, model: str) -> Dict[str, Any]:
        """Collect core storage metrics. Subclasses may extend via _augment_storage_info."""

        model_filter = model if model not in ("all", None) else None

        entry_stmt = (
            select(func.count())
            .select_from(RosterEntryModel)
            .where(RosterEntryModel.tenant_id == self._tenant_uuid)
        )
        if model_filter:
            entry_stmt = entry_stmt.where(RosterEntryModel.model == model_filter)
        entry_count = int(session.execute(entry_stmt).scalar_one() or 0)

        reference_stmt = (
            select(func.count())
            .select_from(ReferenceEmbeddingModel)
            .join(
                RosterEntryModel,
                ReferenceEmbeddingModel.roster_entry_id == RosterEntryModel.id,
            )
            .where(RosterEntryModel.tenant_id == self._tenant_uuid)
        )
        if model_filter:
            reference_stmt = reference_stmt.where(RosterEntryModel.model == model_filter)
        reference_count = int(session.execute(reference_stmt).scalar_one() or 0)

        augmented_stmt = (
            select(func.count())
            .select_from(AugmentedEmbeddingModel)
            .join(
                RosterEntryModel,
                AugmentedEmbeddingModel.roster_entry_id == RosterEntryModel.id,
            )
            .where(RosterEntryModel.tenant_id == self._tenant_uuid)
        )
        if model_filter:
            augmented_stmt = augmented_stmt.where(RosterEntryModel.model == model_filter)
        augmented_count = int(session.execute(augmented_stmt).scalar_one() or 0)

        return {
            "backend": "database",
            "backend_details": {},
            "database_url": self.database_url,
            "tenant_id": self.tenant_id,
            "model": model_filter or "all",
            "roster_stats": {
                "entry_count": entry_count,
                "reference_embeddings": reference_count,
                "augmented_embeddings": augmented_count,
                "total_embeddings": reference_count + augmented_count,
            },
        }

    def _fallback_storage_info(self) -> Dict[str, Any]:
        """Fallback payload when metrics cannot be collected."""

        return {
            "backend": "database",
            "backend_details": {},
            "database_url": self.database_url,
            "tenant_id": self.tenant_id,
            "model": "unknown",
            "roster_stats": {
                "entry_count": 0,
                "reference_embeddings": 0,
                "augmented_embeddings": 0,
                "total_embeddings": 0,
            },
        }

    def _augment_storage_info(self, info: Dict[str, Any]) -> None:
        """Hook for subclasses to append backend-specific details."""

        info.setdefault("backend_details", {})
