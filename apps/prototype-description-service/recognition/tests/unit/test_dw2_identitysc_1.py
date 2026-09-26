from pathlib import Path


def test_wrong_vector_typmod_pg_fixture_drops_dependent_matview_before_alter() -> None:
    schema_test = Path(__file__).parents[1] / "schema" / "test_identity_schema_heal_pg.py"
    source = schema_test.read_text(encoding="utf-8")
    fixture = source.split("def test_heal_refuses_wrong_table_vector_typmod", 1)[1].split("\ndef ", 1)[0]

    heal_index = fixture.index("MIGRATION.heal(conn)")
    drop_index = fixture.index("DROP MATERIALIZED VIEW mv_identity_cluster_centroids")
    alter_index = fixture.index("ALTER TABLE media_identities ALTER COLUMN embedding TYPE vector")

    assert heal_index < drop_index < alter_index
