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
        "policy_names": {(t, f"tenant_isolation_{t}") for t in tenant},
        "matview_relkind": "m",
    }


def test_dropped_policy_is_heal_repairable_and_named() -> None:
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["policy_names"] = {("image_descriptions", "tenant_isolation_image_descriptions")}

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
    kwargs["matview_centroid_typmod"] = -1

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == script.EXIT_HEAL_REPAIRABLE
    assert report["matview_centroid_typmod"] == -1


def test_matching_matview_centroid_typmod_is_ok() -> None:
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["matview_centroid_typmod"] = script.EMBEDDING_DIMENSION

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is True
    assert report["matview_centroid_typmod"] == script.EMBEDDING_DIMENSION


def test_mismatched_matview_centroid_typmod_is_heal_repairable_and_named() -> None:
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["matview_centroid_typmod"] = -1

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["matview_centroid_typmod"] == -1
    assert report["exit_code"] == script.EXIT_HEAL_REPAIRABLE


def test_collect_and_validate_rejects_non_vector_centroid_with_matching_typmod(monkeypatch) -> None:
    script = _import_script()

    class _Result:
        def __init__(self, rows=(), scalar_value=None):
            self._rows = rows
            self._scalar_value = scalar_value

        def __iter__(self):
            return iter(self._rows)

        def all(self):
            return list(self._rows)

        def scalar(self):
            return self._scalar_value

        def scalar_one_or_none(self):
            return self._scalar_value

    class _Inspector:
        def get_table_names(self):
            return [*script.EXPECTED_TABLES, "alembic_version"]

    class _Connection:
        centroid_probe_sql = ""

        def execute(self, statement, _params=None):
            sql = str(statement).lower()
            if "select version_num" in sql:
                return _Result(scalar_value=script.EXPECTED_REVISION)
            if "relrowsecurity" in sql:
                return _Result((name, True, True) for name in script.TENANT_TABLES)
            if "from pg_policies" in sql:
                return _Result((name, f"tenant_isolation_{name}") for name in script.TENANT_TABLES)
            if "select c.relname, c.relkind" in sql:
                return _Result((name, "m" if name == script.MATVIEW_NAME else "r") for name in script.EXPECTED_TABLES)
            if "from pg_attribute" in sql:
                self.centroid_probe_sql = sql
                if "join pg_type t on t.oid = a.atttypid" in sql and "t.typname = 'vector'" in sql:
                    # Simulate a centroid column with a non-vector type that happens
                    # to expose the expected numeric typmod.
                    return _Result(scalar_value=None)
                return _Result(scalar_value=script.EMBEDDING_DIMENSION)
            if "select c.relkind from" in sql:
                return _Result(scalar_value="m")
            raise AssertionError(f"unexpected SQL: {sql}")

    connection = _Connection()
    monkeypatch.setattr(script, "inspect", lambda _connection: _Inspector())
    monkeypatch.setattr(script, "_expected_columns", lambda: {})

    report = script.collect_and_validate(connection)

    assert "join pg_type t on t.oid = a.atttypid" in connection.centroid_probe_sql
    assert "t.typname = 'vector'" in connection.centroid_probe_sql
    assert report["matview_relkind"] == "m"
    assert report["matview_centroid_typmod"] is None
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


def test_missing_column_is_heal_repairable_and_named() -> None:
    # MAINT-TPR-01 / PA-03: an existing table missing an ORM-declared column is
    # heal-repairable (heal() now adds it additively) and the gap names the
    # table + column so operators/logs see the exact drift.
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["column_gaps"] = {"tenants": ["naming_agreement_enabled"]}

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["column_gaps"] == {"tenants": ["naming_agreement_enabled"]}
    assert report["exit_code"] == script.EXIT_HEAL_REPAIRABLE


def test_non_additive_column_gap_requires_operator() -> None:
    # MAINT-TPR-BR-04: a missing NOT NULL-without-default (or PK) column makes
    # heal RAISE, so it must classify operator-required (exit 2), NOT
    # heal-repairable (exit 1) — otherwise the boot chain crash-loops re-running
    # a heal that can never converge.
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["column_gaps"] = {"media_identities": ["confidence"]}
    kwargs["non_additive_column_gaps"] = {"media_identities": ["confidence"]}

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == script.EXIT_OPERATOR_REQUIRED
    assert report["non_additive_column_gaps"] == {"media_identities": ["confidence"]}


def test_empty_column_gaps_is_ok() -> None:
    # An explicit empty mapping (no drift) must not flip the schema to failed.
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["column_gaps"] = {"tenants": []}

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is True
    assert report["column_gaps"] == {}
    assert report["exit_code"] == script.EXIT_OK
