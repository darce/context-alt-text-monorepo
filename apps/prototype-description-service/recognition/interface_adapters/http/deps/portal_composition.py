"""Composition root for the gated portal and billing HTTP surfaces."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.checkout_service import CheckoutService
from recognition.application.services.usage_admission_service import UsageAdmissionService
from recognition.config.settings import RecognitionSettings
from recognition.infrastructure.billing.polar_provider import PolarBillingProvider
from recognition.infrastructure.repositories.billing_repository import BillingRepository
from recognition.infrastructure.repositories.checkout_attempt_repository import CheckoutAttemptRepository
from recognition.interface_adapters.http.deps.portal_auth import (
    PortalAuthSettings,
    build_portal_token_verifier,
)
from recognition.interface_adapters.http.deps.session import get_session
from recognition.interface_adapters.http.routers.billing_webhooks import get_billing_repository
from shared.secrets import get_secret_provider

_MISSING = object()
_POLAR_SANDBOX_BASE_URL = "https://sandbox-api.polar.sh"
_POLAR_LIVE_BASE_URL = "https://api.polar.sh"
_POLAR_SANDBOX_HOST = "sandbox-api.polar.sh"
_POLAR_LIVE_HOST = "api.polar.sh"
_ALLOWED_POLAR_ENVIRONMENTS = frozenset({"sandbox", "live"})
_DEFAULT_POLAR_BASE_URL = _POLAR_SANDBOX_BASE_URL
_DEFAULT_POLAR_TIMEOUT_SECONDS = 10.0
_DEFAULT_USAGE_ADMISSION_TIMEOUT_S = 5.0


@dataclass(frozen=True, slots=True)
class PortalCompositionConfig:
    """Validated settings needed to construct the portal and billing adapters."""

    portal_auth: PortalAuthSettings
    billing_webhook_secret: str = field(repr=False)
    billing_product_ids: Mapping[str, str]
    billing_access_token: str | None = field(default=None, repr=False)
    billing_base_url: str = _DEFAULT_POLAR_BASE_URL
    billing_timeout_seconds: float = _DEFAULT_POLAR_TIMEOUT_SECONDS
    billing_payments_enabled: bool = False
    billing_environment: str = "sandbox"
    billing_allowed_return_origins: tuple[str, ...] = ()
    billing_seller_account: str | None = None
    app_public_origin: str = ""
    app_allowed_origins: tuple[str, ...] = ()


class _OutboundHttpClient:
    """Adapt bounded httpx calls to the portal and Polar client protocols."""

    def __init__(self, *, default_timeout_seconds: float) -> None:
        self._default_timeout_seconds = default_timeout_seconds

    async def get(
        self,
        url: str,
        *,
        timeout: float | None = None,
        request_timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        resolved_timeout = self._resolve_timeout(timeout, request_timeout)
        async with httpx.AsyncClient(timeout=resolved_timeout) as client:
            return await client.get(url, headers=headers, timeout=resolved_timeout)

    async def post(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        headers: Mapping[str, str],
        request_timeout: float,
    ) -> httpx.Response:
        resolved_timeout = self._resolve_timeout(request_timeout, None)
        async with httpx.AsyncClient(timeout=resolved_timeout) as client:
            return await client.post(
                url,
                json=json,
                headers=headers,
                timeout=resolved_timeout,
            )

    def _resolve_timeout(self, timeout: float | None, request_timeout: float | None) -> float:
        resolved = timeout if timeout is not None else request_timeout
        if resolved is None:
            resolved = self._default_timeout_seconds
        if isinstance(resolved, bool) or not isinstance(resolved, (int, float)):
            raise ValueError("outbound request timeout must be a positive number")
        if resolved <= 0 or not math.isfinite(float(resolved)):
            raise ValueError("outbound request timeout must be a positive number")
        return float(resolved)


@dataclass(frozen=True, slots=True)
class BillingRepositoryFactory:
    """Construct a billing repository around the session for one request."""

    environment: str | None = None
    seller_account: str | None = None

    def __call__(self, session: AsyncSession) -> BillingRepository:
        return BillingRepository(
            session,
            environment=self.environment,
            seller_account=self.seller_account,
        )


@dataclass(frozen=True, slots=True)
class CheckoutServiceFactory:
    """Construct a checkout service around the session for one request."""

    provider: Any
    seller_account: str
    payments_enabled: bool = False
    provider_name: str = "polar"
    environment: str = "sandbox"

    def __call__(self, session: AsyncSession) -> CheckoutService:
        return CheckoutService(
            CheckoutAttemptRepository(session),
            self.provider,
            payments_enabled=self.payments_enabled,
            provider_name=self.provider_name,
            environment=self.environment,
            seller_account=self.seller_account,
        )


class UsageAdmissionServiceFactory:
    """Construct a usage admission service around the session for one request."""

    def __init__(self, *, timeout_s: float = _DEFAULT_USAGE_ADMISSION_TIMEOUT_S) -> None:
        self.timeout_s = _positive_float(
            timeout_s,
            setting_name="RECOGNITION_USAGE_ADMISSION_TIMEOUT_S",
            default=_DEFAULT_USAGE_ADMISSION_TIMEOUT_S,
        )

    def __call__(self, session: AsyncSession) -> UsageAdmissionService:
        return UsageAdmissionService(session, timeout_s=self.timeout_s)


def _setting_value(settings: RecognitionSettings, sections: Collection[str], names: Collection[str]) -> object:
    for name in names:
        value = getattr(settings, name, _MISSING)
        if value is not _MISSING:
            return value

    for section_name in sections:
        section = getattr(settings, section_name, _MISSING)
        if section is _MISSING or section is None:
            continue
        for name in names:
            if isinstance(section, Mapping):
                value = section.get(name, _MISSING)
            else:
                value = getattr(section, name, _MISSING)
            if value is not _MISSING:
                return value
    return None


def _environment_value(names: Collection[str]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value.strip()
    return None


def _secret_value(names: Collection[str]) -> str | None:
    provider = get_secret_provider()
    for name in names:
        value = provider.get_secret_optional(name)
        if value is not None:
            return value
    return None


def _text_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Collection) and not isinstance(value, (bytes, bytearray, Mapping)):
        return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return ()


def _required_text_setting(
    settings: RecognitionSettings,
    *,
    sections: Collection[str],
    setting_names: Collection[str],
    environment_names: Collection[str],
    missing: list[str],
) -> str:
    value = _setting_value(settings, sections, setting_names)
    if not isinstance(value, str) or not value.strip():
        value = _environment_value(environment_names)
    if not isinstance(value, str) or not value.strip():
        missing.append(next(iter(environment_names)))
        return ""
    return value.strip()


def _portal_auth_settings(
    settings: RecognitionSettings,
    missing: list[str],
) -> PortalAuthSettings | None:
    sections = ("portal", "portal_auth", "portal_authentication")
    issuer = _required_text_setting(
        settings,
        sections=sections,
        setting_names=("issuer", "portal_issuer"),
        environment_names=("ACX_CLERK_ISSUER",),
        missing=missing,
    )
    jwks_url = _required_text_setting(
        settings,
        sections=sections,
        setting_names=("jwks_url", "portal_jwks_url"),
        environment_names=("ACX_CLERK_JWKS_URL",),
        missing=missing,
    )
    audience_setting = _setting_value(settings, sections, ("audience", "portal_audience"))
    audience_values = _text_values(audience_setting) or _text_values(_environment_value(("ACX_CLERK_AUDIENCE",)))
    parties_setting = _setting_value(settings, sections, ("authorized_parties",))
    party_values = _text_values(parties_setting) or _text_values(_environment_value(("ACX_CLERK_AUTHORIZED_PARTIES",)))
    if not audience_values:
        missing.append("ACX_CLERK_AUDIENCE")
    if not party_values:
        missing.append("ACX_CLERK_AUTHORIZED_PARTIES")
    if not issuer or not jwks_url or not audience_values or not party_values:
        return None
    return PortalAuthSettings(
        issuer=issuer,
        jwks_url=jwks_url,
        audience=audience_values,
        authorized_parties=party_values,
    )


def _product_ids(
    settings: RecognitionSettings,
    missing: list[str],
    *,
    required: bool = True,
) -> Mapping[str, str]:
    sections = ("billing", "polar")
    configured = _setting_value(settings, sections, ("product_ids", "products", "plan_products"))
    if configured is None:
        configured = _environment_value(("POLAR_PRODUCT_IDS",))
    if configured is None:
        single_product = _environment_value(("POLAR_PRODUCT_ID",))
        if single_product:
            configured = {"starter": single_product}

    if isinstance(configured, Mapping):
        result = {
            str(plan).strip(): str(product).strip()
            for plan, product in configured.items()
            if isinstance(plan, str) and plan.strip() and isinstance(product, str) and product.strip()
        }
    elif isinstance(configured, str) and configured.strip():
        raw = configured.strip()
        if raw.startswith("{"):
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("POLAR_PRODUCT_IDS must be a plan-to-product mapping") from exc
            if not isinstance(decoded, Mapping):
                raise ValueError("POLAR_PRODUCT_IDS must be a plan-to-product mapping")
            result = {
                str(plan).strip(): str(product).strip()
                for plan, product in decoded.items()
                if isinstance(plan, str) and plan.strip() and isinstance(product, str) and product.strip()
            }
        else:
            result = {}
            for item in raw.split(","):
                plan, separator, product = item.partition("=")
                if not separator:
                    raise ValueError("POLAR_PRODUCT_IDS must use plan=product entries")
                if plan.strip() and product.strip():
                    result[plan.strip()] = product.strip()
    else:
        result = {}

    if not result and required:
        missing.append("POLAR_PRODUCT_IDS")
    return result


def _positive_float(value: object, *, setting_name: str, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{setting_name} must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{setting_name} must be a positive number")
    return parsed


def _boolean(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError("billing payments enabled must be boolean")


def _polar_environment(settings: RecognitionSettings) -> str:
    sections = ("billing", "polar")
    environment = _setting_value(settings, sections, ("environment", "polar_environment"))
    if not isinstance(environment, str) or not environment.strip():
        environment = _environment_value(("POLAR_ENVIRONMENT",)) or "sandbox"
    normalized = environment.strip().lower()
    if normalized not in _ALLOWED_POLAR_ENVIRONMENTS:
        raise ValueError("POLAR_ENVIRONMENT must be sandbox or live")
    return normalized


def _polar_host(base_url: str) -> str:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username is not None:
        raise ValueError("POLAR_BASE_URL must be an absolute HTTPS URL")
    return host


def _validated_polar_base_url(base_url: str, *, environment: str) -> str:
    host = _polar_host(base_url)
    if host == _POLAR_LIVE_HOST and environment != "live":
        raise ValueError(f"POLAR_BASE_URL host {_POLAR_LIVE_HOST} does not match environment {environment}")
    if host == _POLAR_SANDBOX_HOST and environment != "sandbox":
        raise ValueError(f"POLAR_BASE_URL host {_POLAR_SANDBOX_HOST} does not match environment {environment}")
    return base_url.rstrip("/")


def _polar_base_url(settings: RecognitionSettings, *, environment: str) -> str:
    sections = ("billing", "polar")
    base_url = _setting_value(settings, sections, ("base_url", "api_base_url", "polar_base_url"))
    if not isinstance(base_url, str) or not base_url.strip():
        base_url = _environment_value(("POLAR_BASE_URL", "POLAR_API_BASE_URL"))
    if not isinstance(base_url, str) or not base_url.strip():
        return _POLAR_SANDBOX_BASE_URL if environment == "sandbox" else _POLAR_LIVE_BASE_URL
    return _validated_polar_base_url(base_url.strip(), environment=environment)


def _absolute_origin(value: str, *, setting_name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{setting_name} must be an absolute HTTP(S) origin")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username is not None:
        raise ValueError(f"{setting_name} must be an absolute HTTP(S) origin")
    return f"{parsed.scheme}://{parsed.netloc}"


def _seller_account(
    settings: RecognitionSettings,
    missing: list[str],
    *,
    required: bool,
) -> str | None:
    sections = ("billing", "polar")
    value = _setting_value(
        settings,
        sections,
        ("seller_account", "organization_id", "polar_organization_id", "polar_seller_account"),
    )
    if not isinstance(value, str) or not value.strip():
        value = _environment_value(("POLAR_ORGANIZATION_ID", "POLAR_SELLER_ACCOUNT", "POLAR_ORGANIZATION"))
    if isinstance(value, str) and value.strip():
        return value.strip()
    if required:
        missing.append("POLAR_ORGANIZATION_ID")
    return None


def _app_public_origin(
    settings: RecognitionSettings,
    missing: list[str],
    *,
    required: bool,
) -> str:
    sections = ("portal", "app", "billing")
    value = _setting_value(settings, sections, ("public_origin", "app_public_origin"))
    if not isinstance(value, str) or not value.strip():
        value = _environment_value(("APP_PUBLIC_ORIGIN",))
    if isinstance(value, str) and value.strip():
        return _absolute_origin(value.strip(), setting_name="APP_PUBLIC_ORIGIN")
    if required:
        missing.append("APP_PUBLIC_ORIGIN")
    return ""


def _app_allowed_origins(settings: RecognitionSettings) -> tuple[str, ...]:
    sections = ("portal", "app")
    configured = _setting_value(settings, sections, ("allowed_origins", "app_allowed_origins"))
    if configured is None:
        configured = _environment_value(("APP_ALLOWED_ORIGINS",))
    return _text_values(configured)


def _composition_config(settings: RecognitionSettings) -> PortalCompositionConfig:
    missing: list[str] = []
    portal_auth = _portal_auth_settings(settings, missing)
    sections = ("billing", "polar")
    payments_enabled = _setting_value(settings, sections, ("payments_enabled", "polar_payments_enabled"))
    if payments_enabled is None:
        payments_enabled = _environment_value(("POLAR_PAYMENTS_ENABLED",))
    billing_payments_enabled = _boolean(payments_enabled, default=False)

    webhook_secret = _secret_value(("POLAR_WEBHOOK_SECRET", "POLAR_WEBHOOK_SIGNING_SECRET")) or ""
    product_ids = _product_ids(settings, missing, required=billing_payments_enabled)
    if billing_payments_enabled and not webhook_secret:
        missing.append("POLAR_WEBHOOK_SECRET")
    if missing:
        missing_names = ", ".join(dict.fromkeys(missing))
        raise ValueError(f"portal and billing composition requires: {missing_names}")
    if portal_auth is None:
        raise ValueError("portal and billing composition requires portal authentication settings")

    environment = _polar_environment(settings)
    base_url = _polar_base_url(settings, environment=environment)

    timeout_value = _setting_value(settings, sections, ("timeout_seconds", "request_timeout_seconds"))
    if timeout_value is None:
        timeout_value = _environment_value(("POLAR_REQUEST_TIMEOUT_SECONDS",))
    timeout_seconds = _positive_float(
        timeout_value,
        setting_name="POLAR_REQUEST_TIMEOUT_SECONDS",
        default=_DEFAULT_POLAR_TIMEOUT_SECONDS,
    )

    seller_account = _seller_account(settings, missing, required=billing_payments_enabled)
    app_public_origin = _app_public_origin(settings, missing, required=billing_payments_enabled)
    app_allowed_origins = _app_allowed_origins(settings)
    if missing:
        missing_names = ", ".join(dict.fromkeys(missing))
        raise ValueError(f"portal and billing composition requires: {missing_names}")

    origins = _setting_value(settings, sections, ("allowed_return_origins", "return_origins"))
    if origins is None:
        origins = _environment_value(("POLAR_ALLOWED_RETURN_ORIGINS",))
    allowed_return_origins = _text_values(origins)
    if app_public_origin and app_public_origin not in allowed_return_origins:
        allowed_return_origins = (*allowed_return_origins, app_public_origin)

    access_token = _secret_value(("POLAR_ACCESS_TOKEN", "POLAR_API_TOKEN"))
    return PortalCompositionConfig(
        portal_auth=portal_auth,
        billing_webhook_secret=webhook_secret,
        billing_product_ids=product_ids,
        billing_access_token=access_token,
        billing_base_url=base_url,
        billing_timeout_seconds=timeout_seconds,
        billing_payments_enabled=billing_payments_enabled,
        billing_environment=environment,
        billing_allowed_return_origins=allowed_return_origins,
        billing_seller_account=seller_account,
        app_public_origin=app_public_origin,
        app_allowed_origins=app_allowed_origins,
    )


async def _resolve_billing_repository(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BillingRepository:
    factory = getattr(request.app.state, "billing_repository", None)
    if not isinstance(factory, BillingRepositoryFactory):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing repository unavailable",
        )
    return factory(session)


def install_usage_admission_factory(app: FastAPI) -> None:
    """Install usage admission without portal Clerk/Polar configuration."""
    usage_timeout_value = _environment_value(("RECOGNITION_USAGE_ADMISSION_TIMEOUT_S",))
    usage_timeout_s = _positive_float(
        usage_timeout_value,
        setting_name="RECOGNITION_USAGE_ADMISSION_TIMEOUT_S",
        default=_DEFAULT_USAGE_ADMISSION_TIMEOUT_S,
    )
    app.state.usage_admission_service = UsageAdmissionServiceFactory(timeout_s=usage_timeout_s)


def install_portal_fallback(
    app: FastAPI,
    *,
    settings: RecognitionSettings,
    http_client: Any | None = None,
) -> None:
    """Install Clerk portal auth/keys/usage without Polar."""
    config = _composition_config(settings)
    outbound_client = http_client or _OutboundHttpClient(
        default_timeout_seconds=config.billing_timeout_seconds,
    )
    app.state.portal_token_verifier = build_portal_token_verifier(
        outbound_client,
        config.portal_auth,
    )
    app.state.portal_composition_config = config
    app.state.app_allowed_origins = config.app_allowed_origins
    app.state.billing_provider = None
    app.state.billing_repository = None
    app.state.checkout_service = None
    install_usage_admission_factory(app)


def _polar_configured(config: PortalCompositionConfig) -> bool:
    return bool(config.billing_webhook_secret and config.billing_product_ids)


def install_portal_composition(
    app: FastAPI,
    *,
    settings: RecognitionSettings,
    http_client: Any | None = None,
) -> None:
    """Construct and install all collaborators for the gated portal surface."""
    config = _composition_config(settings)
    outbound_client = http_client or _OutboundHttpClient(
        default_timeout_seconds=config.billing_timeout_seconds,
    )
    app.state.portal_token_verifier = build_portal_token_verifier(
        outbound_client,
        config.portal_auth,
    )
    app.state.portal_composition_config = config
    app.state.app_allowed_origins = config.app_allowed_origins
    if not _polar_configured(config):
        install_portal_fallback(app, settings=settings, http_client=outbound_client)
        return
    billing_provider = PolarBillingProvider(
        outbound_client,
        config.billing_webhook_secret,
        access_token=config.billing_access_token,
        product_ids=config.billing_product_ids,
        base_url=config.billing_base_url,
        timeout=config.billing_timeout_seconds,
        payments_enabled=config.billing_payments_enabled,
        environment=config.billing_environment,
        allowed_return_origins=config.billing_allowed_return_origins,
        seller_account=config.billing_seller_account,
    )
    app.state.billing_provider = billing_provider
    if config.billing_environment and config.billing_seller_account:
        app.state.billing_repository = BillingRepositoryFactory(
            environment=config.billing_environment,
            seller_account=config.billing_seller_account,
        )
    else:
        app.state.billing_repository = None
    if config.billing_seller_account:
        app.state.checkout_service = CheckoutServiceFactory(
            provider=billing_provider,
            seller_account=config.billing_seller_account,
            payments_enabled=config.billing_payments_enabled,
            provider_name="polar",
            environment=config.billing_environment,
        )
    else:
        app.state.checkout_service = None
    install_usage_admission_factory(app)
    app.dependency_overrides[get_billing_repository] = _resolve_billing_repository


__all__ = [
    "BillingRepositoryFactory",
    "CheckoutServiceFactory",
    "PortalCompositionConfig",
    "UsageAdmissionServiceFactory",
    "install_portal_composition",
    "install_portal_fallback",
    "install_usage_admission_factory",
]
