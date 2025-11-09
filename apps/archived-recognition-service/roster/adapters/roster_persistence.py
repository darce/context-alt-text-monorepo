"""Roster persistence helpers shared by storage adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    AugmentedEmbedding as AugmentedEmbeddingModel,
    ReferenceEmbedding as ReferenceEmbeddingModel,
    RosterEntry as RosterEntryModel,
)
from roster.domain.entities import RosterEntry

from .database_base_utils import coerce_datetime, coerce_metadata

DEFAULT_AUGMENT_SOURCE = "external_confirm"


def prepare_entry_metadata(
    entry: RosterEntry, model: str
) -> tuple[Dict[str, Any], List[Dict[str, Any]], str, str]:
    """Prepare metadata for storage without mutating the entry."""
    working_metadata = dict(entry.metadata or {})
    augmented_records = working_metadata.pop("augmented_embeddings", [])
    working_metadata.setdefault("model", model)

    preferred_name = entry.name or entry.display_name or entry.unique_id
    if preferred_name:
        working_metadata["name"] = preferred_name

    display_value = entry.display_name or preferred_name or entry.unique_id
    return working_metadata, augmented_records, display_value, preferred_name


def replace_reference_embeddings(
    session: Session,
    entry_id: Any,
    reference_images: Iterable[Any],
) -> None:
    """Diff-and-update reference embeddings to minimise churn."""
    existing_rows = (
        session.execute(
            select(ReferenceEmbeddingModel).where(
                ReferenceEmbeddingModel.roster_entry_id == entry_id
            )
        )
        .scalars()
        .all()
    )

    existing_by_embedding = {tuple(row.embedding): row for row in existing_rows}
    seen_embeddings = set()

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

        if embedding_key in existing_by_embedding:
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
            session.add(
                ReferenceEmbeddingModel(
                    roster_entry_id=entry_id,
                    embedding=embedding,
                    image_path=image_path,
                    meta=metadata or {},
                )
            )

    for embedding_key, row in existing_by_embedding.items():
        if embedding_key not in seen_embeddings:
            session.delete(row)


def replace_augmented_embeddings(
    session: Session,
    entry_id: Any,
    augmented_embeddings: Iterable[Dict[str, Any]],
    *,
    source_default: str = DEFAULT_AUGMENT_SOURCE,
) -> None:
    """Diff-and-update augmented embeddings by observation_id."""
    existing_rows = (
        session.execute(
            select(AugmentedEmbeddingModel).where(
                AugmentedEmbeddingModel.roster_entry_id == entry_id
            )
        )
        .scalars()
        .all()
    )

    existing_by_obs_id = {row.observation_id: row for row in existing_rows}
    seen_obs_ids = set()

    for record in augmented_embeddings:
        if not isinstance(record, dict):
            continue

        embedding = record.get("embedding")
        observation_id = record.get("observation_id")
        if not embedding or not observation_id:
            continue

        seen_obs_ids.add(observation_id)
        created_at = coerce_datetime(record.get("created_at")) or datetime.utcnow()

        if observation_id in existing_by_obs_id:
            existing = existing_by_obs_id[observation_id]
            needs_update = False

            if existing.embedding != embedding:
                existing.embedding = embedding
                needs_update = True

            new_source = record.get("source", source_default)
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
            session.add(
                AugmentedEmbeddingModel(
                    roster_entry_id=entry_id,
                    observation_id=observation_id,
                    embedding=embedding,
                    source=record.get("source", source_default),
                    attachment_id=record.get("attachment_id"),
                    bbox=record.get("bbox"),
                    confidence=record.get("confidence"),
                    quality_tier=record.get("quality_tier", "medium"),
                    created_at=created_at,
                )
            )

    for obs_id, row in existing_by_obs_id.items():
        if obs_id not in seen_obs_ids:
            session.delete(row)


def load_reference_embeddings(
    session: Session,
    entry_ids: List[Any],
) -> Dict[Any, List[Dict[str, Any]]]:
    """Load reference embeddings for a collection of roster entries."""
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
                "metadata": coerce_metadata(row.meta),
                "image_path": row.image_path,
            }
        )
    return result


def load_augmented_embeddings(
    session: Session,
    entry_ids: List[Any],
) -> Dict[Any, List[Dict[str, Any]]]:
    """Load augmented embeddings for a collection of roster entries."""
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


def hydrate_entry(
    row: RosterEntryModel,
    reference_images: List[Dict[str, Any]],
    augmented_embeddings: List[Dict[str, Any]],
) -> RosterEntry:
    """Create a domain object from database row + attached embeddings."""
    metadata = coerce_metadata(row.meta)
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
