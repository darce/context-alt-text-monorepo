"""Stale centroid indexes are repaired without rebuilding a healthy matview."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.verify_identity_schema import identity_schema as migration


@pytest.mark.parametrize("kind,stale", [("m", True), ("m", False), (None, True)])
def test_ensure_matview_repairs_only_existing_stale_index(monkeypatch, kind, stale):
    statements = []
    op = SimpleNamespace(execute=lambda sql: statements.append(str(sql).strip()))
    monkeypatch.setattr(migration, "_relkind", lambda *args: kind)
    monkeypatch.setattr(migration, "_matview_centroid_typmod", lambda _: migration.EMBEDDING_DIMENSION)
    monkeypatch.setattr(migration, "_matview_create_privilege_gaps", lambda _: ())
    stale_index = Mock(return_value=stale)
    monkeypatch.setattr(migration, "_matview_stale_cluster_id_index", stale_index, raising=False)

    migration.ensure_matview(op)

    drop = "DROP INDEX IF EXISTS mv_cluster_centroids_cluster_id"
    create_position = next(
        i
        for i, sql in enumerate(statements)
        if sql.startswith("CREATE UNIQUE INDEX IF NOT EXISTS mv_cluster_centroids_cluster_id")
    )
    if kind == "m" and stale:
        assert drop in statements
        assert statements.index(drop) < create_position
    else:
        assert drop not in statements
    if kind is None:
        stale_index.assert_not_called()
