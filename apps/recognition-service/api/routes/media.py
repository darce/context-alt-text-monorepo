from fastapi import APIRouter, UploadFile, File, HTTPException
import uuid
from pathlib import Path
from typing import Tuple
from shared.config.settings import get_config

router = APIRouter(prefix="/media", tags=["media"])

async def _store_upload(file: UploadFile, media_dir: Path) -> Tuple[str, Path]:
    """
    Save an UploadFile to disk under media_dir, returning a (media_id, path).
    """
    media_id = str(uuid.uuid4())
    suffix = Path(file.filename).suffix
    media_dir.mkdir(parents=True, exist_ok=True)
    target_path = media_dir / f"{media_id}{suffix}"
    contents = await file.read()
    with open(target_path, "wb") as f:
        f.write(contents)
    return media_id, target_path

@router.post("/upload")
async def upload_media(file: UploadFile = File(...)):
    """
    Upload a media file and return a unique media_id and storage path.
    """
    try:
        # Get media storage configuration from canonical settings
        config = get_config()
        media_config = config['media_storage']['config']
        media_dir = Path(media_config['upload_directory'])
        
        # Validate file size and extension from configuration
        max_size_mb = media_config['max_file_size_mb']
        allowed_extensions = media_config['allowed_extensions']
        
        # Check file extension
        file_suffix = Path(file.filename).suffix.lower()
        if file_suffix not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"File type {file_suffix} not allowed. Allowed types: {allowed_extensions}"
            )
        
        # Check file size (approximate check using content-length header if available)
        if hasattr(file, 'size') and file.size and file.size > max_size_mb * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {max_size_mb}MB"
            )
        
        media_id, target_path = await _store_upload(file, media_dir)
        return {"media_id": media_id, "path": str(target_path)}
    except HTTPException:
        raise  # Re-raise HTTPExceptions as-is
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Media upload failed: {e}")
