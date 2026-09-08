"""E15-34 Slice 3: heal() convergence, idempotence, and lock serialization.

``heal(connection)`` composes the same idempotent ``ensure_*`` helpers as
``upgrade()``, so healing from any partial state — including an empty
database — converges to the full schema **with RLS**. Regressions covered:
E15-33-BR2-01 (raw-SQL queue table heal-creatable), BR2-02 (heal-created
tenant tables carry RLS), BR2-10 (advisory-lock serialization exercised
against real Postgres).
"""

from __future__ import annotations

import importlib
import inspect
import os
import uuid
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")

pytestmark = pytest.mark.pg


def _table_names(engine) -> set[str]:
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))}


def _rls_state(engine) -> dict[str, tuple[bool, bool]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname = ANY(:tables)"
            ),
            {"tables": list(MIGRATION.TENANT_TABLES)},
        ).fetchall()
    return {name: (enabled, forced) for name, enabled, forced in rows}


def test_heal_from_empty_db_converges_to_full_schema_with_rls(pg_empty_engine) -> None:
    # BR2-01 + BR2-02: from a bare database heal creates every expected table
    # (including the raw-SQL refresh queue) and tenant tables get enabled+forced RLS.
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    missing = set(MIGRATION.EXPECTED_SCHEMA_TABLES) - _table_names(pg_empty_engine)
    assert not missing, f"heal left tables missing: {sorted(missing)}"

    state = _rls_state(pg_empty_engine)
    weak = {t: f for t, f in state.items() if f != (True, True)}
    assert not weak and set(state) == set(MIGRATION.TENANT_TABLES), (
        f"heal-created tenant tables without enabled+forced RLS: {weak}"
    )

    with pg_empty_engine.connect() as conn:
        relkind = conn.execute(
            text(
                "SELECT c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname='mv_identity_cluster_centroids'"
            )
        ).scalar()
    assert relkind == "m"


def test_heal_twice_is_a_noop(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    before = _table_names(pg_empty_engine)
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)  # must not raise or emit duplicate-object errors
    assert _table_names(pg_empty_engine) == before


def test_heal_recreates_dropped_refresh_queue(pg_empty_engine) -> None:
    # BR2-01 regression: the exact E15-29 drift shape — stamped DB missing the
    # raw-SQL table — must be repaired by heal.
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.begin() as conn:
        conn.execute(text("DROP TABLE identity_cluster_refresh_queue"))
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    assert "identity_cluster_refresh_queue" in _table_names(pg_empty_engine)


def _centroid_typmod(engine) -> int | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT a.atttypmod FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname='mv_identity_cluster_centroids' "
                "AND a.attname='centroid'"
            )
        ).scalar()


def test_heal_rebuilds_matview_that_lost_its_vector_typmod(pg_empty_engine) -> None:
    # Every stack deployed before the outer cast carries a centroid column with
    # atttypmod -1, which /health and /ready reject. Boot heal must rebuild it
    # (indexes included) rather than leave the 503 to an operator.
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    assert _centroid_typmod(pg_empty_engine) == MIGRATION.EMBEDDING_DIMENSION
    with pg_empty_engine.begin() as conn:
        conn.execute(text("DROP MATERIALIZED VIEW mv_identity_cluster_centroids"))
        conn.execute(
            text(
                "CREATE MATERIALIZED VIEW mv_identity_cluster_centroids AS "
                "SELECT c.id AS cluster_id, c.tenant_id, 0 AS identity_count, "
                "NULL::vector AS centroid, c.updated_at AS refreshed_at "
                "FROM identity_clusters c"
            )
        )
    assert _centroid_typmod(pg_empty_engine) == -1

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    assert _centroid_typmod(pg_empty_engine) == MIGRATION.EMBEDDING_DIMENSION
    with pg_empty_engine.connect() as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename='mv_identity_cluster_centroids'")
            )
        }
    assert {
        "mv_cluster_centroids_cluster_id",
        "mv_cluster_centroids_tenant_idx",
        "mv_cluster_centroids_vector_idx",
    } <= indexes


def _admin_engine_for_scratch(app_engine):
    """Connect IDENTITY_PG_ADMIN_URL (or the conftest default) to app_engine's DB.

    CREATE ROLE is cluster-wide; ALTER OWNER must run against the scratch
    database. Never use the app-role engine for role setup (P14).
    """
    scratch_url = str(app_engine.url)
    scratch_db = urlsplit(scratch_url).path.lstrip("/")
    admin_url = os.environ.get("IDENTITY_PG_ADMIN_URL")
    if not admin_url:
        parts = urlsplit(scratch_url)
        admin_url = f"postgresql+psycopg://{parts.hostname or 'localhost'}:{parts.port or 5432}/postgres"
    return create_engine(admin_url.rsplit("/", 1)[0] + f"/{scratch_db}", isolation_level="AUTOCOMMIT")


def test_heal_refuses_typmod_rebuild_when_matview_has_foreign_owner(pg_empty_engine) -> None:
    # A role-owned matview cannot be dropped by the app role. The refusal must
    # leave the drifted relation in place and give an operator copy/pasteable
    # remediation rather than attempting a partial rebuild.
    # VLMHEAL-1-REV-A-02: create/drop the scratch role and transfer ownership
    # through the admin engine. pytest.fail (never skip) if that setup fails.
    owner_role = f"identity_mv_owner_{uuid.uuid4().hex[:12]}"
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        conn.execute(text("DROP MATERIALIZED VIEW mv_identity_cluster_centroids"))
        conn.execute(
            text(
                "CREATE MATERIALIZED VIEW mv_identity_cluster_centroids AS "
                "SELECT c.id AS cluster_id, c.tenant_id, 0 AS identity_count, "
                "NULL::vector AS centroid, c.updated_at AS refreshed_at "
                "FROM identity_clusters c"
            )
        )
        app_role = str(conn.execute(text("SELECT current_user")).scalar())

    admin = _admin_engine_for_scratch(pg_empty_engine)
    try:
        try:
            with admin.connect() as aconn:
                aconn.execute(text(f'CREATE ROLE "{owner_role}" NOLOGIN'))
                aconn.execute(text(f'ALTER MATERIALIZED VIEW mv_identity_cluster_centroids OWNER TO "{owner_role}"'))
        except Exception as exc:
            pytest.fail(f"scratch owner role setup failed via admin engine: {exc}")

        with pg_empty_engine.begin() as conn:
            with pytest.raises(RuntimeError) as exc_info:
                MIGRATION.heal(conn)
            message = str(exc_info.value)
            operator_sql = f"ALTER MATERIALIZED VIEW mv_identity_cluster_centroids OWNER TO {app_role};"
            assert "mv_identity_cluster_centroids" in message
            assert "-1" in message
            assert owner_role in message
            assert app_role in message
            assert operator_sql in message
            assert "python -m scripts.sync_identity_schema" in message
            assert (
                conn.execute(
                    text(
                        "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=current_schema() "
                        "AND c.relname='mv_identity_cluster_centroids' AND c.relkind='m'"
                    )
                ).scalar()
                == 1
            )
    finally:
        with admin.connect() as aconn:
            aconn.execute(
                text(f'ALTER MATERIALIZED VIEW IF EXISTS mv_identity_cluster_centroids OWNER TO "{app_role}"')
            )
            aconn.execute(text(f'DROP ROLE IF EXISTS "{owner_role}"'))
        admin.dispose()


def test_foreign_owner_scratch_role_setup_does_not_skip_without_createrole() -> None:
    # VLMHEAL-1-REV-A-02: a CREATEROLE denial on the *app* engine must not skip
    # the ownership-refusal branch. Observation that would refute the finding:
    # this test's source uses IDENTITY_PG_ADMIN_URL to create the scratch role
    # and contains no pytest.skip on SQLSTATE 42501.
    src = inspect.getsource(test_heal_refuses_typmod_rebuild_when_matview_has_foreign_owner)
    assert "_admin_engine_for_scratch" in src or "IDENTITY_PG_ADMIN_URL" in src
    assert "pytest.skip" not in src
    assert "_createrole_denied" not in src


def test_heal_does_not_rebuild_matview_when_vector_typmod_matches(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.connect() as conn:
        before_oid = conn.execute(
            text(
                "SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() AND c.relname='mv_identity_cluster_centroids' "
                "AND c.relkind='m'"
            )
        ).scalar()
    assert _centroid_typmod(pg_empty_engine) == MIGRATION.EMBEDDING_DIMENSION

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    with pg_empty_engine.connect() as conn:
        after_oid = conn.execute(
            text(
                "SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() AND c.relname='mv_identity_cluster_centroids' "
                "AND c.relkind='m'"
            )
        ).scalar()
    assert after_oid == before_oid


class _FakeScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value[0] if isinstance(self._value, tuple) else self._value

    def one(self):
        return self._value

    def one_or_none(self):
        return self._value

    def all(self):
        if self._value is None:
            return []
        if isinstance(self._value, list):
            return self._value
        return [self._value]


def _fake_quote_ident(ident: str) -> str:
    if ident.isidentifier() and ident.lower() == ident and not ident.startswith("_"):
        # Postgres quote_ident leaves [a-z_][a-z0-9_]* unquoted; leading
        # underscore is still unquoted. Hyphens/mixed case need quotes.
        return ident
    if ident.replace("_", "").isalnum() and ident == ident.lower():
        return ident
    return '"' + ident.replace('"', '""') + '"'


class _FakeOp:
    """Minimal alembic Operations stand-in for owner-safe ensure_matview branches."""

    def __init__(self, current_user: str = "app_role") -> None:
        self.statements: list[str] = []
        self.current_user = current_user

    def get_bind(self):
        op = self

        class _Bind:
            def execute(self, stmt, params=None):  # noqa: ANN001
                sql = str(stmt).lower()
                if "quote_ident(current_user)" in sql:
                    return _FakeScalarResult((op.current_user, _fake_quote_ident(op.current_user)))
                if "select quote_ident(" in sql:
                    ident = (params or {}).get("ident", op.current_user)
                    return _FakeScalarResult(_fake_quote_ident(str(ident)))
                if "select current_user" in sql:
                    return _FakeScalarResult(op.current_user)
                raise AssertionError(f"unexpected bind SQL: {stmt}")

        return _Bind()

    def execute(self, sql) -> None:  # noqa: ANN001
        self.statements.append(str(sql))


def _issued_drop(op: _FakeOp) -> bool:
    needle = "DROP MATERIALIZED VIEW mv_identity_cluster_centroids"
    return any(needle in sql.replace("\n", " ") for sql in op.statements)


def test_ensure_matview_rebuilds_when_current_role_can_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    op = _FakeOp()
    monkeypatch.setattr(MIGRATION, "_relkind", lambda _op, _name: "m")
    monkeypatch.setattr(MIGRATION, "_matview_centroid_typmod", lambda _op: -1)
    monkeypatch.setattr(MIGRATION, "_matview_owner_and_can_drop", lambda _op: ("app_role", True))
    monkeypatch.setattr(MIGRATION, "_matview_create_privilege_gaps", lambda _op: [])
    monkeypatch.setattr(MIGRATION, "_matview_nonowner_grants", lambda _op: ())

    MIGRATION.ensure_matview(op)

    assert _issued_drop(op)
    assert any("CREATE MATERIALIZED VIEW" in sql for sql in op.statements)


def test_ensure_matview_refuses_rebuild_with_named_owner_and_operator_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_role = "identity_mv_owner_abc123"
    app_role = "context"
    op = _FakeOp(current_user=app_role)
    monkeypatch.setattr(MIGRATION, "_relkind", lambda _op, _name: "m")
    monkeypatch.setattr(MIGRATION, "_matview_centroid_typmod", lambda _op: -1)
    monkeypatch.setattr(MIGRATION, "_matview_owner_and_can_drop", lambda _op: (owner_role, False))

    with pytest.raises(RuntimeError) as exc_info:
        MIGRATION.ensure_matview(op)

    message = str(exc_info.value)
    operator_sql = f"ALTER MATERIALIZED VIEW mv_identity_cluster_centroids OWNER TO {app_role};"
    assert "mv_identity_cluster_centroids" in message
    assert "-1" in message
    assert owner_role in message
    assert app_role in message
    assert operator_sql in message
    assert "python -m scripts.sync_identity_schema" in message
    assert not _issued_drop(op)
    assert not any("CREATE MATERIALIZED VIEW" in sql for sql in op.statements)


def test_ensure_matview_skips_drop_when_vector_typmod_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    op = _FakeOp()

    def _ownership_must_not_run(_op) -> tuple[str, bool]:
        raise AssertionError("ownership check must not run when typmod already matches")

    monkeypatch.setattr(MIGRATION, "_relkind", lambda _op, _name: "m")
    monkeypatch.setattr(MIGRATION, "_matview_centroid_typmod", lambda _op: MIGRATION.EMBEDDING_DIMENSION)
    monkeypatch.setattr(MIGRATION, "_matview_owner_and_can_drop", _ownership_must_not_run)

    MIGRATION.ensure_matview(op)

    assert not _issued_drop(op)
    assert any("CREATE MATERIALIZED VIEW IF NOT EXISTS" in sql for sql in op.statements)


def test_matview_centroid_typmod_probe_requires_pgvector_type() -> None:
    # VLMHEAL-1-INT-01: a non-vector centroid with a matching numeric typmod
    # must not count as healthy. Observation that would refute the finding:
    # _matview_centroid_typmod joins pg_type and filters typname='vector'.
    src = inspect.getsource(MIGRATION._matview_centroid_typmod)
    assert "pg_type" in src
    assert "typname" in src
    assert "vector" in src


def test_operator_sql_quote_idents_hyphenated_role(monkeypatch: pytest.MonkeyPatch) -> None:
    # VLMHEAL-1-REV-A-06: unquoted current_user in the ALTER OWNER remediation
    # is not paste-safe for hyphenated managed-PG roles (rg-006). Observation
    # that would refute the finding: the raised SQL uses quote_ident output.
    app_role = "alt-context-app"
    op = _FakeOp(current_user=app_role)
    monkeypatch.setattr(MIGRATION, "_relkind", lambda _op, _name: "m")
    monkeypatch.setattr(MIGRATION, "_matview_centroid_typmod", lambda _op: -1)
    monkeypatch.setattr(MIGRATION, "_matview_owner_and_can_drop", lambda _op: ("identity_mv_owner", False))

    with pytest.raises(RuntimeError) as exc_info:
        MIGRATION.ensure_matview(op)

    message = str(exc_info.value)
    assert 'OWNER TO "alt-context-app"' in message
    assert "OWNER TO alt-context-app;" not in message
    assert not _issued_drop(op)


def test_matview_owner_probe_names_vanished_relation() -> None:
    # VLMHEAL-1-REV-A-07: a concurrent drop between _relkind and the owner
    # probe must not surface sqlalchemy.exc.NoResultFound. Observation that
    # would refute the finding: the helper raises a named RuntimeError.
    from sqlalchemy.exc import NoResultFound

    class _Op:
        def get_bind(self):
            class _Bind:
                def execute(self, stmt):  # noqa: ANN001
                    class _Res:
                        def one(self):
                            raise NoResultFound()

                        def one_or_none(self):
                            return None

                    return _Res()

            return _Bind()

    with pytest.raises(RuntimeError, match="vanished mid-heal"):
        MIGRATION._matview_owner_and_can_drop(_Op())


def test_ensure_matview_refuses_drop_when_create_privileges_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # VLMHEAL-1-REV-A-03: DROP-capable membership is not enough to CREATE the
    # replacement view. Observation that would refute the finding: missing
    # CREATE/SELECT/EXECUTE privileges are named and no DROP is issued.
    op = _FakeOp()
    monkeypatch.setattr(MIGRATION, "_relkind", lambda _op, _name: "m")
    monkeypatch.setattr(MIGRATION, "_matview_centroid_typmod", lambda _op: -1)
    monkeypatch.setattr(MIGRATION, "_matview_owner_and_can_drop", lambda _op: ("r_owner", True))
    monkeypatch.setattr(
        MIGRATION,
        "_matview_create_privilege_gaps",
        lambda _op: ["CREATE on schema public", "SELECT on identity_clusters"],
    )

    with pytest.raises(RuntimeError) as exc_info:
        MIGRATION.ensure_matview(op)

    message = str(exc_info.value)
    assert "CREATE on schema public" in message
    assert "SELECT on identity_clusters" in message
    assert not _issued_drop(op)


def test_ensure_matview_restores_owner_and_grants_after_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    # VLMHEAL-1-REV-A-04: member-of-owner DROP+CREATE transfers ownership and
    # clears relacl. Observation that would refute the finding: the same
    # transaction reissues GRANT and ALTER OWNER before returning.
    op = _FakeOp()
    monkeypatch.setattr(MIGRATION, "_relkind", lambda _op, _name: "m")
    monkeypatch.setattr(MIGRATION, "_matview_centroid_typmod", lambda _op: -1)
    monkeypatch.setattr(MIGRATION, "_matview_owner_and_can_drop", lambda _op: ("r_owner_x", True))
    monkeypatch.setattr(MIGRATION, "_matview_create_privilege_gaps", lambda _op: [])
    monkeypatch.setattr(
        MIGRATION,
        "_matview_nonowner_grants",
        lambda _op: (("r_reader_x", "SELECT", False),),
    )

    MIGRATION.ensure_matview(op)

    joined = " ".join(op.statements)
    assert "DROP MATERIALIZED VIEW mv_identity_cluster_centroids" in joined
    assert "CREATE MATERIALIZED VIEW" in joined
    assert "GRANT SELECT ON mv_identity_cluster_centroids TO" in joined
    assert "r_reader_x" in joined
    assert "ALTER MATERIALIZED VIEW mv_identity_cluster_centroids OWNER TO" in joined
    assert "r_owner_x" in joined


def test_ensure_table_vector_typmods_refuses_wrong_table_typmod(monkeypatch: pytest.MonkeyPatch) -> None:
    # VLMHEAL-1-REV-A-01: a wrong-typmod table column cannot be drop-rebuilt.
    # Observation that would refute the finding: ensure raises a named
    # operator action naming the table.column and does not DROP the table.
    op = _FakeOp()
    monkeypatch.setattr(MIGRATION, "_relkind", lambda _op, name: "r" if name == "media_identities" else None)
    monkeypatch.setattr(
        MIGRATION,
        "_vector_column_typmod",
        lambda _op, table, _col: -1 if table == "media_identities" else MIGRATION.EMBEDDING_DIMENSION,
    )

    with pytest.raises(RuntimeError) as exc_info:
        MIGRATION.ensure_identity_vector_typmods(op)

    message = str(exc_info.value)
    assert "media_identities.embedding" in message
    assert "operator" in message.lower()
    assert not any("DROP TABLE media_identities" in sql for sql in op.statements)


def test_identity_vector_columns_agree_with_health_ready_probe() -> None:
    # VLMHEAL-1-REV-A-08: heal/verify/health must share the vector-column
    # contract. Observation that would refute the finding: the migration
    # tuple equals recognition.application.health.IDENTITY_VECTOR_COLUMNS.
    from recognition.application.health import IDENTITY_VECTOR_COLUMNS as HEALTH_COLS

    assert MIGRATION.IDENTITY_VECTOR_COLUMNS == HEALTH_COLS


def test_heal_restores_dropped_rls_policy(pg_empty_engine) -> None:
    # BR2-02 drift direction: a tenant table that lost its policy is re-covered.
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.begin() as conn:
        conn.execute(text("DROP POLICY tenant_isolation_export_jobs ON export_jobs"))
        conn.execute(text("ALTER TABLE export_jobs DISABLE ROW LEVEL SECURITY"))
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    state = _rls_state(pg_empty_engine)
    assert state["export_jobs"] == (True, True)
    with pg_empty_engine.connect() as conn:
        has_policy = conn.execute(
            text(
                "SELECT 1 FROM pg_policies WHERE schemaname='public' "
                "AND tablename='export_jobs' AND policyname='tenant_isolation_export_jobs'"
            )
        ).first()
    assert has_policy


def _table_columns(engine, table_name: str) -> set[str]:
    with engine.connect() as conn:
        return {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=:t"
                ),
                {"t": table_name},
            )
        }


def test_heal_restores_dropped_column(pg_empty_engine) -> None:
    # MAINT-TPR-01 / PA-03: an existing table missing an expand-first column is
    # the exact prod drift — `_ensure_table` no-ops on the existing table, so
    # column reconciliation is what re-adds it. NOT NULL-with-server-default
    # (naming_agreement_enabled) is additively re-addable.
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.begin() as conn:
        conn.execute(text("ALTER TABLE tenants DROP COLUMN naming_agreement_enabled"))
    assert "naming_agreement_enabled" not in _table_columns(pg_empty_engine, "tenants")

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    assert "naming_agreement_enabled" in _table_columns(pg_empty_engine, "tenants")


def test_heal_creates_every_orm_declared_column(pg_empty_engine) -> None:
    # MAINT-TPR-BR-05 ratchet: verify_identity_schema derives expected columns
    # from ORM Base.metadata while heal adds them from the migration's
    # ensure_tables literals. If a model column is forgotten in ensure_tables,
    # verify flags a gap heal can never fill (boot crash-loop). Assert the healed
    # DB carries every ORM-declared column for each migration-owned table, so the
    # two sources cannot silently diverge.
    import db.models  # noqa: F401 - populate Base.metadata
    from db.models.base_imports import Base

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    expected = set(MIGRATION.EXPECTED_SCHEMA_TABLES)
    gaps: dict[str, list[str]] = {}
    for name, table in Base.metadata.tables.items():
        if name not in expected:
            continue
        actual = _table_columns(pg_empty_engine, name)
        missing = sorted(col.name for col in table.columns if col.name not in actual)
        if missing:
            gaps[name] = missing

    assert not gaps, f"ORM columns not created by heal (ensure_tables drift): {gaps}"


def test_verifier_detects_dropped_column_then_heal_repairs(pg_empty_engine) -> None:
    # Slice 3 E2E: a dropped column -> verifier exit 1 naming table+column;
    # heal -> verifier OK. Stamp alembic_version so the revision check passes
    # and the column drift is isolated.
    from scripts.verify_identity_schema import EXIT_HEAL_REPAIRABLE, collect_and_validate

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        conn.execute(text("CREATE TABLE alembic_version (version_num varchar(64) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES (:rev)"), {"rev": MIGRATION.revision})

    with pg_empty_engine.connect() as conn:
        assert collect_and_validate(conn)["ok"] is True

    with pg_empty_engine.begin() as conn:
        conn.execute(text("ALTER TABLE tenants DROP COLUMN plan"))

    with pg_empty_engine.connect() as conn:
        report = collect_and_validate(conn)
    assert report["exit_code"] == EXIT_HEAL_REPAIRABLE
    assert "plan" in report["column_gaps"].get("tenants", [])

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.connect() as conn:
        assert collect_and_validate(conn)["ok"] is True


def test_concurrent_sync_entrypoints_serialize_on_advisory_lock(pg_empty_engine) -> None:
    # BR2-10: two concurrent sync_schema() runs against the same empty DB must
    # both succeed (the loser waits on pg_advisory_xact_lock, then no-ops).
    from concurrent.futures import ThreadPoolExecutor

    from scripts.sync_identity_schema import sync_schema

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sync_schema(pg_empty_engine), range(2)))

    assert all(isinstance(r, list) for r in results)
    missing = set(MIGRATION.EXPECTED_SCHEMA_TABLES) - _table_names(pg_empty_engine)
    assert not missing, f"concurrent heal left tables missing: {sorted(missing)}"


def test_verifier_detects_dropped_policy_then_heal_repairs(pg_empty_engine) -> None:
    # Slice 4 E2E: dropped policy -> verifier exit 1 naming the table; heal ->
    # verifier OK. (Revision check passes because heal-only DBs have no
    # alembic_version — stamp it manually to isolate the RLS drift.)
    from scripts.verify_identity_schema import EXIT_HEAL_REPAIRABLE, collect_and_validate

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        conn.execute(text("CREATE TABLE alembic_version (version_num varchar(64) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES (:rev)"), {"rev": MIGRATION.revision})

    with pg_empty_engine.connect() as conn:
        assert collect_and_validate(conn)["ok"] is True

    with pg_empty_engine.begin() as conn:
        conn.execute(text("DROP POLICY tenant_isolation_export_jobs ON export_jobs"))

    with pg_empty_engine.connect() as conn:
        report = collect_and_validate(conn)
    assert report["exit_code"] == EXIT_HEAL_REPAIRABLE
    assert report["policy_gaps"] == ["export_jobs"]

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.connect() as conn:
        assert collect_and_validate(conn)["ok"] is True


def test_adopted_observability_tables_isolate_tenants(pg_empty_engine) -> None:
    # Slice 5: assignment_decisions / clustering_job_reports are migration-owned
    # tenant tables now — tenant B must not read (or write over) tenant A rows,
    # matching the runtime writer path (SET LOCAL app.current_tenant).
    import uuid

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        for t in (tenant_a, tenant_b):
            conn.execute(
                text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
                {"id": t, "url": f"https://{t}.example"},
            )

    def _insert_as(tenant: str) -> None:
        with pg_empty_engine.begin() as conn:
            conn.execute(text(f"SET LOCAL app.current_tenant = '{tenant}'"))
            conn.execute(
                text(
                    "INSERT INTO assignment_decisions "
                    "(id, tenant_id, identity_id, decision, timestamp) "
                    "VALUES (:id, :tenant, 'ident-1', 'accept', now())"
                ),
                {"id": str(uuid.uuid4()), "tenant": tenant},
            )
            conn.execute(
                text(
                    "INSERT INTO clustering_job_reports "
                    "(id, tenant_id, job_id, algorithm, started_at, total_identities, "
                    " accept_count, suggest_count, reject_count, clusters_created, "
                    " success_rate, duration_ms, payload) "
                    "VALUES (:id, :tenant, 'job-1', 'hdbscan', now(), 1, 1, 0, 0, 1, 1.0, 5.0, '{}')"
                ),
                {"id": str(uuid.uuid4()), "tenant": tenant},
            )

    def _counts_as(tenant: str) -> tuple[int, int]:
        with pg_empty_engine.begin() as conn:
            conn.execute(text(f"SET LOCAL app.current_tenant = '{tenant}'"))
            a = conn.execute(text("SELECT count(*) FROM assignment_decisions")).scalar()
            b = conn.execute(text("SELECT count(*) FROM clustering_job_reports")).scalar()
        return a, b

    _insert_as(tenant_a)
    assert _counts_as(tenant_a) == (1, 1)
    assert _counts_as(tenant_b) == (0, 0), "tenant B can read tenant A observability rows"

    # WITH CHECK: writing a row for the OTHER tenant must be rejected.
    import sqlalchemy.exc

    with pytest.raises(sqlalchemy.exc.DBAPIError), pg_empty_engine.begin() as conn:
        conn.execute(text(f"SET LOCAL app.current_tenant = '{tenant_b}'"))
        conn.execute(
            text(
                "INSERT INTO assignment_decisions "
                "(id, tenant_id, identity_id, decision, timestamp) "
                "VALUES (:id, :tenant, 'ident-x', 'accept', now())"
            ),
            {"id": str(uuid.uuid4()), "tenant": tenant_a},
        )


# ---- FL30B-GATE-01: test-role privilege guard (decision logic) ----------
#
# Superusers / BYPASSRLS roles are exempt from RLS even under FORCE. The
# harness must fail (not skip) when IDENTITY_PG_TEST_URL is privileged so a
# remote gate cannot go green while isolation assertions are vacuous.
# These tests exercise the pure decision helper without needing two real roles.


def test_rls_privilege_guard_fires_for_superuser() -> None:
    from recognition.tests.conftest import rls_unenforceable_role_message

    msg = rls_unenforceable_role_message(role="daniel", rolsuper=True, rolbypassrls=False)
    assert msg is not None
    assert "unenforceable" in msg.lower()
    assert "daniel" in msg
    assert "IDENTITY_PG_TEST_URL" in msg
    assert "BYPASSRLS" in msg or "bypassrls" in msg.lower()


def test_rls_privilege_guard_fires_for_bypassrls() -> None:
    from recognition.tests.conftest import rls_unenforceable_role_message

    msg = rls_unenforceable_role_message(role="adminish", rolsuper=False, rolbypassrls=True)
    assert msg is not None
    assert "unenforceable" in msg.lower()
    assert "adminish" in msg
    assert "IDENTITY_PG_TEST_URL" in msg


def test_rls_privilege_guard_silent_for_unprivileged() -> None:
    from recognition.tests.conftest import rls_unenforceable_role_message

    assert rls_unenforceable_role_message(role="context", rolsuper=False, rolbypassrls=False) is None


def test_assert_engine_role_rls_enforceable_fails_on_privileged_row() -> None:
    """Fixture-path helper must pytest.fail (not skip) when the role is privileged."""
    from recognition.tests.conftest import assert_engine_role_rls_enforceable

    class _Result:
        def one(self):
            return ("superuser_test", True, False)

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, stmt):  # noqa: ANN001
            assert "rolsuper" in str(stmt) and "rolbypassrls" in str(stmt)
            assert "current_user" in str(stmt)
            return _Result()

    class _Engine:
        def connect(self):
            return _Conn()

    with pytest.raises(pytest.fail.Exception, match="unenforceable"):
        assert_engine_role_rls_enforceable(_Engine())


def test_assert_engine_role_rls_enforceable_passes_for_unprivileged_row() -> None:
    from recognition.tests.conftest import assert_engine_role_rls_enforceable

    class _Result:
        def one(self):
            return ("context", False, False)

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, stmt):  # noqa: ANN001
            return _Result()

    class _Engine:
        def connect(self):
            return _Conn()

    assert_engine_role_rls_enforceable(_Engine())  # must not raise
