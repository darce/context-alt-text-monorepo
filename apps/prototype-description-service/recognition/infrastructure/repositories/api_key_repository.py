"""Repository for tenant API-key records and lifecycle journal rows."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey

ClassifyResult = Literal["active", "expired", "revoked", "unknown"]
_UNSET = object()


def _as_utc(value: datetime) -> datetime:
    """Coerce a naive timestamp (SQLite returns these) to UTC for safe comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_uuid(value: uuid.UUID | str, *, field_name: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


def _portal_model(name: str) -> Any:
    """Load foundation portal models lazily so recognition auth remains boot-safe."""
    from db import models as model_module

    try:
        return getattr(model_module, name)
    except AttributeError as exc:
        raise RuntimeError("portal key foundation schema is unavailable") from exc


class SqlAlchemyApiKeyRepository:
    """API key persistence helpers.

    The caller owns the surrounding transaction. Every lifecycle operation
    flushes its writes so a request-scoped transaction can commit or roll back
    the complete mutation as one unit.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """Expose the request-scoped session to lifecycle services."""
        return self._session

    async def get_by_hash(self, api_key_hash: str) -> ApiKey | None:
        """Return active API key record matching the provided hash.

        Expired keys and revoked keys are filtered out so callers never mistake
        them for valid auth.
        """
        stmt = select(ApiKey).where(
            and_(
                ApiKey.api_key_hash == api_key_hash,
                ApiKey.revoked_at.is_(None),
            )
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        expires_at = getattr(record, "expires_at", None)
        if expires_at is not None and _as_utc(expires_at) <= datetime.now(tz=UTC):
            return None
        return record

    async def classify_by_hash(self, api_key_hash: str) -> ClassifyResult:
        """Classify a hash as active/expired/revoked/unknown without hiding it."""
        result = await self._session.execute(select(ApiKey).where(ApiKey.api_key_hash == api_key_hash))
        record = result.scalar_one_or_none()
        if record is None:
            return "unknown"
        if record.revoked_at is not None:
            return "revoked"
        if record.expires_at is not None and _as_utc(record.expires_at) <= datetime.now(tz=UTC):
            return "expired"
        return "active"

    async def create(
        self,
        *,
        tenant_id: uuid.UUID | str,
        hashed_key: str,
        rate_limit_tier: object | None = None,
        expires_at: datetime | None = None,
        lifetime_seconds: int | None | object = _UNSET,
    ) -> ApiKey:
        """Insert a new API key and return the persisted row."""
        tier_value: str | None
        if rate_limit_tier is None:
            tier_value = None
        elif hasattr(rate_limit_tier, "value"):
            tier_value = str(rate_limit_tier.value)
        else:
            tier_value = str(rate_limit_tier)

        if lifetime_seconds is _UNSET:
            lifetime_value: int | None = None
        elif lifetime_seconds is None:
            lifetime_value = None
        elif isinstance(lifetime_seconds, bool) or not isinstance(lifetime_seconds, int) or lifetime_seconds <= 0:
            raise ValueError("lifetime_seconds must be a positive integer or None")
        else:
            lifetime_value = lifetime_seconds

        tid = _as_uuid(tenant_id, field_name="tenant_id")
        record = ApiKey(
            tenant_id=tid,
            api_key_hash=hashed_key,
            rate_limit_tier=tier_value,
            expires_at=expires_at,
            lifetime_seconds=lifetime_value,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)

        # Older operator callers pass only an absolute expiry. Capture that
        # original policy after the server timestamp is materialized; portal
        # callers pass the immutable lifetime explicitly.
        if lifetime_seconds is _UNSET and expires_at is not None:
            created_at = _as_utc(record.created_at)
            expiry = _as_utc(expires_at)
            record.lifetime_seconds = max(1, int((expiry - created_at).total_seconds()))
            await self._session.flush()
            await self._session.refresh(record)
        return record

    async def get_by_id(
        self,
        api_key_id: uuid.UUID | str,
        *,
        tenant_id: uuid.UUID | str | None = None,
        for_update: bool = False,
    ) -> ApiKey | None:
        """Return one key, optionally scoped and locked to its tenant."""
        kid = _as_uuid(api_key_id, field_name="api_key_id")
        stmt = select(ApiKey).where(ApiKey.id == kid)
        if tenant_id is not None:
            stmt = stmt.where(ApiKey.tenant_id == _as_uuid(tenant_id, field_name="tenant_id"))
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt.limit(1))
        return result.scalar_one_or_none()

    async def lock_tenant(self, tenant_id: uuid.UUID | str) -> Any | None:
        """Lock the tenant serialization row used by portal key mutations."""
        tenant_model = _portal_model("Tenant")
        tid = _as_uuid(tenant_id, field_name="tenant_id")
        result = await self._session.execute(select(tenant_model).where(tenant_model.id == tid).with_for_update())
        return result.scalar_one_or_none()

    async def get_idempotency(
        self,
        tenant_id: uuid.UUID | str,
        *,
        operation: str,
        idempotency_key: str,
        for_update: bool = False,
    ) -> Any | None:
        """Find one durable lifecycle reservation."""
        model = _portal_model("TenantKeyIdempotency")
        stmt = select(model).where(
            model.tenant_id == _as_uuid(tenant_id, field_name="tenant_id"),
            model.operation == operation,
            model.idempotency_key == idempotency_key,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt.limit(1))
        return result.scalar_one_or_none()

    async def create_idempotency(
        self,
        tenant_id: uuid.UUID | str,
        *,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
        api_key_id: uuid.UUID | str,
        created_at: datetime,
    ) -> Any:
        """Persist the result pointer for one normalized lifecycle request."""
        model = _portal_model("TenantKeyIdempotency")
        record = model(
            tenant_id=_as_uuid(tenant_id, field_name="tenant_id"),
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            api_key_id=_as_uuid(api_key_id, field_name="api_key_id"),
            created_at=created_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_rotation_history(
        self,
        tenant_id: uuid.UUID | str,
        api_key_id: uuid.UUID | str,
        *,
        for_update: bool = False,
    ) -> Any | None:
        """Return the single observed rotation for an old key, if any."""
        model = _portal_model("ApiKeyRotationHistory")
        stmt = select(model).where(
            model.tenant_id == _as_uuid(tenant_id, field_name="tenant_id"),
            model.api_key_id == _as_uuid(api_key_id, field_name="api_key_id"),
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt.order_by(model.created_at).limit(1))
        return result.scalar_one_or_none()

    async def create_rotation_history(
        self,
        tenant_id: uuid.UUID | str,
        *,
        api_key_id: uuid.UUID | str,
        replaced_by_key_id: uuid.UUID | str,
        cutoff_at: datetime,
        reason: str,
        created_at: datetime,
    ) -> Any:
        """Write the audit row for a successful portal rotation."""
        model = _portal_model("ApiKeyRotationHistory")
        record = model(
            tenant_id=_as_uuid(tenant_id, field_name="tenant_id"),
            api_key_id=_as_uuid(api_key_id, field_name="api_key_id"),
            replaced_by_key_id=_as_uuid(replaced_by_key_id, field_name="replaced_by_key_id"),
            cutoff_at=cutoff_at,
            reason=reason,
            created_at=created_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def latest_replacement_for_tenant(self, tenant_id: uuid.UUID | str) -> uuid.UUID | None:
        """Return the newest durable primary replacement for a tenant."""
        model = _portal_model("ApiKeyRotationHistory")
        stmt = (
            select(model.replaced_by_key_id)
            .where(model.tenant_id == _as_uuid(tenant_id, field_name="tenant_id"))
            .order_by(model.created_at.desc(), model.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return _as_uuid(value, field_name="api_key_id") if value is not None else None

    async def usable_for_tenant(
        self,
        tenant_id: uuid.UUID | str,
        *,
        now: datetime,
        for_update: bool = False,
    ) -> list[ApiKey]:
        """Return currently usable keys in deterministic creation order."""
        tid = _as_uuid(tenant_id, field_name="tenant_id")
        stmt = (
            select(ApiKey)
            .where(
                ApiKey.tenant_id == tid,
                ApiKey.revoked_at.is_(None),
                or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
            )
            .order_by(ApiKey.created_at, ApiKey.id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_page(
        self,
        tenant_id: uuid.UUID | str,
        *,
        include_revoked: bool,
        limit: int,
        after_created_at: datetime | None = None,
        after_id: uuid.UUID | None = None,
    ) -> tuple[list[ApiKey], int]:
        """Return one bounded page and a database count for its envelope."""
        tid = _as_uuid(tenant_id, field_name="tenant_id")
        filters = [ApiKey.tenant_id == tid]
        if not include_revoked:
            filters.append(ApiKey.revoked_at.is_(None))

        count_result = await self._session.execute(select(func.count(ApiKey.id)).where(*filters))
        total = int(count_result.scalar_one() or 0)

        stmt = select(ApiKey).where(*filters).order_by(ApiKey.created_at, ApiKey.id)
        if after_created_at is not None and after_id is not None:
            stmt = stmt.where(
                or_(
                    ApiKey.created_at > after_created_at,
                    and_(ApiKey.created_at == after_created_at, ApiKey.id > after_id),
                )
            )
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_for_tenant(self, tenant_id: uuid.UUID | str, *, include_revoked: bool = False) -> list[ApiKey]:
        """Return API keys for a tenant, optionally including revoked rows."""
        tid = _as_uuid(tenant_id, field_name="tenant_id")
        stmt = select(ApiKey).where(ApiKey.tenant_id == tid).order_by(ApiKey.created_at)
        if not include_revoked:
            stmt = stmt.where(ApiKey.revoked_at.is_(None))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def revoke(self, api_key_id: uuid.UUID | str, *, now: datetime | None = None) -> ApiKey:
        """Soft-revoke a key by setting revoked_at. Raises LookupError if absent."""
        kid = _as_uuid(api_key_id, field_name="api_key_id")
        record = await self._session.get(ApiKey, kid)
        if record is None:
            raise LookupError(f"api key not found: {api_key_id}")
        record.revoked_at = now or datetime.now(tz=UTC)
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def touch(self, api_key: ApiKey) -> None:
        """Update last_used_at for bookkeeping."""
        api_key.last_used_at = datetime.now(tz=UTC)
        await self._session.flush()

    async def touch_by_id(self, api_key_id: str) -> None:
        """Update last_used_at for a record identified by id."""
        await self._session.execute(
            update(ApiKey).where(ApiKey.id == uuid.UUID(str(api_key_id))).values(last_used_at=datetime.now(tz=UTC))
        )


__all__ = ["SqlAlchemyApiKeyRepository"]
