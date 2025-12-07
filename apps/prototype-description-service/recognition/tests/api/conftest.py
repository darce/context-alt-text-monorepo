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
from recognition.interface_adapters.http.routers import analyze as analyze_router
from recognition.interface_adapters.http.routers import clusters as clusters_router
from recognition.interface_adapters.http.routers import suggestions as suggestions_router
from recognition.interface_adapters.http.schemas.responses import ClusterResponse
from recognition.shared.ids import generate_id
from recognition.tests.conftest import FakeClusterService, FakeJobService


class FakeSession:
    """Minimal async session stub used to bypass real DB work."""

    def __init__(self) -> None:
        self.added: list[object] = []

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


class FakeScanService:
    """Fake ScanService that returns completed jobs without persistence."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.session: object | None = None

    async def analyze_media(self, tenant_id: str, media_ids: list[str]):
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


class FakeSuggestionStatus:
    """Lightweight status wrapper mirroring SuggestionStatus enum."""

    def __init__(self, value: str = "pending") -> None:
        self.value = value


class FakeSuggestion:
    """Minimal suggestion record for API contract tests."""

    def __init__(self, identity_id: str, cluster_id: str) -> None:
        self.id = str(uuid.uuid4())
        self.identity_id = identity_id
        self.cluster_id = cluster_id
        self.representative_similarity = 0.9
        self.member_similarity = 0.85
        self.status = FakeSuggestionStatus()


class FakeSuggestionService:
    """In-memory suggestion service used by API tests."""

    def __init__(self) -> None:
        self.suggestions: dict[str, FakeSuggestion] = {}

    async def list_for_identity(self, identity_id: str) -> list[FakeSuggestion]:
        return [s for s in self.suggestions.values() if s.identity_id == identity_id]

    async def accept(self, suggestion_id: str) -> FakeSuggestion | None:
        suggestion = self.suggestions.get(suggestion_id)
        if not suggestion:
            return None
        suggestion.status = FakeSuggestionStatus("accepted")
        return suggestion

    async def reject(self, suggestion_id: str) -> FakeSuggestion | None:
        suggestion = self.suggestions.get(suggestion_id)
        if not suggestion:
            return None
        suggestion.status = FakeSuggestionStatus("rejected")
        return suggestion

    async def create(self, identity_id: str, cluster_id: str) -> FakeSuggestion:
        suggestion = FakeSuggestion(identity_id=identity_id, cluster_id=cluster_id)
        self.suggestions[suggestion.id] = suggestion
        return suggestion

    async def list_pending(self, limit: int = 50, offset: int = 0) -> list[FakeSuggestion]:
        items = list(self.suggestions.values())
        return items[offset : offset + limit]


class FakeMediaIdentity:
    def __init__(self, media_id: int, identity_id: str, cluster_id: str | None = None) -> None:
        self.media_id = media_id
        self.identity_id = identity_id
        self.cluster_id = cluster_id
        self.bbox = {"w": 1, "h": 1}
        self.confidence = 0.99


class FakeMediaIdentityService:
    def __init__(self) -> None:
        self.identities: list[FakeMediaIdentity] = []

    def add_identity(self, media_id: int, identity_id: str, cluster_id: str | None = None) -> None:
        self.identities.append(FakeMediaIdentity(media_id, identity_id, cluster_id))

    async def list_by_media_ids(self, tenant_id: str, media_ids: list[int]) -> list[FakeMediaIdentity]:
        return [mi for mi in self.identities if mi.media_id in media_ids]


@pytest.fixture
def fake_cluster_service() -> FakeClusterService:
    return FakeClusterService()


@pytest.fixture
def fake_job_service() -> FakeJobService:
    return FakeJobService()


@pytest.fixture
def fake_suggestion_service() -> FakeSuggestionService:
    return FakeSuggestionService()


@pytest.fixture
def fake_media_identity_service() -> FakeMediaIdentityService:
    return FakeMediaIdentityService()


@pytest.fixture
def fake_scan_service() -> FakeScanService:
    return FakeScanService()


@pytest.fixture
def tenant_id() -> str:
    """Provide a valid tenant UUID for API contract tests."""
    return str(uuid.uuid4())


@pytest.fixture
def api_client(
    monkeypatch,
    tenant_id: str,
    fake_cluster_service: FakeClusterService,
    fake_job_service: FakeJobService,
    fake_suggestion_service: FakeSuggestionService,
    fake_scan_service: FakeScanService,
    fake_media_identity_service: FakeMediaIdentityService,
) -> TestClient:
    """Build a TestClient with faked dependencies and no real DB."""
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _no_session():
        yield FakeSession()

    def cluster_builder():
        async def _build(_tenant_id: str):
            return fake_cluster_service

        return _build

    async def job_service_dep():
        return fake_job_service

    async def suggestion_service_dep(session=None, tenant_id=None):  # noqa: ANN001
        return fake_suggestion_service

    async def _no_observability_repo():
        return None

    app.dependency_overrides[dependencies.get_session] = _no_session
    app.dependency_overrides[dependencies.get_optional_session] = _no_session
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder
    app.dependency_overrides[dependencies.get_job_service_dependency] = job_service_dep
    app.dependency_overrides[dependencies.get_suggestion_service] = suggestion_service_dep
    app.dependency_overrides[dependencies.get_observability_repository] = _no_observability_repo
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id

    # Monkeypatch router helpers to point at fakes
    async def _fake_build_cluster_service(session, tenant_id, settings=None):  # noqa: ANN001
        return fake_cluster_service

    monkeypatch.setattr(dependencies, "build_cluster_service", _fake_build_cluster_service)
    monkeypatch.setattr(clusters_router, "build_cluster_service", _fake_build_cluster_service)

    async def _fake_get_job_service(**_kwargs):
        return fake_job_service

    monkeypatch.setattr(dependencies, "get_job_service", _fake_get_job_service)
    monkeypatch.setattr(clusters_router, "get_job_service", _fake_get_job_service)

    def _fake_scan_service_factory(session=None, *_args, **_kwargs):
        fake_scan_service.session = session
        return fake_scan_service

    monkeypatch.setattr(analyze_router, "ScanService", _fake_scan_service_factory)

    async def _fake_suggestion_service(session=None, tenant_id=None):  # noqa: ANN001
        return fake_suggestion_service

    monkeypatch.setattr(dependencies, "get_suggestion_service", _fake_suggestion_service)
    monkeypatch.setattr(suggestions_router, "get_suggestion_service", _fake_suggestion_service)

    async def _fake_media_identity_service(**_kwargs):
        return fake_media_identity_service

    monkeypatch.setattr(dependencies, "get_media_identity_service", _fake_media_identity_service)

    return TestClient(app)


def seed_cluster(fake_cluster_service: FakeClusterService, tenant_id: str, label: str = "test") -> ClusterResponse:
    """Helper to seed a fake cluster for API tests."""
    cluster = ClusterResponse(
        id=str(uuid.uuid4()),
        tenant_id=str(tenant_id),
        label=label,
        is_labeled=bool(label),
        member_count=1,
        representatives=[],
    )
    fake_cluster_service.clusters.append(cluster)
    return cluster
