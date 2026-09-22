"""Contract tests for the canonical API request id.

The request id is a validated transport value, an error-response diagnostic,
and a field on the request-scoped access record.  These tests deliberately
exercise the ASGI boundary so malformed header bytes cannot be hidden by an
HTTP client library's header validation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterable

import httpx
import pytest
from fastapi import FastAPI

from recognition.interface_adapters.http.exception_handlers import register_exception_handlers
from recognition.interface_adapters.http.middleware.correlation import (
    CORRELATION_ID_HEADER,
    CORRELATION_ID_LOG_FIELD,
    CorrelationIdFilter,
    CorrelationIdMiddleware,
    get_correlation_id,
)


UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
ACCESS_LOGGER_NAME = "recognition.access"
REQUEST_LOGGER_NAME = "recognition.application.test_request_id"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    request_logger = logging.getLogger(REQUEST_LOGGER_NAME)

    @app.get("/ok")
    async def ok() -> dict[str, str | None]:
        request_logger.info("request handled")
        return {"correlation_id": get_correlation_id()}

    @app.get("/slow")
    async def slow() -> dict[str, str | None]:
        await asyncio.sleep(0.001)
        request_logger.info("slow request handled")
        return {"correlation_id": get_correlation_id()}

    @app.get("/validate")
    async def validate(required: int) -> dict[str, int]:
        return {"required": required}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("request failed")

    return app


async def _raw_request(
    app: FastAPI,
    *,
    path: str = "/ok",
    header_values: Iterable[bytes] = (),
) -> tuple[int, dict[str, str], bytes]:
    """Call the ASGI app with exact header bytes, including malformed values."""

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [(CORRELATION_ID_HEADER.lower().encode("ascii"), value) for value in header_values],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []
    request_sent = False

    async def receive() -> dict:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    await app(scope, receive, send)
    response_start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in response_start["headers"]}
    return response_start["status"], headers, body


def _install_capture_filter(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    caplog.handler.addFilter(CorrelationIdFilter())


def _records_for(caplog: pytest.LogCaptureFixture, correlation_id: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if getattr(record, CORRELATION_ID_LOG_FIELD, None) == correlation_id]


def test_valid_v4_is_preserved_and_echoed() -> None:
    app = _build_app()
    incoming = "00000000-0000-4000-8000-000000000001"

    status, headers, body = asyncio.run(_raw_request(app, header_values=[incoming.encode("ascii")]))

    assert status == 200
    assert headers[CORRELATION_ID_HEADER.lower()] == incoming
    assert json.loads(body)["correlation_id"] == incoming


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_values",
    [
        [b"00000000-0000-1000-8000-000000000001"],
        [b"00000000-0000-7000-8000-000000000001"],
        [b"garbage"],
        [b"x" * 37],
        [b""],
        [b"00000000-0000-4000-8000-000000000001\r\nforged: yes"],
        [b"00000000-0000-4000-8000-000000000001", b"00000000-0000-4000-8000-000000000002"],
    ],
)
async def test_invalid_request_id_is_replaced_and_never_observable(
    raw_values: list[bytes], caplog: pytest.LogCaptureFixture
) -> None:
    app = _build_app()
    _install_capture_filter(caplog)

    status, headers, body = await _raw_request(app, header_values=raw_values)

    replacement = headers[CORRELATION_ID_HEADER.lower()]
    assert status == 200
    assert UUID4_RE.fullmatch(replacement)
    assert json.loads(body)["correlation_id"] == replacement
    raw_texts = [raw.decode("latin-1") for raw in raw_values if raw]
    assert all(raw not in body.decode("utf-8") for raw in raw_texts)
    assert all(raw not in caplog.text for raw in raw_texts)
    assert all(raw not in value for raw in raw_texts for value in headers.values())


@pytest.mark.asyncio
async def test_success_not_found_validation_and_unhandled_500_echo_and_log_same_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _build_app()
    _install_capture_filter(caplog)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    cases = [("/ok", 200), ("/missing", 404), ("/validate", 422), ("/boom", 500)]

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for index, (path, expected_status) in enumerate(cases):
            incoming = f"00000000-0000-4000-8000-{index + 1:012x}"
            response = await client.get(path, headers={CORRELATION_ID_HEADER: incoming})

            assert response.status_code == expected_status
            assert response.headers[CORRELATION_ID_HEADER] == incoming
            records = _records_for(caplog, incoming)
            assert records, f"expected logs carrying {incoming}"
            access_records = [record for record in records if record.name == ACCESS_LOGGER_NAME]
            assert len(access_records) == 1


@pytest.mark.asyncio
async def test_concurrent_requests_keep_ids_in_their_own_records(caplog: pytest.LogCaptureFixture) -> None:
    app = _build_app()
    _install_capture_filter(caplog)
    incoming_ids = [f"00000000-0000-4000-8000-{index + 1:012x}" for index in range(8)]
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = await asyncio.gather(
            *(client.get("/slow", headers={CORRELATION_ID_HEADER: incoming}) for incoming in incoming_ids)
        )

    assert [response.headers[CORRELATION_ID_HEADER] for response in responses] == incoming_ids
    for incoming in incoming_ids:
        records = _records_for(caplog, incoming)
        assert records
        assert all(getattr(record, CORRELATION_ID_LOG_FIELD) == incoming for record in records)
        assert len([record for record in records if record.name == ACCESS_LOGGER_NAME]) == 1


def test_log_outside_request_has_no_fabricated_request_id(caplog: pytest.LogCaptureFixture) -> None:
    _install_capture_filter(caplog)
    logging.getLogger(REQUEST_LOGGER_NAME).info("background record")

    record = next(record for record in caplog.records if record.getMessage() == "background record")
    assert getattr(record, CORRELATION_ID_LOG_FIELD) == "-"
