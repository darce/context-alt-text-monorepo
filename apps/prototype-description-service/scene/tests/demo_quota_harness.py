"""Shared demo-quota HTTP harness for scene route tests (DS2B-PM-H-02).

One fixture covers describe multipart/async and describe/run clients so table
lists and auth wiring cannot diverge again.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.identity import (
    IdentityCluster,
    IdentityMember,
    IdentityNameSuppression,
    MediaIdentity,
)
from db.models.observability import AuditEvent
from db.models.scene import DescribeRun, DescribeRunItem, ImageDescription
from db.models.tenant import ApiKey, DemoInstance, Tenant
from recognition.application.services.demo_provisioning_service import provision_demo
from recognition.interface_adapters.http.deps import get_optional_session
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
from scene.interface_adapters.http.router import router as scene_router

_DESCRIBE_TABLES: Sequence[Table] = (
    Tenant.__table__,
    ApiKey.__table__,
    DemoInstance.__table__,
    ImageDescription.__table__,
    AuditEvent.__table__,
    MediaIdentity.__table__,
    IdentityCluster.__table__,
    IdentityMember.__table__,
    IdentityNameSuppression.__table__,
)

_RUN_TABLES: Sequence[Table] = (
    Tenant.__table__,
    ApiKey.__table__,
    DemoInstance.__table__,
    DescribeRun.__table__,
    DescribeRunItem.__table__,
)


@contextmanager
def demo_quota_client(
    *,
    recognition_quota: int = 5,
    non_demo: bool = False,
    tables: str = "describe",
) -> Iterator[tuple[Any, Any, Any, str, str]]:
    """Yield ``(client, session_factory, provisioned, tenant_id, slug)``.

    ``tables`` is ``"describe"`` (multipart/async tables) or ``"run"`` (describe-run).
    """
    table_list = list(_RUN_TABLES if tables == "run" else _DESCRIBE_TABLES)
    path = os.path.join(tempfile.gettempdir(), f"ds2c_demo_{uuid.uuid4().hex}.db")
    url = f"sqlite+aiosqlite:///{path}"

    async def _init() -> None:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=cast(list[Table], table_list),
            )
        await engine.dispose()

    asyncio.run(_init())
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async def _provision():
        async with sf() as s:
            result = await provision_demo(
                s, label="Scene Demo", seed="default", recognition_quota=recognition_quota
            )
            await s.commit()
            return result

    provisioned = asyncio.run(_provision())
    tenant_id = str(provisioned.instance.tenant_id)
    slug = provisioned.instance.slug

    if non_demo:
        auth = AuthContext(
            token="not-a-demo-key",
            tenant_claim=tenant_id,
            api_key_id=None,
            is_admin=False,
            enabled=True,
        )
    else:
        auth = AuthContext(
            token=provisioned.raw_api_key,
            tenant_claim=tenant_id,
            api_key_id=None,
            is_admin=False,
            enabled=True,
        )

    async def _session():
        async with sf() as s:
            yield s

    app = FastAPI()
    app.include_router(scene_router, prefix="/scene")
    app.dependency_overrides[require_auth] = lambda: auth
    app.dependency_overrides[get_optional_session] = _session
    try:
        with TestClient(app) as client:
            yield client, sf, provisioned, tenant_id, slug
    finally:
        asyncio.run(engine.dispose())
        with suppress(OSError):
            os.unlink(path)


def recognition_used(sf, slug: str) -> int:
    async def _read() -> int:
        async with sf() as s:
            row = await s.get(DemoInstance, slug)
            assert row is not None
            return int(row.recognition_used)

    return asyncio.run(_read())
