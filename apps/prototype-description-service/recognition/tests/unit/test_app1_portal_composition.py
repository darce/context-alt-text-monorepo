"""Portal composition wiring: the origin pin must reach the azp check."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from recognition.interface_adapters.http.deps.portal_composition import _portal_auth_settings

ISSUER = "https://clerk.example.test"
JWKS_URL = "https://clerk.example.test/.well-known/jwks.json"


@pytest.fixture(autouse=True)
def _clear_portal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ACX_CLERK_ISSUER", "ACX_CLERK_JWKS_URL", "ACX_CLERK_AUTHORIZED_PARTIES"):
        monkeypatch.delenv(name, raising=False)


def _settings(**portal: object) -> SimpleNamespace:
    return SimpleNamespace(portal={"issuer": ISSUER, "jwks_url": JWKS_URL, **portal})


def test_distinct_audience_enforces_the_configured_authorized_parties() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(
        _settings(audience="clerk-instance-aud", authorized_parties="https://app.altcontext.io"),
        missing,
    )

    assert missing == []
    assert resolved is not None
    assert resolved.audience == ("clerk-instance-aud",)
    assert resolved.authorized_parties == ("https://app.altcontext.io",)


def test_authorized_parties_from_the_environment_reach_the_azp_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACX_CLERK_AUTHORIZED_PARTIES", "https://app.altcontext.io, https://admin.altcontext.io")
    missing: list[str] = []
    resolved = _portal_auth_settings(_settings(audience="clerk-instance-aud"), missing)

    assert resolved is not None
    assert resolved.authorized_parties == ("https://app.altcontext.io", "https://admin.altcontext.io")


def test_authorized_parties_alone_serve_as_the_audience_without_pinning_azp() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(_settings(authorized_parties="https://app.altcontext.io"), missing)

    assert missing == []
    assert resolved is not None
    assert resolved.audience == ("https://app.altcontext.io",)
    # Pinning azp to the audience value would reject every legitimate Clerk token.
    assert resolved.authorized_parties is None


def test_audience_is_never_taken_from_the_authorized_parties_setting_name() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(
        _settings(portal_audience="clerk-instance-aud", authorized_parties="https://app.altcontext.io"),
        missing,
    )

    assert resolved is not None
    assert resolved.audience == ("clerk-instance-aud",)
    assert resolved.authorized_parties == ("https://app.altcontext.io",)


def test_missing_configuration_is_reported_rather_than_guessed() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(_settings(), missing)

    assert resolved is None
    assert "ACX_CLERK_AUTHORIZED_PARTIES" in missing
