"""Reusable roster domain operations shared by services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .entities import RosterEntry, RosterImage
from .interfaces import DataValidationPort, RosterStoragePort


@dataclass(frozen=True)
class MutationResult:
    """Standardised response from domain mutations."""

    success: bool
    status: str
    entry: Optional[RosterEntry] = None
    details: Optional[Dict[str, Any]] = None


def validate_embedding(validator: Optional[DataValidationPort], embedding: Sequence[float], model: str) -> List[str]:
    """Run embedding validation when validator is configured."""
    if not validator:
        return []
    return validator.validate_embedding(list(embedding), model)


def add_entry(
    name: str,
    embedding: List[float],
    model: str,
    roster_storage: RosterStoragePort,
    validator: Optional[DataValidationPort],
    *,
    metadata: Optional[Dict[str, Any]] = None,
    image_path: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> MutationResult:
    """Create a new roster entry or append a reference image when identity exists."""
    errors = validate_embedding(validator, embedding, model)
    if errors:
        if logger:
            logger.error("Embedding validation failed for %s: %s", name, errors)
        return MutationResult(False, "validation_failed", details={"errors": errors})

    roster_image = RosterImage(
        embedding=embedding,
        metadata=metadata or {},
        image_path=image_path,
    )

    existing_entries = roster_storage.load_roster_entries(model)
    existing_entry = next((entry for entry in existing_entries if entry.name == name), None)

    if existing_entry:
        existing_entry.add_reference_image(roster_image)
        if roster_storage.save_roster_entry(existing_entry, model):
            if logger:
                logger.info("Added reference image to existing entry: %s", name)
            return MutationResult(True, "updated", entry=existing_entry)
        if logger:
            logger.error("Failed to persist updated entry: %s", name)
        return MutationResult(False, "persist_failed", entry=existing_entry)

    roster_entry = RosterEntry(
        name=name,
        reference_images=[roster_image],
        metadata=metadata or {},
    )
    if roster_storage.save_roster_entry(roster_entry, model):
        if logger:
            logger.info("Created new roster entry: %s", name)
        return MutationResult(True, "created", entry=roster_entry)

    if logger:
        logger.error("Failed to persist new roster entry: %s", name)
    return MutationResult(False, "persist_failed")


def add_entries_bulk(
    entries_data: List[Dict[str, Any]],
    model: str,
    roster_storage: RosterStoragePort,
    validator: Optional[DataValidationPort],
    *,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Add multiple entries with coarse input validation.

    Returns a tuple of (successful_names, failures).
    """
    max_bulk_size = 1000
    if validator and getattr(validator, "validation_config", None):
        max_bulk_size = validator.validation_config.get("max_bulk_import_size", 1000)

    if len(entries_data) > max_bulk_size:
        if logger:
            logger.error(
                "Bulk import too large: %s entries (max %s)",
                len(entries_data),
                max_bulk_size,
            )
        return [], [
            {
                "reason": "bulk_limit_exceeded",
                "limit": max_bulk_size,
                "count": len(entries_data),
            }
        ]

    successful: List[str] = []
    failures: List[Dict[str, Any]] = []

    for entry_data in entries_data:
        name = entry_data.get("name")
        embedding = entry_data.get("embedding")
        if not name or embedding is None:
            failures.append({"input": entry_data, "reason": "missing_name_or_embedding"})
            if logger:
                logger.warning("Skipping invalid entry payload: %s", entry_data)
            continue

        result = add_entry(
            name,
            embedding,
            model,
            roster_storage,
            validator,
            metadata=entry_data.get("metadata"),
            image_path=entry_data.get("image_path"),
            logger=logger,
        )

        if result.success and result.entry:
            successful.append(name)
        else:
            failure_detail = {"name": name, "status": result.status}
            if result.details:
                failure_detail["details"] = result.details
            failures.append(failure_detail)

    if logger:
        logger.info(
            "Bulk add completed: %s/%s successful",
            len(successful),
            len(entries_data),
        )
    return successful, failures


def update_entry(
    unique_id: str,
    model: str,
    roster_storage: RosterStoragePort,
    *,
    embedding: Optional[List[float]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    image_path: Optional[str] = None,
    validator: Optional[DataValidationPort] = None,
    logger: Optional[logging.Logger] = None,
) -> MutationResult:
    """Update roster entry metadata and/or add a new reference image."""
    entry = roster_storage.get_roster_entry(unique_id, model)
    if not entry:
        return MutationResult(False, "not_found")

    if embedding:
        errors = validate_embedding(validator, embedding, model)
        if errors:
            if logger:
                logger.error("Embedding validation failed for update %s: %s", unique_id, errors)
            return MutationResult(False, "validation_failed", entry=entry, details={"errors": errors})

        roster_image = RosterImage(
            embedding=embedding,
            metadata=metadata or {},
            image_path=image_path,
        )
        entry.add_reference_image(roster_image)

    if metadata:
        entry.metadata.update(metadata)
        entry.update_timestamp()

    if roster_storage.save_roster_entry(entry, model):
        if logger:
            logger.info("Updated roster entry %s", unique_id)
        return MutationResult(True, "updated", entry=entry)

    if logger:
        logger.error("Failed to persist updated entry %s", unique_id)
    return MutationResult(False, "persist_failed", entry=entry)


def delete_entry(
    unique_id: str,
    model: str,
    roster_storage: RosterStoragePort,
) -> MutationResult:
    """Delete a roster entry."""
    success = roster_storage.delete_roster_entry(unique_id, model)
    return MutationResult(success, "deleted" if success else "delete_failed")


def clear_roster(model: str, roster_storage: RosterStoragePort) -> MutationResult:
    """Remove all entries for the model."""
    success = roster_storage.clear_roster(model)
    return MutationResult(success, "cleared" if success else "clear_failed")


def add_augmented_embedding(
    unique_id: str,
    model: str,
    embedding: List[float],
    source: str,
    observation_id: str,
    roster_storage: RosterStoragePort,
    validator: Optional[DataValidationPort],
    *,
    metadata: Optional[Dict[str, Any]] = None,
    logger: Optional[logging.Logger] = None,
) -> MutationResult:
    """
    Append an augmented embedding and trigger progressive-learning refresh.

    Returns MutationResult with status:
      - "stored" when persisted successfully
      - "duplicate_observation" when observation is already present
      - "not_found" when roster entry missing
      - "persist_failed" when saving failed
      - "validation_failed" when embedding invalid
    """
    entry = roster_storage.get_roster_entry(unique_id, model)
    if not entry:
        if logger:
            logger.warning("Roster entry %s not found for augmentation", unique_id)
        return MutationResult(False, "not_found")

    errors = validate_embedding(validator, embedding, model)
    if errors:
        if logger:
            logger.error("Augmented embedding validation failed: %s", errors)
        return MutationResult(False, "validation_failed", entry=entry, details={"errors": errors})

    appended = entry.add_augmented_embedding(
        embedding=embedding,
        source=source,
        observation_id=observation_id,
        metadata=metadata,
    )
    if not appended:
        if logger:
            logger.info("Duplicate augmented embedding for observation %s", observation_id)
        return MutationResult(False, "duplicate_observation", entry=entry)

    if not roster_storage.save_roster_entry(entry, model):
        if logger:
            logger.error(
                "Failed to persist augmented embedding for entry %s in model %s",
                unique_id,
                model,
            )
        return MutationResult(False, "persist_failed", entry=entry)

    refresh_status = _refresh_progressive_learning(roster_storage, unique_id, logger)
    return MutationResult(True, "stored", entry=entry, details={"refresh_status": refresh_status})


def _refresh_progressive_learning(roster_storage: RosterStoragePort, unique_id: str, logger: Optional[logging.Logger]) -> str:
    """Trigger incremental refresh when adapter supports it."""
    if hasattr(roster_storage, "refresh_aggregate_view_incremental"):
        try:
            roster_storage.refresh_aggregate_view_incremental(roster_id=unique_id)  # type: ignore[attr-defined]
            if logger:
                logger.debug("Incremental aggregate refresh completed for %s", unique_id)
            return "incremental"
        except Exception as exc:  # pragma: no cover - defensive
            if logger:
                logger.warning("Failed incremental refresh for %s: %s", unique_id, exc)
            return "incremental_failed"

    if hasattr(roster_storage, "refresh_aggregate_view"):
        try:
            roster_storage.refresh_aggregate_view(roster_id=unique_id)  # type: ignore[attr-defined]
            if logger:
                logger.warning("Using full MV refresh for %s - consider enabling incremental path", unique_id)
            return "full_refresh"
        except Exception as exc:  # pragma: no cover - defensive
            if logger:
                logger.warning("Failed materialized view refresh for %s: %s", unique_id, exc)
            return "full_refresh_failed"

    return "unsupported"
