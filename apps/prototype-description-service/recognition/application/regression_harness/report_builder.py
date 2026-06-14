"""
Canonical report builder for the regression harness.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import numpy as np
from anyio import Path as AsyncPath
from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    IdentityCluster,
    IdentityClusterRepresentative,
    IdentityMember,
    MediaIdentity,
    RecognitionEvent,
    RecognitionRun,
)
from recognition.application.regression_harness.metrics import compute_curation_cost, compute_pairwise_metrics
from recognition.domain.locator import IdentityLocator


async def get_all_run_ids(session: AsyncSession, tenant_id: UUID) -> list[UUID]:
    """Get all recognition run IDs for a tenant, ordered by creation time.

    Args:
        session: Database session.
        tenant_id: Tenant UUID.

    Returns:
        List of run UUIDs, oldest first.
    """
    stmt = (
        select(RecognitionRun.id).where(RecognitionRun.tenant_id == tenant_id).order_by(RecognitionRun.created_at.asc())
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.fetchall()]


async def get_aggregated_settings(
    session: AsyncSession, run_ids: list[UUID]
) -> tuple[dict[str, object], dict[str, object]]:
    """Get aggregated settings_snapshot and dataset_selector from multiple runs.

    Returns the most recent settings_snapshot (assuming settings don't change),
    and merges all media_ids from dataset_selectors.

    Args:
        session: Database session.
        run_ids: List of run UUIDs.

    Returns:
        Tuple of (settings_snapshot, dataset_selector).
    """
    if not run_ids:
        return {}, {}

    stmt = (
        select(RecognitionRun)
        .where(RecognitionRun.id.in_(run_ids))
        .order_by(RecognitionRun.created_at.desc())  # Most recent first
    )
    runs = (await session.execute(stmt)).scalars().all()

    if not runs:
        return {}, {}

    # Use settings from most recent run
    settings_snapshot = runs[0].settings_snapshot or {}

    # Merge all media_ids from dataset_selectors
    all_media_ids: set[int] = set()
    for run in runs:
        selector = run.dataset_selector or {}
        media_ids = selector.get("media_ids")
        if isinstance(media_ids, list):
            all_media_ids.update(mid for mid in media_ids if isinstance(mid, int))

    dataset_selector: dict[str, object] = {}
    if all_media_ids:
        dataset_selector["media_ids"] = sorted(all_media_ids)

    return settings_snapshot, dataset_selector


def _parse_uuid(value: str, *, field_name: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc


def _optional_uuid(value: str | None, *, field_name: str) -> UUID | None:
    if value is None:
        return None
    return _parse_uuid(value, field_name=field_name)


def _locator_payload(identity: MediaIdentity, *, include_crop_hash: bool = False) -> dict[str, object]:
    """Build a minimal locator payload, omitting null fields."""
    payload: dict[str, object] = {
        "media_id": int(identity.media_id),
        "bbox_x": int(identity.bbox_x),
        "bbox_y": int(identity.bbox_y),
        "bbox_width": int(identity.bbox_width),
        "bbox_height": int(identity.bbox_height),
    }
    # Only include crop_hash if present and requested
    crop_hash = getattr(identity, "crop_hash", None)
    if include_crop_hash and crop_hash:
        payload["crop_hash"] = crop_hash
    return payload


async def _build_pre_curation_state(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    run_id: UUID | None = None,
    run_ids: list[UUID] | None = None,
    media_ids: set[int] | None,
) -> dict[str, object]:
    """Build pre-curation state from recognition events.

    Includes assignment details (similarity, confidence, method) and graph run params.

    Args:
        session: Database session.
        tenant_id: Tenant UUID.
        run_id: Single run UUID (legacy, for backward compat).
        run_ids: List of run UUIDs to aggregate (for --all-runs).
        media_ids: Optional filter for media IDs.

    Returns:
        Pre-curation state dict with predicted_clusters and graph_run params.
    """
    # Build list of run IDs to query
    query_run_ids: list[UUID] = []
    if run_ids:
        query_run_ids = run_ids
    elif run_id:
        query_run_ids = [run_id]
    else:
        return {"predicted_clusters": []}

    events_stmt: Select[tuple[RecognitionEvent]] = (
        select(RecognitionEvent)
        .where(
            and_(
                RecognitionEvent.tenant_id == tenant_id,
                RecognitionEvent.run_id.in_(query_run_ids),
                RecognitionEvent.event_type.in_(["cluster_created", "assignment_decision", "graph_run"]),
            )
        )
        .order_by(RecognitionEvent.timestamp.asc(), RecognitionEvent.id.asc())
    )
    events = (await session.execute(events_stmt)).scalars().all()

    members_by_cluster: dict[str, list[dict[str, object]]] = defaultdict(list)
    creation_method_by_cluster: dict[str, str] = {}
    graph_params_by_cluster: dict[str, dict[str, object]] = {}

    def _make_member_entry(
        cluster_key: str, payload: dict[str, object], locator_dict: dict[str, object]
    ) -> dict[str, object] | None:
        try:
            locator = IdentityLocator.from_dict(locator_dict)
        except ValueError:
            return None
        if media_ids is not None and locator.media_id not in media_ids:
            return None

        # Build minimal locator without null crop_hash
        minimal_locator: dict[str, object] = {
            "media_id": locator.media_id,
            "bbox_x": locator.bbox_x,
            "bbox_y": locator.bbox_y,
            "bbox_width": locator.bbox_width,
            "bbox_height": locator.bbox_height,
        }
        if locator.crop_hash:
            minimal_locator["crop_hash"] = locator.crop_hash

        entry: dict[str, object] = {
            "identity_id": payload.get("identity_id"),
            "media_id": locator.media_id,
            "bbox": {
                "x": locator.bbox_x,
                "y": locator.bbox_y,
                "width": locator.bbox_width,
                "height": locator.bbox_height,
            },
            "identity_locator": minimal_locator,
        }

        # Add embedding fingerprint if available in payload
        # (Usually added during logging in incremental_clustering or by fetching)
        if payload.get("embedding_fingerprint"):
            entry["embedding_fingerprint"] = payload.get("embedding_fingerprint")

        # Add original_assignment details from assignment_decision payload
        if payload.get("decision"):
            original_assignment: dict[str, object] = {
                "cluster_id": cluster_key,
                "decision": payload.get("decision"),
                "method": payload.get("method"),
                "stage": payload.get("stage"),
                "similarity": payload.get("similarity"),
                "confidence": payload.get("confidence"),
                "threshold": payload.get("threshold"),
            }
            gate_checks = payload.get("gate_checks")
            if gate_checks:
                original_assignment["gate_checks"] = gate_checks
            if payload.get("algorithm"):
                original_assignment["algorithm"] = payload.get("algorithm")
            if payload.get("anchor_linked"):
                original_assignment["anchor_linked"] = payload.get("anchor_linked")
            entry["original_assignment"] = original_assignment

        return entry

    for event in events:
        cluster_uuid = event.cluster_id
        cluster_key = str(cluster_uuid) if cluster_uuid is not None else None
        payload = event.payload or {}

        if event.event_type == "graph_run":
            # Store graph algorithm params for the run (not cluster-specific)
            graph_params_by_cluster["_global"] = {
                "algorithm": payload.get("algorithm"),
                "params": payload.get("params"),
                "outputs": payload.get("outputs"),
                "anchor_count": payload.get("anchor_count"),
                "identity_count": payload.get("identity_count"),
            }
            continue

        if event.event_type == "cluster_created":
            if cluster_key is None:
                continue
            creation_method = payload.get("creation_method")
            if isinstance(creation_method, str):
                creation_method_by_cluster[cluster_key] = creation_method

            members = payload.get("members")
            if isinstance(members, list):
                for member in members:
                    if not isinstance(member, dict):
                        continue
                    locator_dict = member.get("identity_locator")
                    if not isinstance(locator_dict, dict):
                        continue
                    entry = _make_member_entry(cluster_key, member, locator_dict)
                    if entry:
                        members_by_cluster[cluster_key].append(entry)
            continue

        if event.event_type == "assignment_decision":
            if cluster_key is None:
                continue
            if payload.get("decision") != "accept":
                continue
            locator_dict = payload.get("identity_locator")
            if not isinstance(locator_dict, dict):
                continue
            entry = _make_member_entry(cluster_key, payload, locator_dict)
            if entry:
                members_by_cluster[cluster_key].append(entry)

    predicted_clusters: list[dict[str, object]] = []
    for cluster_key, member_entries in sorted(members_by_cluster.items(), key=lambda item: item[0]):
        cluster_data: dict[str, object] = {
            "predicted_cluster_id": cluster_key,
            "creation_method": creation_method_by_cluster.get(cluster_key),
            "member_identity_locators": [e["identity_locator"] for e in member_entries],
            "identity_count": len(member_entries),
        }
        # Include full member details with assignment info
        members_with_details = [e for e in member_entries if "original_assignment" in e]
        if members_with_details:
            cluster_data["members"] = members_with_details
        predicted_clusters.append(cluster_data)

    result: dict[str, object] = {"predicted_clusters": predicted_clusters}

    # Add graph run params if available
    if "_global" in graph_params_by_cluster:
        result["graph_run"] = graph_params_by_cluster["_global"]

    return result


async def generate_canonical_report(
    session: AsyncSession,
    *,
    tenant_id: str,
    run_id: str | None = None,
    all_runs: bool = False,
    compare_baseline_path: str | None = None,
    baseline_source_type: str = "curated",
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
        all_runs: If True, aggregate events from ALL runs for this tenant.
        compare_baseline_path: Path to a saved baseline JSON file to use as ground truth
            instead of DB clusters. Enables post-reset comparison.
        baseline_source_type: Source of ground truth labels when using compare_baseline_path:
            - "curated": Use canonical_clusters (user-curated labels) [default]
            - "predicted": Use pre_curation_state.predicted_clusters (original algorithm output)
              Use "predicted" to measure clustering reproducibility/consistency.
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

        member_identities = []
        for identity in members:
            entry = {
                "identity_id": str(identity.id),
                "media_id": int(identity.media_id),
                "bbox": {
                    "x": identity.bbox_x,
                    "y": identity.bbox_y,
                    "width": identity.bbox_width,
                    "height": identity.bbox_height,
                },
                "image_phash": identity.image_phash,
                "embedding_fingerprint": _compute_fingerprint(np.asarray(identity.embedding, dtype=np.float32))
                if identity.embedding
                else None,
                "identity_locator": _locator_payload(identity),
                "curation": {"final_label": label},
            }
            member_identities.append(entry)

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
        final_representatives: list[dict[str, object]] = []
        for rep, identity in rep_rows:
            rep_entry: dict[str, object] = {
                "identity_id": str(identity.id),
                "identity_locator": _locator_payload(identity),
                "quality_score": float(rep.quality_score),
                "embedding_fingerprint": _compute_fingerprint(np.asarray(identity.embedding, dtype=np.float32))
                if identity.embedding
                else None,
            }
            # Only include optional fields if present
            if rep.diversity_score is not None:
                rep_entry["diversity_score"] = float(rep.diversity_score)
            if identity.media_url:
                rep_entry["media_url"] = identity.media_url
            final_representatives.append(rep_entry)

        canonical_clusters.append(
            {
                "canonical_label": label,
                "final_cluster_id": str(cluster.id),
                "final_representatives": final_representatives,
                "member_identities": member_identities,
                "summary": {
                    "identity_count": len(member_identities),
                    "representative_count": len(final_representatives),
                },
            }
        )

    dataset_media_ids = (
        sorted(set(resolved_media_ids)) if resolved_media_ids is not None else sorted(inferred_media_ids)
    )

    # Build pre-curation state from events
    pre_curation_state: dict[str, object] | None = None
    run_ids_used: list[str] = []
    aggregated_settings: dict[str, object] = {}
    aggregated_selector: dict[str, object] = {}

    if all_runs:
        # Aggregate events from ALL runs for this tenant
        all_run_uuids = await get_all_run_ids(session, tenant_uuid)
        if all_run_uuids:
            run_ids_used = [str(r) for r in all_run_uuids]
            pre_curation_state = await _build_pre_curation_state(
                session,
                tenant_id=tenant_uuid,
                run_ids=all_run_uuids,
                media_ids=set(dataset_media_ids),
            )
            # Get aggregated settings from all runs
            aggregated_settings, aggregated_selector = await get_aggregated_settings(session, all_run_uuids)
    elif run_uuid is not None:
        run_ids_used = [str(run_uuid)]
        pre_curation_state = await _build_pre_curation_state(
            session,
            tenant_id=tenant_uuid,
            run_id=run_uuid,
            media_ids=set(dataset_media_ids),
        )

    # Add run_ids metadata to pre_curation_state
    if pre_curation_state is not None:
        pre_curation_state["run_ids"] = run_ids_used

    # 4) Build Duplicates Analysis
    by_image_hash: dict[str, list[dict[str, Any]]] = {}
    consistency_issues = []

    # Collect all identity entries from both predicted and canonical clusters
    all_entries: list[dict[str, Any]] = []
    if pre_curation_state:
        pred_clusters = cast(list[dict[str, Any]], pre_curation_state.get("predicted_clusters", []))
        if isinstance(pred_clusters, list):
            for pc in pred_clusters:
                if isinstance(pc, dict):
                    members_list = cast(list[dict[str, Any]], pc.get("members", []))
                    for m in members_list:
                        all_entries.append(m)
    for cc in canonical_clusters:
        member_identities_list = cast(list[dict[str, Any]], cc.get("member_identities", []))
        for m in member_identities_list:
            # Predicted cluster ID might be different if it's from predicted cluster list
            all_entries.append(m)

    # Group by phash
    for entry in all_entries:
        phash_obj = entry.get("image_phash")
        if not phash_obj or not isinstance(phash_obj, str):
            continue
        phash = phash_obj

        if phash not in by_image_hash:
            by_image_hash[phash] = []

        # Avoid exact duplicates in list
        identity_id = entry.get("identity_id")
        if not any(e["identity_id"] == identity_id for e in by_image_hash[phash]):
            by_image_hash[phash].append(
                {
                    "identity_id": identity_id,
                    "media_id": entry.get("media_id"),
                    "bbox": entry.get("bbox"),
                    "embedding_fingerprint": entry.get("embedding_fingerprint"),
                    "cluster_id": cast(dict[str, Any], entry.get("original_assignment", {})).get("cluster_id")
                    or entry.get("final_cluster_id"),
                    "label": cast(dict[str, Any], entry.get("curation", {})).get("final_label"),
                }
            )

    # Find consistency issues (same phash + same bbox -> different clusters)
    for issue_phash, phash_entries in by_image_hash.items():
        if len(phash_entries) < 2:
            continue

        # Group by bbox to find same identities in different images
        by_bbox: dict[tuple, list[dict]] = {}
        for pe in phash_entries:
            bbox = pe.get("bbox")
            if not bbox or not isinstance(bbox, dict):
                continue
            bbox_key = (bbox.get("x"), bbox.get("y"), bbox.get("width"), bbox.get("height"))
            if bbox_key not in by_bbox:
                by_bbox[bbox_key] = []
            by_bbox[bbox_key].append(pe)

        for bbox_coords, bbox_entries in by_bbox.items():
            cluster_ids = {e["cluster_id"] for e in bbox_entries if e.get("cluster_id")}
            if len(cluster_ids) > 1:
                consistency_issues.append(
                    {
                        "image_hash": issue_phash,
                        "issue": "transitivity_failure",
                        "clusters": list(cluster_ids),
                        "bbox": {
                            "x": bbox_coords[0],
                            "y": bbox_coords[1],
                            "width": bbox_coords[2],
                            "height": bbox_coords[3],
                        },
                        "identities": [
                            {"media_id": e.get("media_id"), "cluster_id": e.get("cluster_id")} for e in bbox_entries
                        ],
                    }
                )

    # Compute metrics if we have predicted clusters
    # Ground truth comes from either:
    #   1) compare_baseline_path (saved JSON file) - for post-reset comparison
    #      - baseline_source_type="curated": use canonical_clusters (user-curated labels)
    #      - baseline_source_type="predicted": use predicted_clusters (original algorithm output)
    #   2) canonical_clusters (DB) - for normal usage
    metrics: dict[str, object] = {}
    baseline_source: str | None = None
    canonical_labels: dict[IdentityLocator, str] = {}

    if compare_baseline_path:
        # Load ground truth from saved baseline file
        from pathlib import Path

        from recognition.application.regression_harness.serialization import (
            load_canonical_labels,
            load_predicted_labels,
        )

        baseline_async_path = AsyncPath(compare_baseline_path)
        if await baseline_async_path.exists():
            baseline_path = Path(compare_baseline_path)
            if baseline_source_type == "predicted":
                canonical_labels = load_predicted_labels(baseline_path)
                baseline_source = f"{baseline_path} (predicted)"
            else:
                canonical_labels = load_canonical_labels(baseline_path)
                baseline_source = f"{baseline_path} (curated)"
    else:
        # Build canonical_labels from DB clusters
        for cc_dict in canonical_clusters:
            final_label_obj = cc_dict.get("canonical_label")
            if not isinstance(final_label_obj, str):
                continue
            final_label = final_label_obj

            members_list_obj = cc_dict.get("member_identities")
            if not isinstance(members_list_obj, list):
                continue
            members_list = cast(list[dict[str, Any]], members_list_obj)

            for member in members_list:
                loc_dict = member.get("identity_locator")
                if isinstance(loc_dict, dict):
                    try:
                        locator = IdentityLocator.from_dict(loc_dict)
                        canonical_labels[locator] = final_label
                    except ValueError:
                        pass

    # Build predicted_clusters_map from pre_curation_state
    predicted_clusters_map: dict[IdentityLocator, str] = {}
    if pre_curation_state:
        predicted_list = pre_curation_state.get("predicted_clusters")
        if isinstance(predicted_list, list):
            for pred_cluster in predicted_list:
                if not isinstance(pred_cluster, dict):
                    continue
                cluster_id = pred_cluster.get("predicted_cluster_id")
                if not isinstance(cluster_id, str):
                    continue
                locators = pred_cluster.get("member_identity_locators")
                if not isinstance(locators, list):
                    continue
                for loc_dict in locators:
                    if isinstance(loc_dict, dict):
                        try:
                            locator = IdentityLocator.from_dict(loc_dict)
                            predicted_clusters_map[locator] = cluster_id
                        except ValueError:
                            pass

    if canonical_labels and predicted_clusters_map:
        pairwise = compute_pairwise_metrics(
            canonical_labels=canonical_labels,
            predicted_clusters=predicted_clusters_map,
        )
        curation_cost = compute_curation_cost(
            canonical_labels=canonical_labels,
            predicted_clusters=predicted_clusters_map,
        )
        metrics = {
            "pairwise": asdict(pairwise),
            "curation_cost": {
                "labels_evaluated": curation_cost.labels_evaluated,
                "estimated_merges": curation_cost.estimated_merges,
                "estimated_removals": curation_cost.estimated_removals,
            },
        }
        if baseline_source:
            metrics["baseline_source"] = baseline_source

    # Determine settings_snapshot and dataset_selector
    # Priority: run (single run) > aggregated (all runs) > empty
    final_settings = run.settings_snapshot if run is not None else aggregated_settings
    final_selector = run.dataset_selector if run is not None else aggregated_selector

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
            "all_runs": all_runs,
            "run_ids": run_ids_used if run_ids_used else None,
            "git_sha": run.git_sha if run is not None else None,
            "settings_snapshot": final_settings,
            "dataset_selector": final_selector,
            "embedding_model": {"name": None, "dimension": None},
        },
        "canonical_clusters": canonical_clusters,
        "pre_curation_state": pre_curation_state,
        "duplicates": {
            "by_image_hash": by_image_hash,
            "consistency_issues": consistency_issues,
        },
        "cluster_outcomes": [],
        "metrics": metrics,
    }


def _compute_fingerprint(embedding: np.ndarray) -> str:
    """Compute a stable fingerprint for a face embedding."""
    import hashlib

    from recognition.shared.similarity import extract_face_embedding

    # Use face-only portion for fingerprinting
    face_vec = extract_face_embedding(embedding)
    return hashlib.sha256(face_vec.tobytes()).hexdigest()[:8]
