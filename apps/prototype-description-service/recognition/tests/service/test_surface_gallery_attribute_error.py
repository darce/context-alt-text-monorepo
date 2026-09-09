"""B07: live gallery AttributeError must not authorize cached-vector surfacing.

TEST-15: this module is the raw RED for ISSUEDAG-1-SVC-EMBED-SCOPE-B-07.
DATA-13 / Release It Fail Fast (ch-5): an internal repository fault is not a
missing-method double and must not authorize a second write path through a
metadata-free precomputed cache.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest

from db.models import IdentityClusterRepresentative
from recognition.application.settings import ClusteringSettings
from recognition.application.similarity import SimilaritySearch
from recognition.application.suggestions.refresh_service import SuggestionRefreshService
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import SuggestionCreateData
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


class _RecordingSuggestionRepository:
    def __init__(self) -> None:
        self.payloads: list[SuggestionCreateData] = []

    async def upsert_by_identity_cluster(self, tenant_id: str, payload: SuggestionCreateData) -> AssignmentSuggestion:
        self.payloads.append(payload)
        return AssignmentSuggestion(
            id="suggestion-1",
            identity_id=payload.identity_id,
            cluster_id=payload.cluster_id,
            representative_similarity=payload.representative_similarity,
            member_similarity=payload.member_similarity,
            status=SuggestionStatus.PENDING,
            created_at=datetime.now(tz=UTC),
        )


class _RecordingSimilaritySearch(SimilaritySearch):
    def __init__(self, settings: ClusteringSettings) -> None:
        super().__init__(settings)
        self.calls: list[dict[str, Any]] = []

    def find_best_match(
        self,
        query_embedding: np.ndarray,
        representatives_by_cluster: Any,
        *,
        min_similarity: float | None = None,
    ) -> Any:
        self.calls.append(
            {
                "query": query_embedding,
                "gallery": representatives_by_cluster,
            }
        )
        return super().find_best_match(
            query_embedding,
            representatives_by_cluster,
            min_similarity=min_similarity,
        )


class _RepresentativeRowMissingQuality:
    """Production IdentityClusterRepresentative with quality_score unreadable.

    SqlAlchemyClusterRepository.get_all_representatives does
    ``float(model_rep.quality_score)`` after joining MediaIdentity. An internal
    AttributeError on that field is a live-method fault, not a missing Protocol
    method on a structural double.
    """

    def __init__(self, inner: IdentityClusterRepresentative) -> None:
        object.__setattr__(self, "_inner", inner)

    def __getattribute__(self, name: str) -> Any:
        if name in {"_inner", "__class__"}:
            return object.__getattribute__(self, name)
        if name == "quality_score":
            raise AttributeError(f"'{type(self._inner).__name__}' object has no attribute 'quality_score'")
        return getattr(object.__getattribute__(self, "_inner"), name)


class _FaultingExecuteResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def __iter__(self) -> Any:
        return iter(self._rows)


class _FaultingSession:
    """Session whose representative query yields a production-shaped ORM fault."""

    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row
        self.execute_calls = 0

    async def execute(self, _stmt: Any) -> _FaultingExecuteResult:
        self.execute_calls += 1
        return _FaultingExecuteResult([self._row])


class _FaultingSqlAlchemyClusterRepository(SqlAlchemyClusterRepository):
    """Real producer method, with member-identity lookup supplied for surfacing."""

    def __init__(
        self,
        session: _FaultingSession,
        *,
        identities_by_cluster: dict[str, list[MediaIdentity]],
        labeled_cluster: IdentityCluster,
    ) -> None:
        super().__init__(session)  # type: ignore[arg-type]
        self._identities_by_cluster = identities_by_cluster
        self._labeled_cluster = labeled_cluster

    async def get_member_identities_for_clusters(self, cluster_ids: list[str]) -> dict[str, list[MediaIdentity]]:
        return {cid: list(self._identities_by_cluster.get(cid, [])) for cid in cluster_ids}

    async def get_by_id(self, cluster_id: str) -> IdentityCluster:
        return self._labeled_cluster


def _unstamped_identity(identity_id: str, tenant_id: str) -> MediaIdentity:
    return MediaIdentity(
        id=identity_id,
        tenant_id=tenant_id,
        media_id="media-1",
        embedding=_normalize(np.array([1.0, 0.0, 0.0])),
        confidence=0.99,
        bbox_width=10,
        bbox_height=10,
        embedding_model=None,
    )


@pytest.mark.asyncio
async def test_internal_gallery_attribute_error_does_not_authorize_cached_search() -> None:
    """Callable get_all_representatives raising AttributeError must fail closed.

    Unstamped probe identities plus a nonempty metadata-free cache currently
    let _resolve_surface_gallery treat the fault as a missing-method double and
    cosine through cached vectors. Live representatives are the space of record.
    """
    tenant_id = str(uuid4())
    labeled_id = str(uuid4())
    unlabeled_id = str(uuid4())
    tenant_uuid = UUID(tenant_id)
    labeled_uuid = UUID(labeled_id)

    labeled_cluster = IdentityCluster(
        tenant_id=tenant_id,
        is_labeled=True,
        identity_count=1,
        id=labeled_id,
        label="Ada",
        user_confirmed=True,
        representatives=None,
    )
    unstamped = _unstamped_identity("identity-unstamped", tenant_id)

    orm_rep = IdentityClusterRepresentative(
        id=uuid4(),
        tenant_id=tenant_uuid,
        cluster_id=labeled_uuid,
        identity_id=uuid4(),
        embedding=[1.0, 0.0, 0.0],
        quality_score=1.0,
        diversity_score=None,
        is_user_selected=False,
        is_provisional=False,
        pose_pitch=None,
        pose_yaw=None,
        pose_roll=None,
        created_at=datetime.now(tz=UTC),
    )
    session = _FaultingSession(
        (
            _RepresentativeRowMissingQuality(orm_rep),
            None,
            1,
            None,
        )
    )
    repo = _FaultingSqlAlchemyClusterRepository(
        session,
        identities_by_cluster={unlabeled_id: [unstamped]},
        labeled_cluster=labeled_cluster,
    )
    bound = inspect.getattr_static(type(repo), "get_all_representatives")
    assert inspect.iscoroutinefunction(bound), "producer method must exist; this is not a missing-method double"
    assert bound is SqlAlchemyClusterRepository.get_all_representatives

    suggestion_repo = _RecordingSuggestionRepository()
    settings = ClusteringSettings(
        similarity_threshold=0.0,
        suggestion_floor=0.0,
        suggestion_ceiling=1.1,
    )
    search = _RecordingSimilaritySearch(settings)
    service = SuggestionRefreshService(
        repository=suggestion_repo,
        tenant_id=tenant_id,
        cluster_repository=repo,
        session=object(),
        settings=settings,
    )
    service._search = search

    raised: BaseException | None = None
    created: int | None = None
    try:
        created = await service.surface_for_newly_labeled_cluster(
            labeled_id,
            cluster_label="Ada",
            candidate_cluster_ids=[unlabeled_id],
            representatives_by_cluster={labeled_id: [unstamped.embedding]},
        )
    except AttributeError as exc:
        raised = exc

    assert session.execute_calls >= 1, "production get_all_representatives must run against the session"
    assert raised is not None, (
        "internal AttributeError from SqlAlchemyClusterRepository.get_all_representatives "
        "must be observable as domain failure; live gallery load is the space of record "
        f"(TEST-15, DATA-13). swallowed_return={created!r} search_calls={len(search.calls)} "
        f"upserts={len(suggestion_repo.payloads)}"
    )
    assert search.calls == [], (
        "repository fault must not authorize SimilaritySearch against cached vectors "
        f"(got {len(search.calls)} calls)"
    )
    assert suggestion_repo.payloads == [], (
        "repository fault must not persist suggestions from a metadata-free cache "
        f"(got {len(suggestion_repo.payloads)} upserts)"
    )
