"""APP-1 authenticated portal router tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from recognition.application.services.tenant_key_service import (
    IdempotencyKeyReuseError,
    KeyAlreadyRevokedError,
    KeyIssueResult,
    KeyNotFoundError,
    KeyPage,
)
from recognition.domain.portal_contracts import EntitlementSnapshot, EntitlementStatus, PortalPrincipal
from recognition.interface_adapters.http.deps.portal_auth import require_portal_principal
from recognition.interface_adapters.http.routers import portal

TENANT_ID = uuid4()
FOREIGN_TENANT_ID = uuid4()
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class _SessionStub:
    def __init__(self, *, events: list[str] | None = None, fail_commit: bool = False) -> None:
        self.events = events if events is not None else []
        self.fail_commit = fail_commit
        self.commit_calls = 0

    async def commit(self) -> None:
        self.events.append("commit")
        self.commit_calls += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")


def _key(
    tenant_id: UUID,
    *,
    key_id: UUID | None = None,
    raw_key: str | None = None,
    revoked_at: datetime | None = None,
    created_at: datetime = NOW,
    expires_at: datetime | None = None,
    replayed: bool = False,
) -> KeyIssueResult:
    return KeyIssueResult(
        api_key_id=key_id or uuid4(),
        tenant_id=tenant_id,
        created_at=created_at,
        expires_at=expires_at,
        revoked_at=revoked_at,
        rate_limit_tier="standard",
        lifetime_seconds=None,
        raw_key=raw_key,
        replayed=replayed,
    )


class _KeyServiceStub:
    def __init__(self, *, events: list[str] | None = None) -> None:
        self.keys: dict[UUID, KeyIssueResult] = {}
        self.create_calls: list[tuple[UUID, str, int | None, str | None]] = []
        self.rotate_calls: list[tuple[UUID, UUID, str, str]] = []
        self.list_limits: list[int] = []
        self.events = events if events is not None else []
        self._create_requests: dict[tuple[UUID, str], tuple[int | None, str | None, UUID]] = {}
        self._raw_counter = 0

    async def create_key(
        self,
        tenant_id: UUID,
        *,
        idempotency_key: str,
        lifetime_seconds: int | None = None,
        rate_limit_tier: str | None = None,
    ) -> KeyIssueResult:
        self.events.append("create")
        normalized_key = idempotency_key.strip()
        self.create_calls.append((tenant_id, normalized_key, lifetime_seconds, rate_limit_tier))
        request_key = (tenant_id, normalized_key)
        existing = self._create_requests.get(request_key)
        fingerprint = (lifetime_seconds, rate_limit_tier)
        if existing is not None:
            if existing[:2] != fingerprint:
                raise IdempotencyKeyReuseError("idempotency key was already used for a different request")
            result = self.keys[existing[2]]
            return result.__class__(
                api_key_id=result.api_key_id,
                tenant_id=result.tenant_id,
                created_at=result.created_at,
                expires_at=result.expires_at,
                revoked_at=result.revoked_at,
                rate_limit_tier=result.rate_limit_tier,
                lifetime_seconds=result.lifetime_seconds,
                raw_key=None,
                replayed=True,
            )
        self._raw_counter += 1
        result = _key(tenant_id, raw_key=f"raw-secret-{self._raw_counter}")
        self.keys[result.api_key_id] = result
        self._create_requests[request_key] = (*fingerprint, result.api_key_id)
        return result

    async def rotate_key(
        self,
        tenant_id: UUID,
        api_key_id: UUID,
        *,
        idempotency_key: str,
        reason: str,
    ) -> KeyIssueResult:
        self.rotate_calls.append((tenant_id, api_key_id, idempotency_key.strip(), reason))
        previous = self.keys.get(api_key_id)
        if previous is None or previous.tenant_id != tenant_id:
            raise KeyNotFoundError("api key not found")
        result = _key(tenant_id, raw_key="replacement-secret")
        self.keys[result.api_key_id] = result
        return result

    async def revoke_key(self, tenant_id: UUID, api_key_id: UUID, *, reason: str) -> None:
        current = self.keys.get(api_key_id)
        if current is None or current.tenant_id != tenant_id:
            raise KeyNotFoundError("api key not found")
        if current.revoked_at is not None:
            raise KeyAlreadyRevokedError("api key is already revoked")
        self.keys[api_key_id] = _key(
            tenant_id,
            key_id=api_key_id,
            revoked_at=NOW,
            created_at=current.created_at,
            expires_at=current.expires_at,
        )

    async def list_keys(
        self,
        tenant_id: UUID,
        *,
        cursor: str | None = None,
        limit: int = 25,
        include_revoked: bool = True,
    ) -> KeyPage:
        self.list_limits.append(limit)
        rows = [item for item in self.keys.values() if item.tenant_id == tenant_id]
        rows.sort(key=lambda item: item.created_at)
        if not include_revoked:
            rows = [item for item in rows if item.revoked_at is None]
        return KeyPage(data=tuple(rows[:limit]), next_cursor=None, limit=limit, total=len(rows), cursor=cursor)


class _EntitlementStub:
    async def snapshot(self, tenant_id: UUID) -> EntitlementSnapshot:
        return EntitlementSnapshot(
            tenant_id=tenant_id,
            status=EntitlementStatus.BETA_ACTIVE,
            allowance_jobs=10,
            used_jobs=3,
            period_start=NOW,
            period_end=NOW + timedelta(days=30),
            grace_until=None,
        )


async def _principal() -> PortalPrincipal:
    return PortalPrincipal(
        tenant_id=TENANT_ID,
        issuer="https://issuer.example",
        subject="subject-1",
        email="user@example.test",
    )


async def _missing_auth() -> PortalPrincipal:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="portal authorization required")


def _app(
    *,
    key_service: _KeyServiceStub | None = None,
    entitlement_service: _EntitlementStub | None = None,
    authenticate: bool = True,
    session: _SessionStub | None = None,
) -> FastAPI:
    application = FastAPI()
    application.include_router(portal.router)
    portal_session = session or _SessionStub()
    if authenticate:
        application.dependency_overrides[require_portal_principal] = _principal
    else:
        application.dependency_overrides[require_portal_principal] = _missing_auth
    if key_service is not None:

        async def override_key_service() -> _KeyServiceStub:
            return key_service

        application.dependency_overrides[portal.get_tenant_key_service] = override_key_service
    if entitlement_service is not None:

        async def override_entitlement_service() -> _EntitlementStub:
            return entitlement_service

        application.dependency_overrides[portal.get_tenant_entitlement_service] = override_entitlement_service

    async def override_usage_service() -> None:
        return None

    application.dependency_overrides[portal.get_portal_usage_service] = override_usage_service

    async def override_portal_session() -> _SessionStub:
        return portal_session

    application.dependency_overrides[portal.get_portal_session] = override_portal_session
    return application


def test_every_portal_endpoint_requires_authentication() -> None:
    key_service = _KeyServiceStub()
    key = _key(TENANT_ID)
    key_service.keys[key.api_key_id] = key
    application = _app(key_service=key_service, entitlement_service=_EntitlementStub(), authenticate=False)

    with TestClient(application) as client:
        responses = [
            client.get("/portal/me"),
            client.get("/portal/keys"),
            client.get(f"/portal/keys/{key.api_key_id}"),
            client.post("/portal/keys", headers={"Idempotency-Key": "create"}, json={}),
            client.post(
                f"/portal/keys/{key.api_key_id}/rotate",
                headers={"Idempotency-Key": "rotate"},
                json={"reason": "routine"},
            ),
            client.post(f"/portal/keys/{key.api_key_id}/revoke", json={}),
            client.get("/portal/usage"),
        ]

    assert [response.status_code for response in responses] == [401] * len(responses)


def test_foreign_key_is_not_disclosed_by_get_rotate_or_revoke() -> None:
    key_service = _KeyServiceStub()
    foreign = _key(FOREIGN_TENANT_ID)
    key_service.keys[foreign.api_key_id] = foreign
    application = _app(key_service=key_service, entitlement_service=_EntitlementStub())

    with TestClient(application) as client:
        get_response = client.get(f"/portal/keys/{foreign.api_key_id}")
        rotate_response = client.post(
            f"/portal/keys/{foreign.api_key_id}/rotate",
            headers={"Idempotency-Key": "rotate-foreign"},
            json={"reason": "routine"},
        )
        revoke_response = client.post(f"/portal/keys/{foreign.api_key_id}/revoke", json={})

    assert get_response.status_code == 404
    assert rotate_response.status_code == 404
    assert revoke_response.status_code == 404
    assert foreign.api_key_id.hex not in get_response.text
    assert foreign.api_key_id.hex not in rotate_response.text
    assert foreign.api_key_id.hex not in revoke_response.text


def test_create_replay_returns_secret_once_and_changed_body_is_422() -> None:
    key_service = _KeyServiceStub()
    application = _app(key_service=key_service, entitlement_service=_EntitlementStub())

    with TestClient(application) as client:
        first = client.post(
            "/portal/keys",
            headers={"Idempotency-Key": " create-1 "},
            json={"lifetime_seconds": 3600, "rate_limit_tier": " standard "},
        )
        replay = client.post(
            "/portal/keys",
            headers={"Idempotency-Key": "create-1"},
            json={"lifetime_seconds": 3600, "rate_limit_tier": "standard"},
        )
        changed = client.post(
            "/portal/keys",
            headers={"Idempotency-Key": "create-1"},
            json={"lifetime_seconds": 7200, "rate_limit_tier": "standard"},
        )

    assert first.status_code == 200
    assert first.json()["raw_key"] == "raw-secret-1"
    assert first.json()["replayed"] is False
    assert replay.status_code == 200
    assert replay.json()["raw_key"] is None
    assert replay.json()["replayed"] is True
    assert changed.status_code == 422
    assert "raw-secret-1" not in replay.text
    assert "raw-secret-1" not in changed.text


def test_revoke_confirms_last_usable_key_and_repeated_revoke_is_conflict() -> None:
    key_service = _KeyServiceStub()
    key = _key(TENANT_ID, raw_key=None)
    key_service.keys[key.api_key_id] = key
    application = _app(key_service=key_service, entitlement_service=_EntitlementStub())

    with TestClient(application) as client:
        warning = client.post(f"/portal/keys/{key.api_key_id}/revoke", json={})
        confirmed = client.post(
            f"/portal/keys/{key.api_key_id}/revoke",
            json={"confirm_last_usable": True},
        )
        repeated = client.post(f"/portal/keys/{key.api_key_id}/revoke", json={"confirm": True})

    assert warning.status_code == 409
    assert "API access" in warning.text
    assert confirmed.status_code == 200
    assert confirmed.json()["revoked"] is True
    assert repeated.status_code == 409
    assert warning.headers["cache-control"] == "no-store"


def test_key_responses_are_no_store_and_lists_exclude_secrets_and_hashes() -> None:
    key_service = _KeyServiceStub()
    key = _key(TENANT_ID)
    key_service.keys[key.api_key_id] = key
    application = _app(key_service=key_service, entitlement_service=_EntitlementStub())

    with TestClient(application) as client:
        listed = client.get("/portal/keys")
        detail = client.get(f"/portal/keys/{key.api_key_id}")

    assert listed.status_code == 200
    assert detail.status_code == 200
    assert listed.headers["cache-control"] == "no-store"
    assert detail.headers["cache-control"] == "no-store"
    assert "api_key_hash" not in listed.text
    assert "raw_key" not in listed.text
    assert "api_key_hash" not in detail.text
    assert "raw_key" not in detail.text


def test_limit_above_maximum_is_clamped_and_applied_limit_is_returned() -> None:
    key_service = _KeyServiceStub()
    for _ in range(105):
        key = _key(TENANT_ID)
        key_service.keys[key.api_key_id] = key
    application = _app(key_service=key_service, entitlement_service=_EntitlementStub())

    with TestClient(application) as client:
        response = client.get("/portal/keys?limit=500")

    assert response.status_code == 200
    assert response.json()["limit"] == 100
    assert len(response.json()["data"]) == 100
    assert key_service.list_limits == [100]


def test_usage_uses_authoritative_entitlement_provenance_without_inventing_metadata() -> None:
    application = _app(key_service=_KeyServiceStub(), entitlement_service=_EntitlementStub())

    with TestClient(application) as client:
        response = client.get("/portal/usage")

    payload = response.json()
    assert response.status_code == 200
    assert payload["used"] == 3
    assert payload["reserved"] is None
    assert payload["remaining"] == 7
    assert payload["status"] == EntitlementStatus.BETA_ACTIVE.value
    assert payload["status"] in {member.value for member in EntitlementStatus}
    assert payload["data_source"] == "authoritative"
    assert payload["period_start"] == NOW.isoformat().replace("+00:00", "Z")
    assert payload["period"]["start"] == payload["period_start"]
    assert payload["as_of"] is None


class _PagedKeyService(_KeyServiceStub):
    def __init__(self, pages: dict[str | None, KeyPage]) -> None:
        super().__init__()
        self.pages = pages
        self.cursors: list[str | None] = []

    async def list_keys(
        self,
        tenant_id: UUID,
        *,
        cursor: str | None = None,
        limit: int = 25,
        include_revoked: bool = True,
    ) -> KeyPage:
        self.cursors.append(cursor)
        return self.pages[cursor]


class _InfiniteCursorKeyService(_KeyServiceStub):
    def __init__(self) -> None:
        super().__init__()
        self.cursors: list[str | None] = []

    async def list_keys(
        self,
        tenant_id: UUID,
        *,
        cursor: str | None = None,
        limit: int = 25,
        include_revoked: bool = True,
    ) -> KeyPage:
        self.cursors.append(cursor)
        next_cursor = f"cursor-{len(self.cursors)}"
        return KeyPage(data=(), next_cursor=next_cursor, limit=limit, total=0, cursor=cursor)


@pytest.mark.parametrize("operation", ["create", "rotate", "revoke"])
def test_mutating_portal_operations_fail_before_returning_any_secret_when_commit_raises(
    operation: str,
) -> None:
    key_service = _KeyServiceStub()
    key = _key(TENANT_ID)
    key_service.keys[key.api_key_id] = key
    session = _SessionStub(fail_commit=True)
    application = _app(key_service=key_service, entitlement_service=_EntitlementStub(), session=session)

    with TestClient(application) as client:
        if operation == "create":
            response = client.post("/portal/keys", headers={"Idempotency-Key": "create-fails"}, json={})
        elif operation == "rotate":
            response = client.post(
                f"/portal/keys/{key.api_key_id}/rotate",
                headers={"Idempotency-Key": "rotate-fails"},
                json={},
            )
        else:
            response = client.post(
                f"/portal/keys/{key.api_key_id}/revoke",
                json={"emergency": True},
            )

    assert response.status_code == 500
    assert response.status_code >= 500
    assert "raw-secret" not in response.text
    assert "replacement-secret" not in response.text


@pytest.mark.parametrize("operation", ["create", "rotate", "revoke"])
def test_mutating_portal_operations_commit_before_response(operation: str) -> None:
    key_service = _KeyServiceStub()
    key = _key(TENANT_ID)
    key_service.keys[key.api_key_id] = key
    session = _SessionStub()
    application = _app(key_service=key_service, entitlement_service=_EntitlementStub(), session=session)

    with TestClient(application) as client:
        if operation == "create":
            response = client.post("/portal/keys", headers={"Idempotency-Key": "create-order"}, json={})
        elif operation == "rotate":
            response = client.post(
                f"/portal/keys/{key.api_key_id}/rotate",
                headers={"Idempotency-Key": "rotate-order"},
                json={},
            )
        else:
            response = client.post(
                f"/portal/keys/{key.api_key_id}/revoke",
                json={"emergency": True},
            )

    assert response.status_code == 200
    assert session.commit_calls == 1


def test_create_commits_before_response_body_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    key_service = _KeyServiceStub(events=events)
    session = _SessionStub(events=events)
    application = _app(key_service=key_service, entitlement_service=_EntitlementStub(), session=session)
    original_issue_response = portal._issue_response

    def observed_issue_response(result: KeyIssueResult, *, tenant_id: UUID):
        events.append("response")
        return original_issue_response(result, tenant_id=tenant_id)

    monkeypatch.setattr(portal, "_issue_response", observed_issue_response)

    with TestClient(application) as client:
        response = client.post("/portal/keys", headers={"Idempotency-Key": "create-order"}, json={})

    assert response.status_code == 200
    assert events == ["create", "commit", "response"]


def test_find_key_follows_cursor_to_second_page() -> None:
    first = _key(TENANT_ID)
    target = _key(TENANT_ID)
    service = _PagedKeyService(
        {
            None: KeyPage(data=(first,), next_cursor="page-2", limit=100, total=2, cursor=None),
            "page-2": KeyPage(data=(target,), next_cursor=None, limit=100, total=2, cursor="page-2"),
        }
    )
    application = _app(key_service=service, entitlement_service=_EntitlementStub())

    with TestClient(application) as client:
        response = client.get(f"/portal/keys/{target.api_key_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(target.api_key_id)
    assert service.cursors == [None, "page-2"]


def test_last_usable_key_counts_usable_rows_across_pages() -> None:
    target = _key(TENANT_ID)
    second_usable = _key(TENANT_ID)
    service = _PagedKeyService(
        {
            None: KeyPage(data=(target,), next_cursor="page-2", limit=100, total=2, cursor=None),
            "page-2": KeyPage(data=(second_usable,), next_cursor=None, limit=100, total=2, cursor="page-2"),
        }
    )
    application = _app(key_service=service, entitlement_service=_EntitlementStub())

    with TestClient(application) as client:
        response = client.post(f"/portal/keys/{target.api_key_id}/revoke", json={})

    assert response.status_code == 200
    assert service.cursors == [None, "page-2", None, "page-2"]


def test_key_lookup_fails_closed_when_cursor_page_bound_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(portal, "MAX_KEY_LOOKUP_PAGES", 2)
    service = _InfiniteCursorKeyService()
    application = _app(key_service=service, entitlement_service=_EntitlementStub())

    with TestClient(application) as client:
        response = client.get(f"/portal/keys/{uuid4()}")

    assert response.status_code == 503
    assert "page bound" in response.text
    assert len(service.cursors) == 2
