"""Tests for correlation ID middleware, filter, and structured JSON logging.

Slice 1 of E15-2 observability baseline: every request gets a correlation ID
(generated or echoed from X-Request-ID), the ID flows through contextvars into
every log record emitted for that request, and logs are serialized as JSON.
"""

from __future__ import annotations

import json
import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.logging_config import build_json_formatter
from recognition.interface_adapters.http.middleware.correlation import (
    CORRELATION_ID_HEADER,
    CorrelationIdFilter,
    CorrelationIdMiddleware,
    _correlation_id_var,
    get_correlation_id,
)

UUID_RE = re.compile(r"^req-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


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
    incoming = "req-00000000-0000-7000-8000-000000000001"

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

    incoming = "req-00000000-0000-7000-8000-0000000000ff"
    resp = client.get("/boom", headers={CORRELATION_ID_HEADER: incoming})

    assert resp.status_code == 400
    body = resp.json()
    assert body["trace_id"] == incoming
    assert resp.headers[CORRELATION_ID_HEADER] == incoming
