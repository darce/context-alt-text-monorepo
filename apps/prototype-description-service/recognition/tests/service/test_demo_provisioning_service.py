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
    SeedBundleStateError,
    UnknownSeedBundleError,
    WordPressSeedState,
    expire_demo,
    generate_slug,
    provision_demo,
    resolve_seed_bundle,
)
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository

_BASE58_RE = re.compile(f"^[{re.escape(BASE58_ALPHABET)}]{{{DEFAULT_SLUG_LENGTH}}}$")


class RecordingWordPressGateway:
    def __init__(self, *, state: WordPressSeedState | None = None) -> None:
        self.state = state or WordPressSeedState(faces_count=0, people_count=0)
        self.provisioned: list[tuple[str, str, str]] = []
        self.disabled: list[str] = []

    async def provision_user(self, *, username: str, password: str, seed_bundle: str) -> WordPressSeedState:
        self.provisioned.append((username, password, seed_bundle))
        return self.state

    async def disable_user(self, *, username: str) -> None:
        self.disabled.append(username)


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
async def test_provisioned_wordpress_user_is_distinct_per_slug(db_session: AsyncSession) -> None:
    wordpress = RecordingWordPressGateway()

    first = await provision_demo(db_session, label="First", seed="default", wordpress=wordpress)
    second = await provision_demo(db_session, label="Second", seed="default", wordpress=wordpress)

    assert first.wordpress_username == f"demo-{first.instance.slug}"
    assert second.wordpress_username == f"demo-{second.instance.slug}"
    assert first.wordpress_username != second.wordpress_username
    assert first.wordpress_password != second.wordpress_password
    assert [call[0] for call in wordpress.provisioned] == [
        first.wordpress_username,
        second.wordpress_username,
    ]


@pytest.mark.asyncio
async def test_provision_demo_fails_if_seed_bundle_is_not_pre_scan(db_session: AsyncSession) -> None:
    wordpress = RecordingWordPressGateway(state=WordPressSeedState(faces_count=3, people_count=1))

    with pytest.raises(SeedBundleStateError, match="faces_count=3.*people_count=1"):
        await provision_demo(db_session, label="Stale", seed="default", wordpress=wordpress)

    assert len(wordpress.provisioned) == 1
    assert wordpress.disabled == [wordpress.provisioned[0][0]]


@pytest.mark.asyncio
async def test_provision_demo_rejects_unknown_seed(db_session: AsyncSession) -> None:
    with pytest.raises(UnknownSeedBundleError):
        await provision_demo(db_session, label="X", seed="missing-bundle")


@pytest.mark.asyncio
async def test_expire_demo_sets_revoked(db_session: AsyncSession) -> None:
    wordpress = RecordingWordPressGateway()
    result = await provision_demo(db_session, label="Expire Me", seed="default", wordpress=wordpress)
    await db_session.commit()

    expired = await expire_demo(db_session, slug=result.instance.slug, wordpress=wordpress)
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
    assert wordpress.disabled == [result.wordpress_username]


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
