"""
API Models (DTOs) for Roster Service

Request and response models for the FastAPI endpoints.
These models define the external API contract.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any, Union
from datetime import datetime


class AddRosterEntryRequest(BaseModel):
    """Request model for adding a roster entry."""
    name: str = Field(..., description="Identity name", min_length=1, max_length=255)
    embedding: List[float] = Field(..., description="Face embedding vector")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    image_path: Optional[str] = Field(None, description="Optional reference image path")
    
    @validator('name')
    def validate_name(cls, v):
        """Validate name field."""
        if not v.strip():
            raise ValueError("Name cannot be empty or whitespace only")
        return v.strip()
    
    @validator('embedding')
    def validate_embedding(cls, v):
        """Validate embedding field."""
        if not v:
            raise ValueError("Embedding cannot be empty")
        if not all(isinstance(x, (int, float)) for x in v):
            raise ValueError("Embedding must contain only numbers")
        return v


class BulkAddRosterRequest(BaseModel):
    """Request model for bulk adding roster entries."""
    entries: List[AddRosterEntryRequest] = Field(..., description="List of entries to add")
    
    @validator('entries')
    def validate_entries(cls, v):
        """Validate entries list."""
        if not v:
            raise ValueError("Entries list cannot be empty")
        if len(v) > 1000:  # Configurable limit
            raise ValueError("Too many entries in bulk request (max 1000)")
        return v


class UpdateRosterEntryRequest(BaseModel):
    """Request model for updating a roster entry."""
    embedding: Optional[List[float]] = Field(None, description="New embedding vector")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Metadata to update")
    image_path: Optional[str] = Field(None, description="New image path")
    
    @validator('embedding')
    def validate_embedding(cls, v):
        """Validate embedding field."""
        if v is not None:
            if not v:
                raise ValueError("Embedding cannot be empty")
            if not all(isinstance(x, (int, float)) for x in v):
                raise ValueError("Embedding must contain only numbers")
        return v


class RosterImageDTO(BaseModel):
    """DTO for roster image data."""
    embedding: List[float] = Field(..., description="Embedding vector")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Image metadata")
    image_path: Optional[str] = Field(None, description="Path to image file")


class RosterEntryDTO(BaseModel):
    """DTO for roster entry data."""
    name: str = Field(..., description="Identity name")
    display_name: str = Field(..., description="Display name")
    unique_id: str = Field(..., description="Unique identifier")
    reference_images: List[RosterImageDTO] = Field(default_factory=list, description="Reference images")
    aggregate_embedding: Optional[List[float]] = Field(None, description="Aggregated embedding")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Entry metadata")
    created_timestamp: Optional[str] = Field(None, description="Creation timestamp")
    updated_timestamp: Optional[str] = Field(None, description="Last update timestamp")
    image_count: int = Field(0, description="Number of reference images")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class RosterEntryResponse(BaseModel):
    """Response model for single roster entry operations."""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Operation result message")
    entry: Optional[RosterEntryDTO] = Field(None, description="Roster entry data")


class BulkAddResponse(BaseModel):
    """Response model for bulk add operations."""
    success: bool = Field(..., description="Overall operation success")
    message: str = Field(..., description="Operation summary message")
    successful_entries: List[str] = Field(..., description="Names of successfully added entries")
    failed_entries: List[Dict[str, str]] = Field(default_factory=list, description="Failed entries with reasons")
    stats: Dict[str, int] = Field(..., description="Operation statistics")


class RosterListResponse(BaseModel):
    """Response model for listing roster entries."""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Operation result message")
    entries: List[RosterEntryDTO] = Field(..., description="List of roster entries")
    count: int = Field(..., description="Number of entries")
    include_embeddings: bool = Field(..., description="Whether embeddings are included")


class RosterStatsResponse(BaseModel):
    """Response model for roster statistics."""
    success: bool = Field(..., description="Operation success status")
    model: str = Field(..., description="Model identifier")
    entry_count: int = Field(..., description="Number of entries")
    storage_info: Dict[str, Any] = Field(..., description="Storage information")


class DeleteEntryResponse(BaseModel):
    """Response model for delete operations."""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Operation result message")
    deleted_id: Optional[str] = Field(None, description="ID of deleted entry")


class ErrorResponse(BaseModel):
    """Error response model."""
    success: bool = Field(False, description="Always false for errors")
    error: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")


class HealthCheckResponse(BaseModel):
    """Health check response model."""
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="Service version")
    timestamp: str = Field(..., description="Check timestamp")
    models: Dict[str, Dict[str, Any]] = Field(..., description="Model status information")


# Union types for flexible responses
RosterResponse = Union[
    RosterEntryResponse,
    BulkAddResponse,
    RosterListResponse,
    RosterStatsResponse,
    DeleteEntryResponse,
    ErrorResponse
]
