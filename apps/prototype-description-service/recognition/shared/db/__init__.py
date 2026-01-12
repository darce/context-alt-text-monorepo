"""Shared database utilities for the recognition service."""

from recognition.shared.db.dialect import is_postgres, is_sqlite, timestamp_as_epoch
from recognition.shared.db.helpers import execute_dml, get_rowcount

__all__ = [
    "execute_dml",
    "get_rowcount",
    "is_postgres",
    "is_sqlite",
    "timestamp_as_epoch",
]
