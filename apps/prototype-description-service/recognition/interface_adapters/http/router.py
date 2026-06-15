"""
Aggregates the recognition sub-routers into a single APIRouter mounted by
api/main.py under /recognition.
"""

from __future__ import annotations

from fastapi import APIRouter

from recognition.interface_adapters.http.routers import (
    analyze,
    analyze_multipart,
    blobs,
    clusters_admission,
    clusters_maintenance,
    clusters_snapshot,
    clusters_topology,
    diagnostics,
    events,
    media,
    retention,
    suggestions,
    tenant,
)

router = APIRouter(tags=["recognition"])


# Mount sub-routers
router.include_router(analyze.router)
router.include_router(analyze_multipart.router)
router.include_router(blobs.router)
# Cluster concern routers (split from the former clusters.py god-router, Slice 6)
router.include_router(clusters_admission.router)
router.include_router(clusters_snapshot.router)
router.include_router(clusters_topology.router)
router.include_router(clusters_maintenance.router)
router.include_router(events.router)
router.include_router(suggestions.router)
router.include_router(diagnostics.router)
router.include_router(media.router)
router.include_router(retention.router)
router.include_router(tenant.router)

# Exception handlers must be registered on the FastAPI app, not the router.
# (See api/main.py where register_exception_handlers is called on the app.)
