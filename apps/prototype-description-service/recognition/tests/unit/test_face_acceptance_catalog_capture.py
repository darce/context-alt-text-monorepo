"""C76 ABI-13/14: injected sessions, no DB, pool, settings or network.

RES-02: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/engineering.md#res-02
Census result column aliases are fixture seams, not an additional frozen ABI.
"""
from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolated_import_state(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    for name in ("shared", "shared.source_identity", "shared.face_role_snapshot",
                 "recognition.application.face_acceptance_catalog"):
        # Register absent keys too, so transitive imports are removed on teardown.
        monkeypatch.setitem(sys.modules, name, None)
        monkeypatch.delitem(sys.modules, name)


def capture():
    path = ROOT / "recognition/application/face_acceptance_catalog.py"
    assert path.is_file(), "CAUSAL_RED: missing face_acceptance_catalog.py (ABI-13)"
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
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


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


class CatalogExpression:
    """Small SQL expression interpreter over inert pg_catalog rows; no database."""
    def __init__(self, sql, values, params):
        self.tokens = re.findall(r"'(?:''|[^'])*'|:[\w]+|<>|!=|>=|<=|[\w.]+|[^\s]", sql)
        self.position = 0
        self.values = values
        self.params = params

    def take(self):
        token = self.tokens[self.position]
        self.position += 1
        return token

    def accept(self, token):
        if self.position < len(self.tokens) and self.tokens[self.position] == token:
            self.position += 1
            return True
        return False

    def expression(self, minimum=0):
        left = self.atom()
        precedences = {'or': 1, 'and': 2, '=': 3, '<>': 3, '!=': 3,
                       '>': 3, '<': 3, '>=': 3, '<=': 3, 'in': 3, 'not': 3}
        while self.position < len(self.tokens):
            operator = self.tokens[self.position]
            precedence = precedences.get(operator, -1)
            if precedence < minimum:
                break
            self.take()
            if operator == 'not':
                assert self.take() == 'in', 'unsupported catalog SQL expression'
                right = self.expression(precedence + 1)
                left = left not in right
            else:
                right = self.expression(precedence + 1)
                if operator == 'and':
                    left = bool(left) and bool(right)
                elif operator == 'or':
                    left = bool(left) or bool(right)
                elif operator == 'in':
                    left = left in right
                elif operator in {'=', '<>', '!='}:
                    equal = left in right if isinstance(right, list) else left == right
                    left = equal if operator == '=' else not equal
                elif left is None or right is None:
                    left = False
                else:
                    left = {'>': lambda: left > right, '<': lambda: left < right,
                            '>=': lambda: left >= right, '<=': lambda: left <= right}[operator]()
        return left

    def atom(self):
        token = self.take()
        if token == 'not':
            return not self.expression(3)
        if token in {'(', '['}:
            closing = ')' if token == '(' else ']'
            items = [self.expression()]
            while self.accept(','):
                items.append(self.expression())
            assert self.accept(closing), 'unbalanced catalog expression'
            return items if len(items) > 1 or closing == ']' else items[0]
        if token == 'array':
            return self.atom()
        if token.startswith("'"):
            return token[1:-1].replace("''", "'")
        if token.startswith(':'):
            return self.params[token[1:]]
        if token.isdigit():
            return int(token)
        if token in {'true', 'false', 'null'}:
            return {'true': True, 'false': False, 'null': None}[token]
        if self.accept('('):
            arguments = [self.expression()]
            while self.accept(','):
                arguments.append(self.expression())
            assert self.accept(')'), 'unbalanced catalog function'
            if token == 'any':
                return arguments[0]
            if token == 'coalesce':
                return next((value for value in arguments if value is not None), None)
            if token == 'nullif':
                return None if arguments[0] == arguments[1] else arguments[0]
            raise AssertionError('unsupported catalog expression function: ' + token)
        if '.' in token:
            alias, field = token.split('.', 1)
            return self.values.get(alias, {}).get(field)
        matches = [row[token] for row in self.values.values() if token in row]
        assert len(matches) <= 1, 'ambiguous catalog field: ' + token
        return matches[0] if matches else None


def catalog_rows(sql, params, columns, width):
    expected = [Record(schema_name='recognition', table_name=f'table_{i}',
                       column_name='embedding', dimensions=width,
                       type_name='vector_domain' if i == 3 else 'vector',
                       relkind='m' if i == 3 else 'p' if i == 2 else 'r')
                for i in range(columns)]
    if sql.strip() == 'select from pg_attribute':
        return expected
    relations = expected + [Record(schema_name='recognition', table_name='index_decoy',
        column_name='embedding', dimensions=width, type_name='vector', relkind='i'),
        Record(schema_name='recognition', table_name='view_decoy', column_name='embedding',
               dimensions=width, type_name='vector', relkind='v'),
        Record(schema_name='recognition', table_name='text_decoy', column_name='title',
               dimensions=None, type_name='text', relkind='r')]
    tables = {
        'pg_namespace': [dict(oid=11, nspname='recognition')],
        'pg_class': [dict(oid=i + 1, relnamespace=11, relname=row['table_name'], relkind=row['relkind'])
                     for i, row in enumerate(relations)],
        'pg_attribute': [dict(attrelid=i + 1, attname=row['column_name'], attnum=1,
                              attisdropped=False, atttypmod=row['dimensions'],
                              atttypid=101 if row['type_name'] == 'vector_domain' else
                                       102 if row['type_name'] == 'text' else 100)
                         for i, row in enumerate(relations)],
        'pg_type': [dict(oid=100, typname='vector', typbasetype=0, typtypmod=-1),
                    dict(oid=101, typname='vector_domain', typbasetype=100, typtypmod=width),
                    dict(oid=102, typname='text', typbasetype=0, typtypmod=-1)],
    }
    pattern = (r'\b(from|(?:left\s+(?:outer\s+)?)?join)\s+(?:pg_catalog\.)?'
               r'(pg_attribute|pg_class|pg_namespace|pg_type)\s+(?:as\s+)?(\w+)')
    joins = list(re.finditer(pattern, sql))
    assert joins, 'catalog SQL must select catalog relations'
    environments = [{}]
    tail_start = len(sql)
    where_match = re.search(r'\bwhere\b', sql)
    if where_match:
        tail_start = where_match.start()
    for i, match in enumerate(joins):
        end = joins[i + 1].start() if i + 1 < len(joins) else tail_start
        clause = sql[match.end():end].strip()
        on = re.match(r'on\s+(.+)', clause, re.S)
        candidates = []
        for environment in environments:
            matches = []
            for row in tables[match[2]]:
                candidate = dict(environment, **{match[3]: row})
                if not on or CatalogExpression(on[1], candidate, params).expression():
                    matches.append(candidate)
            candidates.extend(matches)
            if not matches and match[1].startswith('left'):
                candidates.append(dict(environment, **{match[3]: {}}))
        environments = candidates
    if where_match:
        where = re.split(r'\b(?:order\s+by|limit|group\s+by)\b', sql[where_match.end():])[0]
        environments = [environment for environment in environments
                        if CatalogExpression(where, environment, params).expression()]
    limit_match = re.search(r'\blimit\s+(:\w+|\d+)', sql)
    if limit_match:
        limit = limit_match[1]
        environments = environments[:int(params[limit[1:]] if limit.startswith(':') else limit)]
    rows = []
    for environment in environments:
        attribute = next((row for row in environment.values() if 'attrelid' in row), None)
        assert attribute is not None, 'catalog result has no attribute source'
        rows.append(relations[attribute['attrelid'] - 1].copy())
    return rows


class ServingSession:
    """Recording SQL double. Never creates a connection or engine."""
    def __init__(self, failure=None, columns=4, width=512):
        self.failure = failure
        self.calls = []
        self.rollbacks = 0
        self.columns = columns
        self.width = width
        self.query_started = False
        self.query_completed = False
        self.query_cancelled = False
        self.never_ready = asyncio.Event()

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement).lower()
        self.calls.append(sql)
        if self.failure == "timeout":
            self.query_started = True
            try:
                await self.never_ready.wait()
                self.query_completed = True
            except asyncio.CancelledError:
                self.query_cancelled = True
                raise
        if self.failure == "permission":
            from sqlalchemy.exc import DBAPIError

            class InsufficientPrivilege(Exception):
                sqlstate = "42501"
                pgcode = "42501"

            raise DBAPIError("synthetic statement", {}, InsufficientPrivilege("REJECTED_EXCEPTION_SENTINEL"))
        if "pg_attribute" in sql:
            params = dict(statement.compile().params) if hasattr(statement, 'compile') else {}
            if args and isinstance(args[0], dict):
                params.update(args[0])
            params.update(kwargs.get('params', {}))
            return Result(catalog_rows(sql, params, self.columns, self.width))
        if "current_database" in sql:
            return Result([Record(database_name="synthetic_store", current_database="synthetic_store",
                                  current_user="serving_role", session_user="serving_role",
                                  database_oid=123, server_address="synthetic-instance",
                                  server_version="synthetic", extension_version="synthetic")])
        return Result([Record(row_count=0, model_ids=[], dimensions=self.width)])

    async def rollback(self):
        self.rollbacks += 1


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
    columns = result["columns"]
    assert {column["table_name"] for column in columns} == {f"table_{i}" for i in range(4)}
    assert "table_3" in repr(result), "three named health columns cannot be the full census"


def test_wrong_vector_width_is_observed_without_backfilling_expected_width():
    fn = capture()
    result = run(fn, ServingSession(width=128))
    columns = result["columns"]
    assert len(columns) == 4
    assert all(column["dimensions"] == 128 for column in columns), "expected Aura width must not replace observed width"


@pytest.mark.parametrize("deadline_offset", [0.01, 0.04])
@pytest.mark.parametrize("failure", ["permission", "timeout"])
def test_query_failure_is_sanitized_incomplete_and_rolls_back(failure, monkeypatch, deadline_offset):
    fn = capture()
    session = ServingSession(failure=failure)
    async def bounded_capture():
        loop = asyncio.get_running_loop()
        deadline = loop.time() + deadline_offset
        scheduled = []
        budgets = []
        call_at = loop.call_at
        wait_for = asyncio.wait_for
        wait = asyncio.wait

        async def recording_wait_for(awaitable, timeout):
            if not session.query_cancelled:
                budgets.append(timeout)
            return await wait_for(awaitable, timeout)

        async def recording_wait(awaitables, *, timeout=None, return_when=asyncio.ALL_COMPLETED):
            if not session.query_cancelled:
                budgets.append(timeout)
            return await wait(awaitables, timeout=timeout, return_when=return_when)

        def recording_call_at(when, callback, *callback_args, **callback_kwargs):
            if not session.query_cancelled:
                scheduled.append(when)
            return call_at(when, callback, *callback_args, **callback_kwargs)

        async def observed_capture():
            with monkeypatch.context() as patch:
                patch.setattr(loop, 'call_at', recording_call_at)
                patch.setattr(asyncio, 'wait_for', recording_wait_for)
                patch.setattr(asyncio, 'wait', recording_wait)
                result = await fn(session, **args(deadline=deadline))
                if failure == 'timeout':
                    assert session.query_started
                    assert not session.query_completed
                    assert session.query_cancelled, 'producer abandoned the in-flight query'
                    assert scheduled, 'query had no producer timeout'
                    if budgets:
                        assert all(budget is not None and 0 < budget <= deadline_offset for budget in budgets), 'query timeout ignored the supplied deadline'
                    else:
                        assert max(scheduled) <= deadline + 0.001, 'query timeout ignored the supplied deadline'
                return plain(result)

        try:
            return await asyncio.wait_for(observed_capture(), timeout=0.5)
        except TimeoutError:
            pytest.fail('producer did not finish within its catalog deadline')

    result = asyncio.run(bounded_capture())
    if failure == "timeout":
        assert session.query_started
        assert not session.query_completed
        assert session.query_cancelled
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


def assert_offline_provider_imports(source, package):
    import ast

    node = ast.parse(source)
    imports = set()
    aliases = {}
    for entry in ast.walk(node):
        if isinstance(entry, ast.Import):
            for alias in entry.names:
                imports.add(alias.name)
                aliases[alias.asname or alias.name.split('.')[0]] = (
                    alias.name if alias.asname else alias.name.split('.')[0])
        elif isinstance(entry, ast.ImportFrom):
            module = importlib.util.resolve_name(
                '.' * entry.level + (entry.module or ''), package) if entry.level else entry.module
            if module:
                imports.add(module)
                for alias in entry.names:
                    name = module + '.' + alias.name
                    imports.add(name)
                    aliases[alias.asname or alias.name] = name

    def qualified(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return qualified(node.value) + '.' + node.attr
        return ''

    for entry in ast.walk(node):
        if isinstance(entry, ast.Attribute):
            imports.add(qualified(entry))
    calls = set()
    for entry in ast.walk(node):
        if isinstance(entry, ast.Call):
            name = qualified(entry.func)
            calls.add(name.rsplit('.', 1)[-1])
            imports.add(name)
            if name in {'importlib.import_module', '__import__'} and entry.args:
                target = entry.args[0]
                if isinstance(target, ast.Constant) and isinstance(target.value, str):
                    imports.add(importlib.util.resolve_name(target.value, package)
                                if target.value.startswith('.') else target.value)
    forbidden = (
        'onnxruntime', 'cv2', 'recognition.infrastructure.face_pipeline',
        'recognition.infrastructure.embeddings', 'recognition.infrastructure.embeddings.runtime_factory',
        'recognition.application.settings', 'recognition.config',
        'recognition.interface_adapters.http.deps.session', 'shared.secrets',
        'db', 'api', 'requests', 'httpx', 'urllib', 'socket', 'asyncpg', 'psycopg',
        'sqlalchemy.create_engine', 'sqlalchemy.engine.create_engine',
        'sqlalchemy.engine.create.create_engine', 'sqlalchemy.engine_from_config',
        'sqlalchemy.engine.engine_from_config', 'sqlalchemy.engine.create.engine_from_config',
        'sqlalchemy.ext.asyncio.create_async_engine',
        'sqlalchemy.ext.asyncio.engine.create_async_engine',
        'sqlalchemy.ext.asyncio.async_engine_from_config',
    )
    assert not {name for name in imports
                if any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden)}
    assert not calls & {'get_shared_face_pipeline_runtime', 'build_embedding_runtime',
                        'InferenceSession', 'get_observability_session', 'get_settings',
                        'create_engine', 'create_async_engine', 'engine_from_config',
                        'async_engine_from_config'}


def test_catalog_module_cannot_reconstruct_or_substitute_serving_connection():
    path = ROOT / "recognition/application/face_acceptance_catalog.py"
    assert path.is_file(), "CAUSAL_RED: missing recognition/application/face_acceptance_catalog.py (offline provider guard)"
    assert_offline_provider_imports(path.read_text(), "recognition.application")
    capture()


def test_record_double_supports_attribute_protocol_and_copy():
    import copy
    row = Record(nested=Record(value=1))
    assert not hasattr(row, "missing")
    assert getattr(row, "missing", None) is None
    with pytest.raises(AttributeError):
        row.missing
    assert copy.deepcopy(row) == row


@pytest.mark.parametrize("source", ['import recognition.config as forbidden',
 'from recognition.config import get_settings as forbidden',
 'import recognition.interface_adapters.http.deps.session as forbidden',
 'from recognition.interface_adapters.http.deps.session import '
 'get_observability_session as forbidden',
 'from sqlalchemy import create_engine as forbidden',
 'from sqlalchemy.ext.asyncio import create_async_engine as forbidden',
 'from sqlalchemy import engine_from_config as forbidden',
 'import sqlalchemy as sa\nfactory = sa.create_engine\nfactory()',
 'import sqlalchemy.ext.asyncio as sa\nfactory = sa.create_async_engine\nfactory()',
 'from ..config import get_settings as forbidden'])

def test_provider_guard_detects_aliases_and_relative_imports(source):
    with pytest.raises(AssertionError):
        assert_offline_provider_imports(source, 'recognition.application')


@pytest.mark.parametrize("max_rows", [2, 8])
def test_census_limit_is_bound_to_requested_cap_plus_one(max_rows):
    """GTMC-C80A-G2T-F05: a fixed SQL limit can hide a larger catalog."""
    class LimitSession(ServingSession):
        census = None

        async def execute(self, statement, *positional, **keywords):
            sql = str(statement).lower()
            if "pg_class" in sql:
                params = dict(statement.compile().params)
                if positional:
                    params.update(positional[0])
                params.update(keywords.get("params", {}))
                self.census = sql, params
            return await super().execute(statement, *positional, **keywords)

    session = LimitSession(columns=9)
    result = run(capture(), session, max_rows=max_rows)
    assert session.census is not None, "producer did not execute a census"
    sql, params = session.census
    limit = re.search(r"\blimit\s+(:\w+|\d+)", sql)
    assert limit and limit[1].startswith(":"), "census LIMIT must be a bound cap"
    assert params[limit[1][1:]] == max_rows + 1, "census LIMIT must request cap + 1"
    # Reject literal name restrictions while permitting bound SQL expressions.
    assert not re.search(
        r"\b(?:\w+\.)?(?:relname|table_name|attname)\s*"
        r"(?:(?:=|<>|!=)\s*'|(?:not\s+)?in\s*\([^)]*'|"
        r"=\s*any\s*\(\s*array\s*\[)", sql), "census restricts literal names"
    assert len(result["columns"]) == max_rows
    assert result["status"] == "incomplete"
    assert result["reason_code"] == "catalog_truncated"


@pytest.mark.parametrize("alternative", ["relkind_not_in", "domain_coalesce", "relkind_param"])
def test_census_accepts_equivalent_sql_predicates(alternative, monkeypatch):
    """GTMC-C80A-G2T-F05: spelling controls for the inert SQL evaluator."""
    fn = capture()
    module = sys.modules[fn.__module__]
    sql = module._CENSUS_SQL
    if alternative == "relkind_not_in":
        sql = sql.replace("c.relkind IN ('r', 'p', 'm')",
                          "c.relkind NOT IN ('i', 'S', 't', 'v', 'c', 'f', 'I')")
    elif alternative == "domain_coalesce":
        sql = sql.replace("t.typbasetype = b.oid",
                          "b.oid = coalesce(nullif(t.typbasetype, 0), t.oid)")
    else:
        sql = sql.replace("c.relkind IN ('r', 'p', 'm')", "c.relkind = ANY(:kinds)")
    monkeypatch.setattr(module, "_CENSUS_SQL", sql)

    class AlternativeSession(ServingSession):
        async def execute(self, statement, *positional, **keywords):
            if alternative == "relkind_param" and "pg_class" in str(statement):
                params = dict(positional[0] if positional else keywords.get("params", {}))
                params["kinds"] = ["r", "p", "m"]
                return await super().execute(statement, params)
            return await super().execute(statement, *positional, **keywords)

    result = run(fn, AlternativeSession())
    assert result["status"] == "complete"
    assert {column["table_name"] for column in result["columns"]} == {
        f"table_{i}" for i in range(4)}
