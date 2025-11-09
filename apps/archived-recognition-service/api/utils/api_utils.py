"""
Shared API helper functions for FastAPI routes.
"""
import io
import json
from typing import Optional, Dict, Any

from fastapi import UploadFile, HTTPException
from PIL import Image

async def read_pil_image(file: UploadFile) -> Image.Image:
    """Read an UploadFile into a PIL RGB image."""
    data = await file.read()
    return Image.open(io.BytesIO(data)).convert("RGB")


def parse_metadata(metadata: Optional[str]) -> Dict[str, Any]:
    """Parse JSON metadata or return empty dict; raise HTTPException on failure."""
    if not metadata:
        return {}
    try:
        return json.loads(metadata)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid metadata JSON format")
