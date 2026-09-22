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

from recognition.tests.schema.test_identity_schema_heal_fakeop import (
    _FakeOp,
    _issued_drop,
)

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")


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


@pytest.mark.pg
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


@pytest.mark.pg
def test_heal_twice_is_a_noop(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    before = _table_names(pg_empty_engine)
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)  # must not raise or emit duplicate-object errors
    assert _table_names(pg_empty_engine) == before


@pytest.mark.pg
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


@pytest.mark.pg
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


def _matview_relacl(engine):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT c.relacl FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() "
                "AND c.relname = 'mv_identity_cluster_centroids' AND c.relkind = 'm'"
            )
        ).scalar()


def _matview_nonowner_grantees(engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT CASE WHEN acl.grantee = 0 THEN 'public' "
                "ELSE pg_get_userbyid(acl.grantee) END "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "CROSS JOIN LATERAL aclexplode(c.relacl) AS acl "
                "WHERE n.nspname = current_schema() "
                "AND c.relname = 'mv_identity_cluster_centroids' "
                "AND c.relkind = 'm' "
                "AND acl.grantee IS NOT NULL "
                "AND acl.grantee IS DISTINCT FROM c.relowner"
            )
        ).fetchall()
    return {str(row[0]) for row in rows}


@pytest.mark.pg
def test_heal_rebuilds_typmod_less_matview_with_null_relacl(pg_empty_engine) -> None:
    # VLMHEAL-1-PG-ACL-01: default ACL (relacl NULL) must not trip aclexplode.
    # This test uses pg_empty_engine; it must pytest.fail (never skip) when the
    # fixture connected. Do not add pytest.skip based on IDENTITY_PG_URL.
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
    if _matview_relacl(pg_empty_engine) is not None:
        pytest.fail("typmod-less matview has explicit relacl right after CREATE")
    assert _centroid_typmod(pg_empty_engine) == -1

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    assert _centroid_typmod(pg_empty_engine) == MIGRATION.EMBEDDING_DIMENSION
    assert _matview_nonowner_grantees(pg_empty_engine) == set()
    assert _matview_relacl(pg_empty_engine) is None


def _insert_describe_run(conn, *, tenant_id: str, run_id: str, idempotency_key: str | None) -> None:
    conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
    conn.execute(
        text(
            "INSERT INTO image_description_runs "
            "(id, tenant_id, media_ids, total_items, idempotency_key) "
            "VALUES (:id, :tenant, CAST(:media AS jsonb), 1, :key)"
        ),
        {"id": run_id, "tenant": tenant_id, "media": "[]", "key": idempotency_key},
    )


def _unique_constraint_exists(engine, name: str) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT 1 FROM pg_constraint c "
                    "JOIN pg_class t ON c.conrelid = t.oid "
                    "JOIN pg_namespace n ON t.relnamespace = n.oid "
                    "WHERE n.nspname = current_schema() "
                    "AND t.relname = 'image_description_runs' AND c.conname = :name"
                ),
                {"name": name},
            ).scalar()
            is not None
        )


@pytest.mark.pg
def test_heal_raises_named_action_when_unique_constraint_has_duplicate_rows(pg_empty_engine) -> None:
    constraint = "uq_image_description_runs_idempotency_key"
    tenant_id = str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE image_description_runs DROP CONSTRAINT "{constraint}"'))
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        conn.execute(
            text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
            {"id": tenant_id, "url": f"https://{tenant_id}.example"},
        )
        _insert_describe_run(conn, tenant_id=tenant_id, run_id=str(uuid.uuid4()), idempotency_key="same-token")
        _insert_describe_run(conn, tenant_id=tenant_id, run_id=str(uuid.uuid4()), idempotency_key="same-token")

    with pytest.raises(RuntimeError) as exc_info, pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    message = str(exc_info.value)
    assert constraint in message
    assert "23505" in message
    assert "image_description_runs" in message
    assert "operator" in message.lower()
    assert not _unique_constraint_exists(pg_empty_engine, constraint)


@pytest.mark.pg
def test_heal_adds_unique_constraint_when_rows_are_distinct_or_null(pg_empty_engine) -> None:
    constraint = "uq_image_description_runs_idempotency_key"
    tenant_id = str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE image_description_runs DROP CONSTRAINT "{constraint}"'))
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        conn.execute(
            text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
            {"id": tenant_id, "url": f"https://{tenant_id}.example"},
        )
        _insert_describe_run(conn, tenant_id=tenant_id, run_id=str(uuid.uuid4()), idempotency_key=None)
        _insert_describe_run(conn, tenant_id=tenant_id, run_id=str(uuid.uuid4()), idempotency_key=None)
        _insert_describe_run(conn, tenant_id=tenant_id, run_id=str(uuid.uuid4()), idempotency_key="distinct-a")
        _insert_describe_run(conn, tenant_id=tenant_id, run_id=str(uuid.uuid4()), idempotency_key="distinct-b")
    assert not _unique_constraint_exists(pg_empty_engine, constraint)

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    assert _unique_constraint_exists(pg_empty_engine, constraint)


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


@pytest.mark.pg
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


@pytest.mark.pg
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
    monkeypatch.setattr(MIGRATION, "_matview_stale_cluster_id_index", lambda _op: False)

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
    assert "re-embed" in message.lower()
    assert "null" in message.lower()
    assert f"USING embedding::vector({MIGRATION.EMBEDDING_DIMENSION})" not in message
    assert not any("DROP TABLE media_identities" in sql for sql in op.statements)


def test_identity_vector_columns_agree_with_health_ready_probe() -> None:
    # VLMHEAL-1-REV-A-08: heal/verify/health must share the vector-column
    # contract. Observation that would refute the finding: the migration
    # tuple equals recognition.application.health.IDENTITY_VECTOR_COLUMNS.
    from recognition.application.health import IDENTITY_VECTOR_COLUMNS as HEALTH_COLS

    assert MIGRATION.IDENTITY_VECTOR_COLUMNS == HEALTH_COLS


@pytest.mark.pg
def test_heal_refuses_wrong_table_vector_typmod(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        # Matview FROM identity_clusters/media_identities blocks ALTER TYPE; drop first.
        conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS mv_identity_cluster_centroids"))
        conn.execute(text("ALTER TABLE media_identities ALTER COLUMN embedding TYPE vector"))
    with pytest.raises(RuntimeError) as exc_info, pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    message = str(exc_info.value)
    assert "media_identities.embedding" in message
    assert "re-embed" in message.lower()
    assert "null" in message.lower()
    assert f"USING embedding::vector({MIGRATION.EMBEDDING_DIMENSION})" not in message


@pytest.mark.pg
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


@pytest.mark.pg
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


@pytest.mark.pg
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


@pytest.mark.pg
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


@pytest.mark.pg
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


@pytest.mark.pg
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


@pytest.mark.pg
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


def _unique_constraint_columns(engine, table_name: str, constraint_name: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT a.attname "
                "FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "JOIN pg_namespace n ON t.relnamespace = n.oid "
                "JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true "
                "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
                "WHERE n.nspname = current_schema() "
                "AND t.relname = :table AND c.conname = :name "
                "ORDER BY k.ord"
            ),
            {"table": table_name, "name": constraint_name},
        ).fetchall()
    return [str(row[0]) for row in rows]


def _column_is_nullable(engine, table_name: str, column_name: str) -> bool:
    with engine.connect() as conn:
        value = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"
            ),
            {"t": table_name, "c": column_name},
        ).scalar()
    return value == "YES"


def _constraint_names(engine, table_name: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.conname FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "JOIN pg_namespace n ON t.relnamespace = n.oid "
                "WHERE n.nspname = current_schema() AND t.relname = :t"
            ),
            {"t": table_name},
        ).fetchall()
    return {str(row[0]) for row in rows}


def _strip_usage_reservation_identity(conn, *, tenant_id: str, reservation_id: str, status: str = "committed") -> None:
    conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
    conn.execute(
        text("ALTER TABLE usage_reservation DROP CONSTRAINT IF EXISTS uq_usage_reservation_tenant_operation_id")
    )
    for check_name in (
        "ck_usage_reservation_queue_bytes_nonnegative",
        "ck_usage_reservation_operation_id_present",
        "ck_usage_reservation_request_fingerprint_present",
        "ck_usage_reservation_fence_token_present",
    ):
        conn.execute(text(f'ALTER TABLE usage_reservation DROP CONSTRAINT IF EXISTS "{check_name}"'))
    conn.execute(
        text(
            "ALTER TABLE usage_reservation "
            "DROP COLUMN operation_id, "
            "DROP COLUMN request_fingerprint, "
            "DROP COLUMN job_id, "
            "DROP COLUMN fence_token, "
            "DROP COLUMN queue_bytes"
        )
    )
    conn.execute(text("DROP TABLE IF EXISTS usage_admission_global_state"))
    conn.execute(
        text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
        {"id": tenant_id, "url": f"https://{tenant_id}.example"},
    )
    conn.execute(
        text(
            "INSERT INTO usage_reservation "
            "(id, tenant_id, period_start, idempotency_key, status, cost_units) "
            "VALUES (:id, :tenant, now(), 'pre-g1-key', :status, 4)"
        ),
        {"id": reservation_id, "tenant": tenant_id, "status": status},
    )


def _set_writers_drained(conn) -> None:
    conn.execute(text("SELECT set_config('app.usage_schema_writers_drained', 'true', true)"))


@pytest.mark.pg
def test_heal_upgrades_existing_usage_reservation_rows_and_seeds_global_state(pg_empty_engine) -> None:
    # Existing-DB proof: a pre-G1 usage_reservation row must gain identity
    # columns, backfill, NOT NULL, unique/check constraints, and the nontenant
    # global singleton — not just a greenfield create_all. [DATA-03][RES-05]
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    tenant_id = str(uuid.uuid4())
    reservation_id = str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        _strip_usage_reservation_identity(conn, tenant_id=tenant_id, reservation_id=reservation_id)

    assert "operation_id" not in _table_columns(pg_empty_engine, "usage_reservation")
    assert "usage_admission_global_state" not in _table_names(pg_empty_engine)

    with pg_empty_engine.begin() as conn:
        _set_writers_drained(conn)
        MIGRATION.heal(conn)

    assert {
        "operation_id",
        "request_fingerprint",
        "fence_token",
        "job_id",
        "queue_bytes",
    } <= _table_columns(pg_empty_engine, "usage_reservation")
    for column_name in ("operation_id", "request_fingerprint", "fence_token", "queue_bytes"):
        assert _column_is_nullable(pg_empty_engine, "usage_reservation", column_name) is False

    with pg_empty_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        row = conn.execute(
            text(
                "SELECT operation_id, request_fingerprint, fence_token, queue_bytes, status "
                "FROM usage_reservation WHERE id = :id"
            ),
            {"id": reservation_id},
        ).one()
        global_row = conn.execute(
            text(
                "SELECT id, daily_cost_units, inflight_units, queue_depth, queue_bytes, "
                "stop_requested, fence_epoch, COUNT(*) OVER () "
                "FROM usage_admission_global_state"
            )
        ).one()
        global_flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'usage_admission_global_state'"
            )
        ).one()

    assert row[0] == "pre-g1-key"
    assert row[1] == "pre-g1-key"
    assert row[2] == f"1:legacy:{reservation_id}"
    assert row[3] == 0
    assert row[4] == "committed"
    assert global_row[0] == "global"
    assert global_row[1] == 4
    assert global_row[2] == 0
    assert global_row[3] == 0
    assert global_row[4] == 0
    assert global_row[5] is False
    assert global_row[6] == 1
    assert global_row[7] == 1
    assert global_flags == (False, False)
    names = _constraint_names(pg_empty_engine, "usage_reservation")
    assert "uq_usage_reservation_tenant_operation_id" in names
    assert "ck_usage_reservation_operation_id_present" in names
    assert "ck_usage_reservation_request_fingerprint_present" in names
    assert "ck_usage_reservation_fence_token_present" in names
    assert "ck_usage_reservation_queue_bytes_nonnegative" in names
    assert _unique_constraint_columns(
        pg_empty_engine, "usage_reservation", "uq_usage_reservation_tenant_operation_id"
    ) == ["tenant_id", "operation_id"]


@pytest.mark.pg
def test_heal_refuses_existing_usage_identity_contract_until_writers_drained(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    tenant_id = str(uuid.uuid4())
    reservation_id = str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        _strip_usage_reservation_identity(conn, tenant_id=tenant_id, reservation_id=reservation_id)

    with (
        pytest.raises(RuntimeError, match="app.usage_schema_writers_drained") as exc_info,
        pg_empty_engine.begin() as conn,
    ):
        MIGRATION.heal(conn)
    message = str(exc_info.value)
    assert "docs/runbooks/app1-usage-schema-upgrade.md" in message
    assert "ACX_USAGE_SCHEMA_WRITERS_DRAINED" in message
    assert "operation_id" not in _table_columns(pg_empty_engine, "usage_reservation")
    assert "usage_admission_global_state" not in _table_names(pg_empty_engine)


@pytest.mark.pg
def test_sync_schema_backfills_usage_reservation_under_forced_rls_without_role_bypass(
    pg_empty_engine, monkeypatch
) -> None:
    """NOSUPERUSER/NOBYPASSRLS app role heals existing rows via sync_schema."""
    from scripts.sync_identity_schema import sync_schema

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        role, rolsuper, rolbypassrls = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
    assert rolsuper is False, role
    assert rolbypassrls is False, role

    tenant_id = str(uuid.uuid4())
    reservation_id = str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        _strip_usage_reservation_identity(conn, tenant_id=tenant_id, reservation_id=reservation_id)

    monkeypatch.setenv("ACX_USAGE_SCHEMA_WRITERS_DRAINED", "1")
    sync_schema(pg_empty_engine)

    with pg_empty_engine.begin() as conn:
        leftover_bypass = conn.execute(text("SELECT current_setting('app.bypass_rls', true)")).scalar()
        role_after, rolsuper_after, rolbypass_after = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
    assert str(leftover_bypass or "").lower() not in {"true", "1", "on"}
    assert rolsuper_after is False
    assert rolbypass_after is False
    assert role_after == role

    with pg_empty_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        row = conn.execute(
            text("SELECT operation_id, request_fingerprint, fence_token FROM usage_reservation WHERE id = :id"),
            {"id": reservation_id},
        ).one()
    assert row == ("pre-g1-key", "pre-g1-key", f"1:legacy:{reservation_id}")
    for column_name in ("operation_id", "request_fingerprint", "fence_token"):
        assert _column_is_nullable(pg_empty_engine, "usage_reservation", column_name) is False


@pytest.mark.pg
def test_heal_isolates_checkout_and_usage_reservations_across_tenants(pg_empty_engine) -> None:
    import sqlalchemy.exc

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        for tenant in (tenant_a, tenant_b):
            conn.execute(
                text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
                {"id": tenant, "url": f"https://{tenant}.example"},
            )

    with pg_empty_engine.begin() as conn:
        conn.execute(text(f"SET LOCAL app.current_tenant = '{tenant_a}'"))
        conn.execute(
            text(
                "INSERT INTO usage_reservation "
                "(id, tenant_id, period_start, idempotency_key, operation_id, "
                " request_fingerprint, fence_token, status, cost_units) "
                "VALUES (:id, :tenant, now(), 'op-a', 'op-a', 'fp-a', 'fence-a', 'reserved', 1)"
            ),
            {"id": str(uuid.uuid4()), "tenant": tenant_a},
        )
        conn.execute(
            text(
                "INSERT INTO billing_checkout_attempt "
                "(id, tenant_id, provider, environment, seller_account, plan_code, "
                " idempotency_key, request_fingerprint) "
                "VALUES (:id, :tenant, 'fake', 'sandbox', 'org_sandbox', 'pro', 'key-a', 'fp-a')"
            ),
            {"id": str(uuid.uuid4()), "tenant": tenant_a},
        )

    with pg_empty_engine.begin() as conn:
        conn.execute(text(f"SET LOCAL app.current_tenant = '{tenant_b}'"))
        usage_count = conn.execute(text("SELECT count(*) FROM usage_reservation")).scalar()
        checkout_count = conn.execute(text("SELECT count(*) FROM billing_checkout_attempt")).scalar()
    assert usage_count == 0
    assert checkout_count == 0

    with pytest.raises(sqlalchemy.exc.DBAPIError), pg_empty_engine.begin() as conn:
        conn.execute(text(f"SET LOCAL app.current_tenant = '{tenant_b}'"))
        conn.execute(
            text(
                "INSERT INTO usage_reservation "
                "(id, tenant_id, period_start, idempotency_key, operation_id, "
                " request_fingerprint, fence_token, status, cost_units) "
                "VALUES (:id, :tenant, now(), 'op-x', 'op-x', 'fp-x', 'fence-x', 'reserved', 1)"
            ),
            {"id": str(uuid.uuid4()), "tenant": tenant_a},
        )

    with pytest.raises(sqlalchemy.exc.DBAPIError), pg_empty_engine.begin() as conn:
        conn.execute(text(f"SET LOCAL app.current_tenant = '{tenant_b}'"))
        conn.execute(
            text(
                "INSERT INTO billing_checkout_attempt "
                "(id, tenant_id, provider, environment, seller_account, plan_code, "
                " idempotency_key, request_fingerprint) "
                "VALUES (:id, :tenant, 'fake', 'sandbox', 'org_sandbox', 'pro', 'key-x', 'fp-x')"
            ),
            {"id": str(uuid.uuid4()), "tenant": tenant_a},
        )


@pytest.mark.pg
def test_heal_reconciles_global_counters_from_current_period_chargeable_and_reserved(
    pg_empty_engine,
) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    tenant_id = str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        conn.execute(
            text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
            {"id": tenant_id, "url": f"https://{tenant_id}.example"},
        )
        conn.execute(
            text(
                "UPDATE usage_admission_global_state SET "
                "daily_cost_limit = 42, stop_requested = true, config_version = 'keep-me', "
                "fence_epoch = 3 WHERE id = 'global'"
            )
        )
        period_start, period_end = conn.execute(
            text("SELECT period_start, period_end FROM usage_admission_global_state WHERE id = 'global'")
        ).one()
        conn.execute(
            text(
                "INSERT INTO usage_reservation "
                "(id, tenant_id, period_start, idempotency_key, operation_id, "
                " request_fingerprint, fence_token, queue_bytes, status, cost_units) "
                "VALUES "
                "(:r1, :tenant, :ps, 'k1', 'op-1', 'fp-1', '3:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 7, 'reserved', 3), "
                "(:r2, :tenant, :ps, 'k2', 'op-2', 'fp-2', '3:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 0, 'committed', 5), "
                "(:r3, :tenant, :old, 'k3', 'op-3', 'fp-3', '3:cccccccc-cccc-cccc-cccc-cccccccccccc', 99, 'reserved', 8)"
            ),
            {
                "r1": str(uuid.uuid4()),
                "r2": str(uuid.uuid4()),
                "r3": str(uuid.uuid4()),
                "tenant": tenant_id,
                "ps": period_start,
                "old": period_start - (period_end - period_start),
            },
        )

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    with pg_empty_engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT daily_cost_units, inflight_units, queue_depth, queue_bytes, "
                "daily_cost_limit, stop_requested, config_version, fence_epoch "
                "FROM usage_admission_global_state WHERE id = 'global'"
            )
        ).one()
    assert row == (8, 3, 1, 7, 42, True, "keep-me", 3)


@pytest.mark.pg
def test_heal_failclosed_on_reserved_rows_with_unknown_queue_bytes(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    tenant_id = str(uuid.uuid4())
    reservation_id = str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        _strip_usage_reservation_identity(conn, tenant_id=tenant_id, reservation_id=reservation_id, status="reserved")

    with pytest.raises(RuntimeError, match="unknown queue_bytes") as exc_info, pg_empty_engine.begin() as conn:
        _set_writers_drained(conn)
        MIGRATION.heal(conn)
    assert "docs/runbooks/app1-usage-schema-upgrade.md" in str(exc_info.value)


@pytest.mark.pg
def test_heal_replaces_tenant_scoped_checkout_provider_key_unique(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE billing_checkout_attempt DROP CONSTRAINT uq_billing_checkout_attempt_provider_key")
        )
        conn.execute(
            text(
                "ALTER TABLE billing_checkout_attempt "
                "ADD CONSTRAINT uq_billing_checkout_attempt_provider_key "
                "UNIQUE (tenant_id, provider, environment, seller_account, idempotency_key)"
            )
        )
    assert _unique_constraint_columns(
        pg_empty_engine, "billing_checkout_attempt", "uq_billing_checkout_attempt_provider_key"
    ) == ["tenant_id", "provider", "environment", "seller_account", "idempotency_key"]

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    assert _unique_constraint_columns(
        pg_empty_engine, "billing_checkout_attempt", "uq_billing_checkout_attempt_provider_key"
    ) == ["provider", "environment", "seller_account", "idempotency_key"]


@pytest.mark.pg
def test_heal_refuses_duplicate_seller_wide_checkout_keys_without_deleting_rows(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE billing_checkout_attempt DROP CONSTRAINT uq_billing_checkout_attempt_provider_key")
        )
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        for tenant in (tenant_a, tenant_b):
            conn.execute(
                text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
                {"id": tenant, "url": f"https://{tenant}.example"},
            )
            conn.execute(
                text(
                    "INSERT INTO billing_checkout_attempt "
                    "(id, tenant_id, provider, environment, seller_account, plan_code, "
                    " idempotency_key, request_fingerprint) "
                    "VALUES (:id, :tenant, 'fake', 'sandbox', 'org_sandbox', 'pro', 'shared-key', 'fp')"
                ),
                {"id": str(uuid.uuid4()), "tenant": tenant},
            )

    with pytest.raises(RuntimeError) as exc_info, pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    message = str(exc_info.value)
    assert "uq_billing_checkout_attempt_provider_key" in message
    assert "23505" in message
    assert "operator" in message.lower()
    assert "billing_checkout_attempt" in message
    with pg_empty_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        count = conn.execute(text("SELECT count(*) FROM billing_checkout_attempt")).scalar()
    assert count == 2
    assert "uq_billing_checkout_attempt_provider_key" not in _constraint_names(
        pg_empty_engine, "billing_checkout_attempt"
    )


@pytest.mark.pg
def test_heal_invitation_allows_pending_null_tenant_and_preserves_bound_rows(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    tenant_id = str(uuid.uuid4())
    bound_id = str(uuid.uuid4())
    pending_id = str(uuid.uuid4())
    with pg_empty_engine.begin() as conn:
        conn.execute(text("ALTER TABLE portal_tenant_invitation ALTER COLUMN tenant_id SET NOT NULL"))
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        conn.execute(
            text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
            {"id": tenant_id, "url": f"https://{tenant_id}.example"},
        )
        conn.execute(
            text(
                "INSERT INTO portal_tenant_invitation "
                "(id, tenant_id, invited_email, token_hash, expires_at) "
                "VALUES (:id, :tenant, 'bound@example.test', 'hash-bound', now() + interval '1 day')"
            ),
            {"id": bound_id, "tenant": tenant_id},
        )

    assert _column_is_nullable(pg_empty_engine, "portal_tenant_invitation", "tenant_id") is False

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    assert _column_is_nullable(pg_empty_engine, "portal_tenant_invitation", "tenant_id") is True
    with pg_empty_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        conn.execute(
            text(
                "INSERT INTO portal_tenant_invitation "
                "(id, tenant_id, invited_email, token_hash, expires_at) "
                "VALUES (:id, NULL, 'pending@example.test', 'hash-pending', now() + interval '1 day')"
            ),
            {"id": pending_id},
        )
        rows = conn.execute(
            text("SELECT id, tenant_id IS NULL FROM portal_tenant_invitation ORDER BY invited_email")
        ).fetchall()
        fk = conn.execute(
            text(
                "SELECT 1 FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "JOIN pg_namespace n ON t.relnamespace = n.oid "
                "WHERE n.nspname = current_schema() AND t.relname = 'portal_tenant_invitation' "
                "AND c.contype = 'f' AND pg_get_constraintdef(c.oid) LIKE '%tenant_id%'"
            )
        ).scalar()
    assert {(str(row[0]), bool(row[1])) for row in rows} == {(bound_id, False), (pending_id, True)}
    assert fk == 1


@pytest.mark.pg
def test_heal_preserves_epoch_prefixed_fence_and_expands_unprefixed_uuid(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    tenant_id = str(uuid.uuid4())
    reserved_id = str(uuid.uuid4())
    modern_id = str(uuid.uuid4())
    prefixed_id = str(uuid.uuid4())
    modern_token = str(uuid.uuid4())
    prefixed = "8:dddddddd-dddd-dddd-dddd-dddddddddddd"
    with pg_empty_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        conn.execute(
            text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
            {"id": tenant_id, "url": f"https://{tenant_id}.example"},
        )
        conn.execute(
            text(
                "INSERT INTO usage_reservation "
                "(id, tenant_id, period_start, idempotency_key, operation_id, "
                " request_fingerprint, fence_token, queue_bytes, status, cost_units) "
                "VALUES "
                "(:legacy, :tenant, now(), 'legacy-key', 'legacy-key', 'legacy-key', :legacy_text, 0, 'committed', 1), "
                "(:modern, :tenant, now(), 'modern-key', 'modern-op', 'modern-fp', :modern_token, 0, 'committed', 1), "
                "(:prefixed_id, :tenant, now(), 'pref-key', 'pref-op', 'pref-fp', :prefixed_token, 0, 'committed', 1)"
            ),
            {
                "legacy": reserved_id,
                "legacy_text": reserved_id,
                "modern": modern_id,
                "modern_token": modern_token,
                "prefixed_id": prefixed_id,
                "prefixed_token": prefixed,
                "tenant": tenant_id,
            },
        )
        conn.execute(
            text(
                "ALTER TABLE usage_reservation ALTER COLUMN operation_id DROP NOT NULL, "
                "ALTER COLUMN request_fingerprint DROP NOT NULL, "
                "ALTER COLUMN fence_token DROP NOT NULL"
            )
        )

    with pg_empty_engine.begin() as conn:
        _set_writers_drained(conn)
        MIGRATION.heal(conn)

    with pg_empty_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        tokens = {
            str(row[0]): row[1]
            for row in conn.execute(text("SELECT id, fence_token FROM usage_reservation")).fetchall()
        }
    assert tokens[reserved_id] == f"1:legacy:{reserved_id}"
    assert tokens[modern_id] == f"1:{modern_token}"
    assert tokens[prefixed_id] == prefixed


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
