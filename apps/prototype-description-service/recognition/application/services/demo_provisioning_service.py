"""Per-prospect demo provisioning (launch-plan §5 / DS-3).

Mints a tenant + API key via the shared ``mint_api_key`` minter (same path as
``/admin`` and ``manage_api_keys`` — no parallel key store), records a named
seed-bundle selection, and inserts a ``demo_instances`` slug row. The raw key
is returned to the caller once and is never written to the registry.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DemoInstance, Tenant
from recognition.application.services.api_key_admin_service import mint_api_key
from recognition.config.security import RateLimitTier
from recognition.infrastructure.repositories.api_key_repository import SqlAlchemyApiKeyRepository

# Bitcoin-style base58: no 0/O/I/l to avoid visual ambiguity.
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
DEFAULT_SLUG_LENGTH = 7
DEFAULT_TTL_DAYS = 30
DEFAULT_RECOGNITION_QUOTA = 200
DEMO_URL_TEMPLATE = "https://demo.altcontext.com/x/{slug}"

# Named seed bundles only — real per-prospect image ingestion is out of scope.
KNOWN_SEED_BUNDLES: frozenset[str] = frozenset({"default", "acme"})

_MAX_SLUG_ATTEMPTS = 8


class UnknownSeedBundleError(ValueError):
    """Raised when SEED does not match a known seed-bundle name."""


class DemoInstanceNotFoundError(LookupError):
    """Raised when expire targets an unknown slug."""


@dataclass(frozen=True)
class ProvisionResult:
    """Outcome of a successful provision; raw_key is one-time only."""

    instance: DemoInstance
    raw_api_key: str
    demo_url: str


def generate_slug(length: int = DEFAULT_SLUG_LENGTH) -> str:
    """Return a capability-free random base58 slug (not derived from tenant id)."""
    if length < 1:
        raise ValueError("slug length must be >= 1")
    return "".join(secrets.choice(BASE58_ALPHABET) for _ in range(length))


def demo_url_for(slug: str) -> str:
    return DEMO_URL_TEMPLATE.format(slug=slug)


def resolve_seed_bundle(seed: str) -> str:
    name = (seed or "").strip()
    if not name:
        raise UnknownSeedBundleError("seed bundle name is required")
    if name not in KNOWN_SEED_BUNDLES:
        known = ", ".join(sorted(KNOWN_SEED_BUNDLES))
        raise UnknownSeedBundleError(f"unknown seed bundle {name!r}; known: {known}")
    return name


async def provision_demo(
    session: AsyncSession,
    *,
    label: str,
    seed: str = "default",
    recognition_quota: int = DEFAULT_RECOGNITION_QUOTA,
    ttl_days: int = DEFAULT_TTL_DAYS,
    branding: dict | None = None,
) -> ProvisionResult:
    """Mint tenant+key, select seed bundle, insert demo_instances row.

    Does not print or log the raw key. Caller owns the transaction and must
    commit; this helper flushes inserts. Retries on the vanishingly rare slug
    primary-key collision.
    """
    seed_bundle = resolve_seed_bundle(seed)
    if recognition_quota < 1:
        raise ValueError("recognition_quota must be >= 1")
    if ttl_days < 1:
        raise ValueError("ttl_days must be >= 1")

    last_error: Exception | None = None
    for _ in range(_MAX_SLUG_ATTEMPTS):
        slug = generate_slug()
        tenant_id = uuid.uuid4()
        tenant = Tenant(id=tenant_id, site_url=demo_url_for(slug))
        session.add(tenant)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            last_error = exc
            continue

        record, raw = await mint_api_key(
            session,
            tenant_id=tenant_id,
            tier=RateLimitTier.STANDARD,
            expires_in_days=ttl_days,
        )

        now = datetime.now(tz=UTC)
        expires_at = now + timedelta(days=ttl_days)
        instance = DemoInstance(
            slug=slug,
            tenant_id=tenant_id,
            api_key_ref=record.api_key_hash,  # hash only — never the raw key
            label=(label or "").strip() or None,
            seed_bundle=seed_bundle,
            expires_at=expires_at,
            recognition_quota=recognition_quota,
            recognition_used=0,
            branding_json=branding,
            revoked=False,
        )
        session.add(instance)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            last_error = exc
            continue

        return ProvisionResult(instance=instance, raw_api_key=raw, demo_url=demo_url_for(slug))

    raise RuntimeError(f"failed to allocate unique demo slug after {_MAX_SLUG_ATTEMPTS} attempts") from last_error


async def expire_demo(session: AsyncSession, *, slug: str) -> DemoInstance:
    """Mark a demo instance revoked. Caller owns the commit."""
    cleaned = (slug or "").strip()
    if not cleaned:
        raise DemoInstanceNotFoundError("slug is required")
    instance = await session.get(DemoInstance, cleaned)
    if instance is None:
        raise DemoInstanceNotFoundError(f"demo instance not found: {cleaned}")
    instance.revoked = True
    # Revoke the underlying credential too. Flipping demo_instances.revoked alone
    # is inert: auth gates on api_keys.revoked_at, never the demo registry, so the
    # public demo key would keep authenticating until its natural TTL. Same session
    # transaction; caller owns the commit.
    key = await SqlAlchemyApiKeyRepository(session).get_by_hash(instance.api_key_ref)
    if key is not None and key.revoked_at is None:
        await SqlAlchemyApiKeyRepository(session).revoke(key.id)
    await session.flush()
    return instance


@dataclass(frozen=True)
class DemoResolveContext:
    """Public-safe demo context for GET /x/{slug}. No key material."""

    tenant_id: str
    seed_bundle: str
    branding_json: dict | None
    expires_at: datetime
    quota_remaining: int


class DemoEndedError(LookupError):
    """Slug exists but is expired or revoked (HTTP 410 demo_ended)."""


class DemoQuotaExceededError(RuntimeError):
    """Demo recognition quota exhausted (DS3-BR-02)."""


DEFAULT_SWEEP_STALL_LIMIT = 5


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def resolve_demo(session: AsyncSession, *, slug: str) -> DemoResolveContext:
    """Load public demo context for a slug.

    Raises:
        DemoInstanceNotFoundError: unknown slug (HTTP 404; no existence oracle).
        DemoEndedError: expired or revoked (HTTP 410 + demo_ended).
    """
    cleaned = (slug or "").strip()
    if not cleaned:
        raise DemoInstanceNotFoundError("not found")
    instance = await session.get(DemoInstance, cleaned)
    if instance is None:
        raise DemoInstanceNotFoundError("not found")

    now = datetime.now(tz=UTC)
    expires_at = _as_utc(instance.expires_at)
    if instance.revoked or expires_at < now:
        raise DemoEndedError("demo_ended")

    remaining = max(0, int(instance.recognition_quota) - int(instance.recognition_used))
    return DemoResolveContext(
        tenant_id=str(instance.tenant_id),
        seed_bundle=instance.seed_bundle,
        branding_json=instance.branding_json,
        expires_at=expires_at,
        quota_remaining=remaining,
    )


async def try_consume_demo_quota(session: AsyncSession, *, api_key_hash: str) -> bool:
    """Atomically consume one recognition unit for a demo key if applicable.

    Uses a single guarded UPDATE so concurrent requests cannot lose increments
    (no read-then-write race).

    Returns:
        False when ``api_key_hash`` is not a demo registry key (caller proceeds).
        True when a unit was consumed.

    Raises:
        DemoQuotaExceededError: demo key is at or over quota (0 rows updated
            because ``recognition_used >= recognition_quota``).
    """
    cleaned = (api_key_hash or "").strip()
    if not cleaned:
        return False

    stmt = (
        update(DemoInstance)
        .where(
            DemoInstance.api_key_ref == cleaned,
            DemoInstance.revoked.is_(False),
            DemoInstance.recognition_used < DemoInstance.recognition_quota,
        )
        .values(recognition_used=DemoInstance.recognition_used + 1)
        .returning(DemoInstance.slug, DemoInstance.recognition_used)
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is not None:
        await session.flush()
        return True

    existing = (
        await session.execute(select(DemoInstance).where(DemoInstance.api_key_ref == cleaned))
    ).scalar_one_or_none()
    if existing is None:
        return False
    raise DemoQuotaExceededError("demo_quota_exceeded")


@dataclass(frozen=True)
class SweepResult:
    """Outcome of one expiry sweep cycle."""

    expired: int
    failed: int
    slugs_expired: tuple[str, ...]
    stalled: bool = False


async def sweep_expired_demos(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    stall_limit: int = DEFAULT_SWEEP_STALL_LIMIT,
) -> SweepResult:
    """Revoke demos past ``expires_at`` via ``expire_demo`` (row + api key).

    Per-instance failures are isolated (rg-007): one failure does not halt the
    cycle. Consecutive failures past ``stall_limit`` abort with ``stalled=True``
    so the caller can exit non-zero.
    """
    if stall_limit < 1:
        raise ValueError("stall_limit must be >= 1")
    cutoff = _as_utc(now) if now is not None else datetime.now(tz=UTC)

    rows = (
        await session.execute(
            select(DemoInstance.slug).where(
                DemoInstance.revoked.is_(False),
                DemoInstance.expires_at < cutoff,
            )
        )
    ).scalars().all()

    expired_slugs: list[str] = []
    failed = 0
    consecutive_failures = 0
    stalled = False

    for slug in rows:
        try:
            await expire_demo(session, slug=slug)
            expired_slugs.append(slug)
            consecutive_failures = 0
        except Exception:  # noqa: BLE001 — per-unit isolation (rg-007)
            failed += 1
            consecutive_failures += 1
            if consecutive_failures >= stall_limit:
                stalled = True
                break

    await session.flush()
    return SweepResult(
        expired=len(expired_slugs),
        failed=failed,
        slugs_expired=tuple(expired_slugs),
        stalled=stalled,
    )


__all__ = [
    "BASE58_ALPHABET",
    "DEFAULT_RECOGNITION_QUOTA",
    "DEFAULT_SLUG_LENGTH",
    "DEFAULT_SWEEP_STALL_LIMIT",
    "DEFAULT_TTL_DAYS",
    "DEMO_URL_TEMPLATE",
    "KNOWN_SEED_BUNDLES",
    "DemoEndedError",
    "DemoInstanceNotFoundError",
    "DemoQuotaExceededError",
    "DemoResolveContext",
    "ProvisionResult",
    "SweepResult",
    "UnknownSeedBundleError",
    "demo_url_for",
    "expire_demo",
    "generate_slug",
    "provision_demo",
    "resolve_demo",
    "resolve_seed_bundle",
    "sweep_expired_demos",
    "try_consume_demo_quota",
]
