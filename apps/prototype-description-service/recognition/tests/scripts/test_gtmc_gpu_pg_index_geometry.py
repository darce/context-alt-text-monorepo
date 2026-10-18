"""Offline centroid catalog geometry regressions; no live PostgreSQL claim."""
import json
import importlib.util
from pathlib import Path

import pytest
spec = importlib.util.spec_from_file_location("d5_findings_fakes", Path(__file__).with_name("test_gtmc_gpu_pg_findings.py"))
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)

COL = F.COL
CENTROID = "mv_identity_cluster_centroids"
FIELD = f"catalog.indexes.{CENTROID}.centroid"
_deny_actual_connect = F._deny_actual_connect


def cluster_with(expression, predicate="(centroid IS NOT NULL)", column=None):
    cluster = F.FakeCluster()
    cluster.indexes[-1] = (CENTROID, column, "ivfflat", "vector_cosine_ops", True, predicate, expression)
    return cluster


def index_rows(result):
    receipt = json.loads(result["raw_artifacts"][f"raw/pg/{F.PRIMARY}.json"])
    return next(q["rows"] for q in receipt["queries"] if q["query_id"] == "indexes")


def index_issues(result, bucket):
    return [i for i in result["section"][bucket] if i["field"] == FIELD]


def test_c82_d5_expression_index_key_survives_catalog_projection():
    cluster = cluster_with(f"(centroid)::vector({F.DIMENSION})")
    session = F.FakeSession(cluster, F.PRIMARY)
    rows = session.query(COL.INDEX_SQL, {})
    assert tuple(cluster.indexes[-1]) in rows
    # A modeled inner join must lose the attnum=0 key, proving the projection oracle.
    inner = COL.INDEX_SQL.replace("LEFT JOIN pg_attribute", "JOIN pg_attribute")
    assert not [r for r in session.query(inner, {}) if r[0] == CENTROID]


@pytest.mark.parametrize("expression", ["centroid::vector(768)", "(centroid)::vector(768)", "((centroid)::vector(768))"])
def test_c82_d5_native_centroid_expression_partial_index_is_accepted(expression):
    cluster = cluster_with(expression)
    result = F._run(cluster)
    assert not index_issues(result, "contradictions")
    assert not index_issues(result, "missing_reasons")
    assert list(cluster.indexes[-1]) in index_rows(result)


def test_c82_d5_native_centroid_partial_predicate_is_accepted_if_cast_is_simplified():
    result = F._run(cluster_with(None, column="centroid"))
    assert not index_issues(result, "contradictions")
    assert not index_issues(result, "missing_reasons")


@pytest.mark.parametrize("expression", ["centroid + centroid", "lower(centroid)", "other::vector(768)"])
def test_unknown_expression_stays_missing(expression):
    result = F._run(cluster_with(expression))
    assert index_issues(result, "missing_reasons")
    assert not index_issues(result, "contradictions")
    assert any(r[6] == expression for r in index_rows(result))


@pytest.mark.parametrize("key,value", [(2, "hnsw"), (3, "vector_l2_ops"), (4, False),
                                         (5, "centroid IS NULL"), (6, "centroid::vector(767)")])
def test_known_wrong_centroid_geometry_contradicts(key, value):
    cluster = cluster_with(f"centroid::vector({F.DIMENSION})")
    row = list(cluster.indexes[-1])
    row[key] = value
    cluster.indexes[-1] = tuple(row)
    result = F._run(cluster)
    assert index_issues(result, "contradictions")
    assert list(cluster.indexes[-1]) in index_rows(result)


def test_invalid_index_projection_is_observed():
    cluster = F.FakeCluster()
    row = list(cluster.indexes[0])
    row[4] = False
    cluster.indexes[0] = tuple(row)
    result = F._run(cluster)
    assert any(i["code"] == "vector_index_identity_mismatch" and i["field"] ==
               "catalog.indexes.media_identities.embedding" for i in result["section"]["contradictions"])
    assert index_rows(result)[0][4] is False


def test_unknown_centroid_predicate_stays_missing():
    result = F._run(cluster_with(f"centroid::vector({F.DIMENSION})", predicate="custom_guard(centroid)"))
    assert index_issues(result, "missing_reasons")
    assert not index_issues(result, "contradictions")
