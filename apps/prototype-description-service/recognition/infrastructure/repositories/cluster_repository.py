"""
SQLAlchemy-backed implementation of ClusterRepository.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
from sqlalchemy import Select, delete, exists, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import instance_state

from db.models import IdentityCluster as ClusterModel
from db.models import IdentityClusterRepresentative, IdentitySuggestion, MediaIdentity
from db.models import IdentityMember as IdentityMemberModel
from db.models import NameSuggestion as NameSuggestionModel
from db.settings import get_database_settings
from db.tenant_context import enable_rls_bypass
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity as DomainIdentity
from recognition.domain.maturity import ClusterMaturityInfo, compute_maturity_adjustment, compute_maturity_level
from recognition.domain.repositories import ClusterRepository
from recognition.domain.repositories import IdentityMember as DomainMember
from recognition.domain.representative import ClusterRepresentative
from recognition.infrastructure.repositories._helpers import coerce_uuid as _coerce_uuid
from recognition.shared.db.dialect import is_sqlite
from recognition.shared.db.helpers import execute_dml, get_rowcount

_DB_SETTINGS = get_database_settings()
logger = logging.getLogger(__name__)
_TOP_UNLABELED_FALLBACK_REP_LIMIT = 4
_SNAPSHOT_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

if TYPE_CHECKING:
    from recognition.application.settings.clustering import MaturitySettings


def _choose_embedding_model(models: Sequence[str | None]) -> str | None:
    """Majority embedding_model with lex-stable tie-break (FIR23-01)."""
    counts: dict[str, int] = {}
    for model in models:
        if not model:
            continue
        key = str(model)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    # Sort by (-count, model_id) so highest count wins; ties → lex min.
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _filter_embedding_pairs_to_single_model(
    rows: Sequence[tuple[np.ndarray, str | None]],
) -> list[tuple[np.ndarray, str | None]]:
    """Keep embeddings from one model space; single-model input is a no-op."""
    if not rows:
        return []
    chosen = _choose_embedding_model([model for _, model in rows])
    if chosen is None:
        return list(rows)
    distinct = {str(model) for _, model in rows if model}
    if len(distinct) <= 1:
        return list(rows)
    return [(emb, model) for emb, model in rows if model == chosen]


def _filter_identity_models_to_single_embedding_model(
    models: Sequence[MediaIdentity],
) -> list[MediaIdentity]:
    """Keep MediaIdentity rows from one embedding_model; single-model is a no-op."""
    if not models:
        return []
    chosen = _choose_embedding_model([getattr(m, "embedding_model", None) for m in models])
    if chosen is None:
        return list(models)
    distinct = {str(m.embedding_model) for m in models if getattr(m, "embedding_model", None)}
    if len(distinct) <= 1:
        return list(models)
    return [m for m in models if getattr(m, "embedding_model", None) == chosen]


def _filter_rows_to_single_embedding_model(
    models: Sequence[MediaIdentity],
) -> list[MediaIdentity]:
    """For unclustered sets: single-model no-op; mixed → active model only.

    Prefer the active runtime model when mixed models coexist so clustering
    never compares across embedding spaces. If none match active, keep the
    majority model rather than mixing (still fail-closed relative to mixing).
    """
    if not models:
        return []
    distinct = {str(m.embedding_model) for m in models if getattr(m, "embedding_model", None)}
    if len(distinct) <= 1:
        return list(models)
    try:
        from recognition.application.embedding.manifest import active_embedding_model_id

        active = active_embedding_model_id()
    except Exception:
        active = None
    if active is not None:
        matched = [m for m in models if getattr(m, "embedding_model", None) == active]
        if matched:
            return matched
    return _filter_identity_models_to_single_embedding_model(models)


def _snapshot_version_to_datetime(snapshot_version: int) -> datetime:
    """Decode a microsecond Unix timestamp without float precision loss."""
    normalized_version = max(snapshot_version, 0)
    seconds, micros = divmod(normalized_version, 1_000_000)
    return _SNAPSHOT_EPOCH + timedelta(seconds=seconds, microseconds=micros)


def _datetime_to_snapshot_version(value: datetime | None) -> int:
    """Encode an aware timestamp as a microsecond Unix timestamp."""
    if not isinstance(value, datetime):
        value = _SNAPSHOT_EPOCH
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    delta = value - _SNAPSHOT_EPOCH
    return ((delta.days * 86_400) + delta.seconds) * 1_000_000 + delta.microseconds


_MV_CENTROIDS = "mv_identity_cluster_centroids"


async def _refresh_mv_concurrent_with_bypass(conn: AsyncConnection) -> None:
    """Execute a concurrent MV refresh on an AUTOCOMMIT connection with RLS bypass.

    SET app.bypass_rls is session-scoped (not SET LOCAL) because AUTOCOMMIT mode
    has no enclosing transaction for SET LOCAL to bind to.
    All 18 MV source tables carry relforcerowsecurity=true; without bypass even
    the table owner sees zero rows.
    """
    await conn.execute(text("SET app.bypass_rls = 'true'"))
    try:
        before_result = await conn.execute(text(f"SELECT COUNT(*) FROM {_MV_CENTROIDS}"))
        before_count: int = before_result.scalar_one()
        started_at = datetime.now(tz=UTC)
        await conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {_MV_CENTROIDS}"))
        duration_ms = int((datetime.now(tz=UTC) - started_at).total_seconds() * 1000)
        after_result = await conn.execute(text(f"SELECT COUNT(*) FROM {_MV_CENTROIDS}"))
        after_count: int = after_result.scalar_one()
        logger.info(
            "Refreshed %s: before=%d after=%d duration_ms=%d",
            _MV_CENTROIDS,
            before_count,
            after_count,
            duration_ms,
        )
    finally:
        await conn.execute(text("RESET app.bypass_rls"))


class SqlAlchemyClusterRepository(ClusterRepository):
    """Persist clusters using an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, cluster_id: str):
        """Fetch a cluster by ID."""
        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.id == _coerce_uuid(cluster_id))
            .options(selectinload(ClusterModel.members))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def get_by_ids(self, cluster_ids: Sequence[str]) -> list[IdentityCluster]:
        """Fetch multiple clusters in one query (batched ``get_by_id``, UXP-2 3a)."""
        cluster_uuids = [item for item in (_coerce_uuid(value) for value in cluster_ids) if item is not None]
        if not cluster_uuids:
            return []
        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel).where(ClusterModel.id.in_(cluster_uuids)).options(selectinload(ClusterModel.members))
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(model) for model in result.scalars().all()]

    async def get_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        labeled_only: bool = False,
        search: str | None = None,
    ):
        """Fetch clusters for a tenant, with representatives eagerly loaded for discovery."""
        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == _coerce_uuid(tenant_id))
            .options(
                selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity),
                selectinload(ClusterModel.centroid_data),
            )
            .order_by(ClusterModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        if labeled_only:
            stmt = stmt.where(ClusterModel.label.isnot(None))
            stmt = stmt.where(ClusterModel.user_confirmed.is_(True))

        if search:
            escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(ClusterModel.label.ilike(f"%{escaped_search}%", escape="\\"))

        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def get_top_unlabeled(
        self,
        tenant_id: str,
        limit: int = 10,
        min_identity_count: int = 2,
    ) -> list[IdentityCluster]:
        """Fetch top unlabeled clusters globally by size, with representatives for thumbnails.

        This endpoint is productivity-first: prioritize the largest unlabeled clusters
        across the tenant (not latest-run scoped), so users label the most observations first.
        Dismissed clusters and singletons are excluded.
        """
        from sqlalchemy import or_

        tenant_uuid = _coerce_uuid(tenant_id)
        if tenant_uuid is None:
            return []

        accepted_member_suggestion_exists = (
            select(1)
            .select_from(IdentityMemberModel)
            .join(
                IdentitySuggestion,
                IdentitySuggestion.identity_id == IdentityMemberModel.identity_id,
            )
            .where(IdentityMemberModel.cluster_id == ClusterModel.id)
            .where(IdentitySuggestion.tenant_id == tenant_uuid)
            .where(IdentitySuggestion.resolution == "accepted")
            .where(IdentitySuggestion.suggested_cluster_id != ClusterModel.id)
        )

        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == tenant_uuid)
            .where(ClusterModel.user_confirmed.is_(False))
            .where(or_(ClusterModel.label.is_(None), ClusterModel.label.startswith("cluster-")))
            .where(ClusterModel.identity_count >= min_identity_count)
            .where(ClusterModel.dismissed_at.is_(None))
            .where(~exists(accepted_member_suggestion_exists))
            .options(
                selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity),
            )
            .order_by(ClusterModel.identity_count.desc(), ClusterModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        results = [self._to_domain(row) for row in result.scalars().all()]
        clusters_requiring_top_up = [
            cluster.id
            for cluster in results
            if cluster.id and len(cluster.representatives or []) < _TOP_UNLABELED_FALLBACK_REP_LIMIT
        ]
        topped_up_clusters = 0
        if clusters_requiring_top_up:
            fallback_representatives = await self._get_member_fallback_representatives(
                clusters_requiring_top_up,
                max_per_cluster=_TOP_UNLABELED_FALLBACK_REP_LIMIT,
            )
            for cluster in results:
                if not cluster.id:
                    continue
                existing_representatives = list(cluster.representatives or [])
                if len(existing_representatives) >= _TOP_UNLABELED_FALLBACK_REP_LIMIT:
                    continue

                member_reps = fallback_representatives.get(cluster.id, [])
                if not member_reps:
                    continue

                merged_representatives: list[ClusterRepresentative] = []
                seen_identity_ids: set[str] = set()
                for representative in [*existing_representatives, *member_reps]:
                    identity_id = str(representative.identity_id)
                    if identity_id in seen_identity_ids:
                        continue
                    seen_identity_ids.add(identity_id)
                    merged_representatives.append(representative)
                    if len(merged_representatives) >= _TOP_UNLABELED_FALLBACK_REP_LIMIT:
                        break

                if len(merged_representatives) > len(existing_representatives):
                    cluster.representatives = merged_representatives
                    topped_up_clusters += 1

        logger.info(
            "Top clusters (size-priority): tenant_id=%s returned=%d limit=%d min_identity_count=%d rep_topup_candidates=%d rep_topup_applied=%d",
            tenant_id,
            len(results),
            limit,
            min_identity_count,
            len(clusters_requiring_top_up),
            topped_up_clusters,
        )
        return results

    async def _get_member_fallback_representatives(
        self,
        cluster_ids: Sequence[str],
        *,
        max_per_cluster: int,
    ) -> dict[str, list[ClusterRepresentative]]:
        """Build thumbnail-capable fallback representatives from top-scoring cluster members."""
        cluster_uuids = [_coerce_uuid(cluster_id) for cluster_id in cluster_ids]
        cluster_uuids = [cluster_id for cluster_id in cluster_uuids if cluster_id is not None]
        if not cluster_uuids:
            return {}

        stmt = (
            select(
                IdentityMemberModel.cluster_id,
                IdentityMemberModel.id,
                IdentityMemberModel.identity_id,
                IdentityMemberModel.similarity,
                IdentityMemberModel.assigned_at,
                MediaIdentity.media_id,
                MediaIdentity.media_url,
                MediaIdentity.bbox_x,
                MediaIdentity.bbox_y,
                MediaIdentity.bbox_width,
                MediaIdentity.bbox_height,
                MediaIdentity.embedding_model,
            )
            .join(MediaIdentity, MediaIdentity.id == IdentityMemberModel.identity_id)
            .where(IdentityMemberModel.cluster_id.in_(cluster_uuids))
            .order_by(
                IdentityMemberModel.cluster_id,
                IdentityMemberModel.similarity.desc(),
                IdentityMemberModel.assigned_at.asc(),
            )
        )
        result = await self._session.execute(stmt)
        fallback_by_cluster: dict[str, list[ClusterRepresentative]] = defaultdict(list)
        now = datetime.now(tz=UTC)
        for row in result:
            cluster_key = str(row.cluster_id)
            existing = fallback_by_cluster[cluster_key]
            if len(existing) >= max_per_cluster:
                continue

            assigned_at = row.assigned_at if isinstance(row.assigned_at, datetime) else now
            embedding_model = getattr(row, "embedding_model", None)
            existing.append(
                ClusterRepresentative(
                    id=str(row.id),
                    cluster_id=cluster_key,
                    identity_id=str(row.identity_id),
                    embedding=np.zeros(_DB_SETTINGS.pgvector_dimension, dtype=np.float32),
                    created_at=assigned_at,
                    quality_score=float(row.similarity),
                    media_id=int(row.media_id) if row.media_id is not None else None,
                    media_url=row.media_url,
                    bbox_x=int(row.bbox_x) if row.bbox_x is not None else None,
                    bbox_y=int(row.bbox_y) if row.bbox_y is not None else None,
                    bbox_width=int(row.bbox_width) if row.bbox_width is not None else None,
                    bbox_height=int(row.bbox_height) if row.bbox_height is not None else None,
                    embedding_model=str(embedding_model) if embedding_model else None,
                )
            )

        return dict(fallback_by_cluster)

    async def dismiss_cluster(self, cluster_id: str) -> bool:
        """Mark a cluster as dismissed so it no longer appears in the naming queue.

        Args:
            cluster_id: UUID of the cluster to dismiss.

        Returns:
            True if a cluster was found and dismissed, False otherwise.
        """
        cluster_uuid = _coerce_uuid(cluster_id)
        if cluster_uuid is None:
            return False
        stmt = (
            update(ClusterModel)
            .where(ClusterModel.id == cluster_uuid)
            .where(ClusterModel.dismissed_at.is_(None))
            .values(dismissed_at=datetime.now(tz=UTC))
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def undismiss_cluster(self, cluster_id: str) -> bool:
        """Clear the dismissed flag on a cluster to resurface it in the naming queue.

        Args:
            cluster_id: UUID of the cluster to undismiss.

        Returns:
            True if a cluster was found and undismissed, False otherwise.
        """
        cluster_uuid = _coerce_uuid(cluster_id)
        if cluster_uuid is None:
            return False
        stmt = (
            update(ClusterModel)
            .where(ClusterModel.id == cluster_uuid)
            .where(ClusterModel.dismissed_at.is_not(None))
            .values(dismissed_at=None)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def get_labeled_with_representatives(
        self,
        tenant_id: str,
    ) -> list[tuple[IdentityCluster, list[ClusterRepresentative]]]:
        """Fetch labeled clusters with representatives via eager loading."""
        tenant_uuid = _coerce_uuid(tenant_id)
        if tenant_uuid is None:
            return []

        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == tenant_uuid)
            .where(ClusterModel.user_confirmed.is_(True))
            .where(ClusterModel.label.is_not(None))
            .where(~ClusterModel.label.startswith("cluster-"))
            .options(selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity))
        )
        result = await self._session.execute(stmt)
        output: list[tuple[IdentityCluster, list[ClusterRepresentative]]] = []
        for model in result.scalars().all():
            cluster = self._to_domain(model)
            representatives = list(cluster.representatives or [])
            output.append((cluster, representatives))
        return output

    async def save(self, cluster):
        """Persist a new cluster."""
        tenant_uuid = _coerce_uuid(cluster.tenant_id)
        if tenant_uuid is None:
            raise ValueError("tenant_id must be a valid UUID-compatible string")

        model = self._to_model(cluster)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, cluster):
        """Update cluster metadata."""
        stmt = select(ClusterModel).where(ClusterModel.id == _coerce_uuid(cluster.id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise ValueError(f"Cluster not found: {cluster.id}")

        model.label = cluster.label
        model.user_confirmed = cluster.user_confirmed
        model.identity_count = cluster.identity_count
        rep_uuid = _coerce_uuid(cluster.representative_identity_id) if cluster.representative_identity_id else None
        model.representative_identity_id = rep_uuid
        if cluster.clustering_algorithm:
            model.clustering_algorithm = cluster.clustering_algorithm

        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def delete(self, cluster_id: str) -> None:
        """Delete a cluster."""
        stmt = select(ClusterModel).where(ClusterModel.id == _coerce_uuid(cluster_id))
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()

    async def refresh_centroids_view(self) -> None:
        """Refresh the materialized view for cluster centroids.

        PostgreSQL refreshes the materialized view; SQLite rebuilds the shadow
        table directly. INFRA-5: failures propagate (fail-fast) instead of being
        swallowed — a silently-stale MV would feed wrong centroids to downstream
        reads and merge-suggestion generation.
        """
        if is_sqlite(self._session):
            await self._session.execute(text("DELETE FROM mv_identity_cluster_centroids"))
            # FIR23-01: frame membership to the majority embedding_model per
            # cluster (lex-stable tie-break). SQLite shadow table keeps centroid
            # NULL (no vector avg); the model predicate still gates identity_count.
            # Single-model tenants are a no-op.
            await self._session.execute(
                text(
                    """
                    INSERT INTO mv_identity_cluster_centroids (
                        cluster_id,
                        tenant_id,
                        identity_count,
                        centroid,
                        refreshed_at
                    )
                    WITH member_rows AS (
                        SELECT
                            im.cluster_id AS cluster_id,
                            ic.tenant_id AS tenant_id,
                            mi.embedding_model AS embedding_model,
                            mi.updated_at AS updated_at,
                            ic.updated_at AS cluster_updated_at
                        FROM identity_members im
                        JOIN identity_clusters ic ON ic.id = im.cluster_id
                        JOIN media_identities mi ON mi.id = im.identity_id
                        WHERE mi.embedding IS NOT NULL
                          AND mi.embedding_model IS NOT NULL
                    ),
                    model_counts AS (
                        SELECT
                            cluster_id,
                            embedding_model,
                            COUNT(*) AS n
                        FROM member_rows
                        GROUP BY cluster_id, embedding_model
                    ),
                    chosen_model AS (
                        SELECT
                            mc.cluster_id AS cluster_id,
                            mc.embedding_model AS embedding_model
                        FROM model_counts mc
                        WHERE mc.n = (
                            SELECT MAX(mc2.n) FROM model_counts mc2
                            WHERE mc2.cluster_id = mc.cluster_id
                        )
                        AND mc.embedding_model = (
                            SELECT MIN(mc3.embedding_model) FROM model_counts mc3
                            WHERE mc3.cluster_id = mc.cluster_id
                              AND mc3.n = mc.n
                        )
                    )
                    SELECT
                        mr.cluster_id,
                        mr.tenant_id,
                        COUNT(*) AS identity_count,
                        NULL AS centroid,
                        COALESCE(MAX(mr.updated_at), MAX(mr.cluster_updated_at), CURRENT_TIMESTAMP) AS refreshed_at
                    FROM member_rows mr
                    JOIN chosen_model cm
                      ON cm.cluster_id = mr.cluster_id
                     AND cm.embedding_model = mr.embedding_model
                    GROUP BY mr.cluster_id, mr.tenant_id
                    """
                )
            )
            return
        # Standard (non-concurrent) refresh. CONCURRENTLY lives in the
        # _concurrent variant, which requires a unique index on the MV.
        await enable_rls_bypass(self._session)
        await self._session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
        count_result = await self._session.execute(text("SELECT COUNT(*) FROM mv_identity_cluster_centroids"))
        logger.debug(
            "Refreshed mv_identity_cluster_centroids (standard): count=%d",
            count_result.scalar_one(),
        )

    async def refresh_centroids_view_concurrent(self) -> bool:
        """Refresh the materialized view concurrently.

        This allows reads to continue during the refresh and avoids locking the table.
        It requires a unique index on the MV, which is created in the migration.

        Returns True on success, False when the refresh fails (after logging).
        """
        try:
            if is_sqlite(self._session):
                await self.refresh_centroids_view()
                return True

            # Use CONCURRENTLY for background scheduled refreshes
            # This is critical to avoid locking the MV during updates
            bind = self._session.bind
            if isinstance(bind, AsyncConnection):
                conn = await bind.execution_options(isolation_level="AUTOCOMMIT")
                await _refresh_mv_concurrent_with_bypass(conn)
                return True

            async with bind.connect() as conn:
                conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
                await _refresh_mv_concurrent_with_bypass(conn)
            return True
        except Exception:
            logger.warning("Failed to refresh centroid materialized view concurrently", exc_info=True)
            return False

    async def get_unclustered(self, tenant_id: str):
        """Return media identities not yet assigned to any cluster.

        FIR23-01: when multiple embedding_model values are present, keep only
        the active runtime model (mixed spaces must not enter clustering). A
        single-model tenant is a no-op (all rows pass).
        """
        tenant_uuid = _coerce_uuid(tenant_id)
        stmt = (
            select(MediaIdentity)
            .where(MediaIdentity.tenant_id == tenant_uuid)
            .where(~exists(select(IdentityMemberModel.id).where(IdentityMemberModel.identity_id == MediaIdentity.id)))
        )
        result = await self._session.execute(stmt)
        identities = list(result.scalars().all())
        identities = _filter_rows_to_single_embedding_model(identities)
        return [self._to_domain_identity(model) for model in identities]

    async def get_representative_count(self, cluster_id: str) -> int:
        """Count representatives for a cluster."""
        stmt = select(func.count(IdentityClusterRepresentative.id)).where(
            IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_all_representatives(self, cluster_id: str) -> list[ClusterRepresentative]:
        """Return all representative domain objects for a cluster."""
        stmt = (
            select(IdentityClusterRepresentative, MediaIdentity.image_phash, MediaIdentity.media_id)
            .join(MediaIdentity, MediaIdentity.id == IdentityClusterRepresentative.identity_id)
            .where(IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id))
        )
        result = await self._session.execute(stmt)
        reps = []
        for model_rep, phash, media_id in result:
            reps.append(
                ClusterRepresentative(
                    id=str(model_rep.id),
                    cluster_id=str(model_rep.cluster_id),
                    identity_id=str(model_rep.identity_id),
                    embedding=np.array(model_rep.embedding, dtype=np.float32),
                    created_at=model_rep.created_at,
                    tenant_id=str(model_rep.tenant_id),
                    quality_score=float(model_rep.quality_score),
                    diversity_score=float(model_rep.diversity_score) if model_rep.diversity_score else None,
                    media_id=media_id,
                    image_phash=phash,
                    is_user_selected=bool(model_rep.is_user_selected),
                    is_provisional=bool(model_rep.is_provisional),
                    pose_pitch=float(model_rep.pose_pitch) if model_rep.pose_pitch is not None else None,
                    pose_yaw=float(model_rep.pose_yaw) if model_rep.pose_yaw is not None else None,
                    pose_roll=float(model_rep.pose_roll) if model_rep.pose_roll is not None else None,
                )
            )
        return reps

    async def mark_representative_user_selected(
        self,
        representative_id: str,
        is_selected: bool = True,
    ) -> None:
        """Mark a representative as user-selected (pinned)."""
        stmt = select(IdentityClusterRepresentative).where(
            IdentityClusterRepresentative.id == _coerce_uuid(representative_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise ValueError(f"Representative {representative_id} not found")
        model.is_user_selected = is_selected
        await self._session.flush()

    async def get_user_selected_representatives(
        self,
        cluster_id: str,
    ) -> list[ClusterRepresentative]:
        """Get all user-selected representatives for a cluster."""
        stmt = (
            select(
                IdentityClusterRepresentative,
                MediaIdentity.image_phash,
                MediaIdentity.media_id,
                MediaIdentity.embedding_model,
            )
            .join(MediaIdentity, MediaIdentity.id == IdentityClusterRepresentative.identity_id)
            .where(IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id))
            .where(IdentityClusterRepresentative.is_user_selected.is_(True))
        )
        result = await self._session.execute(stmt)
        reps = []
        for model_rep, _phash, _media_id, emb_model in result:
            reps.append(
                ClusterRepresentative(
                    id=str(model_rep.id),
                    cluster_id=str(model_rep.cluster_id),
                    identity_id=str(model_rep.identity_id),
                    embedding=np.array(model_rep.embedding, dtype=np.float32),
                    created_at=model_rep.created_at,
                    tenant_id=str(model_rep.tenant_id),
                    quality_score=float(model_rep.quality_score),
                    diversity_score=float(model_rep.diversity_score) if model_rep.diversity_score else None,
                    is_user_selected=bool(model_rep.is_user_selected),
                    is_provisional=bool(model_rep.is_provisional),
                    pose_pitch=float(model_rep.pose_pitch) if model_rep.pose_pitch is not None else None,
                    pose_yaw=float(model_rep.pose_yaw) if model_rep.pose_yaw is not None else None,
                    pose_roll=float(model_rep.pose_roll) if model_rep.pose_roll is not None else None,
                    embedding_model=str(emb_model) if emb_model else None,
                )
            )
        return reps

    async def confirm_provisional_representatives(self, cluster_id: str) -> int:
        """Mark all provisional representatives in a cluster as confirmed."""
        from sqlalchemy import update

        stmt = (
            update(IdentityClusterRepresentative)
            .where(IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id))
            .where(IdentityClusterRepresentative.is_provisional.is_(True))
            .values(is_provisional=False)
        )
        result = await execute_dml(self._session, stmt)
        await self._session.flush()
        return get_rowcount(result)

    async def confirm_all_provisional_reps(self, tenant_id: str) -> int:
        """Mark all provisional representatives for a tenant as confirmed."""
        from sqlalchemy import update

        stmt = (
            update(IdentityClusterRepresentative)
            .where(IdentityClusterRepresentative.tenant_id == _coerce_uuid(tenant_id))
            .where(IdentityClusterRepresentative.is_provisional.is_(True))
            .values(is_provisional=False)
        )
        result = await execute_dml(self._session, stmt)
        await self._session.flush()
        return get_rowcount(result)

    async def cleanup_orphaned_provisional_reps(self, tenant_id: str) -> int:
        """Remove provisional reps from clusters with no active batch."""
        stmt = delete(IdentityClusterRepresentative).where(
            IdentityClusterRepresentative.tenant_id == _coerce_uuid(tenant_id),
            IdentityClusterRepresentative.is_provisional.is_(True),
        )
        result = await execute_dml(self._session, stmt)
        await self._session.flush()
        return get_rowcount(result)

    async def get_maturity_info(self, cluster_id: str, *, settings: MaturitySettings) -> ClusterMaturityInfo | None:
        """Fetch maturity information for a cluster including pose coverage."""
        cluster_uuid = _coerce_uuid(cluster_id)
        if cluster_uuid is None:
            return None

        # Query cluster info + representative count
        stmt = (
            select(
                ClusterModel.identity_count,
                ClusterModel.user_confirmed,
                func.count(IdentityClusterRepresentative.id).label("representative_count"),
            )
            .outerjoin(IdentityClusterRepresentative, ClusterModel.id == IdentityClusterRepresentative.cluster_id)
            .where(ClusterModel.id == cluster_uuid)
            .group_by(ClusterModel.id)
        )
        result = await self._session.execute(stmt)
        row = result.first()

        if not row:
            return None

        # Extract values
        identity_count = int(row.identity_count)
        user_confirmed = bool(row.user_confirmed)
        representative_count = int(row.representative_count)

        # Compute pose bucket coverage from representatives
        pose_bucket_coverage = await self._compute_pose_bucket_coverage(cluster_uuid, settings)

        # Compute domain logic
        level = compute_maturity_level(
            identity_count=identity_count,
            representative_count=representative_count,
            user_confirmed=user_confirmed,
            settings=settings,
            pose_bucket_coverage=pose_bucket_coverage,
        )
        adjustment = compute_maturity_adjustment(level, settings=settings)

        return ClusterMaturityInfo(
            level=level,
            identity_count=identity_count,
            representative_count=representative_count,
            user_confirmed=user_confirmed,
            threshold_adjustment=adjustment,
            pose_bucket_coverage=pose_bucket_coverage,
        )

    async def _compute_pose_bucket_coverage(self, cluster_id: uuid.UUID, settings: MaturitySettings) -> float:
        """Compute the fraction of pose buckets filled by cluster representatives.

        Args:
            cluster_id: Cluster UUID.
            settings: Maturity settings with bucket size and total buckets.

        Returns:
            Fraction of pose buckets covered (0.0 to 1.0).
        """
        # Get representative identities with pose data
        stmt = (
            select(MediaIdentity.pose_pitch, MediaIdentity.pose_yaw)
            .join(IdentityClusterRepresentative, MediaIdentity.id == IdentityClusterRepresentative.identity_id)
            .where(IdentityClusterRepresentative.cluster_id == cluster_id)
            .where(MediaIdentity.pose_pitch.isnot(None))
            .where(MediaIdentity.pose_yaw.isnot(None))
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        if not rows:
            return 0.0

        # Count unique pose buckets
        bucket_size = settings.pose_bucket_size
        filled_buckets: set[tuple[int, int]] = set()
        for pose_pitch, pose_yaw in rows:
            bucket = (int(pose_pitch // bucket_size), int(pose_yaw // bucket_size))
            filled_buckets.add(bucket)

        # Return coverage fraction
        total_buckets = settings.total_pose_buckets
        return len(filled_buckets) / total_buckets if total_buckets > 0 else 0.0

    async def get_curriculum_t(self, cluster_id: str) -> float | None:
        """Fetch the curriculum bias parameter for a cluster."""
        stmt = select(ClusterModel.curriculum_t).where(ClusterModel.id == _coerce_uuid(cluster_id))
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return float(value) if value is not None else None

    async def set_curriculum_t(self, cluster_id: str, value: float) -> None:
        """Persist the curriculum bias parameter for a cluster."""
        stmt = (
            update(ClusterModel)
            .where(ClusterModel.id == _coerce_uuid(cluster_id))
            .values(curriculum_t=value, curriculum_t_updated_at=datetime.now(tz=UTC))
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def update_curriculum_t_ema(self, cluster_id: str, new_similarity: float, alpha: float) -> None:
        """Atomically apply EMA update to curriculum_t using a single UPDATE expression.

        Computes: new_value = alpha * new_similarity + (1 - alpha) * current_value
        Falls back to new_similarity when curriculum_t is NULL.

        Uses ANSI SQL CASE-based clamping (compatible with SQLite and PostgreSQL).
        """
        from sqlalchemy import case, literal

        cluster_uuid = _coerce_uuid(cluster_id)
        if cluster_uuid is None:
            return

        alpha_lit = literal(alpha)
        sim_lit = literal(new_similarity)
        new_value = case(
            (ClusterModel.curriculum_t.is_(None), sim_lit),
            else_=alpha_lit * sim_lit + (literal(1.0) - alpha_lit) * ClusterModel.curriculum_t,
        )
        # Clamp to [0, 1] using ANSI CASE instead of func.greatest/func.least
        # so the expression works on both PostgreSQL and SQLite.
        clamped = case(
            (new_value < literal(0.0), literal(0.0)),
            (new_value > literal(1.0), literal(1.0)),
            else_=new_value,
        )
        stmt = (
            update(ClusterModel)
            .where(ClusterModel.id == cluster_uuid)
            .values(curriculum_t=clamped, curriculum_t_updated_at=datetime.now(tz=UTC))
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def get_member_embeddings(self, cluster_id: str) -> list[np.ndarray]:
        """Return embeddings for members of the cluster.

        FIR23-01: restrict to one embedding_model space (majority, lex tie-break).
        Single-model clusters are a no-op.
        """
        stmt = (
            select(MediaIdentity.embedding, MediaIdentity.embedding_model)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .where(IdentityMemberModel.cluster_id == _coerce_uuid(cluster_id))
            .where(MediaIdentity.embedding.isnot(None))
            .where(MediaIdentity.embedding_model.isnot(None))
        )
        result = await self._session.execute(stmt)
        rows = [(np.asarray(emb, dtype=np.float32), model) for emb, model in result.all()]
        return [emb for emb, _ in _filter_embedding_pairs_to_single_model(rows)]

    async def get_representative_embeddings_with_model(self, cluster_id: str) -> tuple[list[np.ndarray], str | None]:
        """Return representative embeddings and the model space they were filtered to.

        FIR23-01: join source identity so reps from a foreign embedding_model are
        excluded when mixed provenance exists. Single-model is a no-op.

        Returns:
            ``(embeddings, chosen_embedding_model)`` where ``chosen_embedding_model``
            is the majority/lex-stable model selected for the returned vectors, or
            ``None`` when nothing was returned or no model could be determined.
        """
        stmt = (
            select(IdentityClusterRepresentative.embedding, MediaIdentity.embedding_model)
            .join(MediaIdentity, MediaIdentity.id == IdentityClusterRepresentative.identity_id)
            .where(IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id))
            .where(MediaIdentity.embedding_model.isnot(None))
        )
        result = await self._session.execute(stmt)
        rows = [(np.asarray(emb, dtype=np.float32), model) for emb, model in result.all()]
        filtered = _filter_embedding_pairs_to_single_model(rows)
        if not filtered:
            return [], None
        embeddings = [emb for emb, _ in filtered]
        # Chosen model is what the filter selected for the returned vectors —
        # re-derive via the same majority/lex helper (never rows[0] alone).
        chosen = _choose_embedding_model([model for _, model in filtered])
        return embeddings, chosen

    async def get_representative_embeddings(self, cluster_id: str) -> list[np.ndarray]:
        """Return embeddings for stored representatives of a cluster.

        FIR23-01: join source identity so reps from a foreign embedding_model are
        excluded when mixed provenance exists. Single-model is a no-op.
        """
        embeddings, _ = await self.get_representative_embeddings_with_model(cluster_id)
        return embeddings

    async def get_member_fallback_embeddings_with_model(
        self, cluster_id: str, limit: int = 4
    ) -> tuple[list[np.ndarray], str | None]:
        """Return top member fallback embeddings and the model space they belong to.

        Ordered by similarity then recency. Mixed-model sets are reduced to one
        space via ``_filter_embedding_pairs_to_single_model`` before the limit.

        Returns:
            ``(embeddings, chosen_embedding_model)`` — same semantics as
            ``get_representative_embeddings_with_model``.
        """
        stmt = (
            select(MediaIdentity.embedding, MediaIdentity.embedding_model)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .where(IdentityMemberModel.cluster_id == _coerce_uuid(cluster_id))
            .where(MediaIdentity.embedding.isnot(None))
            .where(MediaIdentity.embedding_model.isnot(None))
            .order_by(IdentityMemberModel.similarity.desc(), IdentityMemberModel.assigned_at.asc())
        )
        result = await self._session.execute(stmt)
        rows = [(np.asarray(emb, dtype=np.float32), model) for emb, model in result.all()]
        filtered = _filter_embedding_pairs_to_single_model(rows)
        if limit is not None:
            filtered = filtered[: max(limit, 0)]
        if not filtered:
            return [], None
        embeddings = [emb for emb, _ in filtered]
        chosen = _choose_embedding_model([model for _, model in filtered])
        return embeddings, chosen

    async def get_member_fallback_embeddings(self, cluster_id: str, limit: int = 4) -> list[np.ndarray]:
        """Return top member embeddings as fallback representatives ordered by similarity then recency."""
        embeddings, _ = await self.get_member_fallback_embeddings_with_model(cluster_id, limit=limit)
        return embeddings

    async def get_member_identities(self, cluster_id: str) -> list[DomainIdentity]:
        """Return identity records for all members of a cluster.

        FIR23-01: when mixed embedding_model values exist in the cluster, keep
        only the majority model (lex tie-break). Single-model is a no-op.
        """
        stmt: Select[tuple[MediaIdentity]] = (
            select(MediaIdentity)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .where(IdentityMemberModel.cluster_id == _coerce_uuid(cluster_id))
        )
        result = await self._session.execute(stmt)
        models = _filter_identity_models_to_single_embedding_model(list(result.scalars().all()))
        return [self._to_domain_identity(model, cluster_id=cluster_id) for model in models]

    async def get_member_identities_for_clusters(self, cluster_ids: Sequence[str]) -> dict[str, list[DomainIdentity]]:
        """Return identity records for members across multiple clusters, grouped by cluster."""
        cluster_uuids = [_coerce_uuid(cluster_id) for cluster_id in cluster_ids]
        cluster_uuids = [cluster_id for cluster_id in cluster_uuids if cluster_id is not None]
        if not cluster_uuids:
            return {}

        stmt: Select[tuple[MediaIdentity, uuid.UUID]] = (
            select(MediaIdentity, IdentityMemberModel.cluster_id)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .where(IdentityMemberModel.cluster_id.in_(cluster_uuids))
            .where(MediaIdentity.embedding.isnot(None))
        )
        result = await self._session.execute(stmt)
        raw_grouped: dict[str, list[MediaIdentity]] = defaultdict(list)
        for model, cluster_id in result.all():
            if not cluster_id:
                continue
            raw_grouped[str(cluster_id)].append(model)
        grouped: dict[str, list[DomainIdentity]] = {}
        for cluster_key, models in raw_grouped.items():
            kept = _filter_identity_models_to_single_embedding_model(models)
            grouped[cluster_key] = [self._to_domain_identity(model, cluster_id=cluster_key) for model in kept]
        return grouped

    async def get_confirmed_labeled(self, tenant_id: str) -> list[IdentityCluster]:
        """Return confirmed clusters with human labels."""
        stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == _coerce_uuid(tenant_id))
            .where(ClusterModel.user_confirmed.is_(True))
            .where(ClusterModel.label.is_not(None))
            .where(~ClusterModel.label.startswith("cluster-"))
            .order_by(ClusterModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(model) for model in result.scalars().all()]

    async def get_unlabeled_created_after(self, tenant_id: str, *, minutes_ago: int) -> list[IdentityCluster]:
        """Return unlabeled clusters created within the provided time window."""
        tenant_uuid = _coerce_uuid(tenant_id)
        if tenant_uuid is None or minutes_ago <= 0:
            return []

        window_start = datetime.now(tz=UTC) - timedelta(minutes=minutes_ago)
        stmt: Select[tuple[ClusterModel]] = select(ClusterModel).where(
            ClusterModel.tenant_id == tenant_uuid,
            or_(
                ClusterModel.user_confirmed.is_(False),
                ClusterModel.label.is_(None),
                ClusterModel.label.startswith("cluster-"),
            ),
            ClusterModel.created_at >= window_start,
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(model) for model in result.scalars().all()]

    async def get_member_identity_count(self, cluster_id: str) -> int:
        """Return the number of identities currently assigned to a cluster."""
        cluster_uuid = _coerce_uuid(cluster_id)
        if cluster_uuid is None:
            return 0

        stmt = (
            select(func.count()).select_from(IdentityMemberModel).where(IdentityMemberModel.cluster_id == cluster_uuid)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_member_identities_with_similarity(
        self,
        cluster_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[MediaIdentity, float]]:
        """Return identity ORM records with their membership similarity for a cluster.

        Unlike get_member_identities, this returns the raw ORM model
        and the similarity score from the member record, for API responses.
        """
        if limit is not None and limit <= 0:
            return []
        if offset < 0:
            offset = 0

        stmt = (
            select(MediaIdentity, IdentityMemberModel.similarity)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .where(IdentityMemberModel.cluster_id == _coerce_uuid(cluster_id))
            .order_by(IdentityMemberModel.assigned_at, IdentityMemberModel.identity_id)
        )
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]

    async def get_roster_entry_name(self, roster_id: str) -> str | None:
        """Resolve a roster UUID from existing cluster labels only."""
        roster_uuid = _coerce_uuid(roster_id)
        if roster_uuid is None:
            return None

        result = await self._session.execute(
            select(ClusterModel.label)
            .where(ClusterModel.roster_id == roster_uuid)
            .where(ClusterModel.label.isnot(None))
            .where(ClusterModel.label != "")
            .where(~ClusterModel.label.startswith("cluster-"))
            .order_by(ClusterModel.user_confirmed.desc(), ClusterModel.updated_at.desc())
            .limit(1)
        )
        roster_name = result.scalar_one_or_none()
        if roster_name is None:
            return None

        normalized = str(roster_name).strip()
        return normalized or None

    async def get_members(self, cluster_id: str) -> list[DomainMember]:
        """Return member records for a cluster."""
        stmt: Select[tuple[IdentityMemberModel]] = select(IdentityMemberModel).where(
            IdentityMemberModel.cluster_id == _coerce_uuid(cluster_id)
        )
        result = await self._session.execute(stmt)
        return [
            DomainMember(
                id=str(member.id),
                cluster_id=str(member.cluster_id),
                identity_id=str(member.identity_id),
                similarity=float(member.similarity),
                tenant_id=str(member.tenant_id) if member.tenant_id else None,
                assigned_at=member.assigned_at,
            )
            for member in result.scalars().all()
        ]

    async def get_singleton_identities(
        self,
        tenant_id: str,
        *,
        limit: int | None = None,
    ) -> list[DomainIdentity]:
        """Fetch identities that belong to singleton clusters for a tenant.

        FIR23-01: mixed embedding_model rows are reduced to one model space.
        """
        stmt: Select[tuple[MediaIdentity, uuid.UUID]] = (
            select(MediaIdentity, IdentityMemberModel.cluster_id)
            .join(IdentityMemberModel, IdentityMemberModel.identity_id == MediaIdentity.id)
            .join(ClusterModel, ClusterModel.id == IdentityMemberModel.cluster_id)
            .where(ClusterModel.tenant_id == _coerce_uuid(tenant_id))
            .where(ClusterModel.identity_count == 1)
            .where(ClusterModel.user_confirmed.is_(False))
            .where(MediaIdentity.embedding.isnot(None))
            .order_by(ClusterModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        raw: list[tuple[MediaIdentity, uuid.UUID | None]] = list(result.all())
        models = _filter_rows_to_single_embedding_model([m for m, _ in raw])
        kept_ids = {id(m) for m in models}
        identities: list[DomainIdentity] = []
        for model, cluster_id in raw:
            if id(model) not in kept_ids:
                continue
            identities.append(
                self._to_domain_identity(
                    model,
                    cluster_id=str(cluster_id) if cluster_id else None,
                )
            )
            if limit is not None and len(identities) >= limit:
                break
        return identities

    async def assign_identity_to_cluster(self, identity: DomainIdentity, cluster_id: str) -> None:
        """Persist a membership between an identity and cluster."""
        member = IdentityMemberModel(
            tenant_id=_coerce_uuid(identity.tenant_id),
            cluster_id=_coerce_uuid(cluster_id),
            identity_id=_coerce_uuid(identity.id),
            similarity=0.0,
        )
        self._session.add(member)
        await self._session.flush()

    async def add_representative(self, representative: ClusterRepresentative) -> None:
        """Persist a representative embedding for a cluster."""
        rep = IdentityClusterRepresentative(
            id=_coerce_uuid(representative.id) if representative.id else None,
            tenant_id=_coerce_uuid(representative.tenant_id),
            cluster_id=_coerce_uuid(representative.cluster_id),
            identity_id=_coerce_uuid(representative.identity_id),
            embedding=list(representative.embedding),
            quality_score=float(getattr(representative, "quality_score", 1.0)),
            diversity_score=getattr(representative, "diversity_score", None),
            is_user_selected=getattr(representative, "is_user_selected", False),
            is_provisional=getattr(representative, "is_provisional", False),
            pose_pitch=float(representative.pose_pitch) if representative.pose_pitch is not None else None,
            pose_yaw=float(representative.pose_yaw) if representative.pose_yaw is not None else None,
            pose_roll=float(representative.pose_roll) if representative.pose_roll is not None else None,
        )
        self._session.add(rep)
        await self._session.flush()

    async def remove_representative(self, representative_id: str) -> None:
        """Remove a specific representative."""
        stmt = delete(IdentityClusterRepresentative).where(
            IdentityClusterRepresentative.id == _coerce_uuid(representative_id)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def clear_representatives(self, cluster_id: str) -> None:
        """Remove all stored representatives for a cluster."""
        stmt = delete(IdentityClusterRepresentative).where(
            IdentityClusterRepresentative.cluster_id == _coerce_uuid(cluster_id)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def count_labeled(self) -> int:
        """Count clusters with user-provided labels (not auto-generated like 'cluster-xxx').

        Uses RLS (Row Level Security) to filter by current tenant context.
        """
        stmt = select(func.count(ClusterModel.id)).where(
            ClusterModel.label.is_not(None),
            ~ClusterModel.label.startswith("cluster-"),
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    def _to_domain(self, model: ClusterModel) -> IdentityCluster:
        """Convert a SQLAlchemy model into the domain object."""
        # Convert representatives only if eagerly loaded (via selectinload)
        # Check if the relationship has been loaded to avoid triggering lazy load
        domain_reps: list[ClusterRepresentative] = []
        state = instance_state(model)
        if "representatives" in state.dict:
            # Relationship was eagerly loaded, safe to access
            model_reps = model.representatives
            representative_count = len(model_reps)

            # Compute pose buckets summary for the whole cluster
            filled_buckets = set()
            bucket_size = 30.0  # Default from ClusteringSettings
            for r in model_reps:
                if r.identity:
                    pitch = r.identity.pose_pitch
                    yaw = r.identity.pose_yaw
                    if pitch is not None and yaw is not None:
                        filled_buckets.add((int(pitch // bucket_size), int(yaw // bucket_size)))

            for rep in model_reps:
                if rep.disposed_at is not None:
                    continue
                # Extract debug metrics from identity if loaded
                rep_state = instance_state(rep)
                debug_metrics = None
                media_id = None
                media_url = None
                bbox_x = None
                bbox_y = None
                bbox_width = None
                bbox_height = None
                identity_loaded = "identity" in rep_state.dict and rep.identity is not None
                # R3-G2-2: stamp embedding_model only from an already-loaded identity.
                # Never lazy-load and never invent a default model id.
                embedding_model: str | None = None
                if identity_loaded:
                    identity = rep.identity
                    media_id = identity.media_id
                    media_url = identity.media_url
                    bbox_x = int(identity.bbox_x) if identity.bbox_x is not None else None
                    bbox_y = int(identity.bbox_y) if identity.bbox_y is not None else None
                    bbox_width = int(identity.bbox_width) if identity.bbox_width is not None else None
                    bbox_height = int(identity.bbox_height) if identity.bbox_height is not None else None
                    raw_model = getattr(identity, "embedding_model", None)
                    embedding_model = str(raw_model) if raw_model else None
                    logger.debug(
                        "Loaded representative identity pose rep_id=%s identity_id=%s pose_pitch=%s pose_yaw=%s",
                        rep.id,
                        identity.id,
                        identity.pose_pitch,
                        identity.pose_yaw,
                    )
                    debug_metrics = {
                        "pose": {
                            "pitch": float(identity.pose_pitch or 0),
                            "yaw": float(identity.pose_yaw or 0),
                            "roll": float(identity.pose_roll or 0),
                        },
                        "det_score": float(identity.confidence),
                        "bbox_area": int(identity.bbox_width * identity.bbox_height),
                        "landmark_quality": float(identity.quality_score or 1.0),
                        "clustering_method": None,
                        "clustering_algorithm": None,
                        "similarity_threshold": None,
                        "match_similarity": None,
                        "representative_count": representative_count,
                        "pose_buckets": {
                            "filled": len(filled_buckets),
                            "total": 13,  # 10 base + 3 bonus
                            "current_bucket": (
                                int(identity.pose_pitch // bucket_size),
                                int(identity.pose_yaw // bucket_size),
                            )
                            if identity.pose_pitch is not None and identity.pose_yaw is not None
                            else None,
                        },
                    }
                else:
                    logger.debug(
                        "Representative identity not loaded rep_id=%s identity_loaded=%s",
                        rep.id,
                        identity_loaded,
                    )
                if identity_loaded and identity is not None and identity.disposed_at is not None:
                    continue
                domain_reps.append(
                    ClusterRepresentative(
                        id=str(rep.id),
                        cluster_id=str(rep.cluster_id),
                        identity_id=str(rep.identity_id),
                        embedding=np.array(rep.embedding, dtype=np.float32),
                        created_at=rep.created_at,
                        tenant_id=str(rep.tenant_id) if rep.tenant_id else None,
                        quality_score=float(rep.quality_score),
                        diversity_score=float(rep.diversity_score) if rep.diversity_score else None,
                        media_id=media_id,
                        media_url=media_url,
                        bbox_x=bbox_x,
                        bbox_y=bbox_y,
                        bbox_width=bbox_width,
                        bbox_height=bbox_height,
                        is_user_selected=bool(rep.is_user_selected),
                        is_provisional=bool(rep.is_provisional),
                        debug_metrics=debug_metrics,
                        embedding_model=embedding_model,
                    )
                )

        # Extract centroid from materialized view relationship if available
        centroid = None
        if hasattr(model, "centroid_data") and model.centroid_data is not None:
            centroid = np.array(model.centroid_data.centroid, dtype=np.float32)

        return IdentityCluster(
            id=str(model.id) if model.id else None,
            tenant_id=str(model.tenant_id),
            label=model.label,
            is_labeled=bool(model.label),
            identity_count=model.identity_count,
            created_at=model.created_at if isinstance(model.created_at, datetime) else None,
            representative_identity_id=str(model.representative_identity_id)
            if model.representative_identity_id
            else None,
            clustering_algorithm=model.clustering_algorithm,
            user_confirmed=model.user_confirmed,
            dismissed_at=model.dismissed_at if isinstance(model.dismissed_at, datetime) else None,
            representatives=domain_reps,
            centroid=centroid,
        )

    async def get_snapshot(
        self, tenant_id: str, *, stamp_export: bool = False
    ) -> tuple[list[IdentityCluster], list[tuple[DomainMember, DomainIdentity]], int, str | None]:
        """Get complete cluster snapshot for tenant projection."""
        tenant_uuid = _coerce_uuid(tenant_id)
        if tenant_uuid is None:
            return ([], [], 0, None)

        snapshot_generation_id = str(uuid.uuid4()) if stamp_export else None

        # Fetch all clusters
        clusters_stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == tenant_uuid)
            .where(ClusterModel.disposed_at.is_(None))
            .options(selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity))
            .order_by(ClusterModel.created_at)
        )
        clusters_result = await self._session.execute(clusters_stmt)
        cluster_models = list(clusters_result.scalars().all())

        # Compute snapshot_version from max updated_at with microsecond precision so
        # curation replay can detect multiple mutations within the same second.
        max_updated_at = max((c.updated_at for c in cluster_models), default=_SNAPSHOT_EPOCH)
        snapshot_version = _datetime_to_snapshot_version(max_updated_at)

        # Fetch all members with identity data
        members_stmt = (
            select(IdentityMemberModel, MediaIdentity)
            .join(MediaIdentity, IdentityMemberModel.identity_id == MediaIdentity.id)
            .join(ClusterModel, IdentityMemberModel.cluster_id == ClusterModel.id)
            .where(ClusterModel.tenant_id == tenant_uuid)
            .where(ClusterModel.disposed_at.is_(None))
            .where(MediaIdentity.disposed_at.is_(None))
            .order_by(IdentityMemberModel.cluster_id, IdentityMemberModel.assigned_at)
        )
        members_result = await self._session.execute(members_stmt)
        member_rows = list(members_result.all())
        name_suggestion_rows = []
        if snapshot_generation_id is not None:
            name_suggestion_stmt = (
                select(NameSuggestionModel)
                .join(ClusterModel, NameSuggestionModel.cluster_id == ClusterModel.id)
                .where(NameSuggestionModel.tenant_id == tenant_uuid)
                .where(NameSuggestionModel.resolution == "pending")
                .where(NameSuggestionModel.disposed_at.is_(None))
                .where(ClusterModel.disposed_at.is_(None))
                .order_by(NameSuggestionModel.created_at, NameSuggestionModel.id)
            )
            name_suggestion_result = await self._session.execute(name_suggestion_stmt)
            name_suggestion_rows = list(name_suggestion_result.scalars().all())

        if snapshot_generation_id is not None:
            snapshot_generation_uuid = uuid.UUID(snapshot_generation_id)
            for cluster_model in cluster_models:
                cluster_model.last_exported_snapshot_id = snapshot_generation_uuid
                for representative in cluster_model.representatives:
                    if representative.disposed_at is not None:
                        continue
                    if representative.identity is not None and representative.identity.disposed_at is not None:
                        continue
                    representative.last_exported_snapshot_id = snapshot_generation_uuid

            seen_identity_ids: set[uuid.UUID] = set()
            for _member_model, identity_model in member_rows:
                if identity_model.id in seen_identity_ids:
                    continue
                identity_model.last_exported_snapshot_id = snapshot_generation_uuid
                seen_identity_ids.add(identity_model.id)

            for suggestion in name_suggestion_rows:
                suggestion.last_exported_snapshot_id = snapshot_generation_uuid

            if cluster_models or seen_identity_ids or name_suggestion_rows:
                await self._session.flush()

        # Convert to domain objects
        clusters = [self._to_domain(model) for model in cluster_models]

        members_with_identities: list[tuple[DomainMember, DomainIdentity]] = []
        for member_model, identity_model in member_rows:
            domain_member = DomainMember(
                id=str(member_model.id),
                cluster_id=str(member_model.cluster_id),
                identity_id=str(member_model.identity_id),
                similarity=float(member_model.similarity),
                tenant_id=str(member_model.tenant_id) if member_model.tenant_id else None,
                assigned_at=member_model.assigned_at if isinstance(member_model.assigned_at, datetime) else None,
            )
            domain_identity = self._to_domain_identity(identity_model, cluster_id=str(member_model.cluster_id))
            members_with_identities.append((domain_member, domain_identity))

        return (clusters, members_with_identities, snapshot_version, snapshot_generation_id)

    async def get_delta(
        self,
        tenant_id: str,
        *,
        since_version: int,
    ) -> tuple[list[IdentityCluster], list[tuple[DomainMember, DomainIdentity]], int]:
        """Get the current state for clusters changed since a prior snapshot version.

        v0 delta reads return full cluster/member state for clusters whose
        `updated_at` exceeds `since_version`. Destructive changes that remove an
        entire cluster still require higher-layer fallback to a full snapshot
        until tombstone semantics are added to the HTTP contract.
        """
        tenant_uuid = _coerce_uuid(tenant_id)
        if tenant_uuid is None:
            return ([], [], 0)

        since_updated_at = _snapshot_version_to_datetime(since_version)
        snapshot_version = await self.get_snapshot_version(tenant_id)

        clusters_stmt: Select[tuple[ClusterModel]] = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == tenant_uuid)
            .where(ClusterModel.disposed_at.is_(None))
            .where(ClusterModel.updated_at > since_updated_at)
            .options(selectinload(ClusterModel.representatives).selectinload(IdentityClusterRepresentative.identity))
            .order_by(ClusterModel.updated_at.asc(), ClusterModel.created_at.asc())
        )
        clusters_result = await self._session.execute(clusters_stmt)
        cluster_models = list(clusters_result.scalars().all())
        if not cluster_models:
            return ([], [], snapshot_version)

        cluster_ids = [model.id for model in cluster_models if model.id is not None]
        members_stmt = (
            select(IdentityMemberModel, MediaIdentity)
            .join(MediaIdentity, IdentityMemberModel.identity_id == MediaIdentity.id)
            .join(ClusterModel, IdentityMemberModel.cluster_id == ClusterModel.id)
            .where(ClusterModel.tenant_id == tenant_uuid)
            .where(ClusterModel.disposed_at.is_(None))
            .where(IdentityMemberModel.cluster_id.in_(cluster_ids))
            .where(MediaIdentity.disposed_at.is_(None))
            .order_by(IdentityMemberModel.cluster_id, IdentityMemberModel.assigned_at)
        )
        members_result = await self._session.execute(members_stmt)
        member_rows = list(members_result.all())

        clusters = [self._to_domain(model) for model in cluster_models]
        members_with_identities: list[tuple[DomainMember, DomainIdentity]] = []
        for member_model, identity_model in member_rows:
            domain_member = DomainMember(
                id=str(member_model.id),
                cluster_id=str(member_model.cluster_id),
                identity_id=str(member_model.identity_id),
                similarity=float(member_model.similarity),
                tenant_id=str(member_model.tenant_id) if member_model.tenant_id else None,
                assigned_at=member_model.assigned_at if isinstance(member_model.assigned_at, datetime) else None,
            )
            domain_identity = self._to_domain_identity(identity_model, cluster_id=str(member_model.cluster_id))
            members_with_identities.append((domain_member, domain_identity))

        return (clusters, members_with_identities, snapshot_version)

    async def get_members_by_cluster_ids(
        self, tenant_id: str, cluster_ids: Sequence[str]
    ) -> list[tuple[DomainMember, DomainIdentity]]:
        """Fetch member+identity tuples for a targeted set of clusters."""
        tenant_uuid = _coerce_uuid(tenant_id)
        cluster_uuids = [_coerce_uuid(cluster_id) for cluster_id in cluster_ids]
        cluster_uuids = [cluster_uuid for cluster_uuid in cluster_uuids if cluster_uuid is not None]
        if tenant_uuid is None or not cluster_uuids:
            return []

        members_stmt = (
            select(IdentityMemberModel, MediaIdentity)
            .join(MediaIdentity, IdentityMemberModel.identity_id == MediaIdentity.id)
            .join(ClusterModel, IdentityMemberModel.cluster_id == ClusterModel.id)
            .where(ClusterModel.tenant_id == tenant_uuid)
            .where(IdentityMemberModel.cluster_id.in_(cluster_uuids))
            .order_by(IdentityMemberModel.cluster_id, IdentityMemberModel.assigned_at)
        )
        members_result = await self._session.execute(members_stmt)
        member_rows = list(members_result.all())

        members_with_identities: list[tuple[DomainMember, DomainIdentity]] = []
        for member_model, identity_model in member_rows:
            domain_member = DomainMember(
                id=str(member_model.id),
                cluster_id=str(member_model.cluster_id),
                identity_id=str(member_model.identity_id),
                similarity=float(member_model.similarity),
                tenant_id=str(member_model.tenant_id) if member_model.tenant_id else None,
                assigned_at=member_model.assigned_at if isinstance(member_model.assigned_at, datetime) else None,
            )
            domain_identity = self._to_domain_identity(identity_model, cluster_id=str(member_model.cluster_id))
            members_with_identities.append((domain_member, domain_identity))

        return members_with_identities

    async def get_clusters_by_ids(self, tenant_id: str, cluster_ids: Sequence[str]) -> list[IdentityCluster]:
        """Fetch cluster summaries for a targeted set of clusters."""
        tenant_uuid = _coerce_uuid(tenant_id)
        cluster_uuids = [_coerce_uuid(cluster_id) for cluster_id in cluster_ids]
        cluster_uuids = [cluster_uuid for cluster_uuid in cluster_uuids if cluster_uuid is not None]
        if tenant_uuid is None or not cluster_uuids:
            return []

        stmt = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == tenant_uuid)
            .where(ClusterModel.id.in_(cluster_uuids))
            .order_by(ClusterModel.updated_at.asc(), ClusterModel.created_at.asc())
        )
        result = await self._session.execute(stmt)
        cluster_models = list(result.scalars().all())

        clusters: list[IdentityCluster] = []
        for model in cluster_models:
            clusters.append(
                IdentityCluster(
                    id=str(model.id),
                    tenant_id=str(model.tenant_id),
                    label=model.label,
                    is_labeled=bool(model.label),
                    identity_count=int(model.identity_count),
                    user_confirmed=bool(model.user_confirmed),
                    created_at=model.created_at if isinstance(model.created_at, datetime) else None,
                    dismissed_at=model.dismissed_at if isinstance(model.dismissed_at, datetime) else None,
                    representatives=[],
                )
            )

        return clusters

    async def get_snapshot_version(self, tenant_id: str) -> int:
        """Fetch the tenant snapshot version without loading full snapshot rows."""
        tenant_uuid = _coerce_uuid(tenant_id)
        if tenant_uuid is None:
            return 0

        stmt = select(func.max(ClusterModel.updated_at)).where(ClusterModel.tenant_id == tenant_uuid)
        result = await self._session.execute(stmt)
        max_updated_at = result.scalar_one_or_none()
        return _datetime_to_snapshot_version(max_updated_at)

    def _to_domain_identity(self, model: MediaIdentity, *, cluster_id: str | None = None) -> DomainIdentity:
        """Convert MediaIdentity ORM model to domain representation."""
        return DomainIdentity(
            id=str(model.id),
            tenant_id=str(model.tenant_id),
            media_id=str(model.media_id),
            embedding=np.asarray(model.embedding, dtype=np.float32),
            confidence=float(model.confidence),
            bbox_width=int(model.bbox_width),
            bbox_height=int(model.bbox_height),
            bbox_x=int(model.bbox_x),
            bbox_y=int(model.bbox_y),
            pose_pitch=float(model.pose_pitch) if model.pose_pitch is not None else None,
            pose_yaw=float(model.pose_yaw) if model.pose_yaw is not None else None,
            pose_roll=float(model.pose_roll) if model.pose_roll is not None else None,
            image_phash=model.image_phash,
            sharpness=float(model.sharpness) if model.sharpness is not None else None,
            embedding_norm=float(model.embedding_norm) if model.embedding_norm is not None else None,
            occlusion_severity=(float(model.occlusion_severity) if model.occlusion_severity is not None else None),
            cluster_id=cluster_id,
            moved_by_merge_id=str(model.moved_by_merge_id) if getattr(model, "moved_by_merge_id", None) else None,
        )

    def _to_model(self, cluster: IdentityCluster) -> ClusterModel:
        """Convert a domain cluster into a SQLAlchemy model instance."""
        model_kwargs: dict[str, Any] = {
            "tenant_id": _coerce_uuid(cluster.tenant_id),
            "label": cluster.label,
            "identity_count": cluster.identity_count,
            "clustering_algorithm": cluster.clustering_algorithm,
            "user_confirmed": cluster.user_confirmed,
        }

        if cluster.id is not None:
            model_kwargs["id"] = _coerce_uuid(cluster.id)
        if cluster.representative_identity_id:
            model_kwargs["representative_identity_id"] = _coerce_uuid(cluster.representative_identity_id)
        if cluster.created_at:
            model_kwargs["created_at"] = cluster.created_at
        if cluster.dismissed_at:
            model_kwargs["dismissed_at"] = cluster.dismissed_at

        return ClusterModel(**model_kwargs)
