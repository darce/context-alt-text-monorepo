from __future__ import annotations

import importlib.util
import pathlib


def _import_script():
    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "verify_identity_schema.py"
    spec = importlib.util.spec_from_file_location("verify_identity_schema", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_validate_schema_state_reports_missing_tables() -> None:
    script = _import_script()

    report = script._validate_schema_state(
        actual_tables={"tenants", "api_keys"},
        actual_revision=script.EXPECTED_REVISION,
        expected_tables=("tenants", "api_keys", "media_identities"),
    )

    assert report["ok"] is False
    assert report["missing_tables"] == ["media_identities"]


def test_validate_schema_state_accepts_complete_schema() -> None:
    script = _import_script()

    report = script._validate_schema_state(
        actual_tables={"tenants", "api_keys", "media_identities"},
        actual_revision=script.EXPECTED_REVISION,
        expected_tables=("tenants", "api_keys", "media_identities"),
    )

    assert report["ok"] is True
    assert report["missing_tables"] == []
