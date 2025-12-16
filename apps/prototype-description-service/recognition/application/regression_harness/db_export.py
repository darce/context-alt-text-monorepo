"""
Database export helpers for the regression harness.

These functions extract stable identity locators and their canonical/predicted assignments from the database so that
evaluation can be done without relying on unstable UUID primary keys.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast
from uuid import UUID

from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityMember, MediaIdentity
from recognition.domain.locator import IdentityLocator


def _parse_uuid(value: str, *, field_name: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc


async def fetch_canonical_labels(
    session: AsyncSession,
    *,
    tenant_id: str,
    media_ids: Iterable[int] | None = None,
) -> dict[IdentityLocator, str]:
    """Return canonical labels for identities from the *final curated* DB state.

    Canonical labels are derived from clusters where `identity_clusters.user_confirmed=true`.

    Args:
        session: Async SQLAlchemy session.
        tenant_id: Tenant UUID string.
        media_ids: Optional media_id filter to restrict the dataset.

    Returns:
        dict[IdentityLocator, str]: Locator -> canonical label.
    """
    tenant_uuid = _parse_uuid(tenant_id, field_name="tenant_id")
    media_id_list = list(media_ids) if media_ids is not None else None

    stmt: Select[tuple[MediaIdentity, str | None]] = (
        select(MediaIdentity, IdentityCluster.label)
        .join(IdentityMember, IdentityMember.identity_id == MediaIdentity.id)
        .join(IdentityCluster, IdentityCluster.id == IdentityMember.cluster_id)
        .where(MediaIdentity.tenant_id == tenant_uuid)
        .where(and_(IdentityMember.tenant_id == tenant_uuid, IdentityCluster.tenant_id == tenant_uuid))
        .where(IdentityCluster.user_confirmed.is_(True))
        .where(IdentityCluster.label.is_not(None))
    )
    if media_id_list is not None:
        stmt = stmt.where(MediaIdentity.media_id.in_(media_id_list))

    rows = (await session.execute(stmt)).all()
    labels: dict[IdentityLocator, str] = {}
    for identity, label in rows:
        if label is None:
            continue
        locator = IdentityLocator(
            media_id=int(identity.media_id),
            bbox_x=int(identity.bbox_x),
            bbox_y=int(identity.bbox_y),
            bbox_width=int(identity.bbox_width),
            bbox_height=int(identity.bbox_height),
            crop_hash=None,
        )
        if locator in labels and labels[locator] != label:
            raise ValueError(f"Conflicting labels for locator: {locator}")
        labels[locator] = label

    return labels


async def fetch_predicted_clusters(
    session: AsyncSession,
    *,
    tenant_id: str,
    media_ids: Iterable[int] | None = None,
) -> dict[IdentityLocator, str]:
    """Return predicted cluster assignments for identities from the DB state.

    This export is intended to be run immediately after a new clustering run finishes (before manual curation).

    Args:
        session: Async SQLAlchemy session.
        tenant_id: Tenant UUID string.
        media_ids: Optional media_id filter to restrict the dataset.

    Returns:
        dict[IdentityLocator, str]: Locator -> predicted cluster identifier.
    """
    tenant_uuid = _parse_uuid(tenant_id, field_name="tenant_id")
    media_id_list = list(media_ids) if media_ids is not None else None

    stmt: Select[tuple[MediaIdentity, UUID | None]] = cast(
        Select[tuple[MediaIdentity, UUID | None]],
        select(MediaIdentity, IdentityMember.cluster_id)
        .join(
            IdentityMember,
            and_(IdentityMember.identity_id == MediaIdentity.id, IdentityMember.tenant_id == tenant_uuid),
            isouter=True,
        )
        .where(MediaIdentity.tenant_id == tenant_uuid),
    )
    if media_id_list is not None:
        stmt = stmt.where(MediaIdentity.media_id.in_(media_id_list))

    rows = (await session.execute(stmt)).all()
    clusters: dict[IdentityLocator, str] = {}
    for identity, cluster_id in rows:
        locator = IdentityLocator(
            media_id=int(identity.media_id),
            bbox_x=int(identity.bbox_x),
            bbox_y=int(identity.bbox_y),
            bbox_width=int(identity.bbox_width),
            bbox_height=int(identity.bbox_height),
            crop_hash=None,
        )
        clusters[locator] = str(cluster_id) if cluster_id is not None else f"unclustered:{identity.id}"

    return clusters
