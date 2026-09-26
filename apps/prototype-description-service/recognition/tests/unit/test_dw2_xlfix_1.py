from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Response
from pydantic import ValidationError

from recognition.application.health import CheckResult
from recognition.application.settings.clustering import (
    CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK,
    load_cluster_recovery_calibration_policy,
)
from shared.health import HealthStatus


@pytest.mark.asyncio
async def test_ready_database_timeout_returns_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import main as api_main
    monkeypatch.setenv("ACX_HEALTH_DB_TIMEOUT_SECONDS", "0.01")

    async def hanging_database_check(_session: object) -> CheckResult:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(api_main, "check_database", hanging_database_check)
    monkeypatch.setattr(api_main, "get_or_create_session_dependency_circuit_breaker", lambda _app: object())

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(api_main.asyncio, "to_thread", run_inline)
    monkeypatch.setattr(
        api_main,
        "resolve_model_space_probe",
        lambda *_args, **_kwargs: (
            lambda: CheckResult("model_cache", HealthStatus.OK, "ok"),
            Path("."),
            "stub",
        ),
    )
    monkeypatch.setattr(api_main, "assert_space_activatable", lambda _profile: None)
    monkeypatch.setattr(
        api_main,
        "check_breaker",
        lambda _breaker: CheckResult("session_dependency_breaker", HealthStatus.OK, "ok"),
    )
    monkeypatch.setattr(
        api_main,
        "check_active_embedding_model",
        lambda: CheckResult("active_embedding_model", HealthStatus.OK, "ok"),
    )

    async def healthy_disk_probe() -> CheckResult:
        return CheckResult("disk_headroom", HealthStatus.OK, "ok")

    monkeypatch.setattr(api_main, "check_disk_headroom", healthy_disk_probe)

    app = FastAPI()
    api_main.register_health_probes(app)
    readiness = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/ready")
    response = Response()
    try:
        payload = await asyncio.wait_for(readiness(response=response, session=object()), timeout=0.5)
    except TimeoutError:
        pytest.fail("/ready did not enforce ACX_HEALTH_DB_TIMEOUT_SECONDS")

    assert response.status_code == 503
    database_check = next(item for item in payload["checks"] if item["name"] == "database")
    assert database_check["status"] == HealthStatus.UNHEALTHY.value
    assert database_check["detail"] == "probe_timeout"


@pytest.mark.asyncio
async def test_process_scan_job_preserves_generator_media_ids_for_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from recognition.application.scan import service as scan_service_module
    from recognition.application.scan.service import ScanService

    media_ids = ["1", "2"]
    detector_sources: list[str] = []
    persisted: dict[str, list[str] | None] = {}
    job_id = uuid4()

    class Detector:
        async def detect(self, sources: list[str]) -> list[object]:
            detector_sources.extend(sources)
            return []

    service = ScanService(
        session=MagicMock(),
        detector=Detector(),  # type: ignore[arg-type]
        generator=MagicMock(),
    )

    async def save_job_results(**kwargs: object) -> SimpleNamespace:
        received_ids = kwargs["media_ids"]
        received_sources = kwargs["media_sources"]
        persisted["media_ids"] = list(received_ids)  # type: ignore[arg-type]
        persisted["media_sources"] = list(received_sources) if received_sources else None  # type: ignore[arg-type]
        return SimpleNamespace(id=job_id)

    monkeypatch.setattr(service, "mark_job_running", AsyncMock(return_value=SimpleNamespace(id=job_id)))
    monkeypatch.setattr(service, "save_job_results", save_job_results)

    async def run_phases(*, mark_running, detect, persist):
        await mark_running()
        return await persist(await detect())

    monkeypatch.setattr(scan_service_module, "run_scan_three_phase", run_phases)

    await service.process_scan_job(
        tenant_id="tenant",
        job_id=job_id,
        media_ids=(item for item in media_ids),
    )

    assert detector_sources == media_ids
    assert persisted["media_ids"] == media_ids


def test_calibration_policy_rejects_unknown_abstention_selection() -> None:
    raw = deepcopy(CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK)
    raw["abstained_strata"]["selection"] = "cartesian_prodcut"

    with pytest.raises(ValidationError):
        load_cluster_recovery_calibration_policy(raw)


def test_abstained_cells_raises_for_unknown_selection() -> None:
    policy = load_cluster_recovery_calibration_policy(CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK)
    invalid_strata = policy.abstained_strata.model_copy(update={"selection": "cartesian_prodcut"})
    invalid_policy = policy.model_copy(update={"abstained_strata": invalid_strata})

    with pytest.raises(ValueError, match="Unsupported abstained strata selection"):
        invalid_policy.abstained_cells()
