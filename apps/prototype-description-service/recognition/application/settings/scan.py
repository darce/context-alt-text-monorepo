"""
Settings for the Scan module.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScanSettings(BaseModel):
    """Configuration for scan queue processing."""

    model_config = ConfigDict(frozen=True)

    enqueue_chunk_size: int = Field(
        default=500,
        description="Number of items to enqueue per batch operation.",
    )
