from __future__ import annotations

import asyncio
import logging
from time import perf_counter

import pytest


def test_upload_rejection_has_correlation_header_and_access_record(caplog) -> None:
    from api import main as main_module
    from recognition.interface_adapters.http.middleware.correlation import (
        ACCESS_LOGGER_NAME,
        CORRELATION_ID_HEADER,
    )
    from recognition.interface_adapters.http.middleware.upload_size import UploadSizeLimitMiddleware

    request_id = "de305d54-75b4-431b-adb2-eb6b9e546014"
    caplog.set_level(logging.INFO, logger=ACCESS_LOGGER_NAME)
    root_logger = logging.getLogger()
    if caplog.handler not in root_logger.handlers:
        root_logger.addHandler(caplog.handler)
    upload_layer = next(item for item in main_module.app.user_middleware if item.cls is UploadSizeLimitMiddleware)
    content_length = upload_layer.kwargs["max_bytes"] + 1

    messages = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/scene/describe/multipart",
        "raw_path": b"/scene/describe/multipart",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-length", str(content_length).encode("ascii")),
            (CORRELATION_ID_HEADER.lower().encode("ascii"), request_id.encode("ascii")),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(message):
        messages.append(message)

    asyncio.run(main_module.app.build_middleware_stack()(scope, _receive, _send))
    response = next(message for message in messages if message["type"] == "http.response.start")
    response_headers = dict(response["headers"])

    assert response["status"] == 413
    assert response_headers[CORRELATION_ID_HEADER.lower().encode("ascii")] == request_id.encode("ascii")
    access_records = [
        record
        for record in caplog.records
        if record.name == ACCESS_LOGGER_NAME
        and getattr(record, "correlation_id", None) == request_id
        and getattr(record, "status_code", None) == 413
    ]
    assert len(access_records) == 1, (
        "upload rejection must emit exactly one correlated access record; "
        f"got {len(access_records)}"
    )


@pytest.mark.asyncio
async def test_detailed_health_bounds_database_probe(monkeypatch) -> None:
    from api import main as main_module
    from recognition.application.health import CheckResult
    from shared.health import HealthStatus

    monkeypatch.setenv("ACX_HEALTH_DB_TIMEOUT_SECONDS", "0.05")

    async def _slow_database_probe(_session):
        await asyncio.sleep(1)
        return CheckResult("database", HealthStatus.OK, "connected")

    monkeypatch.setattr(main_module, "check_database", _slow_database_probe)

    started = perf_counter()
    result = await main_module._detailed_health_database_check(object(), timeout_seconds=0.05)
    elapsed = perf_counter() - started

    assert elapsed < 0.5, f"/health/detailed DB probe exceeded its bound: {elapsed:.3f}s"
    assert result.status is HealthStatus.UNHEALTHY
    assert result.detail == "probe_timeout"


@pytest.mark.asyncio
async def test_detailed_health_bounds_embedding_capability_probe(monkeypatch) -> None:
    from api import main as main_module

    monkeypatch.setenv("ACX_HEALTH_DB_TIMEOUT_SECONDS", "0.05")

    async def _slow_capability_probe(_session):
        await asyncio.sleep(1)

    monkeypatch.setattr(main_module, "read_embedding_runtime_capability", _slow_capability_probe)
    monkeypatch.setattr(
        main_module,
        "embedding_runtime_health_payload",
        lambda _capability: {"available": True, "reason": None},
    )

    started = perf_counter()
    result = await main_module._detailed_health_embedding_runtime(object(), timeout_seconds=0.05)
    elapsed = perf_counter() - started

    assert elapsed < 0.5, f"/health/detailed capability probe exceeded its bound: {elapsed:.3f}s"
    assert result["reason"] == "capability read failed"


@pytest.mark.asyncio
async def test_local_cpu_readiness_fails_when_adapter_construction_fails(monkeypatch) -> None:
    from api import main as main_module
    from scene.config.profiles import DescriptionProfile
    from scene.interface_adapters.http import deps as scene_deps

    monkeypatch.setattr(scene_deps, "_missing_vlm_dependencies", lambda: ())

    def _construction_failure(_settings):
        raise RuntimeError("VlmSettings could not be constructed")

    monkeypatch.setattr(scene_deps, "_build_florence_small_adapter", _construction_failure)

    readiness = await main_module._description_adapter_readiness(DescriptionProfile.FLORENCE_SMALL)

    assert readiness["usable"] is False
    assert readiness["reason"] == "local_adapter_unavailable"
