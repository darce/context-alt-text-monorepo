"""Regression tests for usage admission composition without portal setup."""

from __future__ import annotations

import pytest


def test_usage_admission_service_installs_without_the_portal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    monkeypatch.delenv("RECOGNITION_PORTAL_ENABLED", raising=False)
    monkeypatch.setenv("RECOGNITION_BETA_ADMISSION_ENABLED", "1")
    monkeypatch.delenv("RECOGNITION_ADMIN_ENABLED", raising=False)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN", raising=False)

    from api.main import create_app
    from recognition.interface_adapters.http.deps.portal_composition import UsageAdmissionServiceFactory

    app = create_app()

    assert isinstance(getattr(app.state, "usage_admission_service", None), UsageAdmissionServiceFactory)
