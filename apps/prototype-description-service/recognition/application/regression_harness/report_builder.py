"""
Canonical report builder for the regression harness.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    IdentityCluster,
    IdentityClusterRepresentative,
    IdentityMember,
    MediaIdentity,
    RecognitionRun,
)
from recognition.domain.locator import IdentityLocator


def _parse_uuid(value: str, *, field_name: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc


def _optional_uuid(value: str | None, *, field_name: str) -> UUID | None:
    if value is None:
        return None
    return _parse_uuid(value, field_name=field_name)


def _locator_payload(identity: MediaIdentity) -> dict[str, object]:
    return IdentityLocator(
        media_id=int(identity.media_id),
        bbox_x=int(identity.bbox_x),
        bbox_y=int(identity.bbox_y),
        bbox_width=int(identity.bbox_width),
        bbox_height=int(identity.bbox_height),
        crop_hash=None,
    ).to_dict()


async def generate_canonical_report(
    session: AsyncSession,
    *,
    tenant_id: str,
    run_id: str | None = None,
    media_ids: Iterable[int] | None = None,
    roster_id: str | None = None,
    dataset_name: str | None = None,
    dataset_notes: str | None = None,
) -> dict[str, object]:
    """Generate the canonical report JSON payload for a tenant/dataset.

    Args:
        session: Async SQLAlchemy session.
        tenant_id: Tenant UUID string.
        run_id: Optional recognition_run UUID string to attach as the baseline run.
        media_ids: Optional dataset filter (media IDs).
        roster_id: Optional dataset filter (roster UUID).
        dataset_name: Optional human-friendly dataset name.
        dataset_notes: Optional dataset notes.

    Returns:
        dict[str, object]: Canonical report payload (JSON-serializable).
    """
    tenant_uuid = _parse_uuid(tenant_id, field_name="tenant_id")
    run_uuid = _optional_uuid(run_id, field_name="run_id")

    run: RecognitionRun | None = None
    if run_uuid is not None:
        run = await session.get(RecognitionRun, run_uuid)

    resolved_media_ids: list[int] | None = list(media_ids) if media_ids is not None else None
    if resolved_media_ids is None and run is not None:
        selector_media_ids = (run.dataset_selector or {}).get("media_ids")
        if isinstance(selector_media_ids, list) and all(isinstance(mid, int) for mid in selector_media_ids):
            resolved_media_ids = selector_media_ids

    resolved_roster_uuid = _optional_uuid(roster_id, field_name="roster_id")
    if resolved_roster_uuid is None and run is not None:
        selector_roster_id = (run.dataset_selector or {}).get("roster_id")
        if isinstance(selector_roster_id, str):
            resolved_roster_uuid = _optional_uuid(selector_roster_id, field_name="roster_id")

    clusters_stmt: Select[tuple[IdentityCluster]] = (
        select(IdentityCluster)
        .where(IdentityCluster.tenant_id == tenant_uuid)
        .where(IdentityCluster.user_confirmed.is_(True))
        .order_by(IdentityCluster.label.asc(), IdentityCluster.id.asc())
    )
    if resolved_roster_uuid is not None:
        clusters_stmt = clusters_stmt.where(IdentityCluster.roster_id == resolved_roster_uuid)

    clusters = (await session.execute(clusters_stmt)).scalars().all()

    canonical_clusters: list[dict[str, object]] = []
    inferred_media_ids: set[int] = set()

    for cluster in clusters:
        label = (cluster.label or "").strip()
        if not label:
            continue

        members_stmt: Select[tuple[MediaIdentity]] = (
            select(MediaIdentity)
            .join(IdentityMember, IdentityMember.identity_id == MediaIdentity.id)
            .where(IdentityMember.tenant_id == tenant_uuid)
            .where(IdentityMember.cluster_id == cluster.id)
            .where(MediaIdentity.tenant_id == tenant_uuid)
        )
        if resolved_media_ids is not None:
            members_stmt = members_stmt.where(MediaIdentity.media_id.in_(resolved_media_ids))

        members = (await session.execute(members_stmt)).scalars().all()
        if not members:
            continue

        for identity in members:
            inferred_media_ids.add(int(identity.media_id))

        member_identities = [
            {
                "identity_locator": _locator_payload(identity),
                "curation": {"final_label": label, "actions": [], "notes": None},
            }
            for identity in members
        ]

        reps_stmt: Select[tuple[IdentityClusterRepresentative, MediaIdentity]] = (
            select(IdentityClusterRepresentative, MediaIdentity)
            .join(MediaIdentity, MediaIdentity.id == IdentityClusterRepresentative.identity_id)
            .where(IdentityClusterRepresentative.tenant_id == tenant_uuid)
            .where(IdentityClusterRepresentative.cluster_id == cluster.id)
            .where(MediaIdentity.tenant_id == tenant_uuid)
            .order_by(
                IdentityClusterRepresentative.quality_score.desc(), IdentityClusterRepresentative.created_at.asc()
            )
        )
        if resolved_media_ids is not None:
            reps_stmt = reps_stmt.where(MediaIdentity.media_id.in_(resolved_media_ids))

        rep_rows = (await session.execute(reps_stmt)).all()
        final_representatives = [
            {
                "identity_locator": _locator_payload(identity),
                "quality_score": float(rep.quality_score),
                "diversity_score": float(rep.diversity_score) if rep.diversity_score is not None else None,
                "thumbnail_url": identity.thumbnail_url,
                "media_url": identity.media_url,
            }
            for rep, identity in rep_rows
        ]

        canonical_clusters.append(
            {
                "canonical_label": label,
                "final_cluster_id": str(cluster.id),
                "final_representatives": final_representatives,
                "member_identities": member_identities,
                "summary": {
                    "identity_count": len(member_identities),
                    "fragmentation_original_cluster_count": None,
                    "contamination_moved_out_count": None,
                    "assignment_method_breakdown": {},
                },
            }
        )

    dataset_media_ids = (
        sorted(set(resolved_media_ids)) if resolved_media_ids is not None else sorted(inferred_media_ids)
    )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "tenant_id": str(tenant_uuid),
        "dataset": {
            "name": dataset_name,
            "roster_id": str(resolved_roster_uuid) if resolved_roster_uuid is not None else None,
            "media_ids": dataset_media_ids,
            "notes": dataset_notes,
        },
        "baseline_run": {
            "run_id": str(run_uuid) if run_uuid is not None else None,
            "git_sha": run.git_sha if run is not None else None,
            "settings_snapshot": run.settings_snapshot if run is not None else {},
            "dataset_selector": run.dataset_selector if run is not None else {},
            "embedding_model": {"name": None, "dimension": None},
        },
        "canonical_clusters": canonical_clusters,
        "cluster_outcomes": [],
        "metrics": {},
    }
