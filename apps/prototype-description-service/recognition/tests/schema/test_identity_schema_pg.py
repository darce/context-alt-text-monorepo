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


def test_matview_builds_weighted_centroid_with_vector_operators(pg_migrated_engine) -> None:
    dimension = MIGRATION.EMBEDDING_DIMENSION
    tenant_id = uuid.uuid4()
    cluster_id = uuid.uuid4()
    media_id = 74821
    identity_ids = [uuid.uuid4(), uuid.uuid4()]
    weights = [0.25, 0.75]

    with pg_migrated_engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
            conn.execute(
                text("INSERT INTO tenants (id, site_url) VALUES (:tenant_id, :site_url)"),
                {"tenant_id": tenant_id, "site_url": f"https://centroid-{tenant_id}.test"},
            )
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
                        "media_id": media_id,
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
                        "cluster_id": cluster_id,
                        "identity_id": identity_id,
                    },
                )

            conn.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
            centroid_text = conn.execute(
                text("SELECT centroid::text FROM mv_identity_cluster_centroids WHERE cluster_id=:cluster_id"),
                {"cluster_id": cluster_id},
            ).scalar_one()
            centroid = [float(value) for value in centroid_text.strip("[]").split(",")]
        finally:
            transaction.rollback()

    magnitude = math.hypot(*weights)
    expected = [weights[0] / magnitude, weights[1] / magnitude, *([0.0] * (dimension - 2))]
    assert centroid == pytest.approx(expected, abs=1e-5)
