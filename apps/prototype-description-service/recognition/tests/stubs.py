"""Shared protocol stubs for recognition tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.maturity import ClusterMaturityInfo
from recognition.domain.repositories import ClusterRepository, IdentityMember
from recognition.domain.representative import ClusterRepresentative


class NullClusterRepository(ClusterRepository):
    """Configurable no-op `ClusterRepository` for unit tests."""

    def __init__(
        self,
        *,
        clusters_by_id: dict[str, IdentityCluster] | None = None,
        representatives_by_cluster: dict[str, list[ClusterRepresentative]] | None = None,
        member_embeddings_by_cluster: dict[str, list[np.ndarray]] | None = None,
        member_identities_by_cluster: dict[str, list[MediaIdentity]] | None = None,
        members_by_cluster: dict[str, list[IdentityMember]] | None = None,
        labeled_with_representatives: list[tuple[IdentityCluster, list[ClusterRepresentative]]] | None = None,
        labeled_count: int | None = None,
        maturity_by_cluster: dict[str, ClusterMaturityInfo] | None = None,
    ) -> None:
        self._clusters_by_id = clusters_by_id or {}
        self._representatives_by_cluster = representatives_by_cluster or {}
        self._member_embeddings_by_cluster = member_embeddings_by_cluster or {}
        self._member_identities_by_cluster = member_identities_by_cluster or {}
        self._members_by_cluster = members_by_cluster or {}
        self._labeled_with_representatives = labeled_with_representatives
        self._labeled_count = labeled_count
        self._maturity_by_cluster = maturity_by_cluster or {}
        self._dismissed_cluster_ids: set[str] = set()
        self._curriculum_t: dict[str, float] = {}

    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None:
        return self._clusters_by_id.get(cluster_id)

    async def get_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        labeled_only: bool = False,
        search: str | None = None,
    ) -> list[IdentityCluster]:
        clusters = [cluster for cluster in self._clusters_by_id.values() if cluster.tenant_id == tenant_id]
        if labeled_only:
            clusters = [cluster for cluster in clusters if cluster.label]
        if search:
            query = search.lower()
            clusters = [cluster for cluster in clusters if cluster.label and query in cluster.label.lower()]
        return clusters[offset : offset + limit]

    async def save(self, cluster: IdentityCluster) -> IdentityCluster:
        if cluster.id:
            self._clusters_by_id[cluster.id] = cluster
        return cluster

    async def update(self, cluster: IdentityCluster) -> IdentityCluster:
        if cluster.id:
            self._clusters_by_id[cluster.id] = cluster
        return cluster

    async def delete(self, cluster_id: str) -> None:
        self._clusters_by_id.pop(cluster_id, None)
        self._representatives_by_cluster.pop(cluster_id, None)
        self._member_embeddings_by_cluster.pop(cluster_id, None)
        self._member_identities_by_cluster.pop(cluster_id, None)
        self._members_by_cluster.pop(cluster_id, None)
        self._dismissed_cluster_ids.discard(cluster_id)

    async def refresh_centroids_view(self) -> None:
        return None

    async def refresh_centroids_view_concurrent(self) -> None:
        return None

    async def get_unclustered(self, tenant_id: str) -> Sequence[MediaIdentity]:
        return []

    async def get_representative_count(self, cluster_id: str) -> int:
        return len(self._representatives_by_cluster.get(cluster_id, []))

    async def get_all_representatives(self, cluster_id: str) -> Sequence[ClusterRepresentative]:
        return list(self._representatives_by_cluster.get(cluster_id, []))

    async def get_maturity_info(  # noqa: ARG002
        self,
        cluster_id: str,
        *,
        settings: Any = None,
    ) -> ClusterMaturityInfo | None:
        return self._maturity_by_cluster.get(cluster_id)

    async def get_curriculum_t(self, cluster_id: str) -> float | None:
        return self._curriculum_t.get(cluster_id)

    async def set_curriculum_t(self, cluster_id: str, value: float) -> None:
        self._curriculum_t[cluster_id] = value

    async def get_member_embeddings(self, cluster_id: str) -> Sequence[np.ndarray]:
        return list(self._member_embeddings_by_cluster.get(cluster_id, []))

    async def get_member_identities(self, cluster_id: str) -> Sequence[MediaIdentity]:
        return list(self._member_identities_by_cluster.get(cluster_id, []))

    async def get_member_identities_with_similarity(self, cluster_id: str) -> list[tuple[MediaIdentity, float]]:
        identities = list(self._member_identities_by_cluster.get(cluster_id, []))
        return [(identity, 0.0) for identity in identities]

    async def get_member_identities_for_clusters(
        self,
        cluster_ids: Sequence[str],
    ) -> Mapping[str, Sequence[MediaIdentity]]:
        return {cluster_id: list(self._member_identities_by_cluster.get(cluster_id, [])) for cluster_id in cluster_ids}

    async def get_members(self, cluster_id: str) -> list[IdentityMember]:
        return list(self._members_by_cluster.get(cluster_id, []))

    async def get_roster_entry_name(self, roster_id: str) -> str | None:  # noqa: ARG002
        return None

    async def get_singleton_identities(
        self,
        tenant_id: str,  # noqa: ARG002
        *,
        limit: int | None = None,  # noqa: ARG002
    ) -> list[MediaIdentity]:
        return []

    async def assign_identity_to_cluster(self, identity: MediaIdentity, cluster_id: str) -> None:
        self._member_identities_by_cluster.setdefault(cluster_id, []).append(identity)

    async def add_representative(self, representative: ClusterRepresentative) -> None:
        self._representatives_by_cluster.setdefault(representative.cluster_id, []).append(representative)

    async def remove_representative(self, representative_id: str) -> None:
        for cluster_id, reps in self._representatives_by_cluster.items():
            self._representatives_by_cluster[cluster_id] = [rep for rep in reps if rep.id != representative_id]

    async def clear_representatives(self, cluster_id: str) -> None:
        self._representatives_by_cluster[cluster_id] = []

    async def count_labeled(self) -> int:
        if self._labeled_count is not None:
            return self._labeled_count
        return sum(1 for cluster in self._clusters_by_id.values() if cluster.label)

    async def get_labeled_with_representatives(
        self,
        tenant_id: str,
    ) -> list[tuple[IdentityCluster, list[ClusterRepresentative]]]:
        if self._labeled_with_representatives is not None:
            return self._labeled_with_representatives

        rows: list[tuple[IdentityCluster, list[ClusterRepresentative]]] = []
        for cluster in self._clusters_by_id.values():
            if cluster.tenant_id != tenant_id or not cluster.label:
                continue
            reps = list(self._representatives_by_cluster.get(cluster.id or "", []))
            rows.append((cluster, reps))
        return rows

    async def get_top_unlabeled(
        self,
        tenant_id: str,
        limit: int = 10,
        min_identity_count: int = 2,
    ) -> list[IdentityCluster]:
        clusters = [
            cluster
            for cluster in self._clusters_by_id.values()
            if cluster.tenant_id == tenant_id
            and cluster.id not in self._dismissed_cluster_ids
            and cluster.identity_count >= min_identity_count
            and (cluster.label is None or cluster.label.startswith("cluster-"))
        ]
        clusters.sort(key=lambda cluster: cluster.identity_count, reverse=True)
        return clusters[:limit]

    async def dismiss_cluster(self, cluster_id: str) -> bool:
        if cluster_id not in self._clusters_by_id:
            return False
        self._dismissed_cluster_ids.add(cluster_id)
        return True

    async def undismiss_cluster(self, cluster_id: str) -> bool:
        if cluster_id not in self._clusters_by_id:
            return False
        self._dismissed_cluster_ids.discard(cluster_id)
        return True

    async def mark_representative_user_selected(self, representative_id: str, is_selected: bool = True) -> None:
        for reps in self._representatives_by_cluster.values():
            for rep in reps:
                if rep.id == representative_id:
                    rep.is_user_selected = is_selected
                    return

    async def get_user_selected_representatives(
        self,
        cluster_id: str,
    ) -> Sequence[ClusterRepresentative]:
        reps = self._representatives_by_cluster.get(cluster_id, [])
        return [rep for rep in reps if rep.is_user_selected]

    async def confirm_provisional_representatives(self, cluster_id: str) -> int:
        confirmed = 0
        for rep in self._representatives_by_cluster.get(cluster_id, []):
            if rep.is_provisional:
                rep.is_provisional = False
                confirmed += 1
        return confirmed

    async def confirm_all_provisional_reps(self, tenant_id: str) -> int:  # noqa: ARG002
        confirmed = 0
        for reps in self._representatives_by_cluster.values():
            for rep in reps:
                if rep.is_provisional:
                    rep.is_provisional = False
                    confirmed += 1
        return confirmed

    async def cleanup_orphaned_provisional_reps(self, tenant_id: str) -> int:  # noqa: ARG002
        removed = 0
        for cluster_id, reps in self._representatives_by_cluster.items():
            keep: list[ClusterRepresentative] = []
            for rep in reps:
                if rep.is_provisional:
                    removed += 1
                    continue
                keep.append(rep)
            self._representatives_by_cluster[cluster_id] = keep
        return removed

    async def get_representative_embeddings(self, cluster_id: str) -> list[np.ndarray]:
        reps = self._representatives_by_cluster.get(cluster_id, [])
        return [np.asarray(getattr(rep, "embedding", rep), dtype=np.float32) for rep in reps]

    async def get_member_fallback_embeddings(self, cluster_id: str, limit: int = 4) -> list[np.ndarray]:
        embeddings = self._member_embeddings_by_cluster.get(cluster_id, [])
        if limit is None or limit < 0:
            return [np.asarray(e, dtype=np.float32) for e in embeddings]
        return [np.asarray(e, dtype=np.float32) for e in embeddings[:limit]]

    async def get_confirmed_labeled(self, tenant_id: str) -> list[IdentityCluster]:
        return [
            cluster
            for cluster in self._clusters_by_id.values()
            if cluster.tenant_id == tenant_id and cluster.label and not cluster.label.startswith("cluster-")
        ]

    async def get_unlabeled_created_after(self, tenant_id: str, *, minutes_ago: int) -> list[IdentityCluster]:
        return [
            cluster
            for cluster in self._clusters_by_id.values()
            if cluster.tenant_id == tenant_id
            and (cluster.label is None or cluster.label.startswith("cluster-") or not cluster.user_confirmed)
        ]

    async def get_snapshot(
        self, tenant_id: str
    ) -> tuple[list[IdentityCluster], list[tuple[IdentityMember, MediaIdentity]], int]:
        """Get snapshot data for tests from configured cluster/member fixtures."""
        clusters = [cluster for cluster in self._clusters_by_id.values() if cluster.tenant_id == tenant_id]
        members = await self.get_members_by_cluster_ids(tenant_id, [cluster.id for cluster in clusters if cluster.id])
        snapshot_version = await self.get_snapshot_version(tenant_id)
        return (clusters, members, snapshot_version)

    async def get_members_by_cluster_ids(
        self, tenant_id: str, cluster_ids: Sequence[str]
    ) -> list[tuple[IdentityMember, MediaIdentity]]:
        rows: list[tuple[IdentityMember, MediaIdentity]] = []
        for cluster_id in cluster_ids:
            for index, identity in enumerate(self._member_identities_by_cluster.get(cluster_id, [])):
                if identity.tenant_id != tenant_id:
                    continue
                members = self._members_by_cluster.get(cluster_id, [])
                member = (
                    members[index]
                    if index < len(members)
                    else IdentityMember(
                        id=f"member-{cluster_id}-{index}",
                        cluster_id=cluster_id,
                        identity_id=identity.id,
                        similarity=0.0,
                        tenant_id=identity.tenant_id,
                    )
                )
                rows.append((member, identity))
        return rows

    async def get_clusters_by_ids(self, tenant_id: str, cluster_ids: Sequence[str]) -> list[IdentityCluster]:
        return [
            cluster
            for cluster in self._clusters_by_id.values()
            if cluster.tenant_id == tenant_id and cluster.id in cluster_ids
        ]

    async def get_snapshot_version(self, tenant_id: str) -> int:
        _ = tenant_id
        return 1
