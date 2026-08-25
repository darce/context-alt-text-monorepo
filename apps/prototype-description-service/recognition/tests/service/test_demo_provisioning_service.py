"""Unit tests for demo provisioning (DS-3 / launch-plan §5)."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, DemoInstance, Tenant
from recognition.application.services.demo_provisioning_service import (
    BASE58_ALPHABET,
    DEFAULT_RECOGNITION_QUOTA,
    DEFAULT_SLUG_LENGTH,
    DemoInstanceNotFoundError,
    DemoSessionExpiredError,
    DemoSessionInvalidError,
    DemoSessionRequiredError,
    PreScanState,
    PreScanStateError,
    UnknownSeedBundleError,
    assert_pre_scan_state,
    expire_demo,
    generate_slug,
    mint_demo_session,
    provision_demo,
    reset_demo_sessions_for_tests,
    resolve_demo_session,
    resolve_seed_bundle,
)
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository

_BASE58_RE = re.compile(f"^[{re.escape(BASE58_ALPHABET)}]{{{DEFAULT_SLUG_LENGTH}}}$")


def test_generate_slug_is_base58_and_random_length() -> None:
    slugs = {generate_slug() for _ in range(20)}
    assert all(_BASE58_RE.match(s) for s in slugs)
    # Unlikely all identical if truly random.
    assert len(slugs) > 1


def test_resolve_seed_bundle_known_and_unknown() -> None:
    assert resolve_seed_bundle("default") == "default"
    assert resolve_seed_bundle("acme") == "acme"
    with pytest.raises(UnknownSeedBundleError):
        resolve_seed_bundle("nope")
    with pytest.raises(UnknownSeedBundleError):
        resolve_seed_bundle("")


@pytest.mark.asyncio
async def test_provision_demo_inserts_registry_row_with_hash_ref(db_session: AsyncSession) -> None:
    before = datetime.now(tz=UTC)
    result = await provision_demo(db_session, label="Test Gallery", seed="default")
    await db_session.commit()

    instance = result.instance
    assert _BASE58_RE.match(instance.slug)
    assert result.demo_url == f"https://demo.altcontext.com/x/{instance.slug}"
    assert instance.label == "Test Gallery"
    assert instance.seed_bundle == "default"
    assert result.pre_scan.seeded_media_present is True
    assert result.pre_scan.scanned_faces == 0
    assert result.pre_scan.people_count == 0
    assert instance.recognition_quota == DEFAULT_RECOGNITION_QUOTA
    assert instance.recognition_used == 0
    assert instance.revoked is False

    expires = instance.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    assert before + timedelta(days=29) <= expires <= before + timedelta(days=31)

    # api_key_ref is the hash — never the raw key.
    raw = result.raw_api_key
    hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert instance.api_key_ref == hashed
    assert raw not in instance.api_key_ref
    assert instance.api_key_ref != raw

    # Tenant exists and key authorizes via hash lookup (require_auth path).
    tenant = await db_session.get(Tenant, instance.tenant_id)
    assert tenant is not None
    found = await SqlAlchemyApiKeyRepository(db_session).get_by_hash(hashed)
    assert found is not None
    assert str(found.tenant_id) == str(instance.tenant_id)

    # Row persisted and re-readable.
    loaded = await db_session.get(DemoInstance, instance.slug)
    assert loaded is not None
    assert loaded.api_key_ref == hashed
    assert raw not in (loaded.api_key_ref or "")


@pytest.mark.asyncio
async def test_provision_demo_rejects_unknown_seed(db_session: AsyncSession) -> None:
    with pytest.raises(UnknownSeedBundleError):
        await provision_demo(db_session, label="X", seed="missing-bundle")


@pytest.mark.asyncio
async def test_expire_demo_sets_revoked(db_session: AsyncSession) -> None:
    result = await provision_demo(db_session, label="Expire Me", seed="default")
    await db_session.commit()

    expired = await expire_demo(db_session, slug=result.instance.slug)
    await db_session.commit()

    assert expired.revoked is True
    reloaded = await db_session.get(DemoInstance, result.instance.slug)
    assert reloaded is not None
    assert reloaded.revoked is True

    # The underlying credential must actually be revoked — flipping the registry
    # flag alone is inert because auth gates on api_keys.revoked_at, not the demo
    # registry, so the public demo key would keep authenticating until its TTL.
    # Query the row directly: get_by_hash filters out revoked keys (auth lookup).
    key = (
        await db_session.execute(select(ApiKey).where(ApiKey.api_key_hash == result.instance.api_key_ref))
    ).scalar_one()
    assert key.revoked_at is not None
    # And the auth lookup now rejects it.
    assert await SqlAlchemyApiKeyRepository(db_session).get_by_hash(result.instance.api_key_ref) is None


@pytest.mark.asyncio
async def test_expire_demo_unknown_slug(db_session: AsyncSession) -> None:
    with pytest.raises(DemoInstanceNotFoundError):
        await expire_demo(db_session, slug="notreal")


@pytest.mark.asyncio
async def test_provision_never_persists_raw_key_in_registry(db_session: AsyncSession) -> None:
    result = await provision_demo(db_session, label="No Leak", seed="acme")
    await db_session.commit()

    rows = (await db_session.execute(select(DemoInstance))).scalars().all()
    assert len(rows) == 1
    blob = " ".join(
        [
            rows[0].slug,
            rows[0].api_key_ref,
            rows[0].label or "",
            rows[0].seed_bundle,
        ]
    )
    assert result.raw_api_key not in blob


def test_mint_demo_session_round_trip() -> None:
    reset_demo_sessions_for_tests()
    minted = mint_demo_session("slugABC")
    bound = resolve_demo_session(minted.token, slug="slugABC")
    assert bound.slug == "slugABC"
    assert bound.expires_at > datetime.now(tz=UTC)


def test_resolve_demo_session_requires_token() -> None:
    reset_demo_sessions_for_tests()
    with pytest.raises(DemoSessionRequiredError):
        resolve_demo_session(None, slug="slugABC")
    with pytest.raises(DemoSessionRequiredError):
        resolve_demo_session("", slug="slugABC")


def test_resolve_demo_session_rejects_invalid_and_mismatched() -> None:
    reset_demo_sessions_for_tests()
    minted = mint_demo_session("slugABC")
    with pytest.raises(DemoSessionInvalidError):
        resolve_demo_session("totally-bogus", slug="slugABC")
    with pytest.raises(DemoSessionInvalidError):
        resolve_demo_session(minted.token, slug="other99")


def test_resolve_demo_session_rejects_expired() -> None:
    reset_demo_sessions_for_tests()
    now = datetime.now(tz=UTC)
    minted = mint_demo_session("slugABC", ttl_seconds=60, now=now)
    with pytest.raises(DemoSessionExpiredError):
        resolve_demo_session(minted.token, slug="slugABC", now=now + timedelta(seconds=61))


def test_pre_scan_invariant_rejects_empty_media() -> None:
    with pytest.raises(PreScanStateError, match="seeded media"):
        assert_pre_scan_state(PreScanState(seeded_media_ids=(), scanned_faces=0, people_count=0))


def test_pre_scan_invariant_rejects_scanned_faces() -> None:
    with pytest.raises(PreScanStateError, match="scanned_faces"):
        assert_pre_scan_state(
            PreScanState(seeded_media_ids=("seed-library-1",), scanned_faces=2, people_count=0)
        )


def test_pre_scan_invariant_rejects_nonzero_people_count() -> None:
    with pytest.raises(PreScanStateError, match="people_count"):
        assert_pre_scan_state(
            PreScanState(seeded_media_ids=("seed-library-1",), scanned_faces=0, people_count=1)
        )


@pytest.mark.asyncio
async def test_provision_demo_fails_loudly_on_catalog_pre_scan_violation(
    db_session: AsyncSession, monkeypatch
) -> None:
    from recognition.application.services import demo_provisioning_service as svc

    monkeypatch.setitem(
        svc.SEED_BUNDLES,
        "default",
        svc.SeedBundleContract(
            name="default",
            pre_scan=PreScanState(seeded_media_ids=(), scanned_faces=0, people_count=0),
        ),
    )
    with pytest.raises(PreScanStateError, match="seeded media"):
        await provision_demo(db_session, label="Broken Catalog", seed="default")
