"""C76 ABI-13/14: injected sessions, no DB, pool, settings or network.

RES-02: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/engineering.md#res-02
Census result column aliases are fixture seams, not an additional frozen ABI.
"""
from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def capture():
    path = ROOT / "recognition/application/face_acceptance_catalog.py"
    assert path.is_file(), "CAUSAL_RED: missing face_acceptance_catalog.py (ABI-13)"
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("recognition.application.face_acceptance_catalog", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    fn = getattr(module, "capture_serving_catalog", None)
    assert callable(fn), "CAUSAL_RED: missing capture_serving_catalog (ABI-13)"
    return fn


def plain(value):
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if hasattr(value, "model_dump"):
        return plain(value.model_dump())
    return value


class Record(dict):
    __getattr__ = dict.__getitem__


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        assert len(self.rows) == 1
        return self.rows[0]

    def scalar(self):
        return 0

    scalar_one = scalar


class ServingSession:
    """Recording SQL double. Never creates a connection or engine."""
    def __init__(self, failure=None, columns=4, width=512):
        self.failure = failure
        self.calls = []
        self.rollbacks = 0
        self.columns = columns
        self.width = width

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement).lower()
        self.calls.append(sql)
        if self.failure == "timeout":
            await asyncio.sleep(1)
            raise AssertionError("capture did not bound the query")
        if self.failure == "permission":
            raise PermissionError("REJECTED_EXCEPTION_SENTINEL")
        if "pg_attribute" in sql:
            return Result([Record(schema_name="recognition", table_name=f"table_{i}",
                                  column_name="embedding", dimensions=self.width,
                                  type_name="vector" if i != 3 else "vector_domain",
                                  relkind="r" if i != 3 else "m")
                           for i in range(self.columns)])
        if "current_database" in sql:
            return Result([Record(database_name="synthetic_store", current_database="synthetic_store",
                                  current_user="serving_role", session_user="serving_role",
                                  database_oid=123, server_address="synthetic-instance",
                                  server_version="synthetic", extension_version="synthetic")])
        return Result([Record(row_count=0, model_ids=[], dimensions=self.width)])

    async def rollback(self):
        self.rollbacks += 1


class ForbiddenObservabilitySession:
    async def execute(self, *args, **kwargs):
        raise AssertionError("observability session used in place of serving session")


def args(deadline=None, max_rows=64):
    return dict(role="worker", process_instance_id="worker-process", pool_identity="serving-pool",
                tenant_context_id="synthetic-tenant",
                instance_binding=Record(instance_id="synthetic-instance", storage_id="synthetic-storage"),
                deadline_monotonic=deadline if deadline is not None else time.monotonic() + 2,
                max_catalog_rows=max_rows, max_model_ids=16)


def run(fn, session, **kwargs):
    return plain(asyncio.run(fn(session, **args(**kwargs))))


def test_empty_store_positive_capture_uses_injected_serving_session():
    fn = capture()
    session = ServingSession()
    result = run(fn, session)
    assert session.calls
    assert result["role"] == "worker"
    assert result["process_instance_id"] == "worker-process"
    assert "serving-pool" in repr(result)
    assert "synthetic-tenant" in repr(result)
    # Empty store does not attest enrollment, preprocessing or execution.
    assert "execution_receipt" not in result
    assert "loaded_weight_hashes" not in result


def test_census_discovers_fourth_column_domain_and_materialized_view():
    fn = capture()
    session = ServingSession()
    result = run(fn, session)
    catalog_sql = " ".join(session.calls)
    assert all(name in catalog_sql for name in ("pg_attribute", "pg_class", "pg_namespace", "pg_type"))
    assert "table_3" in repr(result), "three named health columns cannot be the full census"


def test_wrong_vector_width_is_observed_without_backfilling_expected_width():
    fn = capture()
    result = run(fn, ServingSession(width=128))
    assert "128" in repr(result)
    assert "512" not in repr(result), "expected Aura width must not replace observed width"


@pytest.mark.parametrize("failure", ["permission", "timeout"])
def test_query_failure_is_sanitized_incomplete_and_rolls_back(failure):
    fn = capture()
    session = ServingSession(failure=failure)
    result = run(fn, session, deadline=time.monotonic() + 0.02)
    assert session.rollbacks >= 1
    assert "REJECTED_EXCEPTION_SENTINEL" not in repr(result)
    assert "incomplete" in repr(result) or "failed" in repr(result)


def test_expired_deadline_does_not_query():
    fn = capture()
    session = ServingSession()
    try:
        result = run(fn, session, deadline=time.monotonic() - 1)
    except TimeoutError:
        pass
    else:
        assert "incomplete" in repr(result) or "failed" in repr(result)
    assert session.calls == []


def test_truncated_census_is_not_complete():
    fn = capture()
    result = run(fn, ServingSession(columns=5), max_rows=2)
    assert "incomplete" in repr(result)


def test_unknown_store_binding_cannot_be_complete():
    fn = capture()
    options = args()
    options["instance_binding"] = None
    result = plain(asyncio.run(fn(ServingSession(), **options)))
    assert "incomplete" in repr(result)


def test_recording_fixture_returns_four_independent_columns_without_io():
    session = ServingSession()
    result = asyncio.run(session.execute("select from pg_attribute"))
    assert len(result.mappings().all()) == 4
    assert result.all()[3]["type_name"] == "vector_domain"
    assert session.rollbacks == 0


def test_same_database_names_on_distinct_instances_keep_distinct_binding():
    fn = capture()
    records = []
    for instance in ["instance-one", "instance-two"]:
        options = args()
        options["instance_binding"] = Record(instance_id=instance, storage_id=instance + "-storage")
        records.append(plain(asyncio.run(fn(ServingSession(), **options))))
    assert records[0] != records[1]
    assert "instance-one" in repr(records[0])
    assert "instance-two" in repr(records[1])


def test_catalog_module_cannot_reconstruct_or_substitute_serving_connection():
    import ast
    capture()
    node = ast.parse((ROOT / "recognition/application/face_acceptance_catalog.py").read_text())
    calls = {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
             for n in ast.walk(node) if isinstance(n, ast.Call)
             and isinstance(n.func, (ast.Name, ast.Attribute))}
    assert not calls & {"create_engine", "create_async_engine", "get_observability_session", "get_settings"}
