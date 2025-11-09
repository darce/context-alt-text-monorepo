"""Shared utility helpers for roster storage adapters."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from db.models import Tenant

logger = logging.getLogger(__name__)


DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def coerce_datetime(value: Optional[Any]) -> Optional[datetime]:
    """Convert ISO8601 strings into ``datetime`` instances when possible."""

    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    text_value = str(value).strip()
    if text_value.endswith("Z"):
        text_value = text_value[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(text_value)
    except ValueError:
        logger.debug("Failed to coerce datetime value '%s'", value)
        return None


def coerce_metadata(value: Any) -> Dict[str, Any]:
    """Ensure metadata is returned as a dictionary."""

    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            logger.debug("Failed to decode metadata JSON", exc_info=True)
            return {}
    return {}


def normalize_tenant_id(value: Optional[Any]) -> uuid.UUID:
    """Normalise the configured tenant identifier to a :class:`uuid.UUID`."""

    if value is None:
        return DEFAULT_TENANT_ID

    if isinstance(value, uuid.UUID):
        return value

    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return uuid.uuid5(uuid.NAMESPACE_DNS, value)

    raise TypeError(f"Unsupported tenant identifier type: {type(value)!r}")


def normalize_entry_id(value: Optional[Any]) -> uuid.UUID:
    """Normalise roster entry identifiers to UUID primary keys."""

    if isinstance(value, uuid.UUID):
        return value

    if not value:
        return uuid.uuid4()

    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return uuid.uuid5(uuid.NAMESPACE_URL, value)

    raise TypeError(f"Unsupported entry identifier type: {type(value)!r}")


def ensure_tenant(session: Session, tenant_uuid: uuid.UUID) -> Tenant:
    """Ensure a tenant row exists for the current context."""

    tenant = session.get(Tenant, tenant_uuid)
    if tenant is None:
        slug = f"tenant-{str(tenant_uuid)[:8]}"
        tenant = Tenant(
            id=tenant_uuid,
            slug=slug,
            name=slug,
        )
        session.add(tenant)
        session.flush()
    return tenant
