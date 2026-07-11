"""SECRETS-P3 Slice 2: fail-fast when OCI Vault is unreachable at boot (RES-13).

Failure-injection (TEST-09/TEST-10): mock the real oci transport/auth exception
shapes (mandate a) and prove create_app raises a typed VaultBootError before
any serve step — no env fallback under oci_vault.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from oci.exceptions import RequestException, ServiceError
from oci.secrets import SecretsClient

from shared.secrets import (
    REQUIRED_OCI_VAULT_SECRET_NAMES,
    OciVaultSecretProvider,
    VaultBootError,
    reset_secret_provider,
    set_secret_provider,
    validate_oci_vault_boot,
)

# Map keys are the LOGICAL env-var names consumers pass to get_secret(...) — the
# same keys the deployable RECOGNITION_VAULT_SECRET_MAP uses. The namespaced
# secret/<domain>/<name> is only the Vault-side path, not the map key.
_MAP = {
    "PGPASSWORD": "ocid1.vaultsecret.oc1..pg",
    "RECOGNITION_ADMIN_TOKEN": "ocid1.vaultsecret.oc1..admin",
}


@pytest.fixture(autouse=True)
def _restore_provider() -> Iterator[None]:
    reset_secret_provider()
    yield
    reset_secret_provider()


def _spec_client(**kwargs: Any) -> MagicMock:
    return create_autospec(SecretsClient, instance=True, **kwargs)


def _vault_provider(client: MagicMock) -> OciVaultSecretProvider:
    return OciVaultSecretProvider(
        _MAP,
        secrets_client=client,
        max_attempts=1,
        sleeper=lambda _: None,
    )


def _configure_oci_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_SECRET_BACKEND", "oci_vault")
    monkeypatch.setenv("RECOGNITION_VAULT_SECRET_MAP", json.dumps(_MAP))
    # Env values must not be used as a silent fallback when Vault fails (RES-13).
    monkeypatch.setenv("PGPASSWORD", "must-not-be-used-as-fallback")
    monkeypatch.setenv("RECOGNITION_ADMIN_TOKEN", "must-not-be-used-as-fallback-token-value")


def test_required_vault_secret_names_are_logical_consumer_names() -> None:
    # Boot-required names must be the LOGICAL env-var names consumers request
    # (what OciVaultSecretProvider.get_secret looks up in the map), NOT the
    # namespaced Vault paths — otherwise the map lookup misses and boot fails on
    # a correctly-configured prod map (SEC-RP-01).
    assert REQUIRED_OCI_VAULT_SECRET_NAMES == ("PGPASSWORD", "RECOGNITION_ADMIN_TOKEN")


def test_required_names_present_in_shipped_env_prod_example_map() -> None:
    # Cross-check the constant against the deployable contract: every
    # boot-required name must be a key of the shipped .env.prod.example
    # RECOGNITION_VAULT_SECRET_MAP, so a key-vocabulary drift fails here rather
    # than only in prod (SEC-RP-05).
    example = Path(__file__).resolve().parents[3] / ".env.prod.example"
    text = example.read_text(encoding="utf-8")
    match = re.search(r"^RECOGNITION_VAULT_SECRET_MAP=(\{.*\})\s*$", text, re.MULTILINE)
    assert match, "RECOGNITION_VAULT_SECRET_MAP not found in .env.prod.example"
    shipped_map = json.loads(match.group(1))
    missing = [n for n in REQUIRED_OCI_VAULT_SECRET_NAMES if n not in shipped_map]
    assert not missing, f"boot-required names missing from shipped vault map: {missing}"


def test_validate_oci_vault_boot_noop_for_env_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOGNITION_SECRET_BACKEND", raising=False)
    # Must not raise even with no Vault map / provider.
    validate_oci_vault_boot()


def test_boot_unreachable_vault_raises_typed_error_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Predicted message (TEST-06): Vault unreachable … refusing to serve."""
    _configure_oci_vault(monkeypatch)
    client = _spec_client()
    client.get_secret_bundle.side_effect = RequestException("connection reset")
    set_secret_provider(_vault_provider(client))

    with caplog.at_level(logging.ERROR), pytest.raises(
        VaultBootError,
        match=r"Vault unreachable.*PGPASSWORD.*refusing to serve",
    ):
        validate_oci_vault_boot()

    assert any("Vault unreachable" in rec.message for rec in caplog.records)


def test_boot_auth_failure_raises_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_oci_vault(monkeypatch)
    client = _spec_client()
    client.get_secret_bundle.side_effect = ServiceError(
        status=401,
        code="NotAuthenticated",
        headers={},
        message="nope",
    )
    set_secret_provider(_vault_provider(client))

    with pytest.raises(
        VaultBootError,
        match=r"auth/authorization error.*PGPASSWORD.*refusing to serve",
    ):
        validate_oci_vault_boot()


def test_boot_missing_required_secret_raises_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_oci_vault(monkeypatch)
    client = _spec_client()
    client.get_secret_bundle.side_effect = ServiceError(
        status=404,
        code="NotAuthorizedOrNotFound",
        headers={},
        message="Not found",
    )
    set_secret_provider(_vault_provider(client))

    with pytest.raises(
        VaultBootError,
        match=r"required secret 'PGPASSWORD' not found.*refusing to serve",
    ):
        validate_oci_vault_boot()


def test_boot_unmapped_required_secret_raises_without_client_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First required name missing from the OCID map → fail before any Vault call."""
    monkeypatch.setenv("RECOGNITION_SECRET_BACKEND", "oci_vault")
    # Map only admin-token; pg-password is required first and must fail closed.
    monkeypatch.setenv(
        "RECOGNITION_VAULT_SECRET_MAP",
        json.dumps({"RECOGNITION_ADMIN_TOKEN": "ocid1.vaultsecret.oc1..admin"}),
    )
    client = _spec_client()
    provider = OciVaultSecretProvider(
        {"RECOGNITION_ADMIN_TOKEN": "ocid1.vaultsecret.oc1..admin"},
        secrets_client=client,
        max_attempts=1,
        sleeper=lambda _: None,
    )
    set_secret_provider(provider)

    with pytest.raises(
        VaultBootError,
        match=r"required secret 'PGPASSWORD' not found.*refusing to serve",
    ):
        validate_oci_vault_boot()
    client.get_secret_bundle.assert_not_called()


def _import_create_app_under_env(monkeypatch: pytest.MonkeyPatch):
    """Import api.main.create_app only after env backend is active.

    ``api.main`` constructs ``app = create_app()`` at import time. Configuring
    oci_vault before that import would fail the module load itself and never
    reach the call-site assertion under test.
    """
    monkeypatch.delenv("RECOGNITION_SECRET_BACKEND", raising=False)
    monkeypatch.delenv("RECOGNITION_VAULT_SECRET_MAP", raising=False)
    reset_secret_provider()
    from api.main import create_app

    return create_app


def test_create_app_failfast_on_unreachable_vault_no_partial_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_app raises before returning an app that could serve (no partial serve)."""
    create_app = _import_create_app_under_env(monkeypatch)

    _configure_oci_vault(monkeypatch)
    client = _spec_client()
    client.get_secret_bundle.side_effect = RequestException("connection refused")
    set_secret_provider(_vault_provider(client))

    with pytest.raises(
        VaultBootError,
        match=r"Vault unreachable.*refusing to serve",
    ):
        create_app()

    # Env fallback must not have been used: vault was contacted (or attempted).
    assert client.get_secret_bundle.call_count >= 1


def test_create_app_failfast_on_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    create_app = _import_create_app_under_env(monkeypatch)

    _configure_oci_vault(monkeypatch)
    client = _spec_client()
    client.get_secret_bundle.side_effect = ServiceError(
        status=403,
        code="NotAuthorizedOrNotFound",
        headers={},
        message="forbidden",
    )
    set_secret_provider(_vault_provider(client))

    with pytest.raises(VaultBootError, match=r"auth/authorization error.*refusing to serve"):
        create_app()


def test_create_app_env_backend_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: default env backend still boots (no Vault path required)."""
    create_app = _import_create_app_under_env(monkeypatch)

    app = create_app()
    assert app is not None
    assert app.title == "Prototype Description Service"
