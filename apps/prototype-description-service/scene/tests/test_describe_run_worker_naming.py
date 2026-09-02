"""Bulk describe worker fuses identity names via the naming-preview service."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import cast

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import DescribeItemOutcome, run_describe_job
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000cd")
GENERIC_DRAFT = "A man stands by the window."
FUSED_DRAFT = "A man stands by the window. Pictured from left: Ada."


async def _make_db(*, naming_agreement_enabled: bool = True):
    path = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"wbux6_naming_{uuid.uuid4().hex}.db")
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(list[Table], [Tenant.__table__, DescribeRun.__table__, DescribeRunItem.__table__]),
        )
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as s:
        s.add(
            Tenant(
                id=TENANT_ID,
                site_url="http://naming.test.local",
                naming_agreement_enabled=naming_agreement_enabled,
            )
        )
        await s.commit()
    return path, engine, sf


async def _seed_run(sf, media_ids=(1,)):
    async with sf() as s:
        run_id = await DescribeRunRepository(s).create_run(
            tenant_id=TENANT_ID,
            media_ids=list(media_ids),
            images=dict.fromkeys(media_ids, (b"rawbytes", "image/png")),
        )
        await s.commit()
    return run_id


async def _describe_one(media_id, image_bytes, content_type):
    assert image_bytes == b"rawbytes"
    return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT, caption=f"cap {media_id}")


def test_naming_enabled_item_request_carries_fused_names(monkeypatch):
    import scene.application.describe_run_worker as wmod

    captured: list[dict] = []

    async def fake_naming_preview(**kwargs):
        captured.append(kwargs)
        return FUSED_DRAFT, object()

    monkeypatch.setattr(wmod, "naming_preview", fake_naming_preview, raising=False)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True)
        run_id = await _seed_run(sf)
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=_describe_one, timeout_seconds=1.0
        )
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return run, items

    run, items = asyncio.run(body())
    assert run is not None
    assert run.status == DescribeRunStatus.COMPLETED
    assert captured, "naming_preview must run when naming_agreement_enabled"
    assert captured[0]["generic_draft"] == GENERIC_DRAFT
    assert captured[0]["media_id"] == 1
    assert items[0].status == DescribeItemStatus.COMPLETED
    assert items[0].alt_text_draft == FUSED_DRAFT


def test_naming_disabled_item_has_no_fused_names(monkeypatch):
    import scene.application.describe_run_worker as wmod

    calls: list[dict] = []

    async def fake_naming_preview(**kwargs):
        calls.append(kwargs)
        raise AssertionError("naming_preview must not run when naming is disabled")

    monkeypatch.setattr(wmod, "naming_preview", fake_naming_preview, raising=False)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=False)
        run_id = await _seed_run(sf)
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=_describe_one, timeout_seconds=1.0
        )
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return items

    items = asyncio.run(body())
    assert calls == []
    assert items[0].status == DescribeItemStatus.COMPLETED
    assert items[0].alt_text_draft == GENERIC_DRAFT


def test_naming_failure_still_describes_item(monkeypatch):
    import scene.application.describe_run_worker as wmod

    async def boom(**kwargs):
        raise RuntimeError("naming exploded")

    monkeypatch.setattr(wmod, "naming_preview", boom, raising=False)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True)
        run_id = await _seed_run(sf, media_ids=(1, 2))
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=_describe_one, timeout_seconds=1.0
        )
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return run, items

    run, items = asyncio.run(body())
    assert run is not None
    assert run.status == DescribeRunStatus.COMPLETED
    assert [item.status for item in items] == [DescribeItemStatus.COMPLETED, DescribeItemStatus.COMPLETED]
    assert all(item.alt_text_draft == GENERIC_DRAFT for item in items)


def test_naming_lookup_runs_concurrently_with_describe(monkeypatch):
    import scene.application.describe_run_worker as wmod

    events: list[str] = []

    async def fake_load(**kwargs):
        events.append("load-start")
        await asyncio.sleep(0.05)
        events.append("load-end")
        return [], None

    async def describe_one(media_id, image_bytes, content_type):
        events.append("describe-start")
        await asyncio.sleep(0.05)
        events.append("describe-end")
        return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT)

    async def fake_naming_preview(**kwargs):
        return FUSED_DRAFT, object()

    monkeypatch.setattr(wmod, "load_fusion_naming_inputs", fake_load, raising=False)
    monkeypatch.setattr(wmod, "naming_preview", fake_naming_preview, raising=False)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True)
        run_id = await _seed_run(sf)
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=1.0
        )
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())
    assert "load-start" in events and "describe-start" in events
    assert events.index("describe-start") < events.index("load-end")
    assert events.index("load-start") < events.index("describe-end")
