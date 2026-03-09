"""Common imports shared across all model modules."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.settings import get_database_settings

_DB_SETTINGS = get_database_settings()

__all__ = [
    "uuid",
    "datetime",
    "Vector",
    "BigInteger",
    "JSON",
    "Boolean",
    "CheckConstraint",
    "Float",
    "ForeignKey",
    "Index",
    "Integer",
    "String",
    "Text",
    "UniqueConstraint",
    "func",
    "text",
    "ARRAY",
    "JSONB",
    "TIMESTAMP",
    "UUID",
    "Mapped",
    "mapped_column",
    "relationship",
    "Base",
    "_DB_SETTINGS",
]
