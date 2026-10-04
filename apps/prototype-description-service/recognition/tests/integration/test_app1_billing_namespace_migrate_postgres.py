"""PostgreSQL proof for N1 billing namespace mapping.

Skip is missing release evidence, not a passing result. IDENTITY_PG_REQUIRED=1
fails instead of skip. Role must be NOSUPERUSER / NOBYPASSRLS. Mapping apply
uses transaction-local ``app.bypass_rls`` only.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.pg

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")
_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "billing_namespace_migrate.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("billing_namespace_migrate", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _EngineProxy:
    def __init__(self, engine: object) -> None:
        self._engine = engine

    def connect(self):
        return self._engine.connect()  # type: ignore[attr-defined]

    def dispose(self) -> None:
        return None


def _heal(engine) -> None:
    with engine.begin() as conn:
        MIGRATION.heal(conn)


def _assert_unprivileged(conn) -> None:
    role = conn.execute(
        text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
    ).one()
    assert role[1] is False
    assert role[2] is False


def _seed(conn, *, inbox_id, projection_id, tenant_id, extra_inbox_id=None, colliding_customer: bool = False) -> None:
    conn.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
    conn.execute(
        text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
        {"id": tenant_id, "url": f"https://{tenant_id}.example.test"},
    )
    conn.execute(
        text(
            "INSERT INTO billing_webhook_inbox "
            "(id, provider, provider_event_id, event_type, signature_verified, payload, status) "
            "VALUES (:id, 'polar', 'evt-legacy', 'subscription.active', true, '{}'::jsonb, 'received')"
        ),
        {"id": inbox_id},
    )
    if extra_inbox_id is not None:
        conn.execute(
            text(
                "INSERT INTO billing_webhook_inbox "
                "(id, provider, provider_event_id, event_type, signature_verified, payload, status) "
                "VALUES (:id, 'polar', 'evt-legacy-2', 'subscription.active', true, '{}'::jsonb, 'received')"
            ),
            {"id": extra_inbox_id},
        )
    conn.execute(
        text(
            "INSERT INTO billing_subscription_projection "
            "(id, tenant_id, provider, provider_customer_id, status) "
            "VALUES (:id, :tenant_id, 'polar', 'cus-legacy', 'active')"
        ),
        {"id": projection_id, "tenant_id": tenant_id},
    )
    if colliding_customer:
        other_tenant = uuid4()
        conn.execute(
            text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
            {"id": other_tenant, "url": f"https://{other_tenant}.example.test"},
        )
        conn.execute(
            text(
                "INSERT INTO billing_subscription_projection "
                "(id, tenant_id, provider, provider_customer_id, status, environment, seller_account) "
                "VALUES (:id, :tenant_id, 'polar', 'cus-legacy', 'active', 'sandbox', 'org_xxx')"
            ),
            {"id": uuid4(), "tenant_id": other_tenant},
        )


def _namespace_state(conn, inbox_id, projection_id) -> tuple[tuple[object, object], tuple[object, object]]:
    inbox = conn.execute(
        text("SELECT environment, seller_account FROM billing_webhook_inbox WHERE id = :id"),
        {"id": inbox_id},
    ).one()
    projection = conn.execute(
        text("SELECT environment, seller_account FROM billing_subscription_projection WHERE id = :id"),
        {"id": projection_id},
    ).one()
    return (inbox[0], inbox[1]), (projection[0], projection[1])


def _mapping_file(path: Path, *, inbox_id, projection_id, tenant_id, seller: object = "org_xxx") -> Path:
    path.write_text(
        json.dumps(
            {
                "operator_identity": "ops-oncall",
                "evidence": "Polar org_xxx sandbox dashboard 2026-09-22; row IDs from dry-run",
                "inbox": [
                    {
                        "id": str(inbox_id),
                        "environment": "sandbox",
                        "seller_account": seller,
                    }
                ],
                "projection": [
                    {
                        "id": str(projection_id),
                        "tenant_id": str(tenant_id),
                        "environment": "sandbox",
                        "seller_account": seller,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_postgres_invalid_and_missing_dry_run_do_not_mutate(pg_empty_engine, tmp_path: Path) -> None:
    migrate = _load_script()
    _heal(pg_empty_engine)
    inbox_id = uuid4()
    extra_inbox_id = uuid4()
    projection_id = uuid4()
    tenant_id = uuid4()
    with pg_empty_engine.begin() as conn:
        _assert_unprivileged(conn)
        _seed(conn, inbox_id=inbox_id, projection_id=projection_id, tenant_id=tenant_id, extra_inbox_id=extra_inbox_id)

    proxy = _EngineProxy(pg_empty_engine)

    def _engine(_dsn: str) -> _EngineProxy:
        return proxy

    migrate.create_engine = _engine  # type: ignore[method-assign]
    migrate.get_database_settings = lambda: SimpleNamespace(postgres_sync_dsn="postgresql+psycopg://scratch")  # type: ignore[method-assign]

    invalid = tmp_path / "invalid.json"
    _mapping_file(invalid, inbox_id=inbox_id, projection_id=projection_id, tenant_id=tenant_id, seller=None)
    assert migrate.main(["--mapping", str(invalid)]) == 1
    assert migrate.main(["--mapping", str(invalid), "--apply"]) == 1

    missing = tmp_path / "missing.json"
    _mapping_file(missing, inbox_id=uuid4(), projection_id=projection_id, tenant_id=tenant_id)
    assert migrate.main(["--mapping", str(missing)]) == 1
    assert migrate.main(["--mapping", str(missing), "--apply"]) == 1

    mismatch = tmp_path / "mismatch.json"
    _mapping_file(mismatch, inbox_id=inbox_id, projection_id=projection_id, tenant_id=uuid4())
    assert migrate.main(["--mapping", str(mismatch)]) == 1
    assert migrate.main(["--mapping", str(mismatch), "--apply"]) == 1

    with pg_empty_engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
        assert _namespace_state(conn, inbox_id, projection_id) == ((None, None), (None, None))


def test_postgres_collision_dry_run_and_apply_rollback(pg_empty_engine, tmp_path: Path) -> None:
    migrate = _load_script()
    _heal(pg_empty_engine)
    inbox_id = uuid4()
    extra_inbox_id = uuid4()
    projection_id = uuid4()
    tenant_id = uuid4()
    with pg_empty_engine.begin() as conn:
        _assert_unprivileged(conn)
        _seed(
            conn,
            inbox_id=inbox_id,
            projection_id=projection_id,
            tenant_id=tenant_id,
            extra_inbox_id=extra_inbox_id,
            colliding_customer=True,
        )

    proxy = _EngineProxy(pg_empty_engine)

    def _engine(_dsn: str) -> _EngineProxy:
        return proxy

    migrate.create_engine = _engine  # type: ignore[method-assign]
    migrate.get_database_settings = lambda: SimpleNamespace(postgres_sync_dsn="postgresql+psycopg://scratch")  # type: ignore[method-assign]

    colliding = tmp_path / "collide.json"
    _mapping_file(colliding, inbox_id=inbox_id, projection_id=projection_id, tenant_id=tenant_id)
    assert migrate.main(["--mapping", str(colliding)]) == 1

    partial = tmp_path / "partial.json"
    partial.write_text(
        json.dumps(
            {
                "operator_identity": "ops-oncall",
                "evidence": "Polar org_xxx sandbox dashboard 2026-09-22; row IDs from dry-run",
                "inbox": [
                    {"id": str(inbox_id), "environment": "sandbox", "seller_account": "org_xxx"},
                    {"id": str(extra_inbox_id), "environment": "sandbox", "seller_account": "org_xxx"},
                ],
                "projection": [
                    {
                        "id": str(projection_id),
                        "tenant_id": str(tenant_id),
                        "environment": "sandbox",
                        "seller_account": "org_xxx",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert migrate.main(["--mapping", str(partial), "--apply"]) == 1

    with pg_empty_engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
        assert _namespace_state(conn, inbox_id, projection_id) == ((None, None), (None, None))
        extra = conn.execute(
            text("SELECT environment, seller_account FROM billing_webhook_inbox WHERE id = :id"),
            {"id": extra_inbox_id},
        ).one()
        assert extra == (None, None)


def test_postgres_valid_dry_run_unchanged_then_apply_idempotent(pg_empty_engine, tmp_path: Path) -> None:
    migrate = _load_script()
    _heal(pg_empty_engine)
    inbox_id = uuid4()
    projection_id = uuid4()
    tenant_id = uuid4()
    with pg_empty_engine.begin() as conn:
        _assert_unprivileged(conn)
        _seed(conn, inbox_id=inbox_id, projection_id=projection_id, tenant_id=tenant_id)

    proxy = _EngineProxy(pg_empty_engine)

    def _engine(_dsn: str) -> _EngineProxy:
        return proxy

    migrate.create_engine = _engine  # type: ignore[method-assign]
    migrate.get_database_settings = lambda: SimpleNamespace(postgres_sync_dsn="postgresql+psycopg://scratch")  # type: ignore[method-assign]

    mapping = tmp_path / "valid.json"
    _mapping_file(mapping, inbox_id=inbox_id, projection_id=projection_id, tenant_id=tenant_id)

    assert migrate.main(["--mapping", str(mapping)]) == 0
    with pg_empty_engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
        assert _namespace_state(conn, inbox_id, projection_id) == ((None, None), (None, None))

    assert migrate.main(["--mapping", str(mapping), "--apply"]) == 0
    with pg_empty_engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
        assert _namespace_state(conn, inbox_id, projection_id) == (("sandbox", "org_xxx"), ("sandbox", "org_xxx"))

    assert migrate.main(["--mapping", str(mapping), "--apply"]) == 0
    with pg_empty_engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
        assert _namespace_state(conn, inbox_id, projection_id) == (("sandbox", "org_xxx"), ("sandbox", "org_xxx"))
        unmapped = conn.execute(
            text("SELECT count(*) FROM billing_webhook_inbox WHERE environment IS NULL OR seller_account IS NULL")
        ).scalar()
        assert unmapped == 0
