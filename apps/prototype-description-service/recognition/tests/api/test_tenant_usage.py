"""API tests for the site-key tenant usage read (GET /recognition/tenant/usage)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from recognition.domain.portal_contracts import EntitlementSnapshot, EntitlementStatus, PortalPrincipal
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.deps.portal_auth import require_portal_principal
from recognition.interface_adapters.http.routers import portal
from recognition.interface_adapters.http.routers import tenant as tenant_router
from recognition.interface_adapters.http.usage_read import PortalUsageResponse
from recognition.tests.api.conftest import FakeSession

_SHARED_CONTRACTS = Path(__file__).resolve().parents[5] / "packages" / "shared-contracts"
_SCHEMA_PATH = _SHARED_CONTRACTS / "schemas" / "tenant-usage-response.schema.json"
_GOLDEN_PATH = _SHARED_CONTRACTS / "recognition" / "tenant-usage-response.golden.json"

USAGE_PATH = "/recognition/tenant/usage"
TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
PERIOD_START = datetime(2026, 10, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 11, 1, tzinfo=UTC)

FROZEN_KEYS = frozenset(
    {
        "tenant_id",
        "used",
        "reserved",
        "remaining",
        "allowance",
        "period_start",
        "period_end",
        "period",
        "as_of",
        "status",
        "data_source",
    }
)

# Projection reading that reproduces the golden fixture; remaining comes from the reader, never the builder.
_GOLDEN_PROJECTION = {
    "used": 120,
    "reserved": 8,
    "remaining": 372,
    "allowance": 500,
    "period_start": "2026-10-01T00:00:00Z",
    "period_end": "2026-11-01T00:00:00Z",
    "as_of": "2026-10-26T09:30:00Z",
    "status": "paid_active",
    "data_source": "authoritative",
}
_PENDING_PROJECTION = {
    "used": 4,
    "period": {"start": "2026-10-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"},
}


class _Entitlement:
    def __init__(self, reading: object) -> None:
        self._reading = reading
        self.tenant_ids: list[uuid.UUID] = []

    async def snapshot(self, tenant_id: uuid.UUID) -> object:
        self.tenant_ids.append(tenant_id)
        if isinstance(self._reading, Exception):
            raise self._reading
        return self._reading


class _Projection:
    def __init__(self, reading: Mapping[str, object]) -> None:
        self._reading = reading
        self.tenant_ids: list[uuid.UUID] = []

    async def usage(self, tenant_id: uuid.UUID) -> Mapping[str, object]:
        self.tenant_ids.append(tenant_id)
        return self._reading


def _snapshot() -> EntitlementSnapshot:
    return EntitlementSnapshot(
        tenant_id=TENANT_ID,
        status=EntitlementStatus.PAID_ACTIVE,
        allowance_jobs=500,
        used_jobs=120,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        grace_until=None,
    )


def _auth(*, tenant_claim: str | None = str(TENANT_ID), tier: str = "STANDARD") -> AuthContext:
    return AuthContext(
        token="site-key",
        tenant_claim=tenant_claim,
        api_key_id=f"key-{uuid.uuid4()}",
        rate_limit_tier=tier,
        enabled=True,
    )


async def _portal_principal() -> PortalPrincipal:
    return PortalPrincipal(
        tenant_id=TENANT_ID,
        issuer="https://issuer.example",
        subject="subject-1",
        email="owner@example.test",
    )


async def _portal_session() -> object:
    return object()


def _app(
    *,
    entitlement: _Entitlement,
    projection: _Projection | None = None,
    database_available: bool = True,
) -> FastAPI:
    """Mount both usage routes over one composition so they share fixtures."""
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.include_router(portal.router)
    app.state.tenant_entitlement_service = entitlement
    if projection is not None:
        app.state.portal_usage_service = projection
    session = FakeSession() if database_available else None

    async def _session_override():
        yield session

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[require_portal_principal] = _portal_principal
    app.dependency_overrides[portal.get_portal_session] = _portal_session
    return app


def _client(*, auth: AuthContext, **app_kwargs: object) -> TestClient:
    app = _app(**app_kwargs)  # type: ignore[arg-type]
    app.dependency_overrides[dependencies.require_auth] = lambda: auth
    app.dependency_overrides[dependencies.require_auth_key_only] = lambda: auth
    return TestClient(app)


def _real_auth_client(monkeypatch: pytest.MonkeyPatch, *, key_tenant_id: uuid.UUID, **app_kwargs: object) -> TestClient:
    """Client that runs the real key auth, including the X-Tenant-ID match."""
    from recognition.interface_adapters.http.deps import auth as auth_module

    async def _lookup(api_key, settings, session):  # noqa: ANN001
        return str(key_tenant_id), f"key-{uuid.uuid4()}", "STANDARD", False

    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    monkeypatch.setattr(auth_module, "_lookup_api_key", _lookup)
    monkeypatch.setattr(auth_module, "_enqueue_api_key_telemetry", lambda *_args: None)
    return TestClient(_app(**app_kwargs))  # type: ignore[arg-type]


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _assert_matches_contract(body: dict) -> None:
    schema = _schema()
    jsonschema.Draft7Validator(schema, format_checker=jsonschema.Draft7Validator.FORMAT_CHECKER).validate(body)
    assert set(body) == FROZEN_KEYS
    # The ambient validator does not enforce uuid/date-time formats, so check them directly.
    uuid.UUID(body["tenant_id"])
    for value in (body["period_start"], body["period_end"], body["period"]["start"], body["period"]["end"]):
        assert datetime.fromisoformat(value).tzinfo is not None
    if body["as_of"] is not None:
        assert datetime.fromisoformat(body["as_of"]).tzinfo is not None


def test_schema_and_golden_freeze_the_response_model_fields() -> None:
    schema = _schema()
    golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft7Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(schema["required"]) == FROZEN_KEYS
    assert set(PortalUsageResponse.model_fields) == FROZEN_KEYS
    assert set(schema["properties"]["period"]["properties"]) == {"start", "end"}
    assert schema["properties"]["period"]["additionalProperties"] is False
    assert set(schema["properties"]["status"]["enum"]) == {member.value for member in EntitlementStatus} | {None}
    _assert_matches_contract(golden)


@pytest.mark.parametrize("count", ["used", "reserved", "remaining", "allowance"])
def test_response_model_rejects_a_negative_count(count: str) -> None:
    golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))

    with pytest.raises(ValidationError):
        PortalUsageResponse.model_validate({**golden, count: -1})


def test_key_scoped_tenant_reads_its_own_usage() -> None:
    entitlement = _Entitlement(_snapshot())
    projection = _Projection(_GOLDEN_PROJECTION)
    client = _client(auth=_auth(), entitlement=entitlement, projection=projection)

    response = client.get(USAGE_PATH)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    _assert_matches_contract(body)
    assert body == json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    assert entitlement.tenant_ids == [TENANT_ID]
    assert projection.tenant_ids == [TENANT_ID]


@pytest.mark.parametrize(
    "projection_reading",
    [_GOLDEN_PROJECTION, None, _PENDING_PROJECTION],
    ids=["projection", "entitlement-only", "pending-projection"],
)
def test_portal_and_site_key_reads_return_byte_identical_bodies(projection_reading: dict | None) -> None:
    projection = _Projection(projection_reading) if projection_reading is not None else None
    client = _client(auth=_auth(), entitlement=_Entitlement(_snapshot()), projection=projection)

    portal_response = client.get("/portal/usage")
    tenant_response = client.get(USAGE_PATH)

    assert portal_response.status_code == 200
    assert tenant_response.status_code == 200
    assert tenant_response.content == portal_response.content
    _assert_matches_contract(tenant_response.json())


@pytest.mark.parametrize(
    ("auth", "detail"),
    [
        (_auth(tier="DEMO"), "tenant usage unavailable for demo tier"),
        (_auth(tenant_claim=None), "Tenant usage requires a tenant-scoped API key"),
        (_auth(tenant_claim="not-a-uuid"), "invalid tenant claim"),
    ],
    ids=["demo-tier", "claimless", "malformed-claim"],
)
def test_keys_without_a_usable_tenant_claim_are_forbidden(auth: AuthContext, detail: str) -> None:
    entitlement = _Entitlement(_snapshot())
    client = _client(auth=auth, entitlement=entitlement)

    response = client.get(USAGE_PATH)

    assert response.status_code == 403
    assert response.json() == {"detail": detail}
    assert entitlement.tenant_ids == []


def test_naming_agreement_keeps_its_claim_error_details() -> None:
    client = _client(auth=_auth(tier="DEMO"), entitlement=_Entitlement(_snapshot()))
    demo = client.get("/recognition/tenant/naming-agreement")
    client = _client(auth=_auth(tenant_claim=None), entitlement=_Entitlement(_snapshot()))
    claimless = client.get("/recognition/tenant/naming-agreement")

    assert demo.json() == {"detail": "naming agreement unavailable for demo tier"}
    assert claimless.json() == {"detail": "Naming agreement requires a tenant-scoped API key"}


def test_tenant_header_for_another_tenant_cannot_select_it(monkeypatch: pytest.MonkeyPatch) -> None:
    entitlement = _Entitlement(_snapshot())
    client = _real_auth_client(monkeypatch, key_tenant_id=TENANT_ID, entitlement=entitlement)

    foreign = client.get(
        USAGE_PATH,
        headers={"Authorization": "Bearer site-key", "X-Tenant-ID": str(OTHER_TENANT_ID)},
    )
    own = client.get(USAGE_PATH, headers={"Authorization": "Bearer site-key"})

    assert foreign.status_code == 403
    assert str(OTHER_TENANT_ID) not in foreign.text
    assert own.status_code == 200
    assert own.json()["tenant_id"] == str(TENANT_ID)
    assert entitlement.tenant_ids == [TENANT_ID]


def test_db_context_and_reads_are_scoped_to_the_key_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    contexts: list[uuid.UUID] = []

    async def _record_tenant_context(_session: object, tenant_id: uuid.UUID) -> None:
        contexts.append(tenant_id)

    monkeypatch.setattr(tenant_router, "is_postgres", lambda _session: True)
    monkeypatch.setattr(tenant_router, "set_tenant_context", _record_tenant_context)
    entitlement = _Entitlement(_snapshot())
    projection = _Projection(_GOLDEN_PROJECTION)
    client = _client(auth=_auth(), entitlement=entitlement, projection=projection)

    response = client.get(USAGE_PATH, headers={"X-Tenant-ID": str(OTHER_TENANT_ID)})

    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(TENANT_ID)
    assert contexts == [TENANT_ID]
    assert entitlement.tenant_ids == [TENANT_ID]
    assert projection.tenant_ids == [TENANT_ID]


def test_entitlement_read_failure_is_503_without_counts() -> None:
    entitlement = _Entitlement(RuntimeError("entitlement store unavailable"))
    client = _client(auth=_auth(), entitlement=entitlement, projection=_Projection(_GOLDEN_PROJECTION))

    response = client.get(USAGE_PATH)

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "tenant usage unavailable"}


def test_missing_database_session_is_503() -> None:
    entitlement = _Entitlement(_snapshot())
    client = _client(auth=_auth(), entitlement=entitlement, database_available=False)

    response = client.get(USAGE_PATH)

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert entitlement.tenant_ids == []


@pytest.mark.parametrize(
    ("entitlement_reading", "projection_reading", "expected_counts"),
    [
        (
            {"period_start": PERIOD_START, "period_end": PERIOD_END},
            None,
            {"used": None, "reserved": None, "remaining": None, "allowance": None},
        ),
        (
            {"period_start": PERIOD_START, "period_end": PERIOD_END},
            {"used": 5, "reserved": 1, "data_source": "authoritative"},
            {"used": 5, "reserved": 1, "remaining": None, "allowance": None},
        ),
    ],
    ids=["entitlement-without-counts", "projection-without-allowance"],
)
def test_missing_inputs_leave_remaining_null(
    entitlement_reading: dict,
    projection_reading: dict | None,
    expected_counts: dict,
) -> None:
    projection = _Projection(projection_reading) if projection_reading is not None else None
    client = _client(auth=_auth(), entitlement=_Entitlement(entitlement_reading), projection=projection)

    response = client.get(USAGE_PATH)

    assert response.status_code == 200
    body = response.json()
    _assert_matches_contract(body)
    assert {key: body[key] for key in expected_counts} == expected_counts
    assert body["status"] is None
    assert body["as_of"] is None


@pytest.mark.parametrize(
    "projection_reading",
    [
        {
            "used": 120,
            "reserved": None,
            "remaining": None,
            "allowance": 500,
            "period_start": "2026-10-01T00:00:00Z",
            "period_end": "2026-11-01T00:00:00Z",
        },
        None,
    ],
    ids=["projection", "entitlement-only"],
)
@pytest.mark.parametrize("path", [USAGE_PATH, "/portal/usage"], ids=["site-key", "portal"])
def test_unknown_remaining_is_never_derived_from_used_and_allowance(
    projection_reading: dict | None,
    path: str,
) -> None:
    projection = _Projection(projection_reading) if projection_reading is not None else None
    client = _client(auth=_auth(), entitlement=_Entitlement(_snapshot()), projection=projection)

    response = client.get(path)

    assert response.status_code == 200
    body = response.json()
    _assert_matches_contract(body)
    assert {key: body[key] for key in ("used", "reserved", "remaining", "allowance")} == {
        "used": 120,
        "reserved": None,
        "remaining": None,
        "allowance": 500,
    }


def test_null_projected_used_is_not_filled_from_the_entitlement() -> None:
    projection = _Projection({**_GOLDEN_PROJECTION, "used": None})
    client = _client(auth=_auth(), entitlement=_Entitlement(_snapshot()), projection=projection)

    response = client.get(USAGE_PATH)

    assert response.status_code == 200
    body = response.json()
    _assert_matches_contract(body)
    assert body["used"] is None
