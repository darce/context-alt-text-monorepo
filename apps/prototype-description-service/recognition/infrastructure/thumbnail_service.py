"""Helpers for persisting identity thumbnails."""

from __future__ import annotations

import uuid
import os
from pathlib import Path
from typing import Tuple

from PIL import Image

from recognition.config import get_settings


class ThumbnailService:
    """Generate and persist square thumbnails for detected identities."""

    def __init__(self) -> None:
        settings = get_settings().thumbnail
        storage_dir = os.getenv("THUMBNAIL_DIR") or settings.storage_dir
        base_url = os.getenv("THUMBNAIL_BASE_URL") or settings.base_url
        self._storage_dir = Path(storage_dir)
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._size = settings.size
        self._padding_ratio = settings.padding_ratio
        self._quality = settings.quality
        self._enabled = bool(self._base_url)
        if self._enabled:
            self._storage_dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def build_url(self, identity_id: uuid.UUID) -> str:
        filename = f"{identity_id}.jpg"
        if self._base_url.startswith("http://") or self._base_url.startswith("https://"):
            return f"{self._base_url}/{filename}"
        return f"{self._base_url}/{filename}"

    def _destination_path(self, identity_id: uuid.UUID) -> Path:
        return self._storage_dir / f"{identity_id}.jpg"

    def save(self, *, image: Image.Image, bbox: Tuple[float, float, float, float], identity_id: uuid.UUID) -> str | None:
        if not self.enabled:
            return None

        square = self._crop_square(image, bbox)
        thumbnail = square.resize((self._size, self._size), Image.LANCZOS).convert("RGB")

        dest_path = self._destination_path(identity_id)
        tmp_path = dest_path.with_suffix(".tmp")
        thumbnail.save(tmp_path, format="JPEG", quality=self._quality)
        tmp_path.replace(dest_path)
        return self.build_url(identity_id)

    def _crop_square(self, image: Image.Image, bbox: Tuple[float, float, float, float]) -> Image.Image:
        x, y, width, height = bbox
        padding_x = width * self._padding_ratio
        padding_y = height * self._padding_ratio

        left = max(0.0, x - padding_x)
        top = max(0.0, y - padding_y)
        right = min(image.width, x + width + padding_x)
        bottom = min(image.height, y + height + padding_y)

        center_x = (left + right) / 2
        center_y = (top + bottom) / 2
        half_size = max(right - left, bottom - top) / 2

        left = max(0.0, center_x - half_size)
        top = max(0.0, center_y - half_size)
        right = min(image.width, center_x + half_size)
        bottom = min(image.height, center_y + half_size)

        # Adjust if crop exceeds image bounds
        if right - left != bottom - top:
            size = max(right - left, bottom - top)
            if right - left < size:
                deficit = size - (right - left)
                left = max(0.0, left - deficit / 2)
                right = min(image.width, left + size)
            if bottom - top < size:
                deficit = size - (bottom - top)
                top = max(0.0, top - deficit / 2)
                bottom = min(image.height, top + size)

        box = (int(round(left)), int(round(top)), int(round(right)), int(round(bottom)))
        return image.crop(box)
