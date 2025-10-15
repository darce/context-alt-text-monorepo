from __future__ import annotations

import base64
import binascii
import os
from io import BytesIO
from typing import List, Optional
from urllib.parse import urlparse, urlunparse

import requests
from PIL import Image, ImageFile, UnidentifiedImageError
from pydantic import AnyHttpUrl, BaseModel, Field, root_validator

# Allow loading small or truncated images from fixtures without raising errors
ImageFile.LOAD_TRUNCATED_IMAGES = True


class AnalyzeSceneImage(BaseModel):
    filename: Optional[str] = None
    image_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded image data (without data URI prefix).",
    )
    image_url: Optional[AnyHttpUrl] = Field(
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
            try:
                data = base64.b64decode(self.image_base64)
            except (binascii.Error, ValueError) as exc:
                raise ValueError(f"Invalid base64 payload: {exc}") from exc

            try:
                image = Image.open(BytesIO(data))
                image.load()
            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError(f"Invalid image payload: {exc}") from exc

            return image.convert("RGB")
        if self.image_url:
            url = str(self.image_url)

            override_base_url = os.getenv("CAT_MEDIA_BASE_URL")
            if override_base_url:
                parsed_override = urlparse(override_base_url)
                parsed_original = urlparse(url)

                target_scheme = parsed_override.scheme or parsed_original.scheme
                target_netloc = parsed_override.netloc or parsed_original.netloc

                target_path = parsed_original.path
                if parsed_override.path and parsed_override.path != "/":
                    target_path = parsed_override.path.rstrip("/") + parsed_original.path

                url = urlunparse(
                    (
                        target_scheme,
                        target_netloc,
                        target_path,
                        parsed_original.params,
                        parsed_original.query,
                        parsed_original.fragment,
                    )
                )

            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
            except requests.RequestException as exc:
                raise ValueError(f"Failed to fetch image from {url}: {exc}") from exc

            try:
                image = Image.open(BytesIO(response.content))
                image.load()
            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError(f"Invalid image payload from URL {url}: {exc}") from exc

            return image.convert("RGB")

        raise NotImplementedError("image_url loading requires either a base64 payload or image_url")


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
