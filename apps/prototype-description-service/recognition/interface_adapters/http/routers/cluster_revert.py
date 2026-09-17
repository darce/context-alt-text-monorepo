"""LIFO receipt revert route: POST /recognition/clusters/{id}/revert-merge."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from db.models.identity import ReceiptExpiredError, ReceiptNotTopError, ReceiptStackUnavailableError
from recognition.application.events.broadcaster import get_event_broadcaster
from recognition.application.orchestration.cluster_merge import (
    MergeReceiptNotFoundError,
    MergeReceiptStaleError,
    revert_merge,
)
from recognition.interface_adapters.http.deps import (
    get_cluster_service_builder,
    get_session,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.tenant import get_tenant_id

router = APIRouter(tags=["clusters"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])

_PROBLEM_JSON = "application/problem+json"
_PROBLEM_BASE = "https://context-alt-text.dev/problems"


class RevertMergeRequest(BaseModel):
    receipt_id: UUID


class RevertMergeResponse(BaseModel):
    source_cluster_id: UUID = Field(description="Restored source cluster id")


def _problem(*, code: str, title: str, type_slug: str) -> JSONResponse:
    """RFC 7807 problem details with a stable `code` (API-05)."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        media_type=_PROBLEM_JSON,
        content={
            "type": f"{_PROBLEM_BASE}/{type_slug}",
            "title": title,
            "status": status.HTTP_409_CONFLICT,
            "code": code,
        },
    )


@router.post("/clusters/{cluster_id}/revert-merge", response_model=RevertMergeResponse)
async def revert_merge_cluster(
    cluster_id: UUID,
    body: RevertMergeRequest,
    tenant_id: str = Depends(get_tenant_id),
    _auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> RevertMergeResponse | JSONResponse:
    """Revert the named receipt on the path survivor cluster (CONTRACTSROSTER-R-03)."""
    auth_tenant_id = getattr(_auth, "tenant_claim", None)
    service_tenant_id = tenant_id
    if auth_tenant_id:
        if str(auth_tenant_id).lower() != str(tenant_id).lower():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
        service_tenant_id = str(auth_tenant_id)

    cluster_service = await cluster_service_builder(service_tenant_id)
    try:
        revert_result = await revert_merge(
            tenant_id=service_tenant_id,
            receipt_id=str(body.receipt_id),
            path_cluster_id=str(cluster_id),
            assignment_writer=cluster_service.assignment_writer,
            session=session,
            merge_suggestion_service=cluster_service.merge_suggestion_service,
            return_event_payload=True,
        )
    except MergeReceiptNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from exc
    except MergeReceiptStaleError:
        return _problem(
            code="merge_receipt_stale",
            title="Merge receipt is stale",
            type_slug="merge-receipt-stale",
        )
    except ReceiptNotTopError:
        return _problem(
            code="receipt_not_top",
            title="Receipt is not the top unreverted merge",
            type_slug="receipt-not-top",
        )
    except ReceiptExpiredError:
        return _problem(
            code="receipt_expired",
            title="Merge receipt has expired",
            type_slug="receipt-expired",
        )
    except ReceiptStackUnavailableError:
        return _problem(
            code="receipt_stack_unavailable",
            title="Merge receipt stack is not loaded",
            type_slug="receipt-stack-unavailable",
        )

    if isinstance(revert_result, tuple):
        restored, event_payload = revert_result
    else:
        restored = revert_result
        event_payload = {
            "source_cluster_id": restored.id,
            "survivor_cluster_id": str(cluster_id),
            "receipt_id": str(body.receipt_id),
            "moved_count": 0,
        }
    if restored.id is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="internal server error")

    await session.flush()
    await session.commit()
    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "cluster_merge_reverted",
        event_payload,
        tenant_id=service_tenant_id,
    )
    return RevertMergeResponse(source_cluster_id=UUID(str(restored.id)))
