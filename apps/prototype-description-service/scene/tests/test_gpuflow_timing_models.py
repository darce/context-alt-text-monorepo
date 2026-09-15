"""Storage contracts for durable GPU timing (no service or external DB required)."""

import uuid
from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest
import sqlalchemy as sa

from db.models import scene


@pytest.fixture
def storage():
    metadata = sa.MetaData()
    sa.Table("tenants", metadata, sa.Column("id", sa.UUID, primary_key=True))
    for name in ("DescribeStartup", "DescribeOperation", "DescribeDemandLease", "DescribeRun", "DescribeRunItem"):
        getattr(scene, name).__table__.to_metadata(metadata)
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    metadata.create_all(engine)
    with engine.begin() as connection:
        yield connection, metadata.tables
    engine.dispose()


def test_restart_retains_individual_waits_and_shared_startup(storage):
    connection, tables = storage
    tenant = uuid.uuid4()
    now = datetime.now(UTC)
    connection.execute(tables["tenants"].insert(), {"id": tenant})
    connection.execute(
        tables["describe_startups"].insert(),
        {"startup_id": "shared", "started_at": now, "retain_until": now + timedelta(hours=1)},
    )
    for number in range(2):
        connection.execute(
            tables["describe_operations"].insert(),
            {
                "tenant_id": tenant,
                "operation_id": f"op-{number}",
                "request_digest": "a" * 64,
                "accepted_at": now + timedelta(seconds=number),
                "expires_at": now + timedelta(minutes=1),
                "retain_until": now + timedelta(hours=1),
                "startup_id": "shared",
                "first_ready_at": now + timedelta(seconds=10),
            },
        )
        connection.execute(
            tables["describe_demand_leases"].insert(),
            {
                "tenant_id": tenant,
                "operation_id": f"op-{number}",
                "expires_at": now + timedelta(minutes=1),
                "retain_until": now + timedelta(hours=1),
            },
        )
    rows = connection.execute(sa.select(tables["describe_operations"])).mappings().all()
    assert [int((row["first_ready_at"] - row["accepted_at"]).total_seconds()) for row in rows] == [10, 9]
    assert {row["startup_id"] for row in rows} == {"shared"}


@pytest.mark.parametrize("status", ["failed", "cancelled", "completed"])
def test_run_and_item_timing_preserves_null_and_zero(storage, status):
    connection, tables = storage
    tenant, run = uuid.uuid4(), uuid.uuid4()
    connection.execute(tables["tenants"].insert(), {"id": tenant})
    connection.execute(
        tables["image_description_runs"].insert(),
        {
            "id": run,
            "tenant_id": tenant,
            "media_ids": [1, 2],
            "total_items": 2,
            "status": status,
            "queue_ms": 0,
            "ramp_up_ms": 0,
        },
    )
    for media, value in [(1, None), (2, 0)]:
        connection.execute(
            tables["image_description_run_items"].insert(),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant,
                "run_id": run,
                "media_id": media,
                "status": "failed",
                "processing_ms": value,
            },
        )
    row = connection.execute(sa.select(tables["image_description_runs"])).mappings().one()
    assert row["queue_ms"] == 0
    assert row["processing_ms_p50"] is None
    assert row["startup_id"] is None
    assert connection.execute(sa.select(tables["image_description_run_items"].c.processing_ms)).scalars().all() == [
        None,
        0,
    ]
    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(tables["image_description_runs"].update().values(queue_ms=-1))


def test_canonical_schema_matches_models(monkeypatch):
    migration = import_module("db.migrations.versions.001_identity_schema")
    captured = {}
    monkeypatch.setattr(migration, "_ensure_table", lambda op, name, *elements, **kw: captured.update({name: elements}))
    monkeypatch.setattr(migration, "_ensure_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration, "ensure_identity_vector_typmods", lambda op: None)
    migration.ensure_tables(None)
    for model in (
        scene.DescribeStartup,
        scene.DescribeOperation,
        scene.DescribeDemandLease,
        scene.DescribeRun,
        scene.DescribeRunItem,
    ):
        table = model.__table__
        columns = {c.name: c for c in captured[table.name] if isinstance(c, sa.Column)}
        assert set(columns) == set(table.c.keys())
        for column in table.c:
            assert columns[column.name].nullable == column.nullable
        checks = {str(c.sqltext) for c in captured[table.name] if isinstance(c, sa.CheckConstraint)}
        assert checks == {str(c.sqltext) for c in table.constraints if isinstance(c, sa.CheckConstraint)}
        assert table.name in migration.EXPECTED_SCHEMA_TABLES
        assert table.name in migration.DOWNGRADE_TABLE_ORDER
    assert "describe_startups" not in migration.TENANT_TABLES
    assert {"describe_operations", "describe_demand_leases"} <= set(migration.TENANT_TABLES)


@pytest.mark.parametrize("invalid", ["tenant", "state", "retention", "ready"])
def test_invalid_correlation_and_observations_are_rejected(storage, invalid):
    connection, tables = storage
    tenant, other = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    connection.execute(tables["tenants"].insert(), [{"id": tenant}, {"id": other}])
    operation = {
        "tenant_id": tenant,
        "operation_id": "opaque-token",
        "request_digest": "b" * 64,
        "accepted_at": now,
        "expires_at": now + timedelta(minutes=1),
        "retain_until": now + timedelta(hours=1),
    }
    if invalid == "ready":
        operation["first_ready_at"] = now - timedelta(seconds=1)
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(tables["describe_operations"].insert(), operation)
        return
    connection.execute(tables["describe_operations"].insert(), operation)
    lease = {
        "tenant_id": other if invalid == "tenant" else tenant,
        "operation_id": "opaque-token",
        "state": "invalid" if invalid == "state" else "active",
        "expires_at": now + timedelta(minutes=1),
        "retain_until": now if invalid == "retention" else now + timedelta(hours=1),
    }
    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(tables["describe_demand_leases"].insert(), lease)
