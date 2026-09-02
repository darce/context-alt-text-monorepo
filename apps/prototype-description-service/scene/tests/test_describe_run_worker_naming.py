"""Bulk describe worker fuses identity names via the naming-preview service."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from io import BytesIO
from typing import cast

from PIL import Image
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import _DB_SETTINGS, Base
from db.models.identity import IdentityCluster, IdentityMember, IdentityNameSuppression, MediaIdentity
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import DescribeItemOutcome, run_describe_job
from scene.application.identity_merge import NormalizedBox, PhraseBox
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000cd")
GENERIC_DRAFT = "A man stands by the window."
FUSED_DRAFT = "A man stands by the window. Pictured from left: Ada."
LTR_FUSED_DRAFT = "A man stands by the window. Pictured from left: Ada and Bob."
GROUNDED_BOXES = (
    PhraseBox(
        phrase="A man",
        span_start=0,
        span_end=5,
        box=NormalizedBox(x=0.0, y=0.0, width=0.5, height=1.0),
    ),
)


def _png_bytes(width=100, height=50) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color=(120, 120, 120)).save(buf, format="PNG")
    return buf.getvalue()


def _embedding() -> list[float]:
    return [1.0] + [0.0] * (_DB_SETTINGS.pgvector_dimension - 1)


async def _make_db(*, naming_agreement_enabled: bool = True, with_identities: bool = False):
    path = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"wbux6_naming_{uuid.uuid4().hex}.db")
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url)
    tables: list[Table] = [Tenant.__table__, DescribeRun.__table__, DescribeRunItem.__table__]
    if with_identities:
        tables.extend(
            [
                MediaIdentity.__table__,
                IdentityCluster.__table__,
                IdentityMember.__table__,
                IdentityNameSuppression.__table__,
            ]
        )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=cast(list[Table], tables))
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


async def _seed_run(sf, media_ids=(1,), image_bytes=b"rawbytes"):
    async with sf() as s:
        run_id = await DescribeRunRepository(s).create_run(
            tenant_id=TENANT_ID,
            media_ids=list(media_ids),
            images=dict.fromkeys(media_ids, (image_bytes, "image/png")),
        )
        await s.commit()
    return run_id


async def _seed_confirmed_face(session, *, label: str, media_id: int, bbox: tuple[int, int, int, int], roster_id):
    x, y, w, h = bbox
    identity = MediaIdentity(
        tenant_id=TENANT_ID,
        media_id=media_id,
        media_url=f"http://naming.test.local/{media_id}.png",
        bbox_x=x,
        bbox_y=y,
        bbox_width=w,
        bbox_height=h,
        confidence=0.97,
        embedding=_embedding(),
        embedding_model="buffalo_l@insightface",
    )
    cluster = IdentityCluster(
        tenant_id=TENANT_ID,
        label=label,
        user_confirmed=True,
        roster_id=roster_id,
    )
    session.add_all([identity, cluster])
    await session.flush()
    session.add(
        IdentityMember(
            tenant_id=TENANT_ID,
            cluster_id=cluster.id,
            identity_id=identity.id,
            similarity=0.9,
        )
    )


async def _describe_one(media_id, image_bytes, content_type):
    assert image_bytes == b"rawbytes"
    return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT, caption=f"cap {media_id}")


def _stub_successful_lookup(monkeypatch, wmod):
    async def fake_load(**kwargs):
        return [], object()

    monkeypatch.setattr(wmod, "load_fusion_naming_inputs", fake_load, raising=True)


def test_naming_enabled_item_request_carries_fused_names(monkeypatch):
    import scene.application.describe_run_worker as wmod

    captured: list[dict] = []

    async def fake_naming_preview(**kwargs):
        captured.append(kwargs)
        return FUSED_DRAFT, object()

    _stub_successful_lookup(monkeypatch, wmod)
    monkeypatch.setattr(wmod, "naming_preview", fake_naming_preview, raising=True)

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
    assert items[0].caption == "cap 1"


def test_naming_disabled_item_has_no_fused_names(monkeypatch):
    import scene.application.describe_run_worker as wmod

    calls: list[dict] = []

    async def fake_naming_preview(**kwargs):
        calls.append(kwargs)
        raise AssertionError("naming_preview must not run when naming is disabled")

    monkeypatch.setattr(wmod, "naming_preview", fake_naming_preview, raising=True)

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
    assert items[0].caption == "cap 1"


def test_naming_failure_still_describes_item(monkeypatch):
    import scene.application.describe_run_worker as wmod

    async def boom(**kwargs):
        raise RuntimeError("naming exploded")

    _stub_successful_lookup(monkeypatch, wmod)
    monkeypatch.setattr(wmod, "naming_preview", boom, raising=True)

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
    assert [item.caption for item in items] == ["cap 1", "cap 2"]


def test_naming_lookup_runs_concurrently_with_describe(monkeypatch):
    import scene.application.describe_run_worker as wmod

    events: list[str] = []

    async def fake_load(**kwargs):
        events.append("load-start")
        await asyncio.sleep(0.05)
        events.append("load-end")
        return [], object()

    async def describe_one(media_id, image_bytes, content_type):
        events.append("describe-start")
        await asyncio.sleep(0.05)
        events.append("describe-end")
        return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT, caption=GENERIC_DRAFT)

    async def fake_naming_preview(**kwargs):
        return FUSED_DRAFT, object()

    monkeypatch.setattr(wmod, "load_fusion_naming_inputs", fake_load, raising=True)
    monkeypatch.setattr(wmod, "naming_preview", fake_naming_preview, raising=True)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True)
        run_id = await _seed_run(sf)
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=1.0
        )
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return items

    items = asyncio.run(body())
    assert "load-start" in events and "describe-start" in events
    assert events.index("describe-start") < events.index("load-end")
    assert events.index("load-start") < events.index("describe-end")
    assert items[0].status == DescribeItemStatus.COMPLETED
    assert items[0].alt_text_draft == FUSED_DRAFT
    assert items[0].caption == GENERIC_DRAFT


def test_unstubbed_naming_binds_seeded_faces_left_to_right():
    png = _png_bytes()

    async def describe_one(media_id, image_bytes, content_type):
        assert image_bytes == png
        return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT, caption=GENERIC_DRAFT)

    async def run_once(*, naming_agreement_enabled: bool):
        path, engine, sf = await _make_db(naming_agreement_enabled=naming_agreement_enabled, with_identities=True)
        async with sf() as s:
            # Seed RIGHT face first, then LEFT, so insert-order implementations bind Bob, Ada.
            await _seed_confirmed_face(s, label="Bob", media_id=1, bbox=(60, 10, 20, 20), roster_id=uuid.uuid4())
            await _seed_confirmed_face(s, label="Ada", media_id=1, bbox=(10, 10, 20, 20), roster_id=uuid.uuid4())
            await s.commit()
        run_id = await _seed_run(sf, image_bytes=png)
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=1.0
        )
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return items[0]

    enabled = asyncio.run(run_once(naming_agreement_enabled=True))
    disabled = asyncio.run(run_once(naming_agreement_enabled=False))
    assert enabled.status == DescribeItemStatus.COMPLETED
    assert enabled.caption == GENERIC_DRAFT
    assert enabled.alt_text_draft == LTR_FUSED_DRAFT
    assert (enabled.provenance or {}).get("naming", {}).get("mode") == "positional"
    assert [n["name"] for n in (enabled.provenance or {}).get("naming", {}).get("injected_names", [])] == [
        "Ada",
        "Bob",
    ]
    assert disabled.status == DescribeItemStatus.COMPLETED
    assert disabled.caption == GENERIC_DRAFT
    assert disabled.alt_text_draft == GENERIC_DRAFT


def test_naming_preview_receives_item_phrase_boxes(monkeypatch):
    import scene.application.describe_run_worker as wmod

    captured: list[dict] = []

    async def describe_one(media_id, image_bytes, content_type):
        return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT, caption=GENERIC_DRAFT, phrase_boxes=GROUNDED_BOXES)

    async def fake_naming_preview(**kwargs):
        captured.append(kwargs)
        return FUSED_DRAFT, object()

    _stub_successful_lookup(monkeypatch, wmod)
    monkeypatch.setattr(wmod, "naming_preview", fake_naming_preview, raising=True)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True)
        run_id = await _seed_run(sf)
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=1.0
        )
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return items

    items = asyncio.run(body())
    assert captured, "naming_preview must run when naming is enabled"
    assert captured[0]["phrase_boxes"] == GROUNDED_BOXES
    assert items[0].alt_text_draft == FUSED_DRAFT
    assert items[0].caption == GENERIC_DRAFT


def test_naming_lookup_timeout_persists_generic_draft_without_reload(monkeypatch):
    import scene.application.describe_run_worker as wmod

    calls: list[str] = []

    async def fake_load(**kwargs):
        calls.append("load")
        await asyncio.sleep(60)
        return [], object()

    monkeypatch.setattr(wmod, "NAMING_BUDGET_SECONDS", 0.1, raising=True)
    monkeypatch.setattr(wmod, "load_fusion_naming_inputs", fake_load, raising=True)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True)
        run_id = await _seed_run(sf)
        started = time.monotonic()
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=_describe_one, timeout_seconds=1.0
        )
        elapsed = time.monotonic() - started
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return items, elapsed

    items, elapsed = asyncio.run(body())
    assert elapsed < 2.0
    assert items[0].status == DescribeItemStatus.COMPLETED
    assert items[0].alt_text_draft == GENERIC_DRAFT
    assert items[0].caption == "cap 1"
    assert calls == ["load"]
