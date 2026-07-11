"""Unit tests for OciVaultSecretProvider (SECRETS-P3 Slice 1).

Mocks mirror the real ``oci.secrets.SecretsClient.get_secret_bundle`` return
shape (mandate a): ``Response.data.secret_bundle_content.content`` is base64
(``Base64SecretBundleContentDetails``), verified against oci 2.181.x.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from oci.exceptions import RequestException, ServiceError
from oci.secrets import SecretsClient
from oci.secrets.models import Base64SecretBundleContentDetails, SecretBundle

from shared.secrets import OciVaultSecretProvider, SecretNotFound

_NAMESPACED_PATH = "secret/recognition/admin-token"
_SECRET_OCID = "ocid1.vaultsecret.oc1..exampleadmin"
_PLAINTEXT = "vault-admin-token-value"


def _bundle_response(plaintext: str = _PLAINTEXT) -> SimpleNamespace:
    """Build a Response-shaped object matching the real OCI SDK."""
    content = Base64SecretBundleContentDetails()
    content.content = base64.b64encode(plaintext.encode("utf-8")).decode("ascii")
    content.content_type = "BASE64"
    bundle = SecretBundle()
    bundle.secret_id = _SECRET_OCID
    bundle.secret_bundle_content = content
    # oci.response.Response requires a request object; SimpleNamespace is enough
    # for the adapter which only reads ``.data.secret_bundle_content.content``.
    return SimpleNamespace(data=bundle, status=200)


def _spec_client(**kwargs: Any) -> MagicMock:
    client = create_autospec(SecretsClient, instance=True, **kwargs)
    return client


def test_get_secret_fetches_by_namespaced_path_and_decodes_bundle() -> None:
    client = _spec_client()
    client.get_secret_bundle.return_value = _bundle_response()

    provider = OciVaultSecretProvider(
        {_NAMESPACED_PATH: _SECRET_OCID},
        secrets_client=client,
    )

    assert provider.get_secret(_NAMESPACED_PATH) == _PLAINTEXT
    client.get_secret_bundle.assert_called_once_with(secret_id=_SECRET_OCID)


def test_client_constructed_with_explicit_timeout_tuple() -> None:
    """RES-02: SecretsClient receives explicit connect/read timeout."""
    captured: dict[str, Any] = {}

    def _factory(*, config: dict[str, Any], signer: Any, timeout: Any) -> MagicMock:
        captured["config"] = config
        captured["signer"] = signer
        captured["timeout"] = timeout
        client = _spec_client()
        client.get_secret_bundle.return_value = _bundle_response()
        return client

    provider = OciVaultSecretProvider(
        {_NAMESPACED_PATH: _SECRET_OCID},
        connect_timeout_s=3.5,
        read_timeout_s=7.0,
        client_factory=_factory,
        signer_factory=lambda: object(),
    )

    assert provider.get_secret(_NAMESPACED_PATH) == _PLAINTEXT
    assert captured["timeout"] == (3.5, 7.0)
    assert captured["config"] == {}


def test_unmapped_name_raises_secret_not_found_without_client_call() -> None:
    client = _spec_client()
    provider = OciVaultSecretProvider(
        {_NAMESPACED_PATH: _SECRET_OCID},
        secrets_client=client,
    )

    with pytest.raises(SecretNotFound, match=r"^Secret not found: secret/missing$"):
        provider.get_secret("secret/missing")
    client.get_secret_bundle.assert_not_called()


def test_vault_404_raises_secret_not_found() -> None:
    client = _spec_client()
    client.get_secret_bundle.side_effect = ServiceError(
        status=404,
        code="NotAuthorizedOrNotFound",
        headers={},
        message="Not found",
    )
    provider = OciVaultSecretProvider(
        {_NAMESPACED_PATH: _SECRET_OCID},
        secrets_client=client,
    )

    with pytest.raises(SecretNotFound, match=r"^Secret not found: secret/recognition/admin-token$"):
        provider.get_secret(_NAMESPACED_PATH)
    assert client.get_secret_bundle.call_count == 1


def test_transport_error_retries_then_raises() -> None:
    """RES-06: transport failures retry with backoff; 4xx does not."""
    client = _spec_client()
    client.get_secret_bundle.side_effect = RequestException("connection reset")
    sleeps: list[float] = []

    provider = OciVaultSecretProvider(
        {_NAMESPACED_PATH: _SECRET_OCID},
        secrets_client=client,
        max_attempts=3,
        backoff_base_s=0.1,
        sleeper=sleeps.append,
    )

    with pytest.raises(RequestException, match="connection reset"):
        provider.get_secret(_NAMESPACED_PATH)

    assert client.get_secret_bundle.call_count == 3
    assert sleeps == [0.1, 0.2]


def test_5xx_retries_then_succeeds() -> None:
    client = _spec_client()
    client.get_secret_bundle.side_effect = [
        ServiceError(status=503, code="InternalError", headers={}, message="busy"),
        _bundle_response(),
    ]
    sleeps: list[float] = []

    provider = OciVaultSecretProvider(
        {_NAMESPACED_PATH: _SECRET_OCID},
        secrets_client=client,
        max_attempts=3,
        backoff_base_s=0.05,
        sleeper=sleeps.append,
    )

    assert provider.get_secret(_NAMESPACED_PATH) == _PLAINTEXT
    assert client.get_secret_bundle.call_count == 2
    assert sleeps == [0.05]


def test_4xx_auth_error_does_not_retry() -> None:
    client = _spec_client()
    client.get_secret_bundle.side_effect = ServiceError(
        status=401,
        code="NotAuthenticated",
        headers={},
        message="nope",
    )
    sleeps: list[float] = []

    provider = OciVaultSecretProvider(
        {_NAMESPACED_PATH: _SECRET_OCID},
        secrets_client=client,
        max_attempts=3,
        sleeper=sleeps.append,
    )

    with pytest.raises(ServiceError) as exc_info:
        provider.get_secret(_NAMESPACED_PATH)
    assert exc_info.value.status == 401
    assert client.get_secret_bundle.call_count == 1
    assert sleeps == []


def test_empty_secret_ocid_map_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="non-empty secret_ocid_map"):
        OciVaultSecretProvider({})


def test_get_secret_caches_value_across_reads() -> None:
    """SEC-RP round2: secrets are immutable per process (rotation=restart), so
    repeated reads must NOT re-hit Vault. get_security_settings() rebuilds
    SecuritySettings() per request; without this cache each authenticated
    request would fire a blocking Vault round-trip (CON-01/RES-12/PERF-07)."""
    client = _spec_client()
    client.get_secret_bundle.return_value = _bundle_response()

    provider = OciVaultSecretProvider(
        {_NAMESPACED_PATH: _SECRET_OCID},
        secrets_client=client,
    )

    first = provider.get_secret(_NAMESPACED_PATH)
    second = provider.get_secret(_NAMESPACED_PATH)

    assert first == second == _PLAINTEXT
    client.get_secret_bundle.assert_called_once_with(secret_id=_SECRET_OCID)


def test_get_secret_tolerates_trailing_newline_in_base64_content() -> None:
    """Round2 LOW: an operator-stored base64 value with a trailing newline must
    still decode (strip before validate=True), not abort boot as SecretNotFound;
    the strict decode still rejects embedded corruption."""
    resp = _bundle_response()
    resp.data.secret_bundle_content.content = resp.data.secret_bundle_content.content + "\n"
    client = _spec_client()
    client.get_secret_bundle.return_value = resp

    provider = OciVaultSecretProvider(
        {_NAMESPACED_PATH: _SECRET_OCID},
        secrets_client=client,
    )

    assert provider.get_secret(_NAMESPACED_PATH) == _PLAINTEXT
