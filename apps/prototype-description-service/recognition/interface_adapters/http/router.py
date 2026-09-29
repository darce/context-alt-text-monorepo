"""
Aggregates the recognition sub-routers into a single APIRouter mounted by
api/main.py under /recognition.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from recognition.interface_adapters.http.deps.portal_composition import admit_usage
from recognition.interface_adapters.http.routers import (
    analyze,
    analyze_multipart,
    blobs,
    cluster_merge_candidates,
    cluster_revert,
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
_USAGE_ADMISSION_ROUTES = {
    ("/analyze", frozenset({"POST"})),
    ("/analyze/multipart", frozenset({"POST"})),
}
for child_router in (analyze.router, analyze_multipart.router):
    for route in child_router.routes:
        if not isinstance(route, APIRoute):
            continue
        if (route.path, frozenset(route.methods or ())) not in _USAGE_ADMISSION_ROUTES:
            continue
        if not any(getattr(dependency, "dependency", None) is admit_usage for dependency in route.dependencies):
            route.dependencies.append(Depends(admit_usage))

router.include_router(analyze.router)
router.include_router(analyze_multipart.router)
router.include_router(blobs.router)
# Cluster concern routers (split from the former clusters.py god-router, Slice 6)
router.include_router(clusters_admission.router)
router.include_router(clusters_snapshot.router)
router.include_router(clusters_topology.router)
router.include_router(clusters_maintenance.router)
router.include_router(cluster_merge_candidates.router)
router.include_router(cluster_revert.router)
router.include_router(events.router)
router.include_router(suggestions.router)
router.include_router(diagnostics.router)
router.include_router(media.router)
router.include_router(retention.router)
router.include_router(tenant.router)

# Exception handlers must be registered on the FastAPI app, not the router.
# (See api/main.py where register_exception_handlers is called on the app.)
