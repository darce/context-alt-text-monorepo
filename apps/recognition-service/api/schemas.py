from __future__ import annotations

import base64
from io import BytesIO
from typing import List, Optional

from PIL import Image
from pydantic import BaseModel, Field, HttpUrl, root_validator, validator


class AnalyzeSceneImage(BaseModel):
    filename: Optional[str] = None
    image_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded image data (without data URI prefix).",
    )
    image_url: Optional[HttpUrl] = Field(
        default=None,
        description="Optional URL to fetch the image from.",
    )

    @root_validator
    def validate_source(cls, values: dict) -> dict:
        if not values.get("image_base64") and not values.get("image_url"):
            raise ValueError("image_base64 or image_url must be provided")
        return values

    def load_image(self) -> Image.Image:
        if self.image_base64:
            data = base64.b64decode(self.image_base64)
            return Image.open(BytesIO(data)).convert("RGB")
        raise NotImplementedError("image_url loading not implemented yet")


class AnalyzeSceneRequest(BaseModel):
    images: List[AnalyzeSceneImage]
    use_roster: bool = True
    threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional similarity threshold override.",
    )


class EmbeddingsRequest(BaseModel):
    image: AnalyzeSceneImage
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
