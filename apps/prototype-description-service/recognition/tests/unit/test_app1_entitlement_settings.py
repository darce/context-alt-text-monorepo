"""Unit coverage for the billable plan allowance settings surface."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from recognition.config.settings import RecognitionSettings
from recognition.infrastructure.repositories.tenant_entitlement_repository import _validate_plan_allowances

_PLAN_ALLOWANCES_ENV = "RECOGNITION_PLAN_ALLOWANCES"


def test_recognition_settings_default_plan_allowances_include_paid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_PLAN_ALLOWANCES_ENV, raising=False)

    settings = RecognitionSettings()

    assert "paid" in settings.plan_allowances
    assert type(settings.plan_allowances["paid"]) is int
    assert settings.plan_allowances["paid"] > 0


def test_recognition_settings_plan_allowances_use_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PLAN_ALLOWANCES_ENV, '{"paid": 321}')

    settings = RecognitionSettings()

    assert settings.plan_allowances == {"paid": 321}
    assert all(type(value) is int for value in settings.plan_allowances.values())


def test_recognition_settings_rejects_negative_plan_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PLAN_ALLOWANCES_ENV, '{"paid": -1}')

    with pytest.raises(ValidationError, match="non-negative integer"):
        RecognitionSettings()


def test_recognition_settings_rejects_non_integer_plan_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PLAN_ALLOWANCES_ENV, '{"paid": "not-an-integer"}')

    with pytest.raises(ValidationError, match="non-negative integer"):
        RecognitionSettings()


def test_recognition_settings_rejects_boolean_plan_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PLAN_ALLOWANCES_ENV, '{"paid": true}')

    with pytest.raises(ValidationError, match="non-negative integer"):
        RecognitionSettings()


def test_recognition_settings_rejects_empty_plan_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PLAN_ALLOWANCES_ENV, '{"   ": 10, "paid": 100}')

    with pytest.raises(ValidationError, match="non-empty"):
        RecognitionSettings()


def test_recognition_settings_rejects_allowance_mapping_without_paid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PLAN_ALLOWANCES_ENV, '{"starter": 10}')

    with pytest.raises(ValidationError, match="paid"):
        RecognitionSettings()


def test_recognition_settings_allowances_match_repository_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_PLAN_ALLOWANCES_ENV, raising=False)

    settings = RecognitionSettings()

    assert _validate_plan_allowances(settings.plan_allowances) == settings.plan_allowances
