"""Bounded catalog observations from an injected serving transaction."""
from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import text


_IDENTITY_SQL = """
SELECT current_database() AS database_name, current_user AS current_user,
       session_user AS session_user,
       (SELECT oid FROM pg_catalog.pg_database
        WHERE datname = current_database()) AS database_oid,
       inet_server_addr()::text AS server_address,
       current_setting('server_version') AS server_version,
       (SELECT extversion FROM pg_catalog.pg_extension
        WHERE extname = 'vector') AS extension_version
"""

_CENSUS_SQL = """
SELECT n.nspname AS schema_name, c.relname AS table_name,
       a.attname AS column_name, t.typname AS type_name, c.relkind AS relkind,
       coalesce(nullif(a.atttypmod, -1), nullif(t.typtypmod, -1)) AS dimensions
FROM pg_catalog.pg_attribute AS a
JOIN pg_catalog.pg_class AS c ON a.attrelid = c.oid
JOIN pg_catalog.pg_namespace AS n ON c.relnamespace = n.oid
JOIN pg_catalog.pg_type AS t ON a.atttypid = t.oid
LEFT JOIN pg_catalog.pg_type AS b ON t.typbasetype = b.oid
WHERE n.nspname IN ('recognition', 'public')
  AND c.relkind IN ('r', 'p', 'm')
  AND a.attnum > 0 AND NOT a.attisdropped
  AND (t.typname = 'vector' OR b.typname = 'vector')
ORDER BY n.nspname, c.relname, a.attnum
LIMIT :catalog_limit
"""


@dataclass(frozen=True, kw_only=True)
class ServingCatalogRecordV1:
    producer_abi_version: int = 1
    role: Literal['api', 'worker']
    process_instance_id: str
    pool_identity: str
    tenant_context_id: str
    instance_binding: dict[str, str] | None
    captured_at: datetime
    deadline_monotonic: float
    status: Literal['complete', 'incomplete']
    reason_code: str | None
    database: dict[str, Any]
    columns: tuple[dict[str, Any], ...]


def _quote_identifier(value: str) -> str:
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ValueError('invalid catalog identifier')
    return '"' + value.replace('"', '""') + '"'


def _reason(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return 'deadline_exceeded'
    original = getattr(error, 'orig', error)
    code = getattr(original, 'sqlstate', None) or getattr(original, 'pgcode', None)
    return {'42501': 'permission_denied', '57014': 'query_cancelled'}.get(
        code, 'query_failed')


async def capture_serving_catalog(
    session: Any, *, role: Literal['api', 'worker'], process_instance_id: str,
    pool_identity: str, tenant_context_id: str, instance_binding: Mapping | None,
    deadline_monotonic: float, max_catalog_rows: int, max_model_ids: int,
) -> ServingCatalogRecordV1:
    if role not in ('api', 'worker'):
        raise ValueError('invalid role')
    for cap in (max_catalog_rows, max_model_ids):
        if type(cap) is not int or cap <= 0:
            raise ValueError('invalid catalog cap')
    if (isinstance(deadline_monotonic, bool)
            or not isinstance(deadline_monotonic, (int, float))
            or not math.isfinite(deadline_monotonic)):
        raise ValueError('invalid deadline')
    captured_at = datetime.now(UTC)
    database: dict[str, Any] = {}
    columns: list[dict[str, Any]] = []
    binding = None
    if isinstance(instance_binding, Mapping):
        values = {key: instance_binding.get(key) for key in ('instance_id', 'storage_id')}
        if all(isinstance(value, str) and value for value in values.values()):
            binding = values

    def record(reason: str | None) -> ServingCatalogRecordV1:
        return ServingCatalogRecordV1(
            role=role, process_instance_id=process_instance_id, pool_identity=pool_identity,
            tenant_context_id=tenant_context_id, instance_binding=binding,
            captured_at=captured_at, deadline_monotonic=deadline_monotonic,
            status='incomplete' if reason else 'complete', reason_code=reason,
            database=database, columns=tuple(columns),
        )

    if time.monotonic() >= deadline_monotonic:
        return record('deadline_exceeded')

    async def execute(statement, params=None):
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return await asyncio.wait_for(
            session.execute(statement, params or {}), timeout=remaining)

    async def rollback():
        # Failed queries still need cleanup after acquisition expires. Its separate
        # 50ms ceiling cannot turn a timed-out capture into an unbounded rollback.
        budget = min(0.05, max(0.001, deadline_monotonic - time.monotonic()))
        try:
            await asyncio.wait_for(session.rollback(), timeout=budget)
        except Exception:
            pass

    try:
        identity = (await execute(text(_IDENTITY_SQL))).mappings().first()
        if identity:
            database = {key: identity.get(key) for key in (
                'database_name', 'database_oid', 'current_user', 'session_user',
                'server_address', 'server_version', 'extension_version')}
        rows = (await execute(text(_CENSUS_SQL),
                              {'catalog_limit': max_catalog_rows + 1})).mappings().all()
        reason = 'catalog_truncated' if len(rows) > max_catalog_rows else None
        for row in rows[:max_catalog_rows]:
            column = {key: row.get(key) for key in (
                'schema_name', 'table_name', 'column_name', 'dimensions', 'type_name', 'relkind')}
            columns.append(column)
            if type(column['dimensions']) is not int or column['dimensions'] <= 0:
                reason = reason or 'dimension_unknown'
            relation = '.'.join(_quote_identifier(row[key])
                                for key in ('schema_name', 'table_name'))
            count = (await execute(text(f'SELECT count(*) AS row_count FROM {relation}'))).mappings().first()
            column['row_count'] = count.get('row_count') if count else None
            column['model_ids'] = []
            if type(column['row_count']) is not int or column['row_count'] < 0:
                reason = reason or 'row_count_unknown'
                continue
            if column['row_count'] != 0:
                # Census/count alone cannot attest enrolled vector validity or lineage.
                reason = reason or 'store_validation_missing'
                model_columns = (await execute(text(
                    'SELECT attname AS model_column FROM pg_catalog.pg_attribute '
                    'WHERE attrelid = to_regclass(:relation) AND attnum > 0 '
                    "AND NOT attisdropped AND attname IN ('embedding_model', 'model_id') "
                    'ORDER BY attname LIMIT 2'), {'relation': relation})).mappings().all()
                if len(model_columns) == 1:
                    model_column = model_columns[0]['model_column']
                    model = _quote_identifier(model_column)
                    ids = (await execute(text(
                        f'SELECT DISTINCT {model} AS model_id FROM {relation} '
                        f'ORDER BY {model} LIMIT :model_limit'),
                        {'model_limit': max_model_ids + 1})).mappings().all()
                    column['model_ids'] = [item.get('model_id') for item in ids[:max_model_ids]]
                    if len(ids) > max_model_ids:
                        reason = 'model_ids_truncated'
        if not binding or not pool_identity or not tenant_context_id:
            reason = reason or 'store_binding_missing'
        if not database or any(database.get(key) is None for key in (
                'database_name', 'database_oid', 'current_user', 'session_user')):
            reason = reason or 'database_identity_missing'
        if time.monotonic() >= deadline_monotonic:
            reason = 'deadline_exceeded'
        return record(reason)
    except asyncio.CancelledError:
        await rollback()
        raise
    except Exception as error:
        await rollback()
        return record(_reason(error))
