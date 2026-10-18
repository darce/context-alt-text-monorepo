"""Backend selection for RECOGNITION_SECRET_BACKEND (SECRETS-P3 Slice 1).

rg-008: unknown backend raises at load; default/unset → EnvSecretProvider;
oci_vault → OciVaultSecretProvider.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from shared.secrets import (
    EnvSecretProvider,
    OciVaultSecretProvider,
    build_secret_provider,
    get_secret_provider,
    reset_secret_provider,
    resolve_secret_backend,
)


@pytest.fixture(autouse=True)
def _restore_provider() -> Iterator[None]:
    reset_secret_provider()
    yield
    reset_secret_provider()


def test_resolve_secret_backend_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOGNITION_SECRET_BACKEND", raising=False)
    assert resolve_secret_backend() == "env"


def test_resolve_secret_backend_empty_string_is_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_SECRET_BACKEND", "  ")
    assert resolve_secret_backend() == "env"


def test_resolve_secret_backend_oci_vault_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_SECRET_BACKEND", "OCI_VAULT")
    assert resolve_secret_backend() == "oci_vault"


def test_resolve_secret_backend_unknown_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_SECRET_BACKEND", "doppler")
    with pytest.raises(ValueError, match=r"Unknown RECOGNITION_SECRET_BACKEND='doppler'"):
        resolve_secret_backend()


def test_build_secret_provider_default_is_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOGNITION_SECRET_BACKEND", raising=False)
    provider = build_secret_provider()
    assert isinstance(provider, EnvSecretProvider)


def test_build_secret_provider_oci_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_SECRET_BACKEND", "oci_vault")
    monkeypatch.setenv(
        "RECOGNITION_VAULT_SECRET_MAP",
        json.dumps({"secret/recognition/admin-token": "ocid1.vaultsecret.oc1..example"}),
    )
    provider = build_secret_provider()
    assert isinstance(provider, OciVaultSecretProvider)


def test_build_secret_provider_oci_vault_missing_map_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOGNITION_SECRET_BACKEND", "oci_vault")
    monkeypatch.delenv("RECOGNITION_VAULT_SECRET_MAP", raising=False)
    with pytest.raises(ValueError, match="RECOGNITION_VAULT_SECRET_MAP is required"):
        build_secret_provider()


def test_get_secret_provider_selects_oci_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_SECRET_BACKEND", "oci_vault")
    monkeypatch.setenv(
        "RECOGNITION_VAULT_SECRET_MAP",
        json.dumps({"secret/recognition/pg-password": "ocid1.vaultsecret.oc1..pg"}),
    )
    provider = get_secret_provider()
    assert isinstance(provider, OciVaultSecretProvider)


def test_get_secret_provider_default_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOGNITION_SECRET_BACKEND", raising=False)
    provider = get_secret_provider()
    assert isinstance(provider, EnvSecretProvider)


def test_get_secret_provider_unknown_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_SECRET_BACKEND", "vault-enterprise")
    with pytest.raises(ValueError, match="Unknown RECOGNITION_SECRET_BACKEND"):
        get_secret_provider()
