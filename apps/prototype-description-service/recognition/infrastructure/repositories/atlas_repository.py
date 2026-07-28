"""Atlas read repository — tenant embeddings + centroid MV with fallback.

Caller owns the session. For cross-tenant / maintenance jobs, open the session
via ``async_session_factory`` and call ``enable_rls_bypass`` (mirror
``admin.get_admin_session`` at ``routers/admin.py:67–89`` and the
``SET LOCAL app.bypass_rls`` pattern in ``scripts/utilities/compare_media_embeddings.py``).
This repository does not open its own engine.

The centroids MV is **global** (``SqlAlchemyClusterRepository.refresh_centroids_view``).
This repository never refreshes per-tenant: it reads the current MV state and
exposes the MV refresh timestamp for the builder to record into
``params["centroids_mv_refreshed_at"]``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
import numpy as np
from sqlalchemy import distinct, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ClusterCentroid, IdentityMember, MediaIdentity
from recognition.application.clustering.centroid_utils import compute_centroid
from recognition.infrastructure.repositories._helpers import coerce_uuid as _coerce_uuid
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.shared.db.dialect import is_sqlite


class MixedEmbeddingModelError(ValueError):
    """EMB-01 fail-closed: tenant rows exist for embedding models other than the requested one.

    Raised when mixed models are present and ``allow_partial`` is false.
    Must not be silenced by majority-model filtering.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        requested_model: str,
        foreign_models: Sequence[str],
    ) -> None:
        self.tenant_id = tenant_id
        self.requested_model = requested_model
        self.foreign_models = tuple(sorted({str(m) for m in foreign_models if m}))
        models_fmt = ", ".join(repr(m) for m in self.foreign_models) or "(none)"
        super().__init__(
            f"EMB-01: tenant {tenant_id!r} has embeddings from foreign model(s) "
            f"{models_fmt}; requested {requested_model!r}. "
            f"Refuse mixed-model fit; pass allow_partial=True to use only the requested model."
        )


class AtlasRepository:
    """Read path for atlas build: model-filtered embeddings + cluster centroids."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._clusters = SqlAlchemyClusterRepository(session)

    async def list_foreign_embedding_models(
        self,
        tenant_id: str,
        embedding_model: str,
    ) -> list[str]:
        """Return distinct embedding_model values for tenant rows that are not ``embedding_model``.

        Dedicated COUNT/EXISTS surface for EMB-01. Filters at the SQL boundary:
        rows with non-null embedding whose embedding_model differs from the request.
        """
        tenant_uuid = _require_tenant_uuid(tenant_id)
        stmt = (
            select(distinct(MediaIdentity.embedding_model))
            .where(MediaIdentity.tenant_id == tenant_uuid)
            .where(MediaIdentity.embedding.isnot(None))
            .where(MediaIdentity.embedding_model != embedding_model)
            .order_by(MediaIdentity.embedding_model.asc())
        )
        result = await self._session.execute(stmt)
        return [str(m) for m in result.scalars().all() if m]

    async def assert_requested_embedding_model(
        self,
        tenant_id: str,
        embedding_model: str,
        *,
        allow_partial: bool = False,
    ) -> None:
        """EMB-01 fail-closed guard.

        Runs a dedicated foreign-model query. If any foreign models exist and
        ``allow_partial`` is false, raises :class:`MixedEmbeddingModelError`.

        Intentionally does **not** call or reuse
        ``_filter_embedding_pairs_to_single_model`` (silent majority filter).
        """
        foreign = await self.list_foreign_embedding_models(tenant_id, embedding_model)
        if foreign and not allow_partial:
            raise MixedEmbeddingModelError(
                tenant_id=str(tenant_id),
                requested_model=embedding_model,
                foreign_models=foreign,
            )

    async def iter_tenant_embeddings(
        self,
        tenant_id: str,
        embedding_model: str,
        *,
        allow_partial: bool = False,
    ) -> AsyncIterator[tuple[uuid.UUID, int, uuid.UUID | None, np.ndarray]]:
        """Yield ``(identity_id, media_id, cluster_id, embedding)`` for one model.

        Filtering to ``embedding_model`` happens at the SQL boundary (WHERE),
        never via post-filter majority selection. EMB-01 is enforced first.
        ``cluster_id`` is the current membership (NULL when unclustered).
        """
        await self.assert_requested_embedding_model(
            tenant_id,
            embedding_model,
            allow_partial=allow_partial,
        )
        tenant_uuid = _require_tenant_uuid(tenant_id)

        # SQL-boundary filter: only the requested model. Never majority-filter in Python.
        stmt = (
            select(
                MediaIdentity.id,
                MediaIdentity.media_id,
                IdentityMember.cluster_id,
                MediaIdentity.embedding,
            )
            .outerjoin(IdentityMember, IdentityMember.identity_id == MediaIdentity.id)
            .where(MediaIdentity.tenant_id == tenant_uuid)
            .where(MediaIdentity.embedding.isnot(None))
            .where(MediaIdentity.embedding_model == embedding_model)
            .where(MediaIdentity.disposed_at.is_(None))
            .order_by(MediaIdentity.id.asc())
        )
        result = await self._session.execute(stmt)
        for identity_id, media_id, cluster_id, embedding in result.all():
            yield (
                identity_id if isinstance(identity_id, uuid.UUID) else uuid.UUID(str(identity_id)),
                int(media_id),
                cluster_id if cluster_id is None or isinstance(cluster_id, uuid.UUID) else uuid.UUID(str(cluster_id)),
                np.asarray(embedding, dtype=np.float32),
            )

    async def get_centroids_mv_refreshed_at(self, tenant_id: str) -> datetime | None:
        """Max ``refreshed_at`` from current MV rows for the tenant (or None if empty).

        Comes only from the MV query — no invented timestamp.
        """
        tenant_uuid = _require_tenant_uuid(tenant_id)
        rows = await self._fetch_mv_centroid_rows(tenant_uuid, cluster_uuids=None)
        refreshed: list[datetime] = []
        for _cid, _centroid, refreshed_at in rows:
            parsed = _coerce_datetime(refreshed_at)
            if parsed is not None:
                refreshed.append(parsed)
        return max(refreshed) if refreshed else None

    async def get_tenant_cluster_centroids(
        self,
        tenant_id: str,
        cluster_ids: Sequence[str | uuid.UUID] | None = None,
    ) -> tuple[list[tuple[uuid.UUID, np.ndarray]], datetime | None]:
        """Return ``(cluster_id, centroid)`` pairs and the MV refresh timestamp.

        Reads current ``mv_identity_cluster_centroids`` filtered by ``tenant_id``.
        For clusters missing from the MV (or with NULL centroid), falls back to
        mean-of-representatives via
        :meth:`SqlAlchemyClusterRepository.get_representative_embeddings`, then
        :meth:`SqlAlchemyClusterRepository.get_member_fallback_embeddings`.

        Does **not** refresh the MV. The returned timestamp is
        ``max(refreshed_at)`` from MV rows present for the tenant (None if none).
        """
        tenant_uuid = _require_tenant_uuid(tenant_id)
        cluster_uuids = _coerce_cluster_ids(cluster_ids)

        if cluster_uuids is not None and not cluster_uuids:
            return [], await self.get_centroids_mv_refreshed_at(tenant_id)

        mv_rows = await self._fetch_mv_centroid_rows(tenant_uuid, cluster_uuids=cluster_uuids)

        by_cluster: dict[uuid.UUID, np.ndarray] = {}
        null_centroid_ids: list[uuid.UUID] = []
        refreshed_values: list[datetime] = []
        for cluster_id, centroid, refreshed_at in mv_rows:
            cid = cluster_id if isinstance(cluster_id, uuid.UUID) else uuid.UUID(str(cluster_id))
            parsed_ts = _coerce_datetime(refreshed_at)
            if parsed_ts is not None:
                refreshed_values.append(parsed_ts)
            if centroid is None:
                null_centroid_ids.append(cid)
                continue
            arr = _as_embedding_array(centroid)
            if arr is None:
                null_centroid_ids.append(cid)
                continue
            by_cluster[cid] = arr

        missing: list[uuid.UUID] = list(null_centroid_ids)
        if cluster_uuids is not None:
            missing.extend(cid for cid in cluster_uuids if cid not in by_cluster and cid not in missing)

        for cid in missing:
            if cid in by_cluster:
                continue
            fallback = await self._mean_of_representatives_centroid(str(cid))
            if fallback is not None:
                by_cluster[cid] = fallback

        pairs = [(cid, emb) for cid, emb in sorted(by_cluster.items(), key=lambda item: str(item[0]))]
        mv_refreshed_at = max(refreshed_values) if refreshed_values else None
        return pairs, mv_refreshed_at

    async def _fetch_mv_centroid_rows(
        self,
        tenant_uuid: uuid.UUID,
        *,
        cluster_uuids: list[uuid.UUID] | None,
    ) -> list[tuple[object, object, object]]:
        """Read MV rows for tenant.

        SQLite test substrate stores UUID keys as TEXT; ORM UUID binds do not
        match those strings, so SQLite uses a text query with string binds.
        Postgres uses the ClusterCentroid ORM path.
        """
        if is_sqlite(self._session):
            sql = """
                SELECT cluster_id, centroid, refreshed_at
                FROM mv_identity_cluster_centroids
                WHERE tenant_id = :tenant_id
            """
            params: dict[str, object] = {"tenant_id": str(tenant_uuid)}
            if cluster_uuids is not None:
                placeholders = ", ".join(f":c{i}" for i in range(len(cluster_uuids)))
                if not cluster_uuids:
                    return []
                sql += f" AND cluster_id IN ({placeholders})"
                for i, cid in enumerate(cluster_uuids):
                    params[f"c{i}"] = str(cid)
            result = await self._session.execute(text(sql), params)
            return list(result.all())

        mv_stmt = select(
            ClusterCentroid.cluster_id,
            ClusterCentroid.centroid,
            ClusterCentroid.refreshed_at,
        ).where(ClusterCentroid.tenant_id == tenant_uuid)
        if cluster_uuids is not None:
            mv_stmt = mv_stmt.where(ClusterCentroid.cluster_id.in_(cluster_uuids))
        result = await self._session.execute(mv_stmt)
        return list(result.all())

    async def _mean_of_representatives_centroid(self, cluster_id: str) -> np.ndarray | None:
        """Mean-of-representatives, then member-fallback embeddings — same sources as cluster repo."""
        embeddings = list(await self._clusters.get_representative_embeddings(cluster_id))
        if not embeddings:
            embeddings = list(await self._clusters.get_member_fallback_embeddings(cluster_id))
        if not embeddings:
            return None
        return compute_centroid(embeddings)


def _require_tenant_uuid(tenant_id: str | uuid.UUID) -> uuid.UUID:
    if isinstance(tenant_id, uuid.UUID):
        return tenant_id
    coerced = _coerce_uuid(tenant_id, on_failure="none")
    if coerced is None:
        raise ValueError(f"invalid tenant_id: {tenant_id!r}")
    return coerced


def _coerce_cluster_ids(
    cluster_ids: Sequence[str | uuid.UUID] | None,
) -> list[uuid.UUID] | None:
    if cluster_ids is None:
        return None
    out: list[uuid.UUID] = []
    for raw in cluster_ids:
        if isinstance(raw, uuid.UUID):
            out.append(raw)
            continue
        coerced = _coerce_uuid(raw, on_failure="none")
        if coerced is None:
            raise ValueError(f"invalid cluster_id: {raw!r}")
        out.append(coerced)
    return out


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _as_embedding_array(value: object) -> np.ndarray | None:
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        return value.astype(np.float32, copy=False)
    if isinstance(value, (bytes, bytearray, memoryview)):
        arr = np.frombuffer(value, dtype=np.float32)
        return np.asarray(arr, dtype=np.float32) if arr.size else None
    if isinstance(value, (list, tuple)):
        return np.asarray(value, dtype=np.float32)
    try:
        return np.asarray(value, dtype=np.float32)
    except (TypeError, ValueError):
        return None


__all__ = [
    "AtlasRepository",
    "MixedEmbeddingModelError",
]
