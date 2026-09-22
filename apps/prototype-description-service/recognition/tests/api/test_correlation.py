"""Tests for correlation ID middleware, filter, and structured JSON logging.

Slice 1 of E15-2 observability baseline: every request gets a correlation ID
(generated or echoed from X-Request-ID), the ID flows through contextvars into
every log record emitted for that request, and logs are serialized as JSON.
"""

from __future__ import annotations

import json
import logging
import re
from logging.handlers import MemoryHandler

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.logging_config import RecognitionFilter, build_json_formatter
from recognition.interface_adapters.http.middleware.correlation import (
    ACCESS_LOGGER_NAME,
    CORRELATION_ID_HEADER,
    CorrelationIdFilter,
    CorrelationIdMiddleware,
    _correlation_id_var,
    get_correlation_id,
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _build_app(logger_name: str = "recognition.application.test_correlation") -> tuple[FastAPI, logging.Logger]:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    logger = logging.getLogger(logger_name)

    @app.get("/echo")
    def echo() -> dict[str, str | None]:
        logger.info("first log line")
        logger.info("second log line")
        return {"correlation_id": get_correlation_id()}

    # Importing here keeps the test app optional: the /boom route is only used
    # by the exception-handler test, which registers handlers after building.
    from recognition.interface_adapters.http.exception_handlers import (
        ValidationError as HttpValidationError,
    )

    @app.get("/boom")
    def boom() -> None:
        raise HttpValidationError("kaboom")

    return app, logger


def test_correlation_id_generated_when_header_absent() -> None:
    app, _ = _build_app()
    client = TestClient(app)

    resp = client.get("/echo")

    assert resp.status_code == 200
    header_value = resp.headers.get(CORRELATION_ID_HEADER)
    assert header_value is not None, "middleware must emit X-Request-ID response header"
    assert UUID_RE.match(header_value), f"unexpected correlation id format: {header_value!r}"
    assert resp.json()["correlation_id"] == header_value


def test_correlation_id_echoes_incoming_header() -> None:
    app, _ = _build_app()
    client = TestClient(app)
    incoming = "00000000-0000-4000-8000-000000000001"

    resp = client.get("/echo", headers={CORRELATION_ID_HEADER: incoming})

    assert resp.status_code == 200
    assert resp.headers.get(CORRELATION_ID_HEADER) == incoming
    assert resp.json()["correlation_id"] == incoming


def test_correlation_id_injected_into_log_records(caplog: pytest.LogCaptureFixture) -> None:
    app, _ = _build_app()
    caplog.handler.addFilter(CorrelationIdFilter())
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="recognition.application.test_correlation"):
        resp = client.get("/echo")

    records = [r for r in caplog.records if r.name == "recognition.application.test_correlation"]
    assert len(records) == 2, "both log lines should be captured"

    expected_id = resp.headers[CORRELATION_ID_HEADER]
    ids = {getattr(record, "correlation_id", None) for record in records}
    assert ids == {expected_id}, f"correlation IDs should be stable across records, got {ids}"


def test_recognition_filter_keeps_request_access_record() -> None:
    app, _ = _build_app()
    access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
    handler = MemoryHandler(capacity=100, target=None)
    handler.addFilter(RecognitionFilter())
    previous_level = access_logger.level
    access_logger.setLevel(logging.INFO)
    access_logger.addHandler(handler)
    try:
        with TestClient(app) as client:
            response = client.get("/echo")

        assert response.status_code == 200
        records = [record for record in handler.buffer if record.name == ACCESS_LOGGER_NAME]
        assert records, "request-scoped access record should survive RecognitionFilter"
    finally:
        access_logger.removeHandler(handler)
        access_logger.setLevel(previous_level)
        handler.close()


def test_recognition_filter_drops_file_infrastructure_record() -> None:
    logger = logging.getLogger("recognition.infrastructure.file.test")
    handler = MemoryHandler(capacity=100, target=None)
    handler.addFilter(RecognitionFilter())
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info("thumbnail file request")

        assert not handler.buffer
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.close()


def test_correlation_id_stable_across_concurrent_requests() -> None:
    app, _ = _build_app()
    client = TestClient(app)

    resp_a = client.get("/echo")
    resp_b = client.get("/echo")

    id_a = resp_a.headers[CORRELATION_ID_HEADER]
    id_b = resp_b.headers[CORRELATION_ID_HEADER]
    assert id_a != id_b, "each request should get a unique generated correlation ID"


def test_contextvar_clears_between_requests() -> None:
    app, _ = _build_app()
    client = TestClient(app)

    client.get("/echo")

    assert _correlation_id_var.get() is None, "correlation id contextvar must be reset after the request scope exits"


def test_json_formatter_emits_correlation_id_field() -> None:
    formatter = build_json_formatter()
    filter_ = CorrelationIdFilter()
    token = _correlation_id_var.set("req-abc-123")
    try:
        record = logging.getLogger("recognition.application.fmt_test").makeRecord(
            name="recognition.application.fmt_test",
            level=logging.INFO,
            fn="file.py",
            lno=42,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        filter_.filter(record)
        output = formatter.format(record)
    finally:
        _correlation_id_var.reset(token)

    payload = json.loads(output)
    assert payload["correlation_id"] == "req-abc-123"
    assert payload["message"] == "hello world"
    level = payload.get("levelname") or payload.get("level")
    assert level == "INFO"
    assert payload["name"] == "recognition.application.fmt_test"


def test_json_formatter_defaults_missing_correlation_id_to_placeholder() -> None:
    formatter = build_json_formatter()
    filter_ = CorrelationIdFilter()

    # Ensure contextvar is unset
    assert _correlation_id_var.get() is None

    record = logging.getLogger("recognition.application.fmt_test").makeRecord(
        name="recognition.application.fmt_test",
        level=logging.INFO,
        fn="file.py",
        lno=1,
        msg="no context",
        args=None,
        exc_info=None,
    )
    filter_.filter(record)
    output = formatter.format(record)

    payload = json.loads(output)
    assert payload["correlation_id"] == "-"


def test_exception_handler_uses_contextvar_correlation_id() -> None:
    """Unhandled exceptions should surface the same correlation id present in headers."""
    from recognition.interface_adapters.http.exception_handlers import register_exception_handlers

    app, _ = _build_app()
    register_exception_handlers(app)
    client = TestClient(app)

    incoming = "00000000-0000-4000-8000-0000000000ff"
    resp = client.get("/boom", headers={CORRELATION_ID_HEADER: incoming})

    assert resp.status_code == 400
    body = resp.json()
    assert body["correlation_id"] == incoming
    assert "trace_id" not in body
    assert resp.headers[CORRELATION_ID_HEADER] == incoming


@pytest.mark.asyncio
async def test_middleware_releases_the_contextvar_on_the_success_path() -> None:
    sent_messages: list[dict[str, object]] = []

    async def app(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)

    middleware = CorrelationIdMiddleware(app)
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    outer_token = _correlation_id_var.set(None)
    try:
        await middleware(scope, receive, send)
        assert get_correlation_id() is None

        sentinel_token = _correlation_id_var.set("pre-existing")
        try:
            await middleware(scope, receive, send)
            assert get_correlation_id() == "pre-existing"
        finally:
            _correlation_id_var.reset(sentinel_token)
        assert get_correlation_id() is None
    finally:
        _correlation_id_var.reset(outer_token)


@pytest.mark.asyncio
async def test_middleware_keeps_the_contextvar_bound_when_the_app_raises() -> None:
    request_id = "00000000-0000-4000-8000-0000000000aa"

    async def app(scope, receive, send) -> None:
        raise RuntimeError("boom")

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        raise AssertionError("the raising app must not send a response")

    middleware = CorrelationIdMiddleware(app)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/boom",
        "headers": [(CORRELATION_ID_HEADER.lower().encode("latin-1"), request_id.encode("latin-1"))],
    }
    outer_token = _correlation_id_var.set(None)
    try:
        with pytest.raises(RuntimeError, match="boom"):
            await middleware(scope, receive, send)
        assert get_correlation_id() == request_id
    finally:
        _correlation_id_var.reset(outer_token)


@pytest.mark.asyncio
async def test_two_sequential_requests_in_one_context_do_not_inherit_the_previous_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request_ids = [
        "00000000-0000-4000-8000-0000000000ab",
        "00000000-0000-4000-8000-0000000000ac",
    ]

    async def app(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    sent_messages: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)

    middleware = CorrelationIdMiddleware(app)
    outer_token = _correlation_id_var.set("pre-test")
    try:
        with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER_NAME):
            for request_id in request_ids:
                sent_messages.clear()

                scope = {
                    "type": "http",
                    "method": "GET",
                    "path": "/echo",
                    "headers": [
                        (CORRELATION_ID_HEADER.lower().encode("latin-1"), request_id.encode("latin-1"))
                    ],
                }
                await middleware(scope, receive, send)

                response_start = next(message for message in sent_messages if message["type"] == "http.response.start")
                response_headers = response_start["headers"]
                echoed_ids = [
                    value
                    for key, value in response_headers
                    if key.lower() == CORRELATION_ID_HEADER.lower().encode("latin-1")
                ]
                assert echoed_ids == [request_id.encode("latin-1")]

        assert get_correlation_id() == "pre-test"
    finally:
        _correlation_id_var.reset(outer_token)

    access_records = [record for record in caplog.records if record.name == ACCESS_LOGGER_NAME]
    assert [record.correlation_id for record in access_records] == request_ids
