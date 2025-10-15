"""Roster management endpoints.

These routes support onboarding embeddings from clients (e.g., WP plugin)
and managing roster entries required by the recognition pipeline.
Clients are expected to obtain embeddings via `/api/v0/embeddings` and then
POST them here to upsert roster entries. The service aggregates reference
embeddings so additional images improve InsightFace accuracy automatically.
"""

import copy
import math
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, validator

from roster.domain.roster_service import RosterService
from shared.dtos.roster import RosterEntryDTO
from api.dependencies import get_roster_service

DEFAULT_MODEL = "insightface_w600k"
IDEMPOTENCY_TTL_SECONDS = 600

router = APIRouter()

_IDEMPOTENCY_CACHE: Dict[str, Dict[str, object]] = {}


def _get_cached_idempotent_response(key: str) -> Optional[Dict[str, object]]:
    entry = _IDEMPOTENCY_CACHE.get(key)
    if not entry:
        return None

    expires_at = entry.get("_expires_at")
    if isinstance(expires_at, (int, float)) and expires_at < time.time():
        _IDEMPOTENCY_CACHE.pop(key, None)
        return None

    cached = copy.deepcopy(entry)
    cached.pop("_expires_at", None)
    return cached


def _store_idempotent_response(key: str, response: Dict[str, object]) -> None:
    payload = copy.deepcopy(response)
    payload["_expires_at"] = time.time() + IDEMPOTENCY_TTL_SECONDS
    _IDEMPOTENCY_CACHE[key] = payload


class RosterEntryPayload(BaseModel):
    """Incoming payload describing a roster entry embedding."""

    name: str = Field(..., description="Identity name")
    embedding: List[float] = Field(..., description="Normalized face embedding vector")
    metadata: Optional[Dict[str, object]] = Field(None, description="Optional metadata dictionary")
    image_path: Optional[str] = Field(None, description="Optional reference image path or URI")

    @validator("embedding")
    def validate_embedding_non_empty(cls, value: List[float]) -> List[float]:
        if not value:
            raise ValueError("embedding must contain values")
        return value


class RosterBatchRequest(BaseModel):
    entries: List[RosterEntryPayload]
    model: Optional[str] = Field(DEFAULT_MODEL, description="Model identifier")
    idempotency_key: Optional[str] = Field(
        None,
        description="Optional idempotency key for safely retrying bulk imports",
    )


class RosterReferencePayload(BaseModel):
    embedding: List[float]
    metadata: Optional[Dict[str, object]] = None
    image_path: Optional[str] = None
    model: Optional[str] = Field(DEFAULT_MODEL, description="Model identifier")

    @validator("embedding")
    def validate_embedding_non_empty(cls, value: List[float]) -> List[float]:
        if not value:
            raise ValueError("embedding must contain values")
        return value


@router.post("/roster")
async def upsert_roster_embeddings(
    payload: RosterBatchRequest,
    roster_service: RosterService = Depends(get_roster_service),
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Add or update roster entries using precomputed embeddings."""

    model = payload.model or DEFAULT_MODEL
    idempotency_key = payload.idempotency_key or idempotency_key_header

    if idempotency_key:
        cached_response = _get_cached_idempotent_response(idempotency_key)
        if cached_response is not None:
            cached_response["idempotency_key"] = idempotency_key
            return cached_response

    successes: List[str] = []
    failures: List[Dict[str, str]] = []
    conflicts: List[Dict[str, str]] = []
    new_entries = 0

    existing_by_name = {entry.name: entry for entry in roster_service.get_entries(model)}

    for entry in payload.entries:
        existing_entry = existing_by_name.get(entry.name)

        result = roster_service.add_entry(
            name=entry.name,
            embedding=entry.embedding,
            model=model,
            metadata=entry.metadata,
            image_path=entry.image_path,
        )
        if result:
            successes.append(entry.name)
            if existing_entry:
                reason = "duplicate_name"
                if entry.metadata and existing_entry.metadata != entry.metadata:
                    reason = "metadata_conflict"
                conflicts.append({"name": entry.name, "reason": reason})
            else:
                new_entries += 1
            existing_by_name[entry.name] = result
        else:
            failures.append({"name": entry.name, "reason": "validation or storage failure"})

    total_entries = roster_service.get_entry_count(model)

    response_body: Dict[str, object] = {
        "model": model,
        "processed": len(payload.entries),
        "successful": successes,
        "failed": failures,
        "conflicts": conflicts,
        "roster_stats": {
            "total_entries": total_entries,
            "newly_added": new_entries,
        },
    }

    if idempotency_key:
        response_body["idempotency_key"] = idempotency_key
        _store_idempotent_response(idempotency_key, response_body)

    return response_body


@router.post("/roster/{unique_id}/embeddings")
async def append_reference_embedding(
    unique_id: str,
    payload: RosterReferencePayload,
    roster_service: RosterService = Depends(get_roster_service),
):
    """Attach an additional reference embedding to an existing roster entry."""

    model = payload.model or DEFAULT_MODEL
    success = roster_service.update_entry(
        unique_id=unique_id,
        model=model,
        embedding=payload.embedding,
        metadata=payload.metadata,
        image_path=payload.image_path,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Roster entry '{unique_id}' not found or update failed",
        )

    updated = roster_service.get_entry(unique_id, model)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Entry updated but could not be reloaded",
        )

    dto = RosterEntryDTO(
        unique_id=updated.unique_id,
        name=updated.name,
        display_name=updated.display_name,
        aggregate_embedding=updated.aggregate_embedding,
        metadata=updated.metadata,
        created_timestamp=updated.created_timestamp,
        updated_timestamp=updated.updated_timestamp,
        image_count=updated.image_count,
        roster_image_path=None,
        embedding_length=len(updated.aggregate_embedding or []),
        reference_embeddings=[img.embedding for img in updated.reference_images],
    )

    return {"message": "Reference embedding appended", "entry": dto.model_dump()}


@router.get("/roster")
async def list_roster_entries(
    include_embeddings: bool = False,
    model: str = DEFAULT_MODEL,
    page: int = Query(1, ge=1, description="One-based page number for paginated results"),
    page_size: int = Query(50, ge=1, le=200, description="Number of entries per page"),
    roster_service: RosterService = Depends(get_roster_service),
):
    """Return the current roster entries for the configured model."""

    entries = roster_service.get_entries(model)
    total_entries = len(entries)
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    page_entries = entries[start_index:end_index]

    serialized = []
    for entry in page_entries:
        dto = RosterEntryDTO(
            unique_id=entry.unique_id,
            name=entry.name,
            display_name=entry.display_name,
            aggregate_embedding=entry.aggregate_embedding if include_embeddings else None,
            metadata=entry.metadata,
            created_timestamp=entry.created_timestamp,
            updated_timestamp=entry.updated_timestamp,
            image_count=entry.image_count,
            roster_image_path=None,
            embedding_length=len(entry.aggregate_embedding or []),
            reference_embeddings=[img.embedding for img in entry.reference_images] if include_embeddings else None,
        )
        serialized.append(dto.model_dump())

    total_pages = math.ceil(total_entries / page_size) if total_entries else 0

    return {
        "model": model,
        "count": len(serialized),
        "entries": serialized,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_entries": total_entries,
            "total_pages": total_pages,
            "has_next": end_index < total_entries,
            "has_previous": start_index > 0,
        },
    }


@router.delete("/roster/{unique_id}")
async def delete_roster_entry(
    unique_id: str,
    model: str = DEFAULT_MODEL,
    roster_service: RosterService = Depends(get_roster_service),
):
    """Delete a roster entry by unique ID."""

    success = roster_service.delete_entry(unique_id, model)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Roster entry '{unique_id}' not found",
        )

    total_entries = roster_service.get_entry_count(model)
    return {"message": f"Deleted roster entry '{unique_id}'", "roster_stats": {"total_entries": total_entries}}


@router.get("/roster/stats")
async def roster_stats(
    model: str = DEFAULT_MODEL,
    roster_service: RosterService = Depends(get_roster_service),
):
    """Return simple roster statistics."""

    total_entries = roster_service.get_entry_count(model)
    storage_info = roster_service.get_storage_info(model)
    return {
        "model": model,
        "total_entries": total_entries,
        "storage": storage_info,
    }
