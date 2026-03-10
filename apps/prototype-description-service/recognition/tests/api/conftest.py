"""API test fixtures with faked dependencies (no real DB)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.routers import media as media_router
from recognition.interface_adapters.http.schemas.responses import ClusterResponse
from recognition.shared.ids import generate_id
from recognition.tests.fakes import FakeClusterRepository, FakeClusterService, FakeJobService


class FakeSession:
    """Minimal async session stub used to bypass real DB work."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self._get_results: dict[tuple[object, object], object | None] = {}
        self._execute_results: list[FakeSessionResult] = []

    def set_get_result(self, *, model_class: object, pk: object, value: object | None) -> None:
        """Register a deterministic return value for `get(model_class, pk)`."""
        self._get_results[(model_class, pk)] = value

    def queue_execute_result(
        self,
        *,
        scalar_one_or_none: object | None = None,
        scalar: object = 0,
        all_rows: list[object] | None = None,
    ) -> None:
        """Queue a deterministic execute result for the next `execute()` call."""
        self._execute_results.append(
            FakeSessionResult(
                scalar_one_or_none_value=scalar_one_or_none,
                scalar_value=scalar,
                all_rows=all_rows or [],
            )
        )

    async def execute(self, _statement, _params=None):  # noqa: ANN001
        if self._execute_results:
            return self._execute_results.pop(0)
        return FakeSessionResult()

    def add(self, obj) -> None:  # noqa: ANN001
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def add_all(self, objs) -> None:  # noqa: ANN001
        for obj in objs:
            self.add(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def get(self, model_class, pk):  # noqa: ANN001
        """Stub get method for repository compatibility."""
        return self._get_results.get((model_class, pk))


class FakeSessionResult:
    """Minimal SQLAlchemy result stub with configurable scalar/all payloads."""

    def __init__(
        self,
        *,
        scalar_one_or_none_value: object | None = None,
        scalar_value: object = 0,
        all_rows: list[object] | None = None,
    ) -> None:
        self._scalar_one_or_none_value = scalar_one_or_none_value
        self._scalar_value = scalar_value
        self._all_rows = all_rows or []

    def scalar_one_or_none(self):  # noqa: ANN001
        return self._scalar_one_or_none_value

    def scalar(self):  # noqa: ANN001
        return self._scalar_value

    def scalars(self):  # noqa: ANN001
        return self

    def all(self):  # noqa: ANN001
        return self._all_rows


class FakeScanService:
    """Fake ScanService that returns completed jobs without persistence."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.session: object | None = None

    async def analyze_media(self, tenant_id: str, media_ids: list[str], media_sources: list[str] | None = None):
        self.calls.append((tenant_id, list(media_ids)))
        now = datetime.now(tz=UTC)
        return SimpleNamespace(
            id=str(generate_id()),
            status="completed",
            total_media=len(media_ids),
            processed_media=len(media_ids),
            started_at=now,
            completed_at=now,
        )


class FakeScanQueueService:
    """Fake ScanQueueService that enqueues jobs without persistence."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple[int, str]]]] = []
        self.created_jobs: list[tuple[str, int]] = []
        self.messages: dict[str, str] = {}

    async def create_scan_job_record(self, *, tenant_id, total, created_by_user_id=None):  # noqa: ANN001
        job_id = generate_id()
        self.created_jobs.append((str(tenant_id), int(total)))
        self.messages[str(job_id)] = f"Queueing 0/{int(total)} items"
        return job_id

    async def populate_scan_job_items(self, *, job_id, tenant_id, media_items, chunk_size=500):  # noqa: ANN001
        self.calls.append((str(tenant_id), list(media_items)))
        self.messages[str(job_id)] = f"Queued {len(media_items)} items"
        return len(media_items)

    async def enqueue_scan_job(self, *, tenant_id, media_items, created_by_user_id=None):  # noqa: ANN001
        job_id = await self.create_scan_job_record(
            tenant_id=tenant_id,
            total=len(media_items),
            created_by_user_id=created_by_user_id,
        )
        total = await self.populate_scan_job_items(job_id=job_id, tenant_id=tenant_id, media_items=media_items)
        return SimpleNamespace(job_id=job_id, total=total)


class FakeSuggestionStatus:
    """Lightweight status wrapper mirroring SuggestionStatus enum."""

    def __init__(self, value: str = "pending") -> None:
        self.value = value


class FakeFaceBox:
    """Simple bounding box for suggestion detail payloads."""

    def __init__(self, x: int = 0, y: int = 0, width: int = 1, height: int = 1) -> None:
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class FakeSuggestion:
    """Suggestion record with optional detail fields for API contract tests."""

    def __init__(
        self,
        identity_id: str,
        cluster_id: str,
        *,
        cluster_label: str | None = None,
        cluster_identity_count: int | None = None,
        identity_media_id: int | None = None,
        identity_media_url: str | None = None,
        identity_bbox: FakeFaceBox | None = None,
        representative_media_id: int | None = None,
        representative_media_url: str | None = None,
        representative_bbox: FakeFaceBox | None = None,
        suggested_label: str | None = None,
        suggested_label_source: str | None = None,
        suggested_label_confidence: float | None = None,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.identity_id = identity_id
        self.cluster_id = cluster_id
        self.representative_similarity = 0.9
        self.member_similarity = 0.85
        self.status = FakeSuggestionStatus()
        self.cluster_label = cluster_label
        self.cluster_identity_count = cluster_identity_count
        self.identity_media_id = identity_media_id
        self.identity_media_url = identity_media_url
        self.identity_bbox = identity_bbox
        self.representative_media_id = representative_media_id
        self.representative_media_url = representative_media_url
        self.representative_bbox = representative_bbox
        self.suggested_label = suggested_label
        self.suggested_label_source = suggested_label_source
        self.suggested_label_confidence = suggested_label_confidence

    def as_details(self) -> SimpleNamespace:
        """Return a detail-shaped suggestion with string status."""
        return SimpleNamespace(
            id=self.id,
            identity_id=self.identity_id,
            cluster_id=self.cluster_id,
            representative_similarity=self.representative_similarity,
            member_similarity=self.member_similarity,
            status=self.status.value,
            cluster_label=self.cluster_label,
            cluster_identity_count=self.cluster_identity_count,
            identity_media_id=self.identity_media_id,
            identity_media_url=self.identity_media_url,
            identity_bbox=self.identity_bbox,
            representative_media_id=self.representative_media_id,
            representative_media_url=self.representative_media_url,
            representative_bbox=self.representative_bbox,
            suggested_label=self.suggested_label,
            suggested_label_source=self.suggested_label_source,
            suggested_label_confidence=self.suggested_label_confidence,
        )


class FakeSuggestionService:
    """In-memory suggestion service used by API tests."""

    def __init__(self) -> None:
        self.suggestions: dict[str, object] = {}

    async def list_for_identity(self, identity_id: str) -> list[FakeSuggestion]:
        return [s for s in self.suggestions.values() if isinstance(s, FakeSuggestion) and s.identity_id == identity_id]

    async def accept(self, suggestion_id: str) -> FakeSuggestion | None:
        suggestion = self.suggestions.get(suggestion_id)
        if not isinstance(suggestion, FakeSuggestion):
            return None
        suggestion.status = FakeSuggestionStatus("accepted")
        return suggestion

    async def reject(self, suggestion_id: str) -> FakeSuggestion | None:
        suggestion = self.suggestions.get(suggestion_id)
        if not isinstance(suggestion, FakeSuggestion):
            return None
        suggestion.status = FakeSuggestionStatus("rejected")
        return suggestion

    async def create(self, identity_id: str, cluster_id: str, **kwargs) -> FakeSuggestion:  # noqa: ANN003
        suggestion = FakeSuggestion(identity_id=identity_id, cluster_id=cluster_id, **kwargs)
        self.suggestions[suggestion.id] = suggestion
        return suggestion

    async def resolve_for_identity(
        self,
        identity_id: str,
        cluster_id: str,
        resolution: str = "accepted",
    ) -> int:
        resolved = 0
        for suggestion in self.suggestions.values():
            if not isinstance(suggestion, FakeSuggestion):
                continue
            if suggestion.identity_id == identity_id and suggestion.cluster_id == cluster_id:
                suggestion.status = FakeSuggestionStatus(resolution)
                resolved += 1
        return resolved

    async def resolve_for_identity_exclusive(
        self,
        *,
        identity_id: str,
        accepted_cluster_id: str,
        reason: str | None = None,
    ) -> int:
        resolved = 0
        for suggestion in self.suggestions.values():
            if not isinstance(suggestion, FakeSuggestion):
                continue
            if suggestion.identity_id != identity_id:
                continue
            if suggestion.cluster_id == accepted_cluster_id:
                suggestion.status = FakeSuggestionStatus("accepted")
            else:
                suggestion.status = FakeSuggestionStatus("rejected")
            resolved += 1
        return resolved

    async def list_pending(self, limit: int = 50, offset: int = 0) -> list[object]:
        items = list(self.suggestions.values())
        pending: list[object] = []
        for suggestion in items[offset : offset + limit]:
            if isinstance(suggestion, FakeSuggestion):
                pending.append(suggestion.as_details())
            else:
                pending.append(suggestion)
        return pending


class FakeSuggestionRefreshService:
    """In-memory suggestion refresh service used by API tests."""

    def __init__(self) -> None:
        self.refresh_calls: list[tuple[str, object]] = []

    async def refresh_for_identity(self, *, identity_id: str, reason) -> list[FakeSuggestion]:
        self.refresh_calls.append((identity_id, reason))
        return []

    async def refresh_for_cluster(self, cluster_id: str) -> list[FakeSuggestion]:
        self.refresh_calls.append((cluster_id, "cluster_refresh"))
        return []

    async def surface_for_newly_labeled_cluster(
        self,
        cluster_id: str,
        *,
        cluster_label: str | None = None,
        candidate_cluster_ids: list[str] | None = None,
        representatives_by_cluster: dict[str, list[object]] | None = None,
    ) -> int:
        self.refresh_calls.append(
            (cluster_id, "surface_new_label", cluster_label, candidate_cluster_ids, representatives_by_cluster)
        )
        return 0

    async def backfill_for_new_unlabeled_clusters(
        self,
        *,
        tenant_id: str,
        created_cluster_ids: list[str],
        fallback_window_minutes: int = 30,
    ) -> int:
        self.refresh_calls.append(("backfill", tenant_id, list(created_cluster_ids), fallback_window_minutes))
        return 0


class FakeMediaIdentity:
    def __init__(self, media_id: int, identity_id: str, cluster_id: str | None = None) -> None:
        self.media_id = media_id
        self.identity_id = identity_id
        self.cluster_id = cluster_id
        self.bbox = {"width": 1, "height": 1, "x": 0, "y": 0}
        self.confidence = 0.99
        self.media_url = "http://example.test/media.jpg"
        self.pose_pitch = 10.0
        self.pose_yaw = -5.0
        self.pose_roll = 0.0
        self.age = 30
        self.gender = 1
        self.quality_score = 0.9


class FakeMediaIdentityService:
    def __init__(self) -> None:
        self.identities: list[FakeMediaIdentity] = []

    def add_identity(self, media_id: int, identity_id: str, cluster_id: str | None = None) -> None:
        self.identities.append(FakeMediaIdentity(media_id, identity_id, cluster_id))

    async def list_by_media_ids(
        self, tenant_id: str, media_ids: list[int], include_debug: bool = False
    ) -> list[dict[str, object]]:
        media_id_set = {int(value) for value in media_ids}
        results = []
        for identity in self.identities:
            if identity.media_id not in media_id_set:
                continue
            payload: dict[str, object] = {
                "identity_id": identity.identity_id,
                "media_id": identity.media_id,
                "cluster_id": identity.cluster_id,
                "cluster_label": None,
                "is_auto_label": True,
                "bbox": identity.bbox,
                "confidence": identity.confidence,
                "media_url": identity.media_url,
            }
            if include_debug:
                payload["debug_metrics"] = {
                    "pose": {
                        "pitch": identity.pose_pitch,
                        "yaw": identity.pose_yaw,
                        "roll": identity.pose_roll,
                    },
                    "age": identity.age,
                    "gender": "male" if identity.gender == 1 else "female",
                    "det_score": identity.confidence,
                    "bbox_area": identity.bbox["width"] * identity.bbox["height"],
                    "landmark_quality": identity.quality_score,
                    "clustering_method": None,
                    "clustering_algorithm": None,
                    "similarity_threshold": None,
                    "match_similarity": None,
                    "representative_count": 1,
                    "pose_buckets": {"filled": 1, "total": 13, "current_bucket": (0, 0)},
                }
            results.append(payload)

        return results


@pytest.fixture
def fake_cluster_service() -> FakeClusterService:
    return FakeClusterService()


@pytest.fixture
def fake_cluster_repository() -> FakeClusterRepository:
    return FakeClusterRepository()


@pytest.fixture
def fake_job_service() -> FakeJobService:
    return FakeJobService()


@pytest.fixture
def fake_suggestion_service() -> FakeSuggestionService:
    return FakeSuggestionService()


@pytest.fixture
def fake_suggestion_refresh_service() -> FakeSuggestionRefreshService:
    return FakeSuggestionRefreshService()


@pytest.fixture
def fake_media_identity_service() -> FakeMediaIdentityService:
    return FakeMediaIdentityService()


@pytest.fixture
def fake_scan_service() -> FakeScanService:
    return FakeScanService()


@pytest.fixture
def fake_scan_queue_service() -> FakeScanQueueService:
    return FakeScanQueueService()


@pytest.fixture
def tenant_id() -> str:
    """Provide a valid tenant UUID for API contract tests."""
    return str(uuid.uuid4())


@pytest.fixture
def api_client(
    monkeypatch,
    tenant_id: str,
    fake_cluster_service: FakeClusterService,
    fake_cluster_repository: FakeClusterRepository,
    fake_job_service: FakeJobService,
    fake_suggestion_service: FakeSuggestionService,
    fake_suggestion_refresh_service: FakeSuggestionRefreshService,
    fake_scan_service: FakeScanService,
    fake_scan_queue_service: FakeScanQueueService,
    fake_media_identity_service: FakeMediaIdentityService,
) -> TestClient:
    """Build a TestClient with faked dependencies and no real DB."""
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")
    # API contract tests should not run the inline processor (it requires real ScanService wiring).
    monkeypatch.setenv("RECOGNITION_ASYNC_ANALYZE_INLINE", "0")
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    fake_session = FakeSession()

    async def _no_session():
        yield fake_session

    def cluster_builder():
        async def _build(_tenant_id: str):
            return fake_cluster_service

        return _build

    async def job_service_dep():
        return fake_job_service

    async def cluster_repo_dep(session=None):  # noqa: ANN001
        return fake_cluster_repository

    async def _no_observability_repo():
        return None

    async def _fake_suggestion_service(session=None, tenant_id=None):  # noqa: ANN001
        return fake_suggestion_service

    async def _fake_suggestion_refresh_service(session=None, tenant_id=None):  # noqa: ANN001
        return fake_suggestion_refresh_service

    app.dependency_overrides[dependencies.get_session] = _no_session
    app.dependency_overrides[dependencies.get_optional_session] = _no_session
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder
    app.dependency_overrides[dependencies.get_cluster_repository] = cluster_repo_dep
    app.dependency_overrides[dependencies.get_job_service_dependency] = job_service_dep
    app.dependency_overrides[dependencies.get_persisted_cluster_job_service] = job_service_dep
    app.dependency_overrides[dependencies.get_persisted_job_service] = job_service_dep
    app.dependency_overrides[dependencies.get_observability_repository] = _no_observability_repo
    app.dependency_overrides[dependencies.get_suggestion_service] = _fake_suggestion_service
    app.dependency_overrides[dependencies.get_suggestion_refresh_service] = _fake_suggestion_refresh_service
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[dependencies.get_scan_queue_service] = lambda: fake_scan_queue_service
    app.dependency_overrides[dependencies.get_scan_queue_service_optional] = lambda: fake_scan_queue_service

    async def _fake_media_identity_service():
        return fake_media_identity_service

    app.dependency_overrides[media_router.get_media_identity_service] = _fake_media_identity_service

    return TestClient(app)


def seed_cluster(
    fake_cluster_service: FakeClusterService,
    tenant_id: str,
    label: str = "test",
    fake_cluster_repository: FakeClusterRepository | None = None,
) -> ClusterResponse:
    """Helper to seed a fake cluster for API tests.

    Seeds both the FakeClusterService (used by cluster services) and FakeClusterRepository
    (used by repository-based endpoints like snapshot) in a single call.

    Args:
        fake_cluster_service: The service to seed
        tenant_id: The tenant ID
        label: The cluster label (default "test")
        fake_cluster_repository: Optional repository to also seed. If provided, seeds both stores.
    """
    cluster = ClusterResponse(
        id=str(uuid.uuid4()),
        tenant_id=str(tenant_id),
        label=label,
        is_labeled=bool(label),
        is_auto_label=False,
        identity_count=1,
        representatives=[],
    )
    fake_cluster_service.clusters.append(cluster)

    # Also seed the repository if provided
    if fake_cluster_repository:
        fake_cluster_repository.seed(cluster.id, tenant_id, label=label, identity_count=1)

    return cluster
