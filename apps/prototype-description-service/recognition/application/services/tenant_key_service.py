"""Tenant-scoped API-key issuance, rotation, revocation, and listing."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.config.security import get_security_settings
from recognition.infrastructure.repositories.api_key_repository import SqlAlchemyApiKeyRepository

_CREATE_OPERATION = "create"
_ROTATE_OPERATION = "rotate"
_ROTATION_GRACE = timedelta(days=7)
_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100


class TenantKeyError(RuntimeError):
    """Base class for tenant portal key lifecycle refusals."""


class InvalidKeyRequestError(ValueError):
    """The caller supplied an invalid lifecycle request."""


class IdempotencyKeyReuseError(TenantKeyError):
    """An idempotency key was reused with a different normalized request."""


class KeyNotFoundError(LookupError):
    """The tenant or key is not visible to this tenant-scoped operation."""


class KeyConflictError(TenantKeyError):
    """The requested lifecycle transition conflicts with current key state."""


class KeyAlreadyRevokedError(KeyConflictError):
    """A portal revoke was requested for a key already revoked."""


class KeyAlreadyRotatedError(KeyConflictError):
    """A key already has a committed replacement."""


class KeyLimitExceededError(KeyConflictError):
    """The beta tenant key cap would be exceeded."""


class KeyLifecycleCorruptionError(TenantKeyError):
    """A durable idempotency row points at missing key metadata."""


@dataclass(frozen=True, slots=True)
class KeyIssueResult:
    """Safe key metadata returned by create and rotate operations."""

    api_key_id: UUID
    tenant_id: UUID
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    rate_limit_tier: str | None
    lifetime_seconds: int | None
    raw_key: str | None
    replayed: bool

    @property
    def id(self) -> UUID:
        """Compatibility alias for callers that use the model's primary-key name."""
        return self.api_key_id

    @property
    def key_id(self) -> UUID:
        """Compatibility alias for HTTP/resource naming."""
        return self.api_key_id

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


@dataclass(frozen=True, slots=True)
class KeyPage:
    """Cursor page whose count and limit come from bounded database queries."""

    data: tuple[KeyIssueResult, ...]
    next_cursor: str | None
    limit: int
    total: int
    cursor: str | None = None

    @property
    def items(self) -> tuple[KeyIssueResult, ...]:
        return self.data

    @property
    def keys(self) -> tuple[KeyIssueResult, ...]:
        return self.data

    @property
    def rows(self) -> tuple[KeyIssueResult, ...]:
        return self.data

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _as_uuid(value: UUID | str, *, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidKeyRequestError(f"{field_name} must be a UUID") from exc


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidKeyRequestError(f"{field_name} must be a non-empty string")
    return value.strip()


def _normalize_tier(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = value.value if hasattr(value, "value") else value
    if not isinstance(normalized, str) or not normalized.strip():
        raise InvalidKeyRequestError("rate_limit_tier must be a non-empty string or None")
    return normalized.strip()


def _normalize_lifetime(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidKeyRequestError("lifetime_seconds must be a positive integer or None")
    return value


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _encode_cursor(row: Any) -> str:
    created_at = _as_utc(row.created_at)
    payload = {"created_at": created_at.isoformat(), "id": str(row.id)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    value = _text(cursor, field_name="cursor")
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode((value + padding).encode("ascii")))
        created_at = payload["created_at"]
        key_id = payload["id"]
        if not isinstance(created_at, str) or not isinstance(key_id, str):
            raise ValueError
        return _as_utc(datetime.fromisoformat(created_at)), UUID(key_id)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError, binascii.Error) as exc:
        raise InvalidKeyRequestError("cursor is invalid") from exc


def _clock_value(clock: Callable[[], datetime] | datetime) -> datetime:
    value = clock() if callable(clock) else clock
    if not isinstance(value, datetime):
        raise InvalidKeyRequestError("now must return a datetime")
    return _as_utc(value)


class TenantKeyService:
    """Implement the tenant API-key lifecycle over a request-scoped repository.

    The surrounding request owns transaction commit. Lifecycle mutations lock
    the tenant row before their second idempotency lookup, then flush every
    required write before returning.
    """

    def __init__(
        self,
        session_or_repository: AsyncSession | Any | None = None,
        *,
        session: AsyncSession | None = None,
        repository: Any | None = None,
        now: Callable[[], datetime] | datetime | None = None,
        clock: Callable[[], datetime] | datetime | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if session_or_repository is not None and (session is not None or repository is not None):
            raise ValueError("provide one session or repository")
        if session is not None and repository is not None:
            raise ValueError("provide a session or repository, not both")
        if now is not None and clock is not None:
            raise ValueError("provide now or clock, not both")
        selected = repository if repository is not None else session
        if selected is None:
            selected = session_or_repository
        if selected is None:
            raise ValueError("a database session or API-key repository is required")

        required = (
            "create",
            "get_by_id",
            "lock_tenant",
            "get_idempotency",
            "create_idempotency",
            "get_rotation_history",
            "create_rotation_history",
            "latest_replacement_for_tenant",
            "usable_for_tenant",
            "list_page",
        )
        self._repository: Any
        if all(callable(getattr(selected, name, None)) for name in required):
            self._repository = selected
        else:
            self._repository = SqlAlchemyApiKeyRepository(selected)
        self._clock = now if now is not None else clock if clock is not None else _utc_now
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def _now(self) -> datetime:
        return _clock_value(self._clock)

    async def _flush(self) -> None:
        session = getattr(self._repository, "session", None)
        if session is not None:
            await session.flush()

    async def _replay(
        self,
        tenant_id: UUID,
        *,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> KeyIssueResult | None:
        existing = await self._repository.get_idempotency(
            tenant_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            return None
        if existing.request_fingerprint != request_fingerprint:
            raise IdempotencyKeyReuseError("idempotency key was already used for a different request")
        result_id = _as_uuid(existing.api_key_id, field_name="api_key_id")
        record = await self._repository.get_by_id(result_id, tenant_id=tenant_id)
        if record is None:
            raise KeyLifecycleCorruptionError("idempotency result is unavailable")
        return self._result(record, raw_key=None, replayed=True)

    def _result(self, record: Any, *, raw_key: str | None, replayed: bool) -> KeyIssueResult:
        try:
            key_id = _as_uuid(record.id, field_name="api_key_id")
            tenant_id = _as_uuid(record.tenant_id, field_name="tenant_id")
            created_at = _as_utc(record.created_at)
        except (AttributeError, TypeError, ValueError) as exc:
            raise KeyLifecycleCorruptionError("persisted key metadata is invalid") from exc
        return KeyIssueResult(
            api_key_id=key_id,
            tenant_id=tenant_id,
            created_at=created_at,
            expires_at=_as_utc(record.expires_at) if record.expires_at is not None else None,
            revoked_at=_as_utc(record.revoked_at) if record.revoked_at is not None else None,
            rate_limit_tier=record.rate_limit_tier,
            lifetime_seconds=record.lifetime_seconds,
            raw_key=raw_key,
            replayed=replayed,
        )

    def _new_secret(self) -> tuple[str, str]:
        raw_key = self._token_factory()
        if not isinstance(raw_key, str) or not raw_key:
            raise RuntimeError("token factory returned an invalid key")
        try:
            digest = hashlib.new(get_security_settings().api_key_hash_algorithm)
        except ValueError as exc:
            raise RuntimeError("unsupported api key hash algorithm") from exc
        digest.update(raw_key.encode("utf-8"))
        return raw_key, digest.hexdigest()

    @staticmethod
    def _expiry(now: datetime, lifetime_seconds: int | None) -> datetime | None:
        if lifetime_seconds is None:
            return None
        try:
            return now + timedelta(seconds=lifetime_seconds)
        except OverflowError as exc:
            raise InvalidKeyRequestError("lifetime_seconds is too large") from exc

    async def create_key(
        self,
        tenant_id: UUID,
        *,
        idempotency_key: str,
        lifetime_seconds: int | None = None,
        rate_limit_tier: str | None = None,
    ) -> KeyIssueResult:
        """Create one primary key and return its raw secret exactly once."""
        tenant_uuid = _as_uuid(tenant_id, field_name="tenant_id")
        idem = _text(idempotency_key, field_name="idempotency_key")
        lifetime = _normalize_lifetime(lifetime_seconds)
        tier = _normalize_tier(rate_limit_tier)
        fingerprint = _fingerprint(
            {
                "operation": _CREATE_OPERATION,
                "lifetime_seconds": lifetime,
                "rate_limit_tier": tier,
            }
        )

        replay = await self._replay(
            tenant_uuid,
            operation=_CREATE_OPERATION,
            idempotency_key=idem,
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            return replay

        tenant = await self._repository.lock_tenant(tenant_uuid)
        if tenant is None:
            raise KeyNotFoundError("tenant not found")
        replay = await self._replay(
            tenant_uuid,
            operation=_CREATE_OPERATION,
            idempotency_key=idem,
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            return replay

        now = self._now()
        usable = await self._repository.usable_for_tenant(tenant_uuid, now=now, for_update=True)
        if usable:
            raise KeyLimitExceededError("tenant already has a usable API key")

        raw_key, hashed_key = self._new_secret()
        record = await self._repository.create(
            tenant_id=tenant_uuid,
            hashed_key=hashed_key,
            rate_limit_tier=tier,
            expires_at=self._expiry(now, lifetime),
            lifetime_seconds=lifetime,
        )
        await self._repository.create_idempotency(
            tenant_uuid,
            operation=_CREATE_OPERATION,
            idempotency_key=idem,
            request_fingerprint=fingerprint,
            api_key_id=record.id,
            created_at=now,
        )
        await self._flush()
        return self._result(record, raw_key=raw_key, replayed=False)

    async def rotate_key(
        self,
        tenant_id: UUID,
        api_key_id: UUID,
        *,
        idempotency_key: str,
        reason: str,
    ) -> KeyIssueResult:
        """Rotate one current key while retaining a bounded grace predecessor."""
        tenant_uuid = _as_uuid(tenant_id, field_name="tenant_id")
        key_uuid = _as_uuid(api_key_id, field_name="api_key_id")
        idem = _text(idempotency_key, field_name="idempotency_key")
        normalized_reason = _text(reason, field_name="reason")
        fingerprint = _fingerprint(
            {
                "operation": _ROTATE_OPERATION,
                "api_key_id": str(key_uuid),
                "reason": normalized_reason,
            }
        )

        replay = await self._replay(
            tenant_uuid,
            operation=_ROTATE_OPERATION,
            idempotency_key=idem,
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            return replay

        tenant = await self._repository.lock_tenant(tenant_uuid)
        if tenant is None:
            raise KeyNotFoundError("tenant not found")
        replay = await self._replay(
            tenant_uuid,
            operation=_ROTATE_OPERATION,
            idempotency_key=idem,
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            return replay

        old_key = await self._repository.get_by_id(key_uuid, tenant_id=tenant_uuid, for_update=True)
        if old_key is None:
            raise KeyNotFoundError("api key not found")
        if old_key.revoked_at is not None:
            raise KeyConflictError("api key is revoked")
        now = self._now()
        old_expiry = _as_utc(old_key.expires_at) if old_key.expires_at is not None else None
        if old_expiry is not None and old_expiry <= now:
            raise KeyConflictError("api key is expired")

        history = await self._repository.get_rotation_history(tenant_uuid, key_uuid, for_update=True)
        if history is not None:
            raise KeyAlreadyRotatedError("api key was already rotated")

        usable = await self._repository.usable_for_tenant(tenant_uuid, now=now, for_update=True)
        if not any(_as_uuid(candidate.id, field_name="api_key_id") == key_uuid for candidate in usable):
            raise KeyConflictError("api key is not usable")
        primary_id = await self._repository.latest_replacement_for_tenant(tenant_uuid)
        if primary_id is None and usable:
            primary_id = _as_uuid(usable[-1].id, field_name="api_key_id")
        if primary_id is not None and primary_id != key_uuid:
            raise KeyConflictError("only the current primary key can be rotated")

        for predecessor in usable:
            predecessor_id = _as_uuid(predecessor.id, field_name="api_key_id")
            if predecessor_id != key_uuid:
                predecessor.revoked_at = now

        cutoff = now + _ROTATION_GRACE if old_expiry is None else min(old_expiry, now + _ROTATION_GRACE)
        lifetime = _normalize_lifetime(getattr(old_key, "lifetime_seconds", None))
        replacement_expiry = self._expiry(now, lifetime)
        raw_key, hashed_key = self._new_secret()
        replacement = await self._repository.create(
            tenant_id=tenant_uuid,
            hashed_key=hashed_key,
            rate_limit_tier=old_key.rate_limit_tier,
            expires_at=replacement_expiry,
            lifetime_seconds=lifetime,
        )
        old_key.expires_at = cutoff
        await self._repository.create_rotation_history(
            tenant_uuid,
            api_key_id=key_uuid,
            replaced_by_key_id=replacement.id,
            cutoff_at=cutoff,
            reason=normalized_reason,
            created_at=now,
        )
        await self._repository.create_idempotency(
            tenant_uuid,
            operation=_ROTATE_OPERATION,
            idempotency_key=idem,
            request_fingerprint=fingerprint,
            api_key_id=replacement.id,
            created_at=now,
        )
        await self._flush()
        return self._result(replacement, raw_key=raw_key, replayed=False)

    async def revoke_key(
        self,
        tenant_id: UUID,
        api_key_id: UUID,
        *,
        reason: str,
    ) -> None:
        """Emergency-revoke a tenant key immediately."""
        tenant_uuid = _as_uuid(tenant_id, field_name="tenant_id")
        key_uuid = _as_uuid(api_key_id, field_name="api_key_id")
        _text(reason, field_name="reason")
        tenant = await self._repository.lock_tenant(tenant_uuid)
        if tenant is None:
            raise KeyNotFoundError("tenant not found")
        record = await self._repository.get_by_id(key_uuid, tenant_id=tenant_uuid, for_update=True)
        if record is None:
            raise KeyNotFoundError("api key not found")
        if record.revoked_at is not None:
            raise KeyAlreadyRevokedError("api key is already revoked")
        record.revoked_at = self._now()
        await self._flush()

    async def list_keys(
        self,
        tenant_id: UUID,
        *,
        cursor: str | None = None,
        limit: int = _DEFAULT_LIMIT,
        include_revoked: bool = True,
    ) -> KeyPage:
        """Return bounded tenant key metadata without hashes or raw secrets."""
        tenant_uuid = _as_uuid(tenant_id, field_name="tenant_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise InvalidKeyRequestError("limit must be a positive integer")
        effective_limit = min(limit, _MAX_LIMIT)
        after_created_at, after_id = _decode_cursor(cursor)
        rows, total = await self._repository.list_page(
            tenant_uuid,
            include_revoked=include_revoked,
            limit=effective_limit + 1,
            after_created_at=after_created_at,
            after_id=after_id,
        )
        has_more = len(rows) > effective_limit
        page_rows = rows[:effective_limit]
        next_cursor = _encode_cursor(page_rows[-1]) if has_more and page_rows else None
        return KeyPage(
            data=tuple(self._result(row, raw_key=None, replayed=False) for row in page_rows),
            next_cursor=next_cursor,
            limit=effective_limit,
            total=total,
            cursor=cursor,
        )


IdempotencyConflictError = IdempotencyKeyReuseError
TenantKeyIdempotencyConflictError = IdempotencyKeyReuseError
TenantKeyConflictError = KeyConflictError


__all__ = [
    "IdempotencyConflictError",
    "IdempotencyKeyReuseError",
    "InvalidKeyRequestError",
    "KeyAlreadyRevokedError",
    "KeyAlreadyRotatedError",
    "KeyConflictError",
    "KeyIssueResult",
    "KeyLifecycleCorruptionError",
    "KeyLimitExceededError",
    "KeyNotFoundError",
    "KeyPage",
    "TenantKeyConflictError",
    "TenantKeyError",
    "TenantKeyIdempotencyConflictError",
    "TenantKeyService",
]
