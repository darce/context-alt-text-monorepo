from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType


def _import_script() -> ModuleType:
    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "verify_identity_schema.py"
    spec = importlib.util.spec_from_file_location("verify_identity_schema", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
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


def _complete_kwargs(script) -> dict:
    tables = ("tenants", "export_jobs", "image_descriptions")
    tenant = ("export_jobs", "image_descriptions")
    return {
        "actual_tables": set(tables),
        "actual_revision": script.EXPECTED_REVISION,
        "expected_tables": tables,
        "tenant_tables": tenant,
        "rls_state": dict.fromkeys(tenant, (True, True)),
        "policy_names": {f"tenant_isolation_{t}" for t in tenant},
        "matview_relkind": "m",
    }


def test_dropped_policy_is_heal_repairable_and_named() -> None:
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["policy_names"] = {"tenant_isolation_image_descriptions"}

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["policy_gaps"] == ["export_jobs"]
    assert report["exit_code"] == script.EXIT_HEAL_REPAIRABLE


def test_unforced_rls_is_heal_repairable_and_named() -> None:
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["rls_state"]["export_jobs"] = (True, False)

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["rls_gaps"] == ["export_jobs"]
    assert report["exit_code"] == script.EXIT_HEAL_REPAIRABLE


def test_matview_as_plain_table_requires_operator() -> None:
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["matview_relkind"] = "r"

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == script.EXIT_OPERATOR_REQUIRED


def test_missing_matview_is_heal_repairable() -> None:
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["matview_relkind"] = None

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == script.EXIT_HEAL_REPAIRABLE


def test_revision_mismatch_requires_operator() -> None:
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["actual_revision"] = "bogus"

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == script.EXIT_OPERATOR_REQUIRED


def test_complete_schema_exits_zero() -> None:
    script = _import_script()

    report = script._validate_schema_state(**_complete_kwargs(script))

    assert report["ok"] is True
    assert report["exit_code"] == script.EXIT_OK
