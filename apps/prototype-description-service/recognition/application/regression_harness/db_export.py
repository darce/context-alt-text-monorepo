"""
Database export helpers for the regression harness.

These functions extract stable identity locators and their canonical/predicted assignments from the database so that
evaluation can be done without relying on unstable UUID primary keys.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.domain.locator import IdentityLocator


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
    raise NotImplementedError("TODO: implement fetch_canonical_labels")


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
    raise NotImplementedError("TODO: implement fetch_predicted_clusters")
