"""
Minimal FastAPI router for the recognition service (stub endpoints).
"""

from __future__ import annotations

from fastapi import APIRouter

from recognition.interface_adapters.http.routers import analyze, clusters, diagnostics, media, suggestions, training

router = APIRouter(tags=["recognition"])


@router.get("/health", summary="Recognition service health")
async def health() -> dict[str, str]:
    """Return a static health response."""
    return {"service": "recognition", "status": "ok"}


# Mount sub-routers
router.include_router(analyze.router)
router.include_router(clusters.router)
router.include_router(suggestions.router)
router.include_router(diagnostics.router)
router.include_router(media.router)
router.include_router(training.router)

# Exception handlers must be registered on the FastAPI app, not the router.
# (See api/main.py where register_exception_handlers is called on the app.)
