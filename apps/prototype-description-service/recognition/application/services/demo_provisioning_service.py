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
from typing import Protocol

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


@dataclass(frozen=True)
class WordPressSeedState:
    """Observable WordPress state after a seed bundle is prepared."""

    faces_count: int
    people_count: int


@dataclass(frozen=True)
class SeedBundleContract:
    """Named media bundle plus the state a viewer must receive."""

    name: str
    expected_state: WordPressSeedState


PRE_SCAN_STATE = WordPressSeedState(faces_count=0, people_count=0)
SEED_BUNDLES: dict[str, SeedBundleContract] = {
    name: SeedBundleContract(name=name, expected_state=PRE_SCAN_STATE) for name in ("default", "acme")
}
KNOWN_SEED_BUNDLES: frozenset[str] = frozenset(SEED_BUNDLES)

_MAX_SLUG_ATTEMPTS = 8


class UnknownSeedBundleError(ValueError):
    """Raised when SEED does not match a known seed-bundle name."""


class DemoInstanceNotFoundError(LookupError):
    """Raised when expire targets an unknown slug."""


class SeedBundleStateError(RuntimeError):
    """Raised when seeded media is not in the bundle's required pre-scan state."""


class WordPressDemoAccountGateway(Protocol):
    """WP-CLI boundary used while the demo database transaction is open."""

    async def provision_user(
        self, *, username: str, password: str, seed_bundle: str
    ) -> WordPressSeedState: ...

    async def disable_user(self, *, username: str) -> None: ...


@dataclass(frozen=True)
class ProvisionResult:
    """Outcome of a successful provision; both secrets are one-time only."""

    instance: DemoInstance
    raw_api_key: str
    demo_url: str
    wordpress_username: str
    wordpress_password: str


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


def wordpress_username_for(slug: str) -> str:
    """Derive the per-instance human identity from its validated base58 slug."""
    return f"demo-{slug}"


def assert_seed_bundle_state(*, seed_bundle: str, actual: WordPressSeedState) -> None:
    """Enforce the named bundle's pre-scan contract for provision and reset."""
    contract = SEED_BUNDLES[resolve_seed_bundle(seed_bundle)]
    if actual != contract.expected_state:
        expected = contract.expected_state
        raise SeedBundleStateError(
            f"seed bundle {seed_bundle!r} is not pre-scan: "
            f"faces_count={actual.faces_count}, people_count={actual.people_count}; "
            f"expected faces_count={expected.faces_count}, people_count={expected.people_count}"
        )


async def provision_demo(
    session: AsyncSession,
    *,
    label: str,
    seed: str = "default",
    recognition_quota: int = DEFAULT_RECOGNITION_QUOTA,
    ttl_days: int = DEFAULT_TTL_DAYS,
    branding: dict | None = None,
    wordpress: WordPressDemoAccountGateway | None = None,
) -> ProvisionResult:
    """Mint tenant+key+per-slug WP login under one open transaction.

    Does not print or log the raw key. Caller owns the transaction and must
    commit; this helper flushes inserts. When supplied, ``wordpress`` performs
    the external WP-CLI side effect while the database transaction remains
    open. A failed pre-scan assertion compensates by disabling the new login.
    Retries on the vanishingly rare slug primary-key collision.
    """
    seed_bundle = resolve_seed_bundle(seed)
    if recognition_quota < 1:
        raise ValueError("recognition_quota must be >= 1")
    if ttl_days < 1:
        raise ValueError("ttl_days must be >= 1")

    last_error: Exception | None = None
    for _ in range(_MAX_SLUG_ATTEMPTS):
        slug = generate_slug()
        wordpress_username = wordpress_username_for(slug)
        wordpress_password = generate_slug(length=24)
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

        if wordpress is not None:
            state = await wordpress.provision_user(
                username=wordpress_username,
                password=wordpress_password,
                seed_bundle=seed_bundle,
            )
            try:
                assert_seed_bundle_state(seed_bundle=seed_bundle, actual=state)
            except Exception:
                # Never leave a usable login behind when bundle verification
                # fails and the caller rolls back the database transaction.
                await wordpress.disable_user(username=wordpress_username)
                raise

        return ProvisionResult(
            instance=instance,
            raw_api_key=raw,
            demo_url=demo_url_for(slug),
            wordpress_username=wordpress_username,
            wordpress_password=wordpress_password,
        )

    raise RuntimeError(f"failed to allocate unique demo slug after {_MAX_SLUG_ATTEMPTS} attempts") from last_error


async def expire_demo(
    session: AsyncSession,
    *,
    slug: str,
    wordpress: WordPressDemoAccountGateway | None = None,
) -> DemoInstance:
    """Disable the WP login and revoke its registry/key unit. Caller commits."""
    cleaned = (slug or "").strip()
    if not cleaned:
        raise DemoInstanceNotFoundError("slug is required")
    instance = await session.get(DemoInstance, cleaned)
    if instance is None:
        raise DemoInstanceNotFoundError(f"demo instance not found: {cleaned}")
    # WordPress authenticates this principal independently of the service DB.
    # Disable first: if the later DB commit fails, expiry is conservative and
    # the human login cannot outlive the requested revoke.
    if wordpress is not None:
        await wordpress.disable_user(username=wordpress_username_for(instance.slug))
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

    def __init__(self, message: str = "demo_quota_exceeded", *, remaining: int = 0) -> None:
        super().__init__(message)
        self.remaining = remaining


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


# Hard ceiling for a single consume call (int4-safe; HTTP boundary also caps).
MAX_DEMO_QUOTA_UNITS = 500


async def try_consume_demo_quota(
    session: AsyncSession,
    *,
    api_key_hash: str,
    units: int = 1,
) -> bool:
    """Atomically consume ``units`` compute units for a demo key if applicable.

    Columns still named ``recognition_*`` meter all compute (pre-rename breadcrumb).
    Uses a single guarded UPDATE so concurrent requests cannot lose increments
    (no read-then-write race). All-or-nothing: either ``units`` fit and are
    consumed, or none are. Successful consumes derive remaining from RETURNING
    (``recognition_quota - recognition_used``) so the post-update state is atomic.

    Returns:
        False when ``api_key_hash`` is not a demo registry key (caller proceeds).
        True when ``units`` were consumed.

    Raises:
        ValueError: when ``units`` is outside ``1..MAX_DEMO_QUOTA_UNITS``.
        DemoQuotaExceededError: demo key cannot fit ``units`` (0 rows updated
            because over quota or revoked). Includes ``remaining`` budget on the
            exception (0 when the instance is revoked).
    """
    if units < 1 or units > MAX_DEMO_QUOTA_UNITS:
        raise ValueError(f"units must be in 1..{MAX_DEMO_QUOTA_UNITS}")

    cleaned = (api_key_hash or "").strip()
    if not cleaned:
        return False

    stmt = (
        update(DemoInstance)
        .where(
            DemoInstance.api_key_ref == cleaned,
            DemoInstance.revoked.is_(False),
            DemoInstance.recognition_used + units <= DemoInstance.recognition_quota,
        )
        .values(recognition_used=DemoInstance.recognition_used + units)
        .returning(
            DemoInstance.slug,
            DemoInstance.recognition_used,
            DemoInstance.recognition_quota,
        )
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is not None:
        # RETURNING yields (slug, used, quota) atomically with the consume;
        # remaining = quota - used is available without a second SELECT.
        await session.flush()
        return True

    # Fallback: classify miss (not-demo vs revoked vs over-quota).
    # Revoked instances are excluded from "active remaining" and report 0.
    existing = (
        await session.execute(select(DemoInstance).where(DemoInstance.api_key_ref == cleaned))
    ).scalar_one_or_none()
    if existing is None:
        return False
    if existing.revoked:
        raise DemoQuotaExceededError(remaining=0)
    remaining = max(0, int(existing.recognition_quota) - int(existing.recognition_used))
    raise DemoQuotaExceededError(remaining=remaining)


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
    wordpress: WordPressDemoAccountGateway | None = None,
) -> SweepResult:
    """Revoke demos past ``expires_at`` via ``expire_demo`` (row + api key).

    Commits per unit so each expiration is durably persisted the instant it
    succeeds and can never be lost by a later failure. On any per-unit error the
    session is rolled back — this both discards that unit's partial work and
    clears Postgres's aborted-transaction state (25P02) so the next unit still
    runs (rg-007 isolation: one unit's failure must not halt the others).
    Consecutive failures past ``stall_limit`` abort with ``stalled=True`` so the
    caller can exit non-zero. This helper owns its transactions.
    """
    if stall_limit < 1:
        raise ValueError("stall_limit must be >= 1")
    cutoff = _as_utc(now) if now is not None else datetime.now(tz=UTC)

    rows = (
        (
            await session.execute(
                select(DemoInstance.slug).where(
                    DemoInstance.revoked.is_(False),
                    DemoInstance.expires_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )

    expired_slugs: list[str] = []
    failed = 0
    consecutive_failures = 0
    stalled = False

    for slug in rows:
        try:
            if wordpress is None:
                await expire_demo(session, slug=slug)
            else:
                await expire_demo(session, slug=slug, wordpress=wordpress)
            await session.commit()
            expired_slugs.append(slug)
            consecutive_failures = 0
        except Exception:  # noqa: BLE001 — per-unit isolation (rg-007)
            await session.rollback()
            failed += 1
            consecutive_failures += 1
            if consecutive_failures >= stall_limit:
                stalled = True
                break

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
    "PRE_SCAN_STATE",
    "SEED_BUNDLES",
    "DemoEndedError",
    "DemoInstanceNotFoundError",
    "DemoQuotaExceededError",
    "MAX_DEMO_QUOTA_UNITS",
    "DemoResolveContext",
    "ProvisionResult",
    "SeedBundleContract",
    "SeedBundleStateError",
    "SweepResult",
    "UnknownSeedBundleError",
    "WordPressDemoAccountGateway",
    "WordPressSeedState",
    "assert_seed_bundle_state",
    "demo_url_for",
    "expire_demo",
    "generate_slug",
    "provision_demo",
    "resolve_demo",
    "resolve_seed_bundle",
    "sweep_expired_demos",
    "try_consume_demo_quota",
    "wordpress_username_for",
]
