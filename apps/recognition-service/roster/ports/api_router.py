"""
FastAPI Router for Roster Service

RESTful API endpoints for roster management operations.
Provides compatibility with existing app.py integration.
"""

import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Path, Query, Depends, status
from fastapi.responses import JSONResponse

from ..domain import RosterService
from .models import (
    AddRosterEntryRequest, BulkAddRosterRequest, UpdateRosterEntryRequest,
    RosterEntryResponse, BulkAddResponse, RosterListResponse, 
    RosterStatsResponse, DeleteEntryResponse, HealthCheckResponse,
    ErrorResponse, RosterEntryDTO
)
from .dependencies import get_roster_service
from ..config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v0/roster", tags=["roster"])


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """
    Health check endpoint for service monitoring.
    """
    try:
        config = get_config()
        service_config = config.get_service_config()
        
        # Check status of each supported model
        models_status = {}
        for model in config.get_supported_models():
            models_status[model] = {
                "supported": True,
                "embedding_dimension": config.get_embedding_dimension(model)
            }
        
        return HealthCheckResponse(
            status="healthy",
            version=service_config.get("version", "1.0.0"),
            timestamp=datetime.now().isoformat(),
            models=models_status
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unhealthy"
        )


@router.post("/{model}/upsert", response_model=RosterEntryResponse)
async def upsert_roster_entry(
    model: str = Path(..., description="Model identifier (e.g., adaface_ir101)"),
    request: AddRosterEntryRequest = ...,
    roster_service: RosterService = Depends(get_roster_service)
):
    """
    Add or update a roster entry for a specific model.
    
    This endpoint provides compatibility with the existing app.py integration
    while supporting the new roster service architecture.
    """
    try:
        # Validate model
        config = get_config()
        supported_models = config.get_supported_models()
        if model not in supported_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported model: {model}. Supported models: {', '.join(supported_models)}"
            )
        
        # Add the entry
        result = roster_service.add_entry(
            name=request.name,
            embedding=request.embedding,
            model=model,
            metadata=request.metadata,
            image_path=request.image_path
        )
        
        if result:
            # Convert to DTO
            entry_dto = RosterEntryDTO(
                name=result.name,
                display_name=result.display_name,
                unique_id=result.unique_id,
                reference_images=[],  # Exclude embeddings by default for performance
                aggregate_embedding=result.aggregate_embedding,
                metadata=result.metadata,
                created_timestamp=result.created_timestamp,
                updated_timestamp=result.updated_timestamp,
                image_count=result.image_count
            )
            
            return RosterEntryResponse(
                success=True,
                message=f"Successfully added/updated entry for {request.name}",
                entry=entry_dto
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to add roster entry"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in upsert_roster_entry: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/{model}/bulk", response_model=BulkAddResponse)
async def bulk_add_roster_entries(
    model: str = Path(..., description="Model identifier"),
    request: BulkAddRosterRequest = ...,
    roster_service: RosterService = Depends(get_roster_service)
):
    """
    Add multiple roster entries in bulk for a specific model.
    """
    try:
        # Validate model
        config = get_config()
        supported_models = config.get_supported_models()
        if model not in supported_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported model: {model}"
            )
        
        # Convert requests to entry data
        entries_data = []
        for entry_req in request.entries:
            entry_data = {
                "name": entry_req.name,
                "embedding": entry_req.embedding,
                "metadata": entry_req.metadata,
                "image_path": entry_req.image_path
            }
            entries_data.append(entry_data)
        
        # Perform bulk add
        successful_names = roster_service.add_entries_bulk(entries_data, model)
        failed_names = [req.name for req in request.entries if req.name not in successful_names]
        
        # Build response
        failed_entries = [
            {"name": name, "reason": "Failed to add entry"}
            for name in failed_names
        ]
        
        stats = {
            "total_requested": len(request.entries),
            "successful": len(successful_names),
            "failed": len(failed_names)
        }
        
        success = len(successful_names) > 0
        message = f"Processed {stats['total_requested']} entries: {stats['successful']} successful, {stats['failed']} failed"
        
        return BulkAddResponse(
            success=success,
            message=message,
            successful_entries=successful_names,
            failed_entries=failed_entries,
            stats=stats
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk_add_roster_entries: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{model}", response_model=RosterListResponse)
async def get_roster_entries(
    model: str = Path(..., description="Model identifier"),
    include_embeddings: bool = Query(False, description="Include embedding vectors in response"),
    roster_service: RosterService = Depends(get_roster_service)
):
    """
    Get all roster entries for a specific model.
    """
    try:
        # Validate model
        config = get_config()
        supported_models = config.get_supported_models()
        if model not in supported_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported model: {model}"
            )
        
        # Get entries
        entries = roster_service.get_entries(model)
        
        # Convert to DTOs
        entry_dtos = []
        for entry in entries:
            entry_dto = RosterEntryDTO(
                name=entry.name,
                display_name=entry.display_name,
                unique_id=entry.unique_id,
                reference_images=[],  # Skip reference images for performance
                aggregate_embedding=entry.aggregate_embedding if include_embeddings else None,
                metadata=entry.metadata,
                created_timestamp=entry.created_timestamp,
                updated_timestamp=entry.updated_timestamp,
                image_count=entry.image_count
            )
            entry_dtos.append(entry_dto)
        
        return RosterListResponse(
            success=True,
            message=f"Retrieved {len(entry_dtos)} entries for model {model}",
            entries=entry_dtos,
            count=len(entry_dtos),
            include_embeddings=include_embeddings
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_roster_entries: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{model}/stats", response_model=RosterStatsResponse)
async def get_roster_stats(
    model: str = Path(..., description="Model identifier"),
    roster_service: RosterService = Depends(get_roster_service)
):
    """
    Get roster statistics and storage information.
    """
    try:
        # Validate model
        config = get_config()
        supported_models = config.get_supported_models()
        if model not in supported_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported model: {model}"
            )
        
        # Get stats
        entry_count = roster_service.get_entry_count(model)
        storage_info = roster_service.get_storage_info(model)
        
        return RosterStatsResponse(
            success=True,
            model=model,
            entry_count=entry_count,
            storage_info=storage_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_roster_stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{model}/{unique_id}", response_model=RosterEntryResponse)
async def get_roster_entry(
    model: str = Path(..., description="Model identifier"),
    unique_id: str = Path(..., description="Unique entry identifier"),
    include_embeddings: bool = Query(False, description="Include embedding vectors"),
    roster_service: RosterService = Depends(get_roster_service)
):
    """
    Get a specific roster entry by unique ID.
    """
    try:
        # Validate model
        config = get_config()
        supported_models = config.get_supported_models()
        if model not in supported_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported model: {model}"
            )
        
        # Get entry
        entry = roster_service.get_entry(unique_id, model)
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entry not found: {unique_id}"
            )
        
        # Convert to DTO
        entry_dto = RosterEntryDTO(
            name=entry.name,
            display_name=entry.display_name,
            unique_id=entry.unique_id,
            reference_images=[],  # Skip for performance
            aggregate_embedding=entry.aggregate_embedding if include_embeddings else None,
            metadata=entry.metadata,
            created_timestamp=entry.created_timestamp,
            updated_timestamp=entry.updated_timestamp,
            image_count=entry.image_count
        )
        
        return RosterEntryResponse(
            success=True,
            message=f"Retrieved entry: {entry.name}",
            entry=entry_dto
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_roster_entry: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/{model}/{unique_id}", response_model=RosterEntryResponse)
async def update_roster_entry(
    model: str = Path(..., description="Model identifier"),
    unique_id: str = Path(..., description="Unique entry identifier"),
    request: UpdateRosterEntryRequest = ...,
    roster_service: RosterService = Depends(get_roster_service)
):
    """
    Update an existing roster entry.
    """
    try:
        # Validate model
        config = get_config()
        supported_models = config.get_supported_models()
        if model not in supported_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported model: {model}"
            )
        
        # Update entry
        success = roster_service.update_entry(
            unique_id=unique_id,
            model=model,
            embedding=request.embedding,
            metadata=request.metadata,
            image_path=request.image_path
        )
        
        if success:
            # Get updated entry
            updated_entry = roster_service.get_entry(unique_id, model)
            if updated_entry:
                entry_dto = RosterEntryDTO(
                    name=updated_entry.name,
                    display_name=updated_entry.display_name,
                    unique_id=updated_entry.unique_id,
                    reference_images=[],
                    aggregate_embedding=updated_entry.aggregate_embedding,
                    metadata=updated_entry.metadata,
                    created_timestamp=updated_entry.created_timestamp,
                    updated_timestamp=updated_entry.updated_timestamp,
                    image_count=updated_entry.image_count
                )
                
                return RosterEntryResponse(
                    success=True,
                    message=f"Successfully updated entry: {unique_id}",
                    entry=entry_dto
                )
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entry not found or update failed: {unique_id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_roster_entry: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/{model}/{unique_id}", response_model=DeleteEntryResponse)
async def delete_roster_entry(
    model: str = Path(..., description="Model identifier"),
    unique_id: str = Path(..., description="Unique entry identifier"),
    roster_service: RosterService = Depends(get_roster_service)
):
    """
    Delete a roster entry by unique ID.
    
    Provides compatibility with existing /roster/{id} DELETE endpoint.
    """
    try:
        # Validate model
        config = get_config()
        supported_models = config.get_supported_models()
        if model not in supported_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported model: {model}"
            )
        
        # Delete entry
        success = roster_service.delete_entry(unique_id, model)
        
        if success:
            return DeleteEntryResponse(
                success=True,
                message=f"Successfully deleted entry: {unique_id}",
                deleted_id=unique_id
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entry not found: {unique_id}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_roster_entry: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/{model}/clear")
async def clear_roster(
    model: str = Path(..., description="Model identifier"),
    roster_service: RosterService = Depends(get_roster_service)
):
    """
    Clear all entries from a roster (admin operation).
    """
    try:
        # Validate model
        config = get_config()
        supported_models = config.get_supported_models()
        if model not in supported_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported model: {model}"
            )
        
        # Clear roster
        success = roster_service.clear_roster(model)
        
        if success:
            return JSONResponse(
                content={
                    "success": True,
                    "message": f"Successfully cleared roster for model: {model}"
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to clear roster"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in clear_roster: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


