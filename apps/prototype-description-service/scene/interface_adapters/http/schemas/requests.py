"""Request schema for POST /scene/describe/multipart (the JSON ``request`` part)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DescribeImageEnvelope(BaseModel):
    """JSON envelope accompanying the single ``image_<media_id>`` multipart part.

    ``media_id`` must equal the ``image_<media_id>`` part suffix (validated at the
    route, 422 on mismatch). ``context`` is inert WordPress transport in Phase 1 —
    the seeded adapter is not scored on consuming it.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(description="Tenant UUID; canonicalized to lowercase.")
    media_id: int = Field(gt=0, description="WordPress attachment id; must equal the image_<media_id> part suffix.")
    context: dict[str, Any] | None = Field(
        default=None,
        description="Inert WP context (Phase 1): title/caption/description/filename.",
    )

    @field_validator("tenant_id")
    @classmethod
    def _canonical_uuid(cls, value: str) -> str:
        # uuid.UUID() raises ValueError on malformed input -> pydantic ValidationError.
        return str(uuid.UUID(value))
