"""
Media identity lookup routes for WordPress integration.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from recognition.interface_adapters.http.dependencies import get_media_identity_service, require_auth
from recognition.interface_adapters.http.deps.tenant import get_tenant_id

router = APIRouter(tags=["media"], dependencies=[Depends(require_auth)])


@router.get("/media/identities")
async def list_media_identities(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
    media_ids: list[int] | None = Query(default=None, alias="media_ids"),
    include_debug: bool | None = Query(default=None),
    service=Depends(get_media_identity_service),
):
    """Return detected identities grouped by media_id."""
    ids: list[int] = []
    if media_ids:
        ids = list(media_ids)
    elif request:
        qp = request.query_params
        ids = [int(v) for v in qp.getlist("media_ids[]") if v.isdigit()]
        if not ids:
            ids = [int(v) for k, v in qp.multi_items() if k.startswith("media_ids[") and v.isdigit()]
    if service is None or not ids:
        return []
    return await service.list_by_media_ids(tenant_id, ids, include_debug=bool(include_debug))
