"""Per-prospect demo provisioning (launch-plan §5 / DS-3).

Mints a tenant + API key via the shared ``mint_api_key`` minter (same path as
``/admin`` and ``manage_api_keys`` — no parallel key store), records a named
seed-bundle selection, and inserts a ``demo_instances`` slug row. The raw key
is returned to the caller once and is never written to the registry.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DemoInstance, IdentityCluster, MediaIdentity, Tenant
from recognition.application.services.api_key_admin_service import mint_api_key
from recognition.config.security import RateLimitTier
from recognition.infrastructure.repositories.api_key_repository import SqlAlchemyApiKeyRepository

# Bitcoin-style base58: no 0/O/I/l to avoid visual ambiguity.
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
DEFAULT_SLUG_LENGTH = 7
DEFAULT_TTL_DAYS = 30
DEFAULT_RECOGNITION_QUOTA = 200
DEMO_URL_TEMPLATE = "https://demo.altcontext.com/x/{slug}"
DEFAULT_SESSION_TTL_SECONDS = 15 * 60
DEMO_SESSION_COOKIE = "acx_demo_session"
DEMO_SESSION_HEADER = "X-Demo-Session"

@dataclass(frozen=True)
class PreScanState:
    """Pre-scan contract encoded in a seed bundle (AUTH-04).

    A provisioned tenant must start with seeded media present, zero scanned
    faces, and people_count == 0. The bundle is the source of truth — not an
    out-of-band reset script.
    """

    seeded_media_ids: tuple[str, ...]
    scanned_faces: int
    people_count: int

    @property
    def seeded_media_present(self) -> bool:
        return len(self.seeded_media_ids) > 0

    def as_public_dict(self) -> dict[str, bool | int]:
        return {
            "seeded_media_present": self.seeded_media_present,
            "scanned_faces": self.scanned_faces,
            "people_count": self.people_count,
        }


@dataclass(frozen=True)
class SeedBundleContract:
    """Named seed bundle plus the pre-scan state it is required to produce."""

    name: str
    pre_scan: PreScanState


SEED_BUNDLES: dict[str, SeedBundleContract] = {
    "default": SeedBundleContract(
        name="default",
        pre_scan=PreScanState(
            seeded_media_ids=("seed-library-1", "seed-library-2", "seed-library-3"),
            scanned_faces=0,
            people_count=0,
        ),
    ),
    "acme": SeedBundleContract(
        name="acme",
        pre_scan=PreScanState(
            seeded_media_ids=("acme-gallery-1", "acme-gallery-2"),
            scanned_faces=0,
            people_count=0,
        ),
    ),
}
# Named seed bundles only — real per-prospect image ingestion is out of scope.
KNOWN_SEED_BUNDLES: frozenset[str] = frozenset(SEED_BUNDLES)

_MAX_SLUG_ATTEMPTS = 8


class UnknownSeedBundleError(ValueError):
    """Raised when SEED does not match a known seed-bundle name."""


class DemoInstanceNotFoundError(LookupError):
    """Raised when expire targets an unknown slug."""


class PreScanStateViolation(RuntimeError):
    """Seed-bundle pre-scan contract violated; provision must not proceed."""


@dataclass(frozen=True)
class ProvisionResult:
    """Outcome of a successful provision; raw_key is one-time only."""

    instance: DemoInstance
    raw_api_key: str
    demo_url: str
    pre_scan: PreScanState


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
    if name not in SEED_BUNDLES:
        known = ", ".join(sorted(SEED_BUNDLES))
        raise UnknownSeedBundleError(f"unknown seed bundle {name!r}; known: {known}")
    return name


def load_seed_bundle(seed: str) -> SeedBundleContract:
    name = resolve_seed_bundle(seed)
    return SEED_BUNDLES[name]


def assert_pre_scan_state(state: PreScanState) -> PreScanState:
    """Fail loudly when a seed bundle or tenant is not in the pre-scan contract."""
    if not state.seeded_media_present:
        raise PreScanStateViolation("seeded media must be present in the seed bundle")
    if state.scanned_faces != 0:
        raise PreScanStateViolation(f"scanned_faces must be 0, got {state.scanned_faces}")
    if state.people_count != 0:
        raise PreScanStateViolation(f"people_count must be 0, got {state.people_count}")
    return state


async def observe_pre_scan_state(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    bundle: SeedBundleContract,
) -> PreScanState:
    """Read tenant face/people counts and pair them with the bundle's media list."""
    scanned_faces = int(
        await session.scalar(
            select(func.count()).select_from(MediaIdentity).where(MediaIdentity.tenant_id == tenant_id)
        )
        or 0
    )
    people_count = int(
        await session.scalar(
            select(func.count())
            .select_from(IdentityCluster)
            .where(
                IdentityCluster.tenant_id == tenant_id,
                IdentityCluster.label.is_not(None),
            )
        )
        or 0
    )
    return PreScanState(
        seeded_media_ids=bundle.pre_scan.seeded_media_ids,
        scanned_faces=scanned_faces,
        people_count=people_count,
    )


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
    bundle = load_seed_bundle(seed)
    assert_pre_scan_state(bundle.pre_scan)
    seed_bundle = bundle.name
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

        observed = await observe_pre_scan_state(session, tenant_id=tenant_id, bundle=bundle)
        assert_pre_scan_state(observed)
        return ProvisionResult(
            instance=instance,
            raw_api_key=raw,
            demo_url=demo_url_for(slug),
            pre_scan=observed,
        )

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
    pre_scan: PreScanState


class DemoEndedError(LookupError):
    """Slug exists but is expired or revoked (HTTP 410 demo_ended)."""


class DemoQuotaExceededError(RuntimeError):
    """Demo recognition quota exhausted (DS3-BR-02)."""

    def __init__(self, message: str = "demo_quota_exceeded", *, remaining: int = 0) -> None:
        super().__init__(message)
        self.remaining = remaining


class DemoSessionFailure(StrEnum):
    """Canonical demo-session failure codes (HTTP 401 detail)."""

    REQUIRED = "session_required"
    INVALID = "session_invalid"
    EXPIRED = "session_expired"


class DemoSessionError(Exception):
    """Base class for demo session failures. Always HTTP 401, never tenant data."""

    code: DemoSessionFailure

    def __init__(self, code: DemoSessionFailure) -> None:
        super().__init__(code.value)
        self.code = code


class DemoSessionRequiredError(DemoSessionError):
    def __init__(self) -> None:
        super().__init__(DemoSessionFailure.REQUIRED)


class DemoSessionInvalidError(DemoSessionError):
    def __init__(self) -> None:
        super().__init__(DemoSessionFailure.INVALID)


class DemoSessionExpiredError(DemoSessionError):
    def __init__(self) -> None:
        super().__init__(DemoSessionFailure.EXPIRED)


@dataclass(frozen=True)
class DemoSession:
    """Short-lived capability minted by exchanging a demo slug."""

    token: str
    slug: str
    expires_at: datetime


# token_hash -> (slug, expires_at). In-process; single-worker like the IP limiter.
_sessions: dict[str, tuple[str, datetime]] = {}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def reset_demo_sessions_for_tests() -> None:
    """Testing seam: drop in-memory demo sessions between tests."""
    _sessions.clear()


def mint_demo_session(
    slug: str,
    *,
    ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    now: datetime | None = None,
) -> DemoSession:
    """Mint a high-entropy session bound to ``slug``. Raw token returned once."""
    cleaned = (slug or "").strip()
    if not cleaned:
        raise ValueError("slug is required")
    if ttl_seconds < 1:
        raise ValueError("ttl_seconds must be >= 1")
    issued = _as_utc(now) if now is not None else datetime.now(tz=UTC)
    expires_at = issued + timedelta(seconds=ttl_seconds)
    token = secrets.token_urlsafe(32)
    _sessions[_token_hash(token)] = (cleaned, expires_at)
    return DemoSession(token=token, slug=cleaned, expires_at=expires_at)


def resolve_demo_session(
    token: str | None,
    *,
    slug: str,
    now: datetime | None = None,
) -> DemoSession:
    """Bind ``token`` to ``slug`` or raise a 401-class session error.

    Does not load tenant data — callers must still ``resolve_demo`` after this
    succeeds. Expired/invalid tokens never return a session record.
    """
    cleaned_token = (token or "").strip()
    if not cleaned_token:
        raise DemoSessionRequiredError()
    record = _sessions.get(_token_hash(cleaned_token))
    if record is None:
        raise DemoSessionInvalidError()
    bound_slug, expires_at = record
    cutoff = _as_utc(now) if now is not None else datetime.now(tz=UTC)
    if _as_utc(expires_at) < cutoff:
        _sessions.pop(_token_hash(cleaned_token), None)
        raise DemoSessionExpiredError()
    if bound_slug != (slug or "").strip():
        raise DemoSessionInvalidError()
    return DemoSession(token=cleaned_token, slug=bound_slug, expires_at=_as_utc(expires_at))


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
    bundle = load_seed_bundle(instance.seed_bundle)
    return DemoResolveContext(
        tenant_id=str(instance.tenant_id),
        seed_bundle=instance.seed_bundle,
        branding_json=instance.branding_json,
        expires_at=expires_at,
        quota_remaining=remaining,
        pre_scan=bundle.pre_scan,
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
            await expire_demo(session, slug=slug)
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
    "DEFAULT_SESSION_TTL_SECONDS",
    "DEFAULT_SLUG_LENGTH",
    "DEFAULT_SWEEP_STALL_LIMIT",
    "DEFAULT_TTL_DAYS",
    "DEMO_SESSION_COOKIE",
    "DEMO_SESSION_HEADER",
    "DEMO_URL_TEMPLATE",
    "KNOWN_SEED_BUNDLES",
    "SEED_BUNDLES",
    "DemoEndedError",
    "DemoInstanceNotFoundError",
    "DemoQuotaExceededError",
    "DemoSession",
    "DemoSessionError",
    "DemoSessionExpiredError",
    "DemoSessionFailure",
    "DemoSessionInvalidError",
    "DemoSessionRequiredError",
    "MAX_DEMO_QUOTA_UNITS",
    "DemoResolveContext",
    "PreScanState",
    "PreScanStateViolation",
    "ProvisionResult",
    "SeedBundleContract",
    "SweepResult",
    "UnknownSeedBundleError",
    "assert_pre_scan_state",
    "demo_url_for",
    "expire_demo",
    "generate_slug",
    "load_seed_bundle",
    "mint_demo_session",
    "observe_pre_scan_state",
    "provision_demo",
    "reset_demo_sessions_for_tests",
    "resolve_demo",
    "resolve_demo_session",
    "resolve_seed_bundle",
    "sweep_expired_demos",
    "try_consume_demo_quota",
]
