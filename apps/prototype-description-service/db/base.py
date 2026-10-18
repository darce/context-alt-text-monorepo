"""Declarative base used across the prototype description service."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""


__all__ = ["Base"]
