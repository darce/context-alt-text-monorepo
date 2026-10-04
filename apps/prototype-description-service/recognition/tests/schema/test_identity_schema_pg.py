"""E15-34 Slice 2: Postgres-backed baseline for the identity schema.

Applies the real migration to an empty scratch database and asserts the
load-bearing invariants the sqlite substrate cannot see: RLS enabled+forced on
every ``TENANT_TABLES`` member, the matview's ``relkind='m'``, and the full
``EXPECTED_SCHEMA_TABLES`` contract. Skips cleanly when Postgres is
unreachable (fixture in ``recognition/tests/conftest.py``).
"""

from __future__ import annotations

import importlib
import math
import uuid

import pytest
from sqlalchemy import text

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")

pytestmark = pytest.mark.pg


@pytest.mark.parametrize("stale_marker", [None, "centroid-definition:obsolete"])
def test_matview_definition_rebuild_preserves_owner_and_grants(pg_migrated_engine, stale_marker) -> None:
    with pg_migrated_engine.connect() as conn:
        transaction = conn.begin()
        try:
            MIGRATION.repair_centroids_matview(conn)
            conn.execute(text("GRANT SELECT ON mv_identity_cluster_centroids TO PUBLIC"))
            state_query = text(
                "SELECT c.oid, c.relowner, c.relacl::text, obj_description(c.oid, 'pg_class') "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'mv_identity_cluster_centroids'"
            )
            before = conn.execute(state_query).one()
            marker_sql = "NULL" if stale_marker is None else "'centroid-definition:obsolete'"
            conn.execute(text(f"COMMENT ON MATERIALIZED VIEW mv_identity_cluster_centroids IS {marker_sql}"))

            MIGRATION.repair_centroids_matview(conn)
            rebuilt = conn.execute(state_query).one()
            assert rebuilt.oid != before.oid, "a stale definition with the right typmod must be rebuilt"
            assert rebuilt.relowner == before.relowner
            assert rebuilt.relacl == before.relacl
            assert rebuilt[3] == MIGRATION.CENTROID_DEFINITION_VERSION

            MIGRATION.repair_centroids_matview(conn)
            assert conn.execute(state_query).one() == rebuilt, "the current definition must retain its OID"
        finally:
            transaction.rollback()


def test_upgrade_on_empty_db_creates_expected_tables(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        names = {row[0] for row in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))}
    missing = set(MIGRATION.EXPECTED_SCHEMA_TABLES) - names
    assert not missing, f"missing after upgrade(): {sorted(missing)}"


def test_upgrade_enables_and_forces_rls_on_tenant_tables(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname = ANY(:tables)"
            ),
            {"tables": list(MIGRATION.TENANT_TABLES)},
        ).fetchall()
    state = {name: (enabled, forced) for name, enabled, forced in rows}
    missing = set(MIGRATION.TENANT_TABLES) - set(state)
    assert not missing, f"tenant tables absent: {sorted(missing)}"
    weak = {name: flags for name, flags in state.items() if flags != (True, True)}
    assert not weak, f"tenant tables without enabled+forced RLS: {weak}"


def test_matview_has_materialized_relkind(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        relkind = conn.execute(
            text(
                "SELECT c.relkind FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname='mv_identity_cluster_centroids'"
            )
        ).scalar()
    assert relkind == "m", f"mv_identity_cluster_centroids relkind={relkind!r}, expected 'm'"


def test_matview_centroid_carries_vector_typmod(pg_migrated_engine) -> None:
    # /health and /ready read pg_attribute.atttypmod for this column and fail
    # closed on -1; a CASE with an untyped NULL arm silently produced exactly that.
    with pg_migrated_engine.connect() as conn:
        typmod = conn.execute(
            text(
                "SELECT a.atttypmod FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname='mv_identity_cluster_centroids' "
                "AND a.attname='centroid'"
            )
        ).scalar()
    assert typmod == MIGRATION.EMBEDDING_DIMENSION, (
        f"centroid typmod={typmod!r}, expected vector({MIGRATION.EMBEDDING_DIMENSION})"
    )


def test_pg_test_role_is_nonsuperuser_without_bypassrls(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        role, rolsuper, rolbypassrls, database = conn.execute(
            text(
                "SELECT current_user, r.rolsuper, r.rolbypassrls, current_database() "
                "FROM pg_roles r WHERE r.rolname = current_user"
            )
        ).one()
    assert rolsuper is False, f"role {role!r} on {database!r} is superuser; RLS evidence would be vacuous"
    assert rolbypassrls is False, f"role {role!r} on {database!r} has BYPASSRLS; RLS evidence would be vacuous"


def test_checkout_and_usage_are_tenant_tables_global_state_is_nontenant_singleton(
    pg_migrated_engine,
) -> None:
    tenant_tables = ("billing_checkout_attempt", "usage_reservation")
    with pg_migrated_engine.connect() as conn:
        tenant_rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname = ANY(:tables)"
            ),
            {"tables": list(tenant_tables)},
        ).fetchall()
        global_flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname='usage_admission_global_state'"
            )
        ).one()
        global_policies = conn.execute(
            text(
                "SELECT policyname FROM pg_policies "
                "WHERE schemaname='public' AND tablename='usage_admission_global_state'"
            )
        ).fetchall()
        singleton = conn.execute(text("SELECT id, COUNT(*) OVER () FROM usage_admission_global_state")).one()
        tenant_id_col = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='usage_admission_global_state' "
                "AND column_name='tenant_id'"
            )
        ).scalar()
    state = {name: (enabled, forced) for name, enabled, forced in tenant_rows}
    assert set(state) == set(tenant_tables)
    assert all(flags == (True, True) for flags in state.values()), state
    assert global_flags == (False, False)
    assert global_policies == []
    assert tenant_id_col is None
    assert singleton[0] == "global"
    assert singleton[1] == 1


def test_checkout_provider_key_unique_and_invitation_nullability(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        unique_cols = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT a.attname "
                    "FROM pg_constraint c "
                    "JOIN pg_class t ON c.conrelid = t.oid "
                    "JOIN pg_namespace n ON t.relnamespace = n.oid "
                    "JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true "
                    "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
                    "WHERE n.nspname = current_schema() "
                    "AND t.relname = 'billing_checkout_attempt' "
                    "AND c.conname = 'uq_billing_checkout_attempt_provider_key' "
                    "ORDER BY k.ord"
                )
            ).fetchall()
        ]
        invitation_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'portal_tenant_invitation' AND column_name = 'tenant_id'"
            )
        ).scalar()
        invitation_fk = conn.execute(
            text(
                "SELECT 1 FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "JOIN pg_namespace n ON t.relnamespace = n.oid "
                "WHERE n.nspname = current_schema() AND t.relname = 'portal_tenant_invitation' "
                "AND c.contype = 'f' AND pg_get_constraintdef(c.oid) LIKE '%tenant_id%'"
            )
        ).scalar()
    assert unique_cols == ["provider", "environment", "seller_account", "idempotency_key"]
    assert invitation_nullable == "YES"
    assert invitation_fk == 1


def test_billing_known_item_lease_is_operator_scope_and_namespace_inbox_unique(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname='billing_known_item_lease'"
            )
        ).one()
        inbox_unique = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT a.attname "
                    "FROM pg_constraint c "
                    "JOIN pg_class t ON c.conrelid = t.oid "
                    "JOIN pg_namespace n ON t.relnamespace = n.oid "
                    "JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true "
                    "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
                    "WHERE n.nspname = current_schema() "
                    "AND t.relname = 'billing_webhook_inbox' "
                    "AND c.conname = 'uq_billing_webhook_inbox_provider_namespace_event' "
                    "ORDER BY k.ord"
                )
            ).fetchall()
        ]
    assert flags == (True, True)
    assert inbox_unique == ["provider", "environment", "seller_account", "provider_event_id"]


@pytest.mark.parametrize(
    "weights,separate_clusters",
    [([0.25, 0.75], False), ([1e-39, 0.75], True)],
    ids=["weighted-media", "tiny-positive-single-member"],
)
def test_matview_builds_weighted_centroid_with_vector_operators(
    pg_migrated_engine, weights, separate_clusters
) -> None:
    dimension = MIGRATION.EMBEDDING_DIMENSION
    tenant_id = uuid.uuid4()
    cluster_ids = [uuid.uuid4()]
    cluster_ids.append(uuid.uuid4() if separate_clusters else cluster_ids[0])
    media_id = 74821
    identity_ids = [uuid.uuid4(), uuid.uuid4()]

    with pg_migrated_engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
            conn.execute(
                text("INSERT INTO tenants (id, site_url) VALUES (:tenant_id, :site_url)"),
                {"tenant_id": tenant_id, "site_url": f"https://centroid-{tenant_id}.test"},
            )
            for cluster_id in dict.fromkeys(cluster_ids):
                conn.execute(
                    text("INSERT INTO identity_clusters (id, tenant_id) VALUES (:cluster_id, :tenant_id)"),
                    {"cluster_id": cluster_id, "tenant_id": tenant_id},
                )

            insert_identity = text(
                f"""INSERT INTO media_identities (
                    id, tenant_id, media_id, media_url, bbox_x, bbox_y, bbox_width, bbox_height,
                    confidence, embedding, embedding_model, quality_score
                ) VALUES (
                    :identity_id, :tenant_id, :media_id, :media_url, :bbox_x, 0, 10, 10,
                    1.0, CAST(:embedding AS vector({dimension})), 'centroid-test', :quality_score
                )"""
            )
            for axis, (identity_id, weight) in enumerate(zip(identity_ids, weights, strict=True)):
                coordinates = ["0"] * dimension
                coordinates[axis] = "1"
                conn.execute(
                    insert_identity,
                    {
                        "identity_id": identity_id,
                        "tenant_id": tenant_id,
                        "media_id": media_id + axis if separate_clusters else media_id,
                        "media_url": "https://centroid.test/image",
                        "bbox_x": axis * 10,
                        "embedding": f"[{','.join(coordinates)}]",
                        "quality_score": weight,
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO identity_members "
                        "(id, tenant_id, cluster_id, identity_id, similarity) "
                        "VALUES (:id, :tenant_id, :cluster_id, :identity_id, 1.0)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "cluster_id": cluster_ids[axis],
                        "identity_id": identity_id,
                    },
                )

            # Exercise creation with populated data as well as refresh: either used
            # to fail for a positive weight whose reciprocal exceeds real's range.
            conn.execute(text("DROP MATERIALIZED VIEW mv_identity_cluster_centroids"))
            MIGRATION.repair_centroids_matview(conn)
            magnitude = math.hypot(*weights)
            for refresh in (False, True):
                if refresh:
                    conn.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
                for axis, cluster_id in enumerate(dict.fromkeys(cluster_ids)):
                    centroid_text = conn.execute(
                        text("SELECT centroid::text FROM mv_identity_cluster_centroids WHERE cluster_id=:cluster_id"),
                        {"cluster_id": cluster_id},
                    ).scalar_one()
                    centroid = [float(value) for value in centroid_text.strip("[]").split(",")]
                    if separate_clusters:
                        expected = [0.0] * dimension
                        expected[axis] = 1.0
                    else:
                        expected = [weights[0] / magnitude, weights[1] / magnitude, *([0.0] * (dimension - 2))]
                    assert centroid == pytest.approx(expected, abs=1e-5)
        finally:
            transaction.rollback()
