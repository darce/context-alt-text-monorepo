"""Shared database-backed roster storage adapter logic."""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from db.models import (
    AugmentedEmbedding as AugmentedEmbeddingModel,
    Base,
    ReferenceEmbedding as ReferenceEmbeddingModel,
    RosterEntry as RosterEntryModel,
    Tenant,
)
from roster.domain.entities import RosterEntry
from roster.domain.interfaces import RosterStoragePort

logger = logging.getLogger(__name__)


DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

def _coerce_datetime(value: Optional[Any]) -> Optional[datetime]:
    """Convert ISO8601 strings into ``datetime`` instances when possible."""

    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        logger.debug("Failed to coerce datetime value '%s'", value)
        return None


def _coerce_metadata(value: Any) -> Dict[str, Any]:
    """Ensure metadata is returned as a dictionary."""

    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            import json

            return json.loads(value)
        except json.JSONDecodeError:
            logger.debug("Failed to decode metadata JSON", exc_info=True)
            return {}
    return {}


def _normalize_tenant_id(value: Optional[Any]) -> uuid.UUID:
    """Normalise the configured tenant identifier to a :class:`uuid.UUID`."""

    if value is None:
        return DEFAULT_TENANT_ID

    if isinstance(value, uuid.UUID):
        return value

    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            # Deterministic UUID derived from provided slug/string.
            return uuid.uuid5(uuid.NAMESPACE_DNS, value)

    raise TypeError(f"Unsupported tenant identifier type: {type(value)!r}")


def _normalize_entry_id(value: Optional[Any]) -> uuid.UUID:
    """Normalise roster entry identifiers to UUID primary keys."""

    if isinstance(value, uuid.UUID):
        return value

    if not value:
        return uuid.uuid4()

    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            # Deterministic namespace UUID so repeated calls resolve to same PK.
            return uuid.uuid5(uuid.NAMESPACE_URL, value)

    raise TypeError(f"Unsupported entry identifier type: {type(value)!r}")


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
        self._tenant_uuid = _normalize_tenant_id(tenant_id)
        self.tenant_id = str(self._tenant_uuid)

        self._engine = self._create_engine(database_url, echo=echo)
        if create_schema:
            Base.metadata.create_all(self._engine)

        self._Session = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            future=True,
        )

    # ------------------------------------------------------------------
    # Engine helpers
    # ------------------------------------------------------------------
    def _create_engine(self, database_url: str, *, echo: bool) -> Engine:
        """Create the SQLAlchemy engine. Subclasses may override."""

        return create_engine(database_url, echo=echo, future=True)

    @contextmanager
    def _session(self) -> Session:
        """Context manager that yields a configured session and ensures cleanup."""

        session = self._Session()
        try:
            self._configure_session(session)
            yield session
        finally:
            session.close()

    def _configure_session(self, session: Session) -> None:  # pragma: no cover - hook for subclasses
        """Hook for subclasses to customise session state per transaction."""

    def close(self) -> None:
        """Dispose the underlying engine."""

        self._engine.dispose()

    # ------------------------------------------------------------------
    # Tenant helpers
    # ------------------------------------------------------------------
    def _ensure_tenant(self, session: Session) -> Tenant:
        tenant = session.get(Tenant, self._tenant_uuid)
        if tenant is None:
            slug = f"tenant-{str(self._tenant_uuid)[:8]}"
            tenant = Tenant(
                id=self._tenant_uuid,
                slug=slug,
                name=slug,
            )
            session.add(tenant)
            session.flush()
        return tenant

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _prepare_entry_metadata(
        entry: RosterEntry, model: str
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]], str, str]:
        """
        Prepare metadata for storage without mutating the entry.
        
        Returns:
            tuple: (metadata_dict, augmented_records, display_value)
        """
        working_metadata = dict(entry.metadata or {})
        augmented_records = working_metadata.pop("augmented_embeddings", [])
        working_metadata.setdefault("model", model)
        
        preferred_name = entry.name or entry.display_name or entry.unique_id
        if preferred_name:
            working_metadata["name"] = preferred_name
        
        display_value = entry.display_name or preferred_name or entry.unique_id
        
        return working_metadata, augmented_records, display_value, preferred_name

    # ------------------------------------------------------------------
    # Port implementation
    # ------------------------------------------------------------------
    def save_roster_entry(self, entry: RosterEntry, model: str) -> bool:
        metadata, augmented_records, display_value, preferred_name = self._prepare_entry_metadata(entry, model)

        try:
            with self._session() as session:
                tenant = self._ensure_tenant(session)

                entry_pk = _normalize_entry_id(entry.unique_id)
                row = session.get(RosterEntryModel, entry_pk)
                created_at = _coerce_datetime(entry.created_timestamp) or datetime.utcnow()
                updated_at = _coerce_datetime(entry.updated_timestamp) or datetime.utcnow()

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _replace_reference_embeddings(
        self,
        session: Session,
        entry_id: Any,
        reference_images: Iterable[Any],
    ) -> None:
        """
        Intelligently update reference embeddings by tracking diffs.
        
        Instead of deleting and reinserting all embeddings, this method:
        1. Loads existing embeddings from the database
        2. Compares with new embeddings to identify changes
        3. Only updates/inserts/deletes what changed
        
        This reduces log noise, database churn, and enables future auditing.
        """
        # Load existing embeddings
        existing_rows = (
            session.execute(
                select(ReferenceEmbeddingModel).where(
                    ReferenceEmbeddingModel.roster_entry_id == entry_id
                )
            )
            .scalars()
            .all()
        )
        
        # Create lookup by embedding vector (using tuple for hashability)
        existing_by_embedding = {
            tuple(row.embedding): row for row in existing_rows
        }
        
        # Track which embeddings are still present
        seen_embeddings = set()
        
        # Process new/updated embeddings
        for image in reference_images:
            if image is None:
                continue

            embedding = getattr(image, "embedding", None) or getattr(image, "get", lambda *_: None)(
                "embedding", None
            )
            image_path = getattr(image, "image_path", None) or getattr(image, "get", lambda *_: None)(
                "image_path", None
            )
            metadata = getattr(image, "metadata", None) or getattr(image, "get", lambda *_: None)(
                "metadata", {}
            )

            if not embedding:
                continue
            
            embedding_key = tuple(embedding)
            seen_embeddings.add(embedding_key)
            
            # Check if this embedding already exists
            if embedding_key in existing_by_embedding:
                # Update existing record if metadata or image_path changed
                existing = existing_by_embedding[embedding_key]
                needs_update = False
                
                if existing.image_path != image_path:
                    existing.image_path = image_path
                    needs_update = True
                
                if existing.meta != (metadata or {}):
                    existing.meta = metadata or {}
                    needs_update = True
                
                if needs_update:
                    session.add(existing)
            else:
                # Insert new embedding
                session.add(
                    ReferenceEmbeddingModel(
                        roster_entry_id=entry_id,
                        embedding=embedding,
                        image_path=image_path,
                        meta=metadata or {},
                    )
                )
        
        # Delete embeddings that are no longer present
        for embedding_key, row in existing_by_embedding.items():
            if embedding_key not in seen_embeddings:
                session.delete(row)

    def _replace_augmented_embeddings(
        self,
        session: Session,
        entry_id: Any,
        augmented_embeddings: Iterable[Dict[str, Any]],
    ) -> None:
        """
        Intelligently update augmented embeddings by tracking diffs.
        
        Instead of deleting and reinserting all embeddings, this method:
        1. Loads existing embeddings from the database
        2. Compares with new embeddings by observation_id
        3. Only updates/inserts/deletes what changed
        
        This reduces log noise, database churn, and enables future auditing.
        """
        # Load existing augmented embeddings
        existing_rows = (
            session.execute(
                select(AugmentedEmbeddingModel).where(
                    AugmentedEmbeddingModel.roster_entry_id == entry_id
                )
            )
            .scalars()
            .all()
        )
        
        # Create lookup by observation_id (unique identifier for augmented embeddings)
        existing_by_obs_id = {
            row.observation_id: row for row in existing_rows
        }
        
        # Track which observation IDs are still present
        seen_obs_ids = set()

        # Process new/updated embeddings
        for record in augmented_embeddings:
            if not isinstance(record, dict):
                continue

            embedding = record.get("embedding")
            observation_id = record.get("observation_id")
            if not embedding or not observation_id:
                continue

            seen_obs_ids.add(observation_id)
            created_at = _coerce_datetime(record.get("created_at")) or datetime.utcnow()
            
            # Check if this observation_id already exists
            if observation_id in existing_by_obs_id:
                # Update existing record if any fields changed
                existing = existing_by_obs_id[observation_id]
                needs_update = False
                
                # Compare all fields
                if existing.embedding != embedding:
                    existing.embedding = embedding
                    needs_update = True
                
                new_source = record.get("source", "wordpress_confirm")
                if existing.source != new_source:
                    existing.source = new_source
                    needs_update = True
                
                new_attachment_id = record.get("attachment_id")
                if existing.attachment_id != new_attachment_id:
                    existing.attachment_id = new_attachment_id
                    needs_update = True
                
                new_bbox = record.get("bbox")
                if existing.bbox != new_bbox:
                    existing.bbox = new_bbox
                    needs_update = True
                
                new_confidence = record.get("confidence")
                if existing.confidence != new_confidence:
                    existing.confidence = new_confidence
                    needs_update = True
                
                new_quality_tier = record.get("quality_tier", "medium")
                if existing.quality_tier != new_quality_tier:
                    existing.quality_tier = new_quality_tier
                    needs_update = True
                
                if needs_update:
                    session.add(existing)
            else:
                # Insert new augmented embedding
                session.add(
                    AugmentedEmbeddingModel(
                        roster_entry_id=entry_id,
                        observation_id=observation_id,
                        embedding=embedding,
                        source=record.get("source", "wordpress_confirm"),
                        attachment_id=record.get("attachment_id"),
                        bbox=record.get("bbox"),
                        confidence=record.get("confidence"),
                        quality_tier=record.get("quality_tier", "medium"),
                        created_at=created_at,
                    )
                )
        
        # Delete augmented embeddings that are no longer present
        for obs_id, row in existing_by_obs_id.items():
            if obs_id not in seen_obs_ids:
                session.delete(row)

    def _load_reference_embeddings(
        self,
        session: Session,
        entry_ids: List[Any],
    ) -> Dict[Any, List[Dict[str, Any]]]:
        if not entry_ids:
            return {}

        rows = (
            session.execute(
                select(ReferenceEmbeddingModel).where(ReferenceEmbeddingModel.roster_entry_id.in_(entry_ids))
            )
            .scalars()
            .all()
        )

        result: Dict[Any, List[Dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(row.roster_entry_id, []).append(
                {
                    "embedding": row.embedding,
                    "metadata": _coerce_metadata(row.meta),
                    "image_path": row.image_path,
                }
            )
        return result

    def _load_augmented_embeddings(
        self,
        session: Session,
        entry_ids: List[Any],
    ) -> Dict[Any, List[Dict[str, Any]]]:
        if not entry_ids:
            return {}

        rows = (
            session.execute(
                select(AugmentedEmbeddingModel).where(AugmentedEmbeddingModel.roster_entry_id.in_(entry_ids))
            )
            .scalars()
            .all()
        )

        result: Dict[Any, List[Dict[str, Any]]] = {}
        for row in rows:
            record: Dict[str, Any] = {
                "embedding": row.embedding,
                "source": row.source,
                "observation_id": row.observation_id,
                "attachment_id": row.attachment_id,
                "bbox": row.bbox,
                "confidence": row.confidence,
                "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else row.created_at,
                "quality_tier": row.quality_tier,
            }
            result.setdefault(row.roster_entry_id, []).append(record)
        return result

    def _hydrate_entry(
        self,
        row: RosterEntryModel,
        reference_images: List[Dict[str, Any]],
        augmented_embeddings: List[Dict[str, Any]],
    ) -> RosterEntry:
        metadata = _coerce_metadata(row.meta)
        metadata.setdefault("model", getattr(row, "model", None))
        metadata["augmented_embeddings"] = augmented_embeddings

        payload: Dict[str, Any] = {
            "name": metadata.get("name", row.display_name or row.label),
            "display_name": row.display_name or row.label,
            "unique_id": row.label,
            "reference_images": reference_images,
            "aggregate_embedding": row.aggregate_embedding,
            "metadata": metadata,
            "created_timestamp": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else None,
            "updated_timestamp": row.updated_at.isoformat() if hasattr(row.updated_at, "isoformat") else None,
        }
        return RosterEntry.from_dict(payload)
