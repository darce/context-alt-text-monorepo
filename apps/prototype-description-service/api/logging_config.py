"""Logging configuration for the recognition service.

Emits structured JSON log records so external aggregators can index fields
without regex parsing. Every record is stamped with the active correlation id
via :class:`CorrelationIdFilter` — see
``recognition/interface_adapters/http/middleware/correlation.py``.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from pythonjsonlogger.json import JsonFormatter

from recognition.interface_adapters.http.middleware.correlation import (
    CORRELATION_ID_LOG_FIELD,
    CORRELATION_ID_PLACEHOLDER,
    CorrelationIdFilter,
)

# Container default: image seeds + chowns /var/log/acx for USER acx (SEC-13).
# Do NOT use /app/logs — /app stays root:root and mkdir fails under USER acx.
_CONTAINER_LOG_DIR = Path("/var/log/acx")
_LOCAL_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def resolve_log_dir() -> Path:
    """Return the directory used for file logging.

    Priority: ``ACX_LOG_DIR`` env → container path when present → package-local
    ``logs/`` for host/dev. Callers must not assume the path is writable;
    :func:`configure_logging` handles unwritable dirs explicitly.
    """
    override = os.environ.get("ACX_LOG_DIR", "").strip()
    if override:
        return Path(override)
    if _CONTAINER_LOG_DIR.is_dir():
        return _CONTAINER_LOG_DIR
    return _LOCAL_LOG_DIR


# Resolved once at import for stable LOG_FILE binding; no mkdir here (USER acx).
LOG_DIR = resolve_log_dir()
LOG_FILE = LOG_DIR / "recognition.log"


def _is_test_environment() -> bool:
    """Check if we're running in a test environment."""
    return "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST") is not None


_JSON_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s %(message)s %(correlation_id)s "
    "%(media_id)s %(cluster_id)s %(identity_id)s %(similarity)s"
)

_STATIC_LOG_DEFAULTS = {
    CORRELATION_ID_LOG_FIELD: CORRELATION_ID_PLACEHOLDER,
    "media_id": "-",
    "cluster_id": "-",
    "identity_id": "-",
    "similarity": "-",
}


def build_json_formatter() -> JsonFormatter:
    """Return a ``JsonFormatter`` configured with our canonical field set.

    ``JsonFormatter`` interprets the format string to determine which attributes
    to extract from each :class:`~logging.LogRecord`; the keys are emitted
    verbatim as top-level fields in the JSON object. Missing optional context
    fields (``media_id``, ``cluster_id``, …) fall back to the ``-`` placeholder
    defined in ``_STATIC_LOG_DEFAULTS`` so every record has a stable schema.
    """
    return JsonFormatter(
        _JSON_FORMAT,
        defaults=_STATIC_LOG_DEFAULTS,
    )


class RecognitionFilter(logging.Filter):
    """Filter to include only recognition/db logs and drop noisy thumbnail/file requests."""

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        if name.startswith("recognition.infrastructure.file"):
            return False
        allowed = (
            name.startswith("recognition.application")
            or name.startswith("recognition.infrastructure")
            or name.startswith("recognition.interface_adapters")
            or name.startswith("recognition.worker")
            or name.startswith("db")
        )
        return allowed


def _try_add_file_handler(
    root: logging.Logger,
    *,
    level: int,
    correlation_filter: logging.Filter,
    recognition_filter: logging.Filter,
) -> bool:
    """Attach WatchedFileHandler when the log dir is usable.

    Returns True when file logging is active. On OSError (unwritable dir under
    USER acx, missing parent, etc.) leaves stream-only logging and emits an
    explicit warning — never a bare ``except: pass``.
    """
    log_dir = resolve_log_dir()
    log_file = log_dir / "recognition.log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.WatchedFileHandler(log_file)
    except OSError as exc:
        root.warning(
            "file logging disabled: cannot use %s (%s: %s); stream-only",
            log_dir,
            type(exc).__name__,
            exc,
        )
        return False
    file_handler.setLevel(level)
    file_handler.setFormatter(build_json_formatter())
    file_handler.addFilter(correlation_filter)
    file_handler.addFilter(recognition_filter)
    root.addHandler(file_handler)
    return True


def configure_logging(level: str = "INFO") -> None:
    """
    Configure logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Note:
        File logging is automatically disabled during tests to prevent
        test output from polluting production log files. Outside tests,
        an unwritable log directory falls back to stream-only logging.
    """
    is_test = _is_test_environment()
    log_level = getattr(logging, level.upper())

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    # Drop previously attached correlation filters so repeat calls don't stack.
    for existing in list(root.filters):
        if isinstance(existing, CorrelationIdFilter):
            root.removeFilter(existing)

    recognition_filter = RecognitionFilter()
    correlation_filter = CorrelationIdFilter()
    # Stamp every LogRecord at the root, so handlers attached by other systems
    # (pytest's caplog, external aggregators injected via addHandler) also see
    # the correlation_id attribute.
    root.addFilter(correlation_filter)

    # Console handler: JSON so stdout/stderr aggregators parse fields without regex.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(build_json_formatter())
    console_handler.addFilter(correlation_filter)
    console_handler.addFilter(recognition_filter)
    root.addHandler(console_handler)

    # File handler: WatchedFileHandler so external log rotation (make logs-rotate)
    # works without restarting the server; JSON payload mirrors the console output.
    if not is_test:
        _try_add_file_handler(
            root,
            level=log_level,
            correlation_filter=correlation_filter,
            recognition_filter=recognition_filter,
        )

    logging.getLogger("recognition.application").setLevel(logging.INFO)
    logging.getLogger("recognition.infrastructure").setLevel(logging.INFO)
    logging.getLogger("db").setLevel(logging.INFO)


def log_db_reset(message: str = "Database reset via reset_dev_db.sh") -> None:
    """Log a database reset event directly to the log file.

    This can be called from shell scripts via:
        python -c "from api.logging_config import log_db_reset; log_db_reset()"

    Args:
        message: Custom message to log (optional)

    Raises:
        OSError: if the log directory cannot be created or opened for write.
    """
    log_dir = resolve_log_dir()
    log_file = log_dir / "recognition.log"
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.WatchedFileHandler(log_file)
    handler.setFormatter(build_json_formatter())
    handler.addFilter(CorrelationIdFilter())

    db_logger = logging.getLogger("db.reset")
    db_logger.setLevel(logging.INFO)
    db_logger.addHandler(handler)

    db_logger.info("=== %s ===", message)

    handler.close()
    db_logger.removeHandler(handler)


def enable_debug_logging() -> None:
    """Enable DEBUG level logging for detailed diagnostics."""
    configure_logging("DEBUG")
