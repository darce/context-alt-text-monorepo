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

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DemoInstance, Tenant
from recognition.application.services.api_key_admin_service import mint_api_key
from recognition.config.security import RateLimitTier

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
    await session.flush()
    return instance


__all__ = [
    "BASE58_ALPHABET",
    "DEFAULT_RECOGNITION_QUOTA",
    "DEFAULT_SLUG_LENGTH",
    "DEFAULT_TTL_DAYS",
    "DEMO_URL_TEMPLATE",
    "KNOWN_SEED_BUNDLES",
    "DemoInstanceNotFoundError",
    "ProvisionResult",
    "UnknownSeedBundleError",
    "demo_url_for",
    "expire_demo",
    "generate_slug",
    "provision_demo",
    "resolve_seed_bundle",
]
