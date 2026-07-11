"""Characterization: SecuritySettings.admin_token env resolution (SECRETS-P2 Slice 3).

Pins the pre-migration observable value for env-set and env-unset cases so the
SecretProvider swap is proven inert (TEST-03 / REF-05).
"""

from __future__ import annotations

import pytest

from recognition.config.security import SecuritySettings


def test_admin_token_resolves_from_env_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: RECOGNITION_ADMIN_TOKEN set → admin_token equals that value."""
    token = "characterization-admin-token-value-32chars"
    monkeypatch.setenv("RECOGNITION_ADMIN_TOKEN", token)

    settings = SecuritySettings()

    assert settings.admin_token == token


def test_admin_token_defaults_to_empty_string_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Characterization: RECOGNITION_ADMIN_TOKEN unset → admin_token is \"\"."""
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN", raising=False)

    settings = SecuritySettings()

    assert settings.admin_token == ""


def test_admin_token_set_empty_string_is_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: set-but-empty env value resolves to \"\" (os.getenv semantics)."""
    monkeypatch.setenv("RECOGNITION_ADMIN_TOKEN", "")

    settings = SecuritySettings()

    assert settings.admin_token == ""
