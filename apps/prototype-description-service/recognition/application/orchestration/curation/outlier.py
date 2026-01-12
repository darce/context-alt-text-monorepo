"""Outlier cluster helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityMember as MemberModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.domain.cluster import IdentityCluster
from recognition.shared.tenant import coerce_tenant_uuid


def is_outlier_cluster(cluster: object) -> bool:
    """Return True if the cluster is considered an outlier/noise grouping."""
    label = (getattr(cluster, "label", "") or "").lower()
    algorithm = (getattr(cluster, "clustering_algorithm", "") or "").lower()
    return label in {"outlier", "-1", "noise"} or algorithm in {"outlier", "noise"}


async def build_outlier_cluster(session: AsyncSession | None, tenant_id: str) -> IdentityCluster | None:
    """Construct a pseudo-cluster representing unassigned identities for the tenant."""
    if session is None:
        return None

    try:
        tenant_uuid = coerce_tenant_uuid(tenant_id)
    except ValueError:
        return None

    stmt: Select[tuple[MediaIdentityModel]] = (
        select(MediaIdentityModel)
        .where(MediaIdentityModel.tenant_id == tenant_uuid)
        .where(~exists(select(MemberModel.id).where(MemberModel.identity_id == MediaIdentityModel.id)))
    )
    result = await session.execute(stmt)
    unclustered = result.scalars().all()
    if not unclustered:
        return None

    return IdentityCluster(
        id=f"outliers-{tenant_id}",
        tenant_id=str(tenant_id),
        label="outliers",
        is_labeled=False,
        identity_count=len(unclustered),
        created_at=datetime.now(tz=UTC),
        clustering_algorithm="outlier",
        user_confirmed=False,
        representatives=[],
    )
