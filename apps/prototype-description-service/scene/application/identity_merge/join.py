"""Read-only identity join: confirmed, human-labeled faces for one media item.

Filter semantics mirror
``recognition/infrastructure/repositories/cluster_repository.py::get_confirmed_labeled``
(placeholder ``cluster-%`` labels are machine names, not human labels) plus the
dismissed-cluster and media scoping filters this merge layer requires.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.identity import (
    IdentityCluster,
    IdentityMember,
    IdentityNameSuppression,
    MediaIdentity,
)
from scene.application.identity_merge.merge import ConfirmedFace, normalize_bbox


async def load_confirmed_faces(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    media_id: int,
    image_width: float,
    image_height: float,
) -> list[ConfirmedFace]:
    """Join MediaIdentity→IdentityMember→IdentityCluster for nameable faces.

    Five filters: ``user_confirmed`` true, ``label`` present, no ``cluster-%``
    placeholder label, cluster not dismissed, and the requested ``media_id``
    (tenant-scoped). Boxes are normalized to [0,1] fractions of the original
    W×H so they share the phrase-box frame.
    """
    # Column projection, not entity load: IdentityCluster eagerly joins the
    # centroid materialized view (lazy="joined"), which this read never needs.
    stmt = (
        select(
            MediaIdentity.id,
            MediaIdentity.confidence,
            MediaIdentity.bbox_x,
            MediaIdentity.bbox_y,
            MediaIdentity.bbox_width,
            MediaIdentity.bbox_height,
            IdentityCluster.id.label("cluster_id"),
            IdentityCluster.roster_id,
            IdentityCluster.label,
        )
        .join(IdentityMember, IdentityMember.identity_id == MediaIdentity.id)
        .join(IdentityCluster, IdentityCluster.id == IdentityMember.cluster_id)
        .where(MediaIdentity.tenant_id == tenant_id)
        .where(MediaIdentity.media_id == media_id)
        .where(MediaIdentity.disposed_at.is_(None))
        # Defense-in-depth: tenant predicate on every joined table, so a
        # corrupted cross-tenant membership row can never leak a name.
        .where(IdentityMember.tenant_id == tenant_id)
        .where(IdentityCluster.tenant_id == tenant_id)
        .where(IdentityCluster.user_confirmed.is_(True))
        .where(IdentityCluster.label.is_not(None))
        .where(~IdentityCluster.label.startswith("cluster-"))
        .where(IdentityCluster.dismissed_at.is_(None))
        .where(IdentityCluster.disposed_at.is_(None))
        .order_by(MediaIdentity.bbox_x)
    )
    rows = (await session.execute(stmt)).all()
    faces: list[ConfirmedFace] = []
    for row in rows:
        label = (row.label or "").strip()
        # Python-side re-check: whitespace-only labels and case-variant
        # placeholders ("CLUSTER-3") pass the SQL filters on some dialects.
        if not label or label.lower().startswith("cluster-"):
            continue
        if row.bbox_width <= 0 or row.bbox_height <= 0:
            continue  # degenerate detection box carries no containment signal
        faces.append(
            ConfirmedFace(
                identity_id=row.id,
                cluster_id=row.cluster_id,
                roster_id=row.roster_id,
                label=label,
                detection_confidence=row.confidence,
                box=normalize_bbox(
                    x=row.bbox_x,
                    y=row.bbox_y,
                    width=row.bbox_width,
                    height=row.bbox_height,
                    image_width=image_width,
                    image_height=image_height,
                ),
            )
        )
    return faces


async def load_suppressed_roster_ids(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> frozenset[uuid.UUID]:
    """Per-roster_id do-not-name set for the tenant's naming policy."""
    stmt = select(IdentityNameSuppression.roster_id).where(IdentityNameSuppression.tenant_id == tenant_id)
    return frozenset((await session.execute(stmt)).scalars().all())
