"""Keep usage admission HTTP errors aligned with the published contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from recognition.application.services.usage_admission_service import (
    AllowanceExceededError,
    GlobalUsageLimitExceededError,
    UsageAdmissionStoppedError,
    UsageAdmissionTimeoutError,
    UsageAdmissionUnavailableError,
    UsageFingerprintConflictError,
)
from recognition.infrastructure.repositories.usage_repository import ExpiredUsageReservationError
from recognition.interface_adapters.http.deps.usage_admission import admit_usage, get_usage_admission_service
from recognition.tests.unit.test_app1_usage_admission_wiring import TENANT_ID, _FakeAdmission

CONTRACT_PATH = Path(__file__).resolve().parents[5] / "docs/workbay/contracts/usage-admission-errors.json"
CONTRACT_API_PATH = CONTRACT_PATH.with_name("usage-admission-api.md")
CONTRACT_CASES = (
    (402, "allowance_exhausted", "when_period_known"),
    (409, "usage_fingerprint_conflict", "never"),
    (409, "usage_reservation_expired", "never"),
    (503, "usage_admission_stopped", "never"),
    (503, "usage_admission_limited", "never"),
    (503, "usage_admission_unavailable", "never"),
    (503, "reservation_timeout", "always"),
    (503, "Usage admission unavailable", "never"),
)
_USE_DEPENDS_DEFAULT = object()


class _RollbackProbe:
    def __init__(self) -> None:
        self.calls = 0

    async def rollback(self) -> None:
        self.calls += 1


def _error_from_exception(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict):
        return exc.detail["error"]
    return exc.detail


def _request_with_service(configured: object) -> Request:
    app = FastAPI()
    app.state.usage_admission_service = configured
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "client": ("testclient", 12345),
        "app": app,
    }
    return Request(scope)


def _row_from_exception(exc: HTTPException) -> tuple[int, str, bool]:
    headers = exc.headers or {}
    return exc.status_code, _error_from_exception(exc), "Retry-After" in headers


def _assert_fixture_row(
    actual: tuple[int, str, bool],
    expected: tuple[int, str, str],
    *,
    period_known: bool = True,
) -> None:
    status_code, error, retry_after = expected
    assert actual[:2] == (status_code, error)
    should_have_retry_after = retry_after == "always" or (retry_after == "when_period_known" and period_known)
    assert actual[2] is should_have_retry_after


async def _admit_error(error: Exception, *, rollback_probe: _RollbackProbe | None = None) -> HTTPException:
    admission = _FakeAdmission()

    async def reject_reservation(*_args, **_kwargs):
        raise error

    admission.reserve = reject_reservation
    if rollback_probe is not None:
        admission._session = rollback_probe

    with pytest.raises(HTTPException) as exc_info:
        async with admit_usage(
            admission,
            tenant_id=TENANT_ID,
            idempotency_key="contract-test",
            job_id=None,
            cost_units=1,
        ):
            pytest.fail("dispatch must not run when reservation fails")

    assert admission.releases == []
    return exc_info.value


@pytest.mark.asyncio
async def test_usage_admission_errors_match_contract_fixture() -> None:
    fixture = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    fixture_rows = {
        (row["status"], row["error"], row["retry_after"])
        for row in fixture
    }
    fixture_order = tuple((row["status"], row["error"], row["retry_after"]) for row in fixture)
    expected_rows = set(CONTRACT_CASES)
    api_rows = []
    for line in CONTRACT_API_PATH.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0].isdigit():
            error = cells[1].split("`", 2)[1]
            api_rows.append((int(cells[0]), error))
    assert fixture_order == CONTRACT_CASES
    assert api_rows == [(status, error) for status, error, _retry_after in CONTRACT_CASES]

    exhausted = AllowanceExceededError(
        period_end=datetime.now(UTC) + timedelta(hours=1),
    )
    admit_scenarios = (
        (exhausted, CONTRACT_CASES[0], True),
        (AllowanceExceededError(), CONTRACT_CASES[0], False),
        (UsageFingerprintConflictError("changed fingerprint"), CONTRACT_CASES[1], True),
        (ExpiredUsageReservationError("idempotency key belongs to an expired reservation"), CONTRACT_CASES[2], True),
        (UsageAdmissionStoppedError("operator stop"), CONTRACT_CASES[3], True),
        (GlobalUsageLimitExceededError("queue limit"), CONTRACT_CASES[4], True),
        (UsageAdmissionUnavailableError("global state missing"), CONTRACT_CASES[5], True),
        (UsageAdmissionTimeoutError("reservation timed out"), CONTRACT_CASES[6], True),
    )

    exercised_rows: set[tuple[int, str, str]] = set()
    for error, expected, period_known in admit_scenarios:
        rollback_probe = _RollbackProbe() if isinstance(error, UsageAdmissionTimeoutError) else None
        exc = await _admit_error(error, rollback_probe=rollback_probe)
        _assert_fixture_row(_row_from_exception(exc), expected, period_known=period_known)
        exercised_rows.add(expected)
        if rollback_probe is not None:
            assert rollback_probe.calls == 1

    invalid_service_cases = (
        (_request_with_service(object()), _USE_DEPENDS_DEFAULT),
        (_request_with_service(object()), None),
        (_request_with_service(object()), SimpleNamespace()),
        (_request_with_service(lambda _session: object()), SimpleNamespace()),
    )
    for request, session in invalid_service_cases:
        with pytest.raises(HTTPException) as exc_info:
            if session is _USE_DEPENDS_DEFAULT:
                get_usage_admission_service(request)
            else:
                get_usage_admission_service(request, session)
        expected = CONTRACT_CASES[7]
        _assert_fixture_row(_row_from_exception(exc_info.value), expected)
        exercised_rows.add(expected)

    assert fixture_rows == exercised_rows == expected_rows
