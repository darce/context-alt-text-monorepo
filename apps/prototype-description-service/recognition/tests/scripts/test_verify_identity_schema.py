from __future__ import annotations

import importlib.util
import inspect
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
        matview_centroid_typmod=script.EMBEDDING_DIMENSION,
        vector_typmods=_healthy_vector_typmods(script),
    )

    assert report["ok"] is False
    assert report["missing_tables"] == ["media_identities"]


def test_validate_schema_state_accepts_complete_schema() -> None:
    script = _import_script()

    report = script._validate_schema_state(
        actual_tables={"tenants", "api_keys", "media_identities"},
        actual_revision=script.EXPECTED_REVISION,
        expected_tables=("tenants", "api_keys", "media_identities"),
        matview_centroid_typmod=script.EMBEDDING_DIMENSION,
        vector_typmods=_healthy_vector_typmods(script),
    )

    assert report["ok"] is True
    assert report["missing_tables"] == []


def _healthy_vector_typmods(script) -> dict[tuple[str, str], int]:
    return dict.fromkeys(script.IDENTITY_VECTOR_COLUMNS, script.EMBEDDING_DIMENSION)


def _set_centroid_typmod(script, kwargs: dict, typmod: int | None) -> dict:
    kwargs["matview_centroid_typmod"] = typmod
    kwargs["vector_typmods"] = {
        **kwargs["vector_typmods"],
        (script.MATVIEW_NAME, "centroid"): typmod,
    }
    return kwargs


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
        "matview_centroid_typmod": script.EMBEDDING_DIMENSION,
        "vector_typmods": _healthy_vector_typmods(script),
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
    _set_centroid_typmod(script, kwargs, -1)

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
    _set_centroid_typmod(script, kwargs, -1)

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["matview_centroid_typmod"] == -1
    assert report["exit_code"] == script.EXIT_HEAL_REPAIRABLE


def test_mismatched_matview_centroid_typmod_without_drop_privilege_requires_operator() -> None:
    # VLMHEAL-1-REV-A-05: a typmod gap on a matview the app role cannot DROP
    # is not heal-repairable. Observation that would refute the finding: the
    # verifier still exits EXIT_HEAL_REPAIRABLE and omits the quote_ident()
    # ALTER OWNER remediation (P3, P16).
    script = _import_script()
    kwargs = _complete_kwargs(script)
    _set_centroid_typmod(script, kwargs, -1)
    kwargs["matview_can_drop"] = False
    kwargs["current_role_quoted"] = '"alt-context-app"'

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == script.EXIT_OPERATOR_REQUIRED
    joined = " ".join(report["operator_actions"])
    assert "ALTER MATERIALIZED VIEW mv_identity_cluster_centroids OWNER TO" in joined
    assert 'OWNER TO "alt-context-app"' in joined
    assert "OWNER TO alt-context-app;" not in joined


def test_mismatched_matview_centroid_typmod_without_create_privilege_requires_operator() -> None:
    # VLMHEAL-1-REV-A-05: DROP-capable membership is not enough to rebuild.
    script = _import_script()
    kwargs = _complete_kwargs(script)
    _set_centroid_typmod(script, kwargs, -1)
    kwargs["matview_can_drop"] = True
    kwargs["matview_create_privilege_gaps"] = ["CREATE on schema public"]

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == script.EXIT_OPERATOR_REQUIRED
    assert "CREATE on schema public" in " ".join(report["operator_actions"])


def test_mismatched_matview_centroid_typmod_with_vanished_grantee_requires_operator() -> None:
    script = _import_script()
    kwargs = _complete_kwargs(script)
    _set_centroid_typmod(script, kwargs, -1)
    kwargs["matview_can_drop"] = True
    kwargs["matview_vanished_grantees"] = ["vanished_reader"]

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == script.EXIT_OPERATOR_REQUIRED
    joined = " ".join(report["operator_actions"])
    assert "vanished_reader" in joined
    assert "cannot receive GRANT" in joined
    assert "python -m scripts.sync_identity_schema" not in joined
    assert report["matview_vanished_grantees"] == ["vanished_reader"]


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

    def one_or_none(self):
        if self._rows:
            return self._rows[0]
        return self._scalar_value

    def one(self):
        value = self.one_or_none()
        if value is None:
            raise AssertionError("one() on empty result")
        return value


class _Inspector:
    def __init__(self, script):
        self._script = script

    def get_table_names(self):
        return [*self._script.EXPECTED_TABLES, "alembic_version"]


def _catalog_connection(
    script,
    *,
    centroid_typmod,
    centroid_is_vector: bool = True,
    matview_can_drop: bool = True,
    current_user: str = "app_role",
    current_user_quoted: str | None = None,
    create_ok: bool = True,
    vector_typmods: dict[tuple[str, str], int | None] | None = None,
    acl_grant_rows: list[tuple[str, str, bool]] | None = None,
    vanished_roles: set[str] | None = None,
):
    quoted = current_user_quoted if current_user_quoted is not None else current_user

    class _Connection:
        def __init__(self) -> None:
            self.sql_log: list[str] = []
            self.params_log: list[object] = []
            self.centroid_probe_sql = ""

        def execute(self, statement, _params=None):
            sql = str(statement).lower()
            self.sql_log.append(sql)
            self.params_log.append(_params)
            if "select version_num" in sql:
                return _Result(scalar_value=script.EXPECTED_REVISION)
            if "relrowsecurity" in sql:
                return _Result(rows=[(name, True, True) for name in script.TENANT_TABLES])
            if "from pg_policies" in sql:
                return _Result(rows=[(name, f"tenant_isolation_{name}") for name in script.TENANT_TABLES])
            if "select c.relname, c.relkind" in sql:
                return _Result(
                    rows=[(name, "m" if name == script.MATVIEW_NAME else "r") for name in script.EXPECTED_TABLES]
                )
            if "from pg_attribute" in sql:
                self.centroid_probe_sql = sql
                params = _params or {}
                table_name = params.get("table_name") or params.get("name")
                column_name = params.get("column_name")
                if table_name == script.MATVIEW_NAME or column_name == "centroid":
                    self.centroid_probe_sql = sql
                if "join pg_type t on t.oid = a.atttypid" in sql and "t.typname = 'vector'" in sql:
                    if column_name == "centroid" or table_name == script.MATVIEW_NAME:
                        if not centroid_is_vector:
                            return _Result(scalar_value=None)
                        return _Result(scalar_value=centroid_typmod)
                    if vector_typmods is not None and table_name is not None and column_name is not None:
                        return _Result(scalar_value=vector_typmods.get((table_name, column_name)))
                    return _Result(scalar_value=script.EMBEDDING_DIMENSION)
                return _Result(scalar_value=centroid_typmod)
            if "pg_has_role" in sql:
                return _Result(
                    rows=[("m", "foreign_owner" if not matview_can_drop else current_user, matview_can_drop, quoted)],
                    scalar_value="m",
                )
            if "has_schema_privilege" in sql or "has_table_privilege" in sql:
                return _Result(rows=[("public", create_ok, create_ok, create_ok, create_ok, create_ok)])
            if "aclexplode" in sql:
                return _Result(rows=list(acl_grant_rows or ()))
            if "from pg_roles" in sql:
                name = (_params or {}).get("name")
                if name in (vanished_roles or set()):
                    return _Result(scalar_value=None)
                return _Result(scalar_value=1)
            if "select c.relkind from" in sql:
                return _Result(scalar_value="m")
            raise AssertionError(f"unexpected SQL: {sql}")

    return _Connection()


def test_collect_and_validate_rejects_non_vector_centroid_with_matching_typmod(monkeypatch) -> None:
    script = _import_script()
    connection = _catalog_connection(
        script,
        centroid_typmod=script.EMBEDDING_DIMENSION,
        centroid_is_vector=False,
        matview_can_drop=True,
    )
    monkeypatch.setattr(script, "inspect", lambda _connection: _Inspector(script))
    monkeypatch.setattr(script, "_expected_columns", lambda: {})

    report = script.collect_and_validate(connection)

    # VLMHEA-H-01 / VLMHEA-M-02: type filter, column selection, missing-row.
    assert "join pg_type t on t.oid = a.atttypid" in connection.centroid_probe_sql
    assert "t.typname = 'vector'" in connection.centroid_probe_sql
    column_probes = [
        (params.get("table_name"), params.get("column_name"))
        for params in connection.params_log
        if isinstance(params, dict) and "column_name" in params
    ]
    assert (script.MATVIEW_NAME, "centroid") in column_probes
    assert set(script.IDENTITY_VECTOR_COLUMNS) <= set(column_probes)
    assert report["matview_relkind"] == "m"
    assert report["matview_centroid_typmod"] is None
    assert report["exit_code"] == script.EXIT_HEAL_REPAIRABLE


def test_collect_and_validate_typmod_gap_with_foreign_owner_requires_operator(monkeypatch) -> None:
    # VLMHEAL-1-REV-A-05: catalog facts must include pg_has_role on relowner
    # and classify an un-droppable typmod gap as operator-required.
    script = _import_script()
    connection = _catalog_connection(
        script,
        centroid_typmod=-1,
        matview_can_drop=False,
        current_user="alt-context-app",
        current_user_quoted='"alt-context-app"',
    )
    monkeypatch.setattr(script, "inspect", lambda _connection: _Inspector(script))
    monkeypatch.setattr(script, "_expected_columns", lambda: {})

    report = script.collect_and_validate(connection)

    assert any("pg_has_role" in sql and "relowner" in sql for sql in connection.sql_log)
    assert report["exit_code"] == script.EXIT_OPERATOR_REQUIRED
    joined = " ".join(report["operator_actions"])
    assert 'OWNER TO "alt-context-app"' in joined


def test_collect_and_validate_typmod_gap_when_role_can_drop_is_heal_repairable(monkeypatch) -> None:
    script = _import_script()
    connection = _catalog_connection(script, centroid_typmod=-1, matview_can_drop=True)
    monkeypatch.setattr(script, "inspect", lambda _connection: _Inspector(script))
    monkeypatch.setattr(script, "_expected_columns", lambda: {})

    report = script.collect_and_validate(connection)

    assert any("pg_has_role" in sql for sql in connection.sql_log)
    assert report["exit_code"] == script.EXIT_HEAL_REPAIRABLE


def test_collect_and_validate_typmod_gap_with_vanished_grantee_requires_operator(monkeypatch) -> None:
    script = _import_script()
    connection = _catalog_connection(
        script,
        centroid_typmod=-1,
        matview_can_drop=True,
        acl_grant_rows=[("vanished_reader", "SELECT", False)],
        vanished_roles={"vanished_reader"},
    )
    monkeypatch.setattr(script, "inspect", lambda _connection: _Inspector(script))
    monkeypatch.setattr(script, "_expected_columns", lambda: {})

    report = script.collect_and_validate(connection)

    assert any("aclexplode" in sql for sql in connection.sql_log)
    assert report["exit_code"] == script.EXIT_OPERATOR_REQUIRED
    joined = " ".join(report["operator_actions"])
    assert "vanished_reader" in joined
    assert "cannot receive GRANT" in joined
    assert report["matview_vanished_grantees"] == ["vanished_reader"]


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


def test_validate_schema_state_vector_typmods_is_required() -> None:
    # VLMHEAL-1-REV-A-08: a default equal to the passing typmod hides drift.
    script = _import_script()
    param = inspect.signature(script._validate_schema_state).parameters["vector_typmods"]
    assert param.default is inspect.Parameter.empty


def test_validate_schema_state_matview_centroid_typmod_has_no_passing_default() -> None:
    # VLMHEAL-1-REV-A-08: the old param (or its successor) must not default to
    # EMBEDDING_DIMENSION. Observation that would refute the finding: omitting
    # the argument still classifies a matching centroid as healthy.
    script = _import_script()
    params = inspect.signature(script._validate_schema_state).parameters
    if "matview_centroid_typmod" in params:
        default = params["matview_centroid_typmod"].default
        assert default is inspect.Parameter.empty or default != script.EMBEDDING_DIMENSION
    else:
        assert "vector_typmods" in params
        assert params["vector_typmods"].default is inspect.Parameter.empty


def test_identity_vector_columns_imported_from_health() -> None:
    # VLMHEAL-1-REV-A-01: single source of truth is health.IDENTITY_VECTOR_COLUMNS.
    from recognition.application.health import IDENTITY_VECTOR_COLUMNS as HEALTH

    script = _import_script()
    assert script.IDENTITY_VECTOR_COLUMNS is HEALTH


def test_wrong_typmod_table_column_requires_named_operator_action() -> None:
    # VLMHEAL-1-REV-A-01: a table vector column cannot be drop-rebuilt like the
    # matview. Observation that would refute the finding: exit 1 or an unnamed gap.
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["actual_tables"] = set(kwargs["actual_tables"]) | {"media_identities"}
    kwargs["expected_tables"] = tuple(kwargs["expected_tables"]) + ("media_identities",)
    kwargs["vector_typmods"] = {
        ("media_identities", "embedding"): -1,
        ("identity_cluster_representatives", "embedding"): script.EMBEDDING_DIMENSION,
        ("mv_identity_cluster_centroids", "centroid"): script.EMBEDDING_DIMENSION,
    }

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is False
    assert report["exit_code"] == script.EXIT_OPERATOR_REQUIRED
    joined = " ".join(report["operator_actions"])
    assert "media_identities.embedding" in joined
    assert "ALTER TABLE media_identities ALTER COLUMN embedding TYPE vector(" in joined
    assert f"vector({script.EMBEDDING_DIMENSION})" in joined
    assert "DROP TABLE" not in joined


def test_collect_and_validate_probes_every_identity_vector_column(monkeypatch) -> None:
    from recognition.application.health import IDENTITY_VECTOR_COLUMNS as HEALTH

    script = _import_script()
    connection = _catalog_connection(script, centroid_typmod=script.EMBEDDING_DIMENSION)
    monkeypatch.setattr(script, "inspect", lambda _connection: _Inspector(script))
    monkeypatch.setattr(script, "_expected_columns", lambda: {})

    report = script.collect_and_validate(connection)

    probed = {
        (params.get("table_name"), params.get("column_name"))
        for params in connection.params_log
        if isinstance(params, dict) and "column_name" in params
    }
    assert set(HEALTH) <= probed
    assert report["exit_code"] == script.EXIT_OK


def test_collect_and_validate_wrong_table_typmod_requires_operator(monkeypatch) -> None:
    script = _import_script()
    connection = _catalog_connection(
        script,
        centroid_typmod=script.EMBEDDING_DIMENSION,
        vector_typmods={
            ("media_identities", "embedding"): -1,
            ("identity_cluster_representatives", "embedding"): script.EMBEDDING_DIMENSION,
            ("mv_identity_cluster_centroids", "centroid"): script.EMBEDDING_DIMENSION,
        },
    )
    monkeypatch.setattr(script, "inspect", lambda _connection: _Inspector(script))
    monkeypatch.setattr(script, "_expected_columns", lambda: {})

    report = script.collect_and_validate(connection)

    assert report["exit_code"] == script.EXIT_OPERATOR_REQUIRED
    joined = " ".join(report["operator_actions"])
    assert "media_identities.embedding" in joined
    assert "ALTER TABLE media_identities" in joined


def test_empty_column_gaps_is_ok() -> None:
    # An explicit empty mapping (no drift) must not flip the schema to failed.
    script = _import_script()
    kwargs = _complete_kwargs(script)
    kwargs["column_gaps"] = {"tenants": []}

    report = script._validate_schema_state(**kwargs)

    assert report["ok"] is True
    assert report["column_gaps"] == {}
    assert report["exit_code"] == script.EXIT_OK
