"""Logging configuration for the recognition service."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "recognition.log"


def _is_test_environment() -> bool:
    """Check if we're running in a test environment."""
    # pytest sets this when running tests
    return "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST") is not None


class ContextualFormatter(logging.Formatter):
    """Formatter that tolerates optional context fields."""

    def __init__(self, fmt: str, defaults: dict[str, Any] | None = None) -> None:
        super().__init__(fmt)
        self.defaults = defaults or {
            "media_id": "-",
            "cluster_id": "-",
            "identity_id": "-",
            "similarity": "-",
        }

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - exercised via logging
        message = super().format(record)
        context_parts = []

        # Add context fields if present
        if hasattr(record, "media_id") and record.media_id != "-":
            context_parts.append(f"media={record.media_id}")
        if hasattr(record, "cluster_id") and record.cluster_id != "-":
            context_parts.append(f"cluster={record.cluster_id}")
        if hasattr(record, "identity_id") and record.identity_id != "-":
            context_parts.append(f"identity={record.identity_id}")
        if hasattr(record, "similarity") and record.similarity != "-":
            context_parts.append(f"similarity={record.similarity}")

        if context_parts:
            return f"{message} [{' '.join(context_parts)}]"
        return message


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
            or name.startswith("db")
        )
        return allowed


def configure_logging(level: str = "INFO") -> None:
    """
    Configure logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Note:
        File logging is automatically disabled during tests to prevent
        test output from polluting production log files.
    """
    is_test = _is_test_environment()

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    root.handlers.clear()

    recognition_filter = RecognitionFilter()

    # Console handler: include timestamps
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s:     %(name)s - %(message)s"))
    console_handler.addFilter(recognition_filter)
    root.addHandler(console_handler)

    # File handler: detailed context with timestamps (skip during tests)
    # Use WatchedFileHandler so external log rotation (make logs-rotate) works without restarting the server.
    # WatchedFileHandler detects when the file is moved/rotated and reopens it automatically.
    if not is_test:
        file_handler = logging.handlers.WatchedFileHandler(LOG_FILE)
        file_handler.setLevel(getattr(logging, level.upper()))
        file_handler.setFormatter(ContextualFormatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
        file_handler.addFilter(recognition_filter)
        root.addHandler(file_handler)

    # Set specific loggers to INFO to see diagnostic output
    logging.getLogger("recognition.application").setLevel(logging.INFO)
    logging.getLogger("recognition.infrastructure").setLevel(logging.INFO)
    logging.getLogger("db").setLevel(logging.INFO)


def log_db_reset(message: str = "Database reset via reset_dev_db.sh") -> None:
    """Log a database reset event directly to the log file.

    This can be called from shell scripts via:
        python -c "from api.logging_config import log_db_reset; log_db_reset()"

    Args:
        message: Custom message to log (optional)
    """
    LOG_DIR.mkdir(exist_ok=True)

    # Create a dedicated handler that bypasses test detection
    # since this is explicitly called from a shell script.
    # Use WatchedFileHandler for consistency with the main logger.
    handler = logging.handlers.WatchedFileHandler(LOG_FILE)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))

    db_logger = logging.getLogger("db.reset")
    db_logger.setLevel(logging.INFO)
    db_logger.addHandler(handler)

    db_logger.info("=== %s ===", message)

    handler.close()
    db_logger.removeHandler(handler)


def enable_debug_logging() -> None:
    """Enable DEBUG level logging for detailed diagnostics."""
    configure_logging("DEBUG")
