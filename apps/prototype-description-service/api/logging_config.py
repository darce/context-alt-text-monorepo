"""Basic logging configuration for the application."""

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """
    Configure logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(levelname)s:     %(name)s - %(message)s",
        stream=sys.stdout,
    )

    # Set specific loggers to INFO to see diagnostic output
    logging.getLogger("recognition.application").setLevel(logging.INFO)
    logging.getLogger("recognition.infrastructure").setLevel(logging.INFO)
    logging.getLogger("db").setLevel(logging.INFO)


def enable_debug_logging() -> None:
    """Enable DEBUG level logging for detailed diagnostics."""
    configure_logging("DEBUG")
