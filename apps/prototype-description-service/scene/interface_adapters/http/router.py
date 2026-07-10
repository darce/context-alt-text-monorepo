"""Scene HTTP router — composes the description routes (E19-1 S5).

Mounted at ``/scene`` by api/main.py, mirroring the recognition router
composition. Kept separate from the recognition router so the describe surface
never extends the wire-locked /recognition/analyze contract.
"""

from __future__ import annotations

from fastapi import APIRouter

from scene.interface_adapters.http.routers.describe import router as describe_router
from scene.interface_adapters.http.routers.describe_run import router as describe_run_router

router = APIRouter()
router.include_router(describe_router)
router.include_router(describe_run_router)
