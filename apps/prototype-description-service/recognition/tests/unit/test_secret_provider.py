"""Unit tests for the SecretProvider port, EnvSecretProvider, and accessor seam.

Slice 1 of SECRETS-P2 — no consumers migrated yet. Proves the port/adapter
contract and the get/set/reset provider seam (REF-15, TEST-06).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from shared.secrets import (
    EnvSecretProvider,
    SecretNotFound,
    SecretProvider,
    get_secret_provider,
    reset_secret_provider,
    set_secret_provider,
)


class _FakeProvider(SecretProvider):
    """Minimal stand-in used only to prove set/reset swaps the active provider."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get_secret(self, name: str) -> str:
        try:
            return self._values[name]
        except KeyError as exc:
            raise SecretNotFound(f"Secret not found: {name}") from exc


@pytest.fixture(autouse=True)
def _restore_provider() -> Iterator[None]:
    """Isolate each test from module-level provider state."""
    reset_secret_provider()
    yield
    reset_secret_provider()


def test_env_provider_returns_present_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_TEST_SECRET_PRESENT", "super-secret")
    provider = EnvSecretProvider()
    assert provider.get_secret("ACX_TEST_SECRET_PRESENT") == "super-secret"


def test_env_provider_absent_raises_secret_not_found_with_predicted_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TEST-06: not-found path raises SecretNotFound with the predicted message."""
    monkeypatch.delenv("ACX_TEST_SECRET_ABSENT", raising=False)
    provider = EnvSecretProvider()
    with pytest.raises(SecretNotFound, match=r"^Secret not found: ACX_TEST_SECRET_ABSENT$"):
        provider.get_secret("ACX_TEST_SECRET_ABSENT")


def test_env_provider_set_empty_is_present_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_TEST_SECRET_EMPTY", "")
    provider = EnvSecretProvider()
    assert provider.get_secret("ACX_TEST_SECRET_EMPTY") == ""


def test_get_secret_optional_matches_os_getenv_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_secret_optional mirrors os.getenv: default when absent, '' when set-empty."""
    provider = EnvSecretProvider()

    monkeypatch.delenv("ACX_TEST_SECRET_OPT", raising=False)
    assert provider.get_secret_optional("ACX_TEST_SECRET_OPT") is None
    assert provider.get_secret_optional("ACX_TEST_SECRET_OPT", "fallback") == "fallback"
    assert provider.get_secret_optional("ACX_TEST_SECRET_OPT") == os.getenv("ACX_TEST_SECRET_OPT")
    assert provider.get_secret_optional("ACX_TEST_SECRET_OPT", "fallback") == os.getenv(
        "ACX_TEST_SECRET_OPT", "fallback"
    )

    monkeypatch.setenv("ACX_TEST_SECRET_OPT", "")
    assert provider.get_secret_optional("ACX_TEST_SECRET_OPT") == ""
    assert provider.get_secret_optional("ACX_TEST_SECRET_OPT", "fallback") == ""
    assert provider.get_secret_optional("ACX_TEST_SECRET_OPT") == os.getenv("ACX_TEST_SECRET_OPT")
    assert provider.get_secret_optional("ACX_TEST_SECRET_OPT", "fallback") == os.getenv(
        "ACX_TEST_SECRET_OPT", "fallback"
    )

    monkeypatch.setenv("ACX_TEST_SECRET_OPT", "present")
    assert provider.get_secret_optional("ACX_TEST_SECRET_OPT") == "present"
    assert provider.get_secret_optional("ACX_TEST_SECRET_OPT", "fallback") == "present"


def test_set_and_reset_secret_provider_swap_then_restore() -> None:
    default = get_secret_provider()
    assert isinstance(default, EnvSecretProvider)

    fake = _FakeProvider({"ACX_TEST_FAKE": "from-fake"})
    set_secret_provider(fake)
    assert get_secret_provider() is fake
    assert get_secret_provider().get_secret("ACX_TEST_FAKE") == "from-fake"

    reset_secret_provider()
    restored = get_secret_provider()
    assert isinstance(restored, EnvSecretProvider)
    assert restored is not fake
