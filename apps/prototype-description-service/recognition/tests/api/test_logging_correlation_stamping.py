"""Regression tests for correlation IDs stamped at LogRecord creation."""

from __future__ import annotations

import logging

import pytest

from api import logging_config
from api.logging_config import configure_logging
from recognition.interface_adapters.http.middleware.correlation import (
    CORRELATION_ID_LOG_FIELD,
    CORRELATION_ID_PLACEHOLDER,
    _correlation_id_var,
)


@pytest.fixture(autouse=True)
def _restore_record_factory_and_root_logging():
    """Keep the process-wide logging hooks isolated between tests."""
    root = logging.getLogger()
    original_factory = logging.getLogRecordFactory()
    original_handlers = root.handlers[:]
    original_filters = root.filters[:]
    original_level = root.level
    token = _correlation_id_var.set(None)
    logging_config._RECORD_FACTORY_INSTALLED = False
    try:
        yield
    finally:
        _correlation_id_var.reset(token)
        logging.setLogRecordFactory(original_factory)
        logging_config._RECORD_FACTORY_INSTALLED = False
        root.handlers.clear()
        root.handlers.extend(original_handlers)
        root.filters.clear()
        root.filters.extend(original_filters)
        root.setLevel(original_level)


def _attach_bare_root_handler() -> list[logging.LogRecord]:
    """Attach a filter-free external handler after configure_logging()."""
    root = logging.getLogger()
    root.handlers.clear()
    records: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _CaptureHandler()
    assert not handler.filters
    root.addHandler(handler)
    return records


def _recognition_logger() -> logging.Logger:
    return logging.getLogger("recognition.application.test_logging_correlation_stamping")


def test_externally_attached_root_handler_sees_correlation_id() -> None:
    configure_logging()
    captured = _attach_bare_root_handler()
    bound_id = "bound-correlation-id"
    token = _correlation_id_var.set(bound_id)
    try:
        _recognition_logger().info("child logger record")
    finally:
        _correlation_id_var.reset(token)

    assert len(captured) == 1
    assert getattr(captured[0], CORRELATION_ID_LOG_FIELD, None) == bound_id


def test_record_without_a_bound_correlation_id_gets_the_placeholder() -> None:
    configure_logging()
    captured = _attach_bare_root_handler()

    _recognition_logger().info("unbound child logger record")

    assert len(captured) == 1
    assert getattr(captured[0], CORRELATION_ID_LOG_FIELD, None) == CORRELATION_ID_PLACEHOLDER


def test_explicit_extra_correlation_id_is_not_overwritten() -> None:
    configure_logging()
    captured = _attach_bare_root_handler()
    token = _correlation_id_var.set("context-correlation-id")
    try:
        _recognition_logger().info(
            "explicit child logger record",
            extra={CORRELATION_ID_LOG_FIELD: "explicit-value"},
        )
    finally:
        _correlation_id_var.reset(token)

    assert len(captured) == 1
    assert getattr(captured[0], CORRELATION_ID_LOG_FIELD, None) == "explicit-value"


def test_configure_logging_is_idempotent_for_the_record_factory() -> None:
    original_factory = logging.getLogRecordFactory()

    configure_logging()
    first_factory = logging.getLogRecordFactory()
    configure_logging()
    second_factory = logging.getLogRecordFactory()
    configure_logging()
    third_factory = logging.getLogRecordFactory()

    assert first_factory is not original_factory
    assert second_factory is first_factory
    assert third_factory is second_factory
