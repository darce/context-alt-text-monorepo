"""GET /recognition/clusters/{cluster_id}/merge-candidates (GPUFLOW-2 B6)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from recognition.application.suggestions.merge_candidates import list_merge_candidates
from recognition.interface_adapters.http.deps import (
    get_cluster_repository,
    get_merge_suggestion_repository,
    require_auth,
)
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.validation import validate_entity_id
from recognition.interface_adapters.http.validation_utils import validate_uuid_format

router = APIRouter(tags=["suggestions"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])


class ClusterMergeCandidateResponse(BaseModel):
    """One other cluster ranked against the probe. extra=forbid matches the schema."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    name: str
    similarity: float
    band: Literal["strong", "possible", "none"]

    @field_validator("cluster_id")
    @classmethod
    def validate_candidate_cluster_id(cls, value: str) -> str:
        return validate_uuid_format(value)


class ClusterMergeCandidatesResponse(BaseModel):
    """Typed payload for GET /recognition/clusters/{cluster_id}/merge-candidates."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    candidates: list[ClusterMergeCandidateResponse] = Field(default_factory=list)

    @field_validator("cluster_id")
    @classmethod
    def validate_probe_cluster_id(cls, value: str) -> str:
        return validate_uuid_format(value)


@router.get("/clusters/{cluster_id}/merge-candidates", response_model=ClusterMergeCandidatesResponse)
async def get_cluster_merge_candidates(
    cluster_id: str,
    _tenant_id: str = Depends(get_tenant_id),
    cluster_repo=Depends(get_cluster_repository),
    merge_repo=Depends(get_merge_suggestion_repository),
) -> ClusterMergeCandidatesResponse:
    """Rank other clusters by centroid cosine merged with fresh pending suggestions.

    Band cuts are applied in list_merge_candidates from ClusteringSettings; this
    route does not contain numeric thresholds (API-05 / rg-015).
    """
    validate_entity_id(cluster_id, field_name="cluster_id")
    try:
        result = await list_merge_candidates(
            _tenant_id,
            cluster_id,
            cluster_repository=cluster_repo,
            merge_suggestion_repository=merge_repo,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found") from None
    return ClusterMergeCandidatesResponse(
        cluster_id=result.cluster_id,
        candidates=[
            ClusterMergeCandidateResponse(
                cluster_id=row.cluster_id,
                name=row.name,
                similarity=row.similarity,
                band=row.band.value,
            )
            for row in result.candidates
        ],
    )
