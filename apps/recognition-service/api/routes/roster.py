"""Roster management endpoints.

These routes support onboarding embeddings from clients (e.g., WP plugin)
and managing roster entries required by the recognition pipeline.
Clients are expected to obtain embeddings via `/api/v0/embeddings` and then
POST them here to upsert roster entries. The service aggregates reference
embeddings so additional images improve InsightFace accuracy automatically.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator

from roster.domain.roster_service import RosterService
from shared.dtos.roster import RosterEntryDTO
from api.dependencies import get_roster_service

DEFAULT_MODEL = "insightface_w600k"

router = APIRouter()


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
):
    """Add or update roster entries using precomputed embeddings."""

    model = payload.model or DEFAULT_MODEL
    successes: List[str] = []
    failures: List[Dict[str, str]] = []

    for entry in payload.entries:
        result = roster_service.add_entry(
            name=entry.name,
            embedding=entry.embedding,
            model=model,
            metadata=entry.metadata,
            image_path=entry.image_path,
        )
        if result:
            successes.append(entry.name)
        else:
            failures.append({"name": entry.name, "reason": "validation or storage failure"})

    total_entries = roster_service.get_entry_count(model)

    return {
        "model": model,
        "processed": len(payload.entries),
        "successful": successes,
        "failed": failures,
        "roster_stats": {"total_entries": total_entries, "newly_added": len(successes)},
    }


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
    roster_service: RosterService = Depends(get_roster_service),
):
    """Return the current roster entries for the configured model."""

    entries = roster_service.get_entries(model)
    serialized = []
    for entry in entries:
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

    return {"model": model, "count": len(serialized), "entries": serialized}


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
