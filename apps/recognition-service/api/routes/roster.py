"""Roster management endpoints.

These routes support onboarding embeddings from clients (e.g., WP plugin)
and managing roster entries required by the recognition pipeline.
Clients are expected to obtain embeddings via `/api/v0/embeddings` and then
POST them here to upsert roster entries. The service aggregates reference
embeddings so additional images improve InsightFace accuracy automatically.
"""

import copy
import hashlib
import logging
import math
import threading
import time
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, validator

from roster.domain.roster_service import RosterService
from shared.dtos.roster import RosterEntryDTO, AugmentedRosterEntryDTO
from shared.metrics import (
    augmented_embedding_requests_total,
    augmented_embedding_duration_seconds,
    track_aggregate_recomputation,
)
from api.dependencies import get_recognition_service, get_roster_service

DEFAULT_MODEL = "insightface_w600k"
IDEMPOTENCY_TTL_SECONDS = 600
ETAG_CACHE_TTL_SECONDS = 300

router = APIRouter()

_IDEMPOTENCY_CACHE: Dict[str, Dict[str, object]] = {}
_RELOAD_DEBOUNCE_SECONDS = 30
_last_reload_request: float = 0.0
_reload_lock = threading.Lock()

# ETag caching
_ETAG_CACHE: Dict[str, str] = {}
_ETAG_CACHE_TIMESTAMP: Dict[str, float] = {}
_etag_lock = threading.Lock()

logger = logging.getLogger(__name__)


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


def _entry_name(entry: Any) -> str:
    name = getattr(entry, "name", None)
    if isinstance(name, str):
        return name
    if name is None:
        return ""
    return str(name)


def _entry_unique_id(entry: Any) -> str:
    unique_id = getattr(entry, "unique_id", None)
    if isinstance(unique_id, str):
        return unique_id
    if unique_id is None:
        return ""
    return str(unique_id)


def _calculate_embedding_counts(entry) -> Dict[str, int]:
    """Calculate reference and augmented embedding counts for a roster entry."""
    reference_count = len(entry.reference_images)
    augmented = entry.metadata.get("augmented_embeddings", []) if entry.metadata else []
    augmented_count = len(augmented)
    return {
        "reference_count": reference_count,
        "augmented_count": augmented_count,
        "embedding_count": reference_count + augmented_count,
    }


def _serialize_augmented_entry(entry) -> Dict[str, Any]:
    """Serialize roster entry with progressive-learning metadata."""
    counts = _calculate_embedding_counts(entry)
    dto = AugmentedRosterEntryDTO(
        unique_id=_entry_unique_id(entry),
        name=_entry_name(entry),
        display_name=str(getattr(entry, "display_name", "")),
        embedding_count=counts["embedding_count"],
        augmented_count=counts["augmented_count"],
        reference_count=counts["reference_count"],
        aggregate_embedding=entry.aggregate_embedding,
        metadata=entry.metadata,
        created_at=entry.created_timestamp,
        updated_at=entry.updated_timestamp,
    )
    return jsonable_encoder(dto.model_dump())


async def _trigger_embedding_reload() -> None:
    """Invoke the recognition service to rebuild its embedding index."""
    recognition_service = get_recognition_service()
    try:
        stats = await recognition_service.reload_embeddings()
        logger.info("[RELOAD] Embedding router refreshed: %s", stats)
    except Exception as exc:  # pragma: no cover - defensive log hook
        logger.exception("[RELOAD] Failed to refresh embeddings: %s", exc)


def _schedule_embedding_reload(background_tasks: BackgroundTasks) -> bool:
    """Debounce embedding reload requests and enqueue background refresh."""
    global _last_reload_request

    if background_tasks is None:
        return False

    now = time.time()
    with _reload_lock:
        if (now - _last_reload_request) < _RELOAD_DEBOUNCE_SECONDS:
            return False
        _last_reload_request = now

    background_tasks.add_task(_trigger_embedding_reload)
    return True


def _compute_roster_etag(entries: List) -> str:
    """Compute ETag from roster content (sorted unique_ids + updated_timestamps)."""
    if not entries:
        return hashlib.sha256(b"empty").hexdigest()[:16]
    
    # Create stable hash from sorted (unique_id, updated_timestamp) pairs
    pairs = sorted([(e.unique_id, e.updated_timestamp) for e in entries])
    content = "|".join(f"{uid}:{ts}" for uid, ts in pairs)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _get_cached_etag(model: str, roster_service: RosterService) -> str:
    """Get cached ETag or compute new one."""
    with _etag_lock:
        now = time.time()
        
        # Check cache
        if model in _ETAG_CACHE:
            cache_age = now - _ETAG_CACHE_TIMESTAMP.get(model, 0)
            if cache_age < ETAG_CACHE_TTL_SECONDS:
                return _ETAG_CACHE[model]
        
        # Compute new ETag
        entries = roster_service.get_entries(model)
        etag = _compute_roster_etag(entries)
        
        # Update cache
        _ETAG_CACHE[model] = etag
        _ETAG_CACHE_TIMESTAMP[model] = now
        
        return etag


def _invalidate_etag_cache(model: str) -> None:
    """Invalidate ETag cache after roster writes."""
    with _etag_lock:
        _ETAG_CACHE.pop(model, None)
        _ETAG_CACHE_TIMESTAMP.pop(model, None)


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


class AddEmbeddingPayload(BaseModel):
    """Payload for adding a confirmed embedding to an existing roster entry."""
    
    rosterId: str = Field(..., description="Unique identifier of the roster entry")
    observationId: str = Field(..., description="Unique identifier of the observation (prevents duplicates)")
    embedding: List[float] = Field(..., description="Normalized face embedding vector (512-dim)")
    model: Optional[str] = Field(DEFAULT_MODEL, description="Model identifier")
    metadata: Optional[Dict[str, object]] = Field(None, description="Optional metadata (attachmentId, bbox, etc.)")

    @validator("embedding")
    def validate_embedding_non_empty(cls, value: List[float]) -> List[float]:
        if not value:
            raise ValueError("embedding must contain values")
        return value


class RosterAugmentPayload(BaseModel):
    """Payload for progressive-learning augmentation."""

    embedding: List[float] = Field(..., description="Normalized face embedding vector (512-dim)")
    observation_id: str = Field(..., description="Observation identifier for idempotency")
    attachment_id: Optional[int] = Field(None, description="Attachment identifier for metadata enrichment")
    bbox: Optional[Dict[str, float]] = Field(None, description="Bounding box coordinates for the observation")
    confidence: Optional[float] = Field(None, description="Confidence score associated with the observation")
    quality_tier: Optional[str] = Field(None, description="Override quality tier (defaults derived from confidence)")
    idempotency_key: Optional[str] = Field(
        None,
        description="Optional idempotency key to safely retry augment requests",
    )

    @validator("embedding")
    def validate_embedding_non_empty(cls, value: List[float]) -> List[float]:
        if not value:
            raise ValueError("embedding must contain values")
        return value

    class Config:
        allow_population_by_field_name = True

# In-memory tracking of synced observationIds per rosterId
# Format: {rosterId: {observationId: timestamp}}
_SYNCED_OBSERVATIONS: Dict[str, Dict[str, float]] = {}


@router.post("/roster")
async def upsert_roster_embeddings(
    payload: RosterBatchRequest,
    background_tasks: BackgroundTasks,
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

    existing_by_name: Dict[str, Any] = {}
    for entry in roster_service.get_entries(model):
        key = _entry_name(entry)
        if key:
            existing_by_name[key] = entry

    for entry in payload.entries:
        entry_name = entry.name
        existing_entry = existing_by_name.get(entry_name)

        result = roster_service.add_entry(
            name=entry.name,
            embedding=entry.embedding,
            model=model,
            metadata=entry.metadata,
            image_path=entry.image_path,
        )
        if result:
            successes.append(entry_name)
            if existing_entry:
                reason = "duplicate_name"
                if entry.metadata and existing_entry.metadata != entry.metadata:
                    reason = "metadata_conflict"
                conflicts.append({"name": entry.name, "reason": reason})
            else:
                new_entries += 1
            existing_by_name[entry_name] = result
            result_name = _entry_name(result)
            if result_name:
                existing_by_name[result_name] = result
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

    if successes:
        _schedule_embedding_reload(background_tasks)
        _invalidate_etag_cache(model)

    if idempotency_key:
        response_body["idempotency_key"] = idempotency_key
        _store_idempotent_response(idempotency_key, response_body)

    return response_body


@router.post("/roster/add-embedding")
async def add_embedding_to_roster(
    payload: AddEmbeddingPayload,
    background_tasks: BackgroundTasks,
    roster_service: RosterService = Depends(get_roster_service),
):
    """Legacy augmentation endpoint preserved for backwards compatibility."""
    
    model = payload.model or DEFAULT_MODEL
    roster_id = payload.rosterId
    observation_id = payload.observationId
    
    # Check if this observationId was already synced for this rosterId
    if roster_id in _SYNCED_OBSERVATIONS:
        if observation_id in _SYNCED_OBSERVATIONS[roster_id]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Observation '{observation_id}' already synced to roster entry '{roster_id}'",
            )
    
    # Verify roster entry exists
    existing_entry = roster_service.get_entry(roster_id, model)
    if not existing_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Roster entry '{roster_id}' not found",
        )
    
    extra_metadata = dict(payload.metadata) if payload.metadata else {}
    augment_payload = RosterAugmentPayload(
        embedding=payload.embedding,
        observation_id=observation_id,
    )
    response_body, _ = await _process_augmentation_request(
        unique_id=roster_id,
        payload=augment_payload,
        background_tasks=background_tasks,
        roster_service=roster_service,
        extra_metadata=extra_metadata,
    )
    return response_body


async def _process_augmentation_request(
    unique_id: str,
    payload: RosterAugmentPayload,
    background_tasks: BackgroundTasks,
    roster_service: RosterService,
    extra_metadata: Optional[Dict[str, Any]] = None,
):
    start_time = time.perf_counter()
    quality_tier = payload.quality_tier or "unknown"
    augment_status = "success"
    
    try:
        model = DEFAULT_MODEL
        idempotency_key = payload.idempotency_key or f"augment:{unique_id}:{payload.observation_id}"

        cached_response: Optional[Dict[str, Any]] = None
        if payload.idempotency_key:
            cached_response = _get_cached_idempotent_response(idempotency_key)
            if cached_response is not None:
                cached_response["idempotency_key"] = idempotency_key
                # Track as cached hit
                augmented_embedding_requests_total.labels(
                    status="cached",
                    quality_tier=quality_tier
                ).inc()
                return cached_response, False

        sync_key = str(unique_id)
        if sync_key in _SYNCED_OBSERVATIONS:
            if payload.observation_id in _SYNCED_OBSERVATIONS[sync_key]:
                augment_status = "duplicate"
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Observation '{payload.observation_id}' already synced to roster entry '{unique_id}'",
                )

        entry = roster_service.get_entry(unique_id, model)
        if not entry:
            augment_status = "not_found"
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Roster entry '{unique_id}' not found",
            )


        # Duplicate observation guard
        augmented_embeddings = entry.metadata.get("augmented_embeddings", []) if entry.metadata else []
        if any(item.get("observation_id") == payload.observation_id for item in augmented_embeddings):
            augment_status = "duplicate"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Observation '{payload.observation_id}' already synced to roster entry '{unique_id}'",
            )

        metadata: Dict[str, Any] = {}
        if payload.attachment_id is not None:
            metadata["attachment_id"] = payload.attachment_id
        if payload.bbox is not None:
            metadata["bbox"] = payload.bbox
        if payload.confidence is not None:
            metadata["confidence"] = payload.confidence
        if payload.quality_tier is not None:
            metadata["quality_tier"] = payload.quality_tier
        if extra_metadata:
            metadata.update(extra_metadata)

        # Track aggregate recomputation time
        with track_aggregate_recomputation():
            appended = roster_service.add_augmented_embedding(
                unique_id=unique_id,
                model=model,
                embedding=payload.embedding,
                source="wordpress_confirm",
                observation_id=payload.observation_id,
                metadata=metadata,
            )

        if not appended:
            # Check whether append failed because of duplicate observation id (race)
            updated_entry = roster_service.get_entry(unique_id, model)
            if updated_entry:
                augmented_list = updated_entry.metadata.get("augmented_embeddings", [])
                if any(item.get("observation_id") == payload.observation_id for item in augmented_list):
                    augment_status = "duplicate"
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Observation '{payload.observation_id}' already synced to roster entry '{unique_id}'",
                    )
            augment_status = "error"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to add embedding to roster entry '{unique_id}'",
            )

        updated_entry = roster_service.get_entry(unique_id, model)
        if not updated_entry:
            augment_status = "error"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Entry updated but could not be reloaded",
            )

        if sync_key not in _SYNCED_OBSERVATIONS:
            _SYNCED_OBSERVATIONS[sync_key] = {}
        _SYNCED_OBSERVATIONS[sync_key][payload.observation_id] = time.time()

        scheduled = _schedule_embedding_reload(background_tasks)
        _invalidate_etag_cache(model)

        response_body = {
            "success": True,
            "roster_entry": _serialize_augmented_entry(updated_entry),
            "index_reloaded": scheduled,
            "idempotency_key": idempotency_key,
        }

        if payload.idempotency_key:
            _store_idempotent_response(idempotency_key, response_body)
        
        return response_body, True
        
    except HTTPException:
        # Re-raise HTTP exceptions but still track metrics
        raise
    except Exception as exc:
        augment_status = "error"
        logger.exception(f"Unexpected error in augmentation: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error processing augmentation: {str(exc)}"
        )
    finally:
        # Track metrics regardless of outcome
        duration = time.perf_counter() - start_time
        augmented_embedding_requests_total.labels(
            status=augment_status,
            quality_tier=quality_tier
        ).inc()
        augmented_embedding_duration_seconds.labels(
            operation="augment_request"
        ).observe(duration)


@router.post(
    "/roster/{unique_id}/augment",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Add augmented embedding to roster entry (progressive learning)",
    description="""
Add a confirmed face observation embedding to a roster entry for progressive learning.

This endpoint enables the recognition service to continuously improve match accuracy
as WordPress users confirm face identities. Each confirmation appends a new augmented
embedding to the roster entry, which is then incorporated into the weighted aggregate
embedding used for future recognition requests.

**Progressive Learning Workflow:**
1. WordPress user confirms a face match via the plugin UI
2. Plugin sends the face embedding + observation metadata to this endpoint
3. Backend validates embedding dimensions and deduplicates by observation_id
4. Augmented embedding is appended with quality tier (derived from confidence or explicit)
5. Aggregate embedding is recomputed with weighted averaging (high=1.0, medium=0.8, low=0.5)
6. FAISS index reload is scheduled (debounced, max every 30 seconds)
7. Future recognition requests benefit from the improved aggregate

**Idempotency:**
- Use `observation_id` to prevent duplicate embeddings (409 if already exists)
- Optional `idempotency_key` for safe retries (cached response returned within 10 minutes)

**Quality Tiers:**
- **high** (1.0 weight): confidence ≥ 0.85 or frontal/clear face conditions
- **medium** (0.8 weight): 0.65 ≤ confidence < 0.85 or partial occlusion
- **low** (0.5 weight): confidence < 0.65 or side profiles, poor lighting

**Performance:**
- Target latency: <100ms p95 (without FAISS reload)
- FAISS reload: <5 seconds for 1,000 roster entries
- Reload debounced to avoid thrashing on rapid confirmations
    """,
    responses={
        200: {
            "description": "Augmented embedding successfully added and aggregate updated",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "entry": {
                            "unique_id": "person-alice-2025",
                            "name": "Alice Johnson",
                            "display_name": "Alice J.",
                            "metadata": {
                                "augmented_embeddings": [
                                    {
                                        "observation_id": "obs-wp-12345",
                                        "attachment_id": 789,
                                        "confidence": 0.92,
                                        "quality_tier": "high",
                                        "source": "wordpress-confirmation",
                                        "bbox": {"x": 120, "y": 80, "width": 150, "height": 200}
                                    }
                                ]
                            },
                            "reference_count": 3,
                            "augmented_count": 1,
                            "embedding_count": 4,
                            "aggregate_embedding": [0.123, 0.456, "..."],
                            "aggregate_updated_at": "2025-11-01T21:30:00Z"
                        },
                        "index_reload_scheduled": True
                    }
                }
            }
        },
        404: {
            "description": "Roster entry not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Roster entry 'unknown-id' not found"}
                }
            }
        },
        409: {
            "description": "Duplicate observation_id (idempotent rejection)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Observation 'obs-wp-12345' already exists for this entry"
                    }
                }
            }
        },
        422: {
            "description": "Validation error (invalid embedding dimensions, missing required fields)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "loc": ["body", "embedding"],
                                "msg": "embedding must be exactly 512 dimensions",
                                "type": "value_error"
                            }
                        ]
                    }
                }
            }
        }
    },
    tags=["roster", "progressive-learning"]
)
async def augment_roster_entry(
    unique_id: str,
    payload: RosterAugmentPayload,
    background_tasks: BackgroundTasks,
    roster_service: RosterService = Depends(get_roster_service),
):
    response_body, _ = await _process_augmentation_request(
        unique_id=unique_id,
        payload=payload,
        background_tasks=background_tasks,
        roster_service=roster_service,
    )
    return response_body


@router.post("/roster/{unique_id}/embeddings")
async def append_reference_embedding(
    unique_id: str,
    payload: RosterReferencePayload,
    background_tasks: BackgroundTasks,
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

    _schedule_embedding_reload(background_tasks)
    _invalidate_etag_cache(model)

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
    response: Response,
    include_embeddings: bool = False,
    model: str = DEFAULT_MODEL,
    page: int = Query(1, ge=1, description="One-based page number for paginated results"),
    page_size: int = Query(50, ge=1, le=200, description="Number of entries per page"),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
    roster_service: RosterService = Depends(get_roster_service),
):
    """Return the current roster entries for the configured model.
    
    Supports ETag-based caching via If-None-Match header.
    Returns 304 Not Modified if content unchanged.
    """

    # Compute current ETag
    current_etag = _get_cached_etag(model, roster_service)
    response.headers["ETag"] = f'"{current_etag}"'
    
    # Check If-None-Match for conditional request
    if if_none_match:
        # Strip quotes if present
        client_etag = if_none_match.strip('"')
        if client_etag == current_etag:
            response.status_code = status.HTTP_304_NOT_MODIFIED
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": f'"{current_etag}"'})

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
        "etag": current_etag,
    }


@router.delete("/roster/{unique_id}")
async def delete_roster_entry(
    unique_id: str,
    background_tasks: BackgroundTasks,
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
    _schedule_embedding_reload(background_tasks)
    _invalidate_etag_cache(model)
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
