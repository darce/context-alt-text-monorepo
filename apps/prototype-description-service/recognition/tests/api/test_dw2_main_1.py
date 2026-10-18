from __future__ import annotations

import asyncio
import io
import json
import logging
from time import perf_counter

import pytest


def test_upload_rejection_has_correlation_header_and_access_record() -> None:
    from api import main as main_module
    from recognition.interface_adapters.http.middleware.correlation import (
        ACCESS_LOGGER_NAME,
        CORRELATION_ID_HEADER,
    )
    from recognition.interface_adapters.http.middleware.upload_size import UploadSizeLimitMiddleware

    request_id = "de305d54-75b4-431b-adb2-eb6b9e546014"
    root_logger = logging.getLogger()
    console_handlers = [
        handler
        for handler in root_logger.handlers
        if type(handler) is logging.StreamHandler
    ]
    assert len(console_handlers) == 1, "application must emit access logs through one configured console handler"
    console_handler = console_handlers[0]
    original_stream = console_handler.stream
    captured_stream = io.StringIO()
    console_handler.setStream(captured_stream)
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

    try:
        asyncio.run(main_module.app.build_middleware_stack()(scope, _receive, _send))
    finally:
        console_handler.setStream(original_stream)
    response = next(message for message in messages if message["type"] == "http.response.start")
    response_headers = dict(response["headers"])

    assert response["status"] == 413
    assert response_headers[CORRELATION_ID_HEADER.lower().encode("ascii")] == request_id.encode("ascii")
    emitted_entries = [json.loads(line) for line in captured_stream.getvalue().splitlines() if line]
    access_entries = [entry for entry in emitted_entries if entry.get("name") == ACCESS_LOGGER_NAME]
    assert len(access_entries) == 1, (
        "upload rejection must emit exactly one JSON access log through the configured console handler; "
        f"got {len(access_entries)}"
    )
    assert access_entries[0]["correlation_id"] == request_id
    assert access_entries[0]["status_code"] == 413


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
