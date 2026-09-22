"""Unit coverage for operator-scope recovery table verification (APP1-RECOVERY-RV05)."""

from __future__ import annotations

import importlib
import inspect

from scripts import verify_identity_schema as verify

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")
BYPASS_RLS_EXPR = MIGRATION.BYPASS_RLS_EXPR
OPERATOR_SCOPE_TABLES = MIGRATION.OPERATOR_SCOPE_TABLES

CURSOR = "billing_reconciliation_cursor"
LEASE = "billing_known_item_lease"
FUTURE_N1 = "billing_future_n1_known_item"


def _base_kwargs() -> dict:
    tenant = ("export_jobs", "image_descriptions")
    tables = ("tenants", *tenant)
    return {
        "actual_tables": set(tables),
        "actual_revision": verify.EXPECTED_REVISION,
        "expected_tables": tables,
        "tenant_tables": tenant,
        "rls_state": dict.fromkeys(tenant, (True, True)),
        "policy_names": {(table, f"tenant_isolation_{table}") for table in tenant},
        "matview_relkind": "m",
        "matview_centroid_typmod": verify.EMBEDDING_DIMENSION,
        "vector_typmods": dict.fromkeys(verify.IDENTITY_VECTOR_COLUMNS, verify.EMBEDDING_DIMENSION),
    }


def _with_operator(
    tables: tuple[str, ...] = (CURSOR, LEASE),
    *,
    body: str | None = None,
) -> dict:
    kwargs = _base_kwargs()
    approved = BYPASS_RLS_EXPR if body is None else body
    kwargs["operator_scope_tables"] = tables
    kwargs["actual_tables"] = set(kwargs["actual_tables"]) | set(tables)
    kwargs["expected_tables"] = tuple(kwargs["expected_tables"]) + tables
    kwargs["rls_state"] = {**kwargs["rls_state"], **dict.fromkeys(tables, (True, True))}
    kwargs["policy_names"] = set(kwargs["policy_names"]) | {(table, f"operator_scope_{table}") for table in tables}
    kwargs["operator_policy_bodies"] = {(table, f"operator_scope_{table}"): (approved, approved) for table in tables}
    return kwargs


def test_verifier_exports_operator_scope_tables_from_migration() -> None:
    assert tuple(OPERATOR_SCOPE_TABLES) == verify.OPERATOR_SCOPE_TABLES
    assert CURSOR in verify.OPERATOR_SCOPE_TABLES
    assert LEASE in verify.OPERATOR_SCOPE_TABLES


def test_validate_schema_state_accepts_generated_operator_scope_body() -> None:
    report = verify._validate_schema_state(**_with_operator())

    assert report["ok"] is True
    assert report["exit_code"] == verify.EXIT_OK
    assert report["rls_gaps"] == []
    assert report["policy_gaps"] == []


def test_validate_schema_state_accepts_pg_normalized_operator_scope_body() -> None:
    pg_form = "(COALESCE(NULLIF(current_setting('app.bypass_rls'::text, true), ''::text), 'false'::text))::boolean"
    report = verify._validate_schema_state(**_with_operator(body=pg_form))

    assert report["ok"] is True
    assert report["exit_code"] == verify.EXIT_OK
    assert report["policy_gaps"] == []


def test_missing_operator_scope_policy_is_heal_repairable() -> None:
    kwargs = _with_operator()
    kwargs["policy_names"] = {pair for pair in kwargs["policy_names"] if pair != (CURSOR, f"operator_scope_{CURSOR}")}

    report = verify._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == verify.EXIT_HEAL_REPAIRABLE
    assert CURSOR in report["policy_gaps"]
    assert LEASE not in report["policy_gaps"]


def test_disabled_operator_rls_is_heal_repairable() -> None:
    kwargs = _with_operator()
    kwargs["rls_state"][CURSOR] = (False, True)

    report = verify._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == verify.EXIT_HEAL_REPAIRABLE
    assert report["rls_gaps"] == [CURSOR]


def test_unforced_operator_rls_is_heal_repairable() -> None:
    kwargs = _with_operator()
    kwargs["rls_state"][CURSOR] = (True, False)

    report = verify._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == verify.EXIT_HEAL_REPAIRABLE
    assert report["rls_gaps"] == [CURSOR]


def test_permissive_or_true_operator_policy_body_does_not_pass() -> None:
    wrapped = f"({BYPASS_RLS_EXPR}) OR true"
    assert "app.bypass_rls" in wrapped

    report = verify._validate_schema_state(**_with_operator(body=wrapped))

    assert report["ok"] is False
    assert report["exit_code"] == verify.EXIT_HEAL_REPAIRABLE
    assert CURSOR in report["policy_gaps"]
    assert LEASE in report["policy_gaps"]


def test_true_operator_policy_body_does_not_pass() -> None:
    report = verify._validate_schema_state(**_with_operator(body="true"))

    assert report["ok"] is False
    assert report["exit_code"] == verify.EXIT_HEAL_REPAIRABLE
    assert CURSOR in report["policy_gaps"]


def test_tenant_isolation_predicate_is_not_accepted_for_operator_scope() -> None:
    tenant_body = f"tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid OR {BYPASS_RLS_EXPR}"
    report = verify._validate_schema_state(**_with_operator(body=tenant_body))

    assert report["ok"] is False
    assert CURSOR in report["policy_gaps"]


def test_operator_scope_tables_are_checked_dynamically_including_future_n1() -> None:
    kwargs = _with_operator((LEASE, FUTURE_N1))
    kwargs["rls_state"].pop(FUTURE_N1)
    kwargs["policy_names"].remove((FUTURE_N1, f"operator_scope_{FUTURE_N1}"))
    kwargs["operator_policy_bodies"].pop((FUTURE_N1, f"operator_scope_{FUTURE_N1}"))

    report = verify._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert FUTURE_N1 in report["rls_gaps"]
    assert FUTURE_N1 in report["policy_gaps"]
    assert LEASE not in report["rls_gaps"]
    assert LEASE not in report["policy_gaps"]


def test_tenant_policy_gap_is_preserved_when_operator_scope_is_healthy() -> None:
    kwargs = _with_operator()
    kwargs["policy_names"].remove(("export_jobs", "tenant_isolation_export_jobs"))

    report = verify._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == verify.EXIT_HEAL_REPAIRABLE
    assert report["policy_gaps"] == ["export_jobs"]


def test_collect_and_validate_requests_operator_scope_tables_for_rls() -> None:
    source = inspect.getsource(verify.collect_and_validate)
    assert "OPERATOR_SCOPE_TABLES" in source
    assert "qual" in source and "with_check" in source
