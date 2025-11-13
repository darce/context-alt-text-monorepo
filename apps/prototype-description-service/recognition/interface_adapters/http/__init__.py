"""HTTP adapters for the recognition service."""

from fastapi import APIRouter

from recognition.interface_adapters.http.recognition_router import router as recognition_router
from recognition.interface_adapters.http.health_router import router as health_router

router = APIRouter()
router.include_router(health_router)
router.include_router(recognition_router)
