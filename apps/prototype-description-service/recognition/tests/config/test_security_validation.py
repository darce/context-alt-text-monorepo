"""Tests for the fail-closed production security config guard."""

from __future__ import annotations

import pytest

from recognition.config.security import (
    InsecureProductionConfigError,
    SecuritySettings,
    validate_production_security,
)


def test_validate_rejects_production_with_dev_api_keys() -> None:
    settings = SecuritySettings(dev_api_keys=["plaintext-dev-key"])
    with pytest.raises(InsecureProductionConfigError):
        validate_production_security(settings, runtime_mode="production")


def test_validate_accepts_production_with_empty_dev_api_keys() -> None:
    settings = SecuritySettings(dev_api_keys=[])
    validate_production_security(settings, runtime_mode="production")


def test_validate_allows_dev_api_keys_outside_production() -> None:
    settings = SecuritySettings(dev_api_keys=["plaintext-dev-key"])
    validate_production_security(settings, runtime_mode="test")
    validate_production_security(settings, runtime_mode="development")


def test_validate_reads_env_when_args_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "production")
    monkeypatch.setenv("RECOGNITION_ALLOWED_API_KEYS", "leaked-prod-key")
    with pytest.raises(InsecureProductionConfigError):
        validate_production_security()


def test_validate_defaults_runtime_mode_to_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOGNITION_RUNTIME_MODE", raising=False)
    settings = SecuritySettings(dev_api_keys=["leaked-key"])
    with pytest.raises(InsecureProductionConfigError):
        validate_production_security(settings)
