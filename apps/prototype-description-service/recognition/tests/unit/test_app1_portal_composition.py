"""Portal composition: distinct Clerk claims and Polar URL fail-closed."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from recognition.application.services.checkout_service import CheckoutService
from recognition.infrastructure.billing.polar_provider import PolarBillingProvider
from recognition.infrastructure.repositories.checkout_attempt_repository import CheckoutAttemptRepository
from recognition.interface_adapters.http.deps import portal_composition as composition
from recognition.interface_adapters.http.deps.portal_composition import (
    _portal_auth_settings,
)

ISSUER = "https://clerk.example.test"
JWKS_URL = "https://clerk.example.test/.well-known/jwks.json"
AUDIENCE = "clerk-instance-aud"
AUTHORIZED_ORIGIN = "https://app.altcontext.io"
SANDBOX_POLAR_URL = "https://sandbox-api.polar.sh"
LIVE_POLAR_URL = "https://api.polar.sh"


@pytest.fixture(autouse=True)
def _clear_portal_and_polar_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ACX_CLERK_ISSUER",
        "ACX_CLERK_JWKS_URL",
        "ACX_CLERK_AUDIENCE",
        "ACX_CLERK_AUTHORIZED_PARTIES",
        "POLAR_BASE_URL",
        "POLAR_API_BASE_URL",
        "POLAR_ENVIRONMENT",
        "POLAR_PAYMENTS_ENABLED",
        "POLAR_PRODUCT_IDS",
        "POLAR_PRODUCT_ID",
        "POLAR_ALLOWED_RETURN_ORIGINS",
        "POLAR_REQUEST_TIMEOUT_SECONDS",
        "POLAR_ORGANIZATION_ID",
        "POLAR_SELLER_ACCOUNT",
        "POLAR_ORGANIZATION",
        "APP_PUBLIC_ORIGIN",
        "APP_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)


def _settings(**portal: object) -> SimpleNamespace:
    return SimpleNamespace(portal={"issuer": ISSUER, "jwks_url": JWKS_URL, **portal})


def _stub_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_secret(names: object) -> str | None:
        known = {
            "POLAR_WEBHOOK_SECRET": "whsec_test",
            "POLAR_WEBHOOK_SIGNING_SECRET": "whsec_test",
        }
        for name in names:
            if name in known:
                return known[name]
        return None

    monkeypatch.setattr(composition, "_secret_value", fake_secret)


def _composition_settings(
    *,
    portal: dict[str, object] | None = None,
    billing: dict[str, object] | None = None,
    omit_portal: tuple[str, ...] = (),
    omit_billing: tuple[str, ...] = (),
) -> SimpleNamespace:
    portal_values: dict[str, object] = {
        "issuer": ISSUER,
        "jwks_url": JWKS_URL,
        "audience": AUDIENCE,
        "authorized_parties": AUTHORIZED_ORIGIN,
    }
    billing_values: dict[str, object] = {"product_ids": {"starter": "prod_test"}}
    if portal:
        portal_values.update(portal)
    if billing:
        billing_values.update(billing)
    for key in omit_portal:
        portal_values.pop(key, None)
    for key in omit_billing:
        billing_values.pop(key, None)
    return SimpleNamespace(portal=portal_values, billing=billing_values)


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


def test_authorized_parties_alone_do_not_become_the_jwt_audience() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(_settings(authorized_parties="https://app.altcontext.io"), missing)

    assert resolved is None
    assert "ACX_CLERK_AUDIENCE" in missing
    assert "ACX_CLERK_AUTHORIZED_PARTIES" not in missing


def test_audience_alone_does_not_become_authorized_parties() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(_settings(audience="clerk-instance-aud"), missing)

    assert resolved is None
    assert "ACX_CLERK_AUTHORIZED_PARTIES" in missing
    assert "ACX_CLERK_AUDIENCE" not in missing


def test_audience_is_never_taken_from_the_authorized_parties_setting_name() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(
        _settings(portal_audience="clerk-instance-aud", authorized_parties="https://app.altcontext.io"),
        missing,
    )

    assert resolved is not None
    assert resolved.audience == ("clerk-instance-aud",)
    assert resolved.authorized_parties == ("https://app.altcontext.io",)


def test_audience_from_environment_stays_distinct_from_authorized_parties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACX_CLERK_AUDIENCE", "clerk-instance-aud")
    monkeypatch.setenv("ACX_CLERK_AUTHORIZED_PARTIES", "https://app.altcontext.io")
    missing: list[str] = []
    resolved = _portal_auth_settings(_settings(), missing)

    assert missing == []
    assert resolved is not None
    assert resolved.audience == ("clerk-instance-aud",)
    assert resolved.authorized_parties == ("https://app.altcontext.io",)


def test_settings_audience_wins_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_CLERK_AUDIENCE", "from-env")
    monkeypatch.setenv("ACX_CLERK_AUTHORIZED_PARTIES", "https://env.example.test")
    missing: list[str] = []
    resolved = _portal_auth_settings(
        _settings(audience="from-settings", authorized_parties="https://settings.example.test"),
        missing,
    )

    assert resolved is not None
    assert resolved.audience == ("from-settings",)
    assert resolved.authorized_parties == ("https://settings.example.test",)


def test_missing_configuration_is_reported_rather_than_guessed() -> None:
    missing: list[str] = []
    resolved = _portal_auth_settings(_settings(), missing)

    assert resolved is None
    assert "ACX_CLERK_AUDIENCE" in missing
    assert "ACX_CLERK_AUTHORIZED_PARTIES" in missing


def test_install_portal_composition_installs_usage_admission_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    config = composition.PortalCompositionConfig(
        portal_auth=SimpleNamespace(),
        billing_webhook_secret="secret",
        billing_product_ids={"starter": "product"},
    )
    monkeypatch.setattr(composition, "_composition_config", lambda _settings: config)
    monkeypatch.setattr(composition, "build_portal_token_verifier", lambda *_args: object())
    monkeypatch.setattr(composition, "PolarBillingProvider", lambda *_args, **_kwargs: object())
    monkeypatch.setenv("RECOGNITION_USAGE_ADMISSION_TIMEOUT_S", "7.5")

    app = FastAPI()
    composition.install_portal_composition(app, settings=SimpleNamespace())

    assert isinstance(app.state.usage_admission_service, composition.UsageAdmissionServiceFactory)
    assert app.state.usage_admission_service.timeout_s == 7.5


def test_sandbox_defaults_to_sandbox_polar_url_with_payments_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_secrets(monkeypatch)
    config = composition._composition_config(_composition_settings())

    assert config.billing_environment == "sandbox"
    assert config.billing_base_url == SANDBOX_POLAR_URL
    assert config.billing_payments_enabled is False


def test_live_environment_defaults_to_live_polar_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)
    config = composition._composition_config(_composition_settings(billing={"environment": "live"}))

    assert config.billing_environment == "live"
    assert config.billing_base_url == LIVE_POLAR_URL
    assert config.billing_payments_enabled is False


def test_live_environment_from_env_defaults_to_live_polar_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)
    monkeypatch.setenv("POLAR_ENVIRONMENT", "live")
    config = composition._composition_config(_composition_settings())

    assert config.billing_environment == "live"
    assert config.billing_base_url == LIVE_POLAR_URL


def test_sandbox_rejects_live_polar_url_before_provider_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_secrets(monkeypatch)
    constructed: list[object] = []

    def _forbidden(*_args: object, **_kwargs: object) -> object:
        constructed.append(_kwargs)
        raise AssertionError("PolarBillingProvider must not be constructed")

    monkeypatch.setattr(composition, "PolarBillingProvider", _forbidden)
    monkeypatch.setattr(composition, "build_portal_token_verifier", lambda *_args, **_kwargs: object())

    with pytest.raises(ValueError, match="does not match environment sandbox"):
        composition.install_portal_composition(
            FastAPI(),
            settings=_composition_settings(billing={"base_url": LIVE_POLAR_URL}),
        )

    assert constructed == []


def test_live_rejects_sandbox_polar_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)

    with pytest.raises(ValueError, match="does not match environment live"):
        composition._composition_config(
            _composition_settings(billing={"environment": "live", "base_url": SANDBOX_POLAR_URL}),
        )


def test_unknown_polar_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)

    with pytest.raises(ValueError, match="POLAR_ENVIRONMENT"):
        composition._composition_config(_composition_settings(billing={"environment": "staging"}))


def test_insecure_and_malformed_polar_urls_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)

    with pytest.raises(ValueError, match="HTTPS"):
        composition._composition_config(
            _composition_settings(billing={"base_url": "http://sandbox-api.polar.sh"}),
        )
    with pytest.raises(ValueError, match="HTTPS"):
        composition._composition_config(_composition_settings(billing={"base_url": "not-a-url"}))
    with pytest.raises(ValueError, match="HTTPS"):
        composition._composition_config(_composition_settings(billing={"base_url": "https://"}))


def test_explicit_https_fake_polar_url_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)
    config = composition._composition_config(
        _composition_settings(billing={"base_url": "https://polar.test.example"}),
    )

    assert config.billing_environment == "sandbox"
    assert config.billing_base_url == "https://polar.test.example"


def test_settings_polar_values_win_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)
    monkeypatch.setenv("POLAR_ENVIRONMENT", "live")
    monkeypatch.setenv("POLAR_BASE_URL", LIVE_POLAR_URL)
    config = composition._composition_config(
        _composition_settings(billing={"environment": "sandbox", "base_url": "https://polar.settings.example"}),
    )

    assert config.billing_environment == "sandbox"
    assert config.billing_base_url == "https://polar.settings.example"


class _StubOutboundClient:
    async def get(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("composition tests must not call Polar")

    async def post(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("composition tests must not call Polar")


def test_missing_billing_product_ids_does_not_block_portal_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_secrets(monkeypatch)
    app = FastAPI()
    composition.install_portal_composition(
        app,
        settings=_composition_settings(omit_billing=("product_ids",)),
        http_client=_StubOutboundClient(),
    )

    assert getattr(app.state, "billing_provider", None) is None
    assert app.state.portal_token_verifier is not None


def test_payments_disabled_installs_without_seller_or_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)
    config = composition._composition_config(_composition_settings())
    app = FastAPI()
    composition.install_portal_composition(app, settings=_composition_settings(), http_client=_StubOutboundClient())

    assert config.billing_payments_enabled is False
    assert config.billing_seller_account is None
    assert config.billing_access_token is None
    assert isinstance(app.state.billing_provider, PolarBillingProvider)
    assert app.state.billing_provider._seller_account is None
    assert getattr(app.state, "checkout_service", None) is None
    assert getattr(app.state, "billing_repository", None) is None
    assert (
        app.state.portal_composition_config is config
        or app.state.portal_composition_config.billing_seller_account is None
    )


def test_payments_enabled_requires_configured_seller_account(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)
    with pytest.raises(ValueError, match="POLAR_ORGANIZATION_ID"):
        composition._composition_config(_composition_settings(billing={"payments_enabled": True}))


def test_seller_account_is_threaded_identically_to_provider_and_checkout_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_secrets(monkeypatch)
    captured: list[dict[str, object]] = []
    real_provider = composition.PolarBillingProvider

    def _capture(*args: object, **kwargs: object) -> PolarBillingProvider:
        captured.append(dict(kwargs))
        return real_provider(*args, **kwargs)

    monkeypatch.setattr(composition, "PolarBillingProvider", _capture)
    settings = _composition_settings(
        billing={
            "payments_enabled": True,
            "seller_account": "org-from-settings",
            "allowed_return_origins": AUTHORIZED_ORIGIN,
        },
        portal={"authorized_parties": AUTHORIZED_ORIGIN},
    )
    monkeypatch.setenv("APP_PUBLIC_ORIGIN", AUTHORIZED_ORIGIN)
    monkeypatch.setenv("APP_ALLOWED_ORIGINS", AUTHORIZED_ORIGIN)
    app = FastAPI()
    composition.install_portal_composition(app, settings=settings, http_client=_StubOutboundClient())

    factory = app.state.checkout_service
    provider = app.state.billing_provider
    session = object()
    service = factory(session)
    assert captured[0]["seller_account"] == "org-from-settings"
    assert provider._seller_account == "org-from-settings"
    assert factory.seller_account == "org-from-settings"
    assert isinstance(factory, composition.CheckoutServiceFactory)
    assert isinstance(service, CheckoutService)
    assert isinstance(service._repository, CheckoutAttemptRepository)
    assert service._repository.session is session
    assert service._seller_account == "org-from-settings"
    assert service._provider is provider
    assert app.state.portal_composition_config.billing_seller_account == "org-from-settings"
    assert app.state.portal_composition_config.app_public_origin == AUTHORIZED_ORIGIN
    assert AUTHORIZED_ORIGIN in app.state.app_allowed_origins


def test_seller_account_from_env_is_used_and_never_defaulted(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)
    monkeypatch.setenv("POLAR_ORGANIZATION_ID", "org-from-env")
    monkeypatch.setenv("POLAR_PAYMENTS_ENABLED", "true")
    monkeypatch.setenv("APP_PUBLIC_ORIGIN", AUTHORIZED_ORIGIN)
    monkeypatch.setenv("APP_ALLOWED_ORIGINS", AUTHORIZED_ORIGIN)
    config = composition._composition_config(
        _composition_settings(billing={"allowed_return_origins": AUTHORIZED_ORIGIN})
    )

    assert config.billing_seller_account == "org-from-env"
    assert config.billing_payments_enabled is True
    assert "org_sandbox" not in {config.billing_seller_account}
    assert config.app_public_origin == AUTHORIZED_ORIGIN


def test_payments_enabled_does_not_invent_an_organization_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)
    monkeypatch.setenv("APP_PUBLIC_ORIGIN", AUTHORIZED_ORIGIN)
    with pytest.raises(ValueError, match="POLAR_ORGANIZATION_ID"):
        composition.install_portal_composition(
            FastAPI(),
            settings=_composition_settings(billing={"payments_enabled": True}),
            http_client=_StubOutboundClient(),
        )


def test_portal_fallback_installs_without_polar_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_secrets(_names: object) -> str | None:
        return None

    monkeypatch.setattr(composition, "_secret_value", no_secrets)
    app = FastAPI()
    composition.install_portal_composition(
        app,
        settings=_composition_settings(omit_billing=("product_ids",)),
        http_client=_StubOutboundClient(),
    )
    assert app.state.portal_token_verifier is not None
    assert getattr(app.state, "billing_provider", None) is None
    assert getattr(app.state, "checkout_service", None) is None
    factory = getattr(app.state, "billing_repository", None)
    if factory is not None:
        repo = factory(object())
        assert getattr(repo, "_environment", None) in {None, "sandbox"}
        assert getattr(repo, "_seller_account", None) is None


def test_billing_repository_factory_binds_configured_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_secrets(monkeypatch)
    settings = _composition_settings(
        billing={
            "payments_enabled": True,
            "seller_account": "org-from-settings",
            "allowed_return_origins": AUTHORIZED_ORIGIN,
        },
        portal={"authorized_parties": AUTHORIZED_ORIGIN},
    )
    monkeypatch.setenv("APP_PUBLIC_ORIGIN", AUTHORIZED_ORIGIN)
    app = FastAPI()
    composition.install_portal_composition(app, settings=settings, http_client=_StubOutboundClient())
    factory = app.state.billing_repository
    session = object()
    repo = factory(session)
    assert factory.environment == "sandbox"
    assert factory.seller_account == "org-from-settings"
    assert repo._environment == "sandbox"
    assert repo._seller_account == "org-from-settings"
    assert repo.session is session
