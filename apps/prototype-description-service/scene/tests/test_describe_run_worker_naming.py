"""Bulk describe worker fuses identity names via the naming-preview service."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from io import BytesIO
from typing import cast

import pytest
from PIL import Image
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import _DB_SETTINGS, Base
from db.models.identity import IdentityCluster, IdentityMember, IdentityNameSuppression, MediaIdentity
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import DescribeItemOutcome, run_describe_job
from scene.application.fusion.reconcile import (
    Attachment,
    AttachmentAltitude,
    AttachmentDecision,
    FactSource,
)
from scene.application.identity_merge import NormalizedBox, PhraseBox
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus
from scene.domain.description import DescriptionResultTier

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
    return cluster.id


async def _describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
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


def test_naming_lookup_completes_before_describe_uses_shared_snapshot(monkeypatch):
    """HARM-F3: Stage-2 and Stage-3 observe the same loaded snapshot object."""
    import scene.application.describe_run_worker as wmod

    events: list[str] = []
    face_a = object()
    face_b = object()
    snapshot_faces = [face_a, face_b]
    snapshot_policy = object()
    describe_snapshot: dict = {}
    preview_snapshot: dict = {}

    async def fake_load(**kwargs):
        events.append("load-start")
        await asyncio.sleep(0.05)
        events.append("load-end")
        return snapshot_faces, snapshot_policy

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        events.append("describe-start")
        describe_snapshot["naming_inputs"] = naming_inputs
        await asyncio.sleep(0.05)
        events.append("describe-end")
        return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT, caption=GENERIC_DRAFT)

    async def fake_naming_preview(**kwargs):
        preview_snapshot["confirmed_faces"] = kwargs.get("confirmed_faces")
        preview_snapshot["naming_policy"] = kwargs.get("naming_policy")
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
    assert events.index("load-end") < events.index("describe-start")
    describe_inputs = describe_snapshot.get("naming_inputs")
    assert describe_inputs is not None
    describe_faces, describe_policy = describe_inputs
    assert describe_policy is snapshot_policy
    assert preview_snapshot.get("naming_policy") is snapshot_policy
    assert describe_policy is preview_snapshot.get("naming_policy")
    preview_faces = list(preview_snapshot.get("confirmed_faces") or [])
    assert len(preview_faces) == len(snapshot_faces) == len(describe_faces)
    assert all(a is b for a, b in zip(describe_faces, snapshot_faces, strict=True))
    assert all(a is b for a, b in zip(preview_faces, snapshot_faces, strict=True))
    assert items[0].status == DescribeItemStatus.COMPLETED
    assert items[0].alt_text_draft == FUSED_DRAFT
    assert items[0].caption == GENERIC_DRAFT


def test_unstubbed_naming_binds_seeded_faces_left_to_right(monkeypatch):
    import scene.application.identity_merge as identity_merge
    import scene.application.naming_preview_service as nps

    png = _png_bytes()
    real_load_confirmed_faces = identity_merge.load_confirmed_faces
    face_loads: list[int] = []

    async def spy_load_confirmed_faces(*args, **kwargs):
        face_loads.append(1)
        return await real_load_confirmed_faces(*args, **kwargs)

    monkeypatch.setattr(nps, "load_confirmed_faces", spy_load_confirmed_faces)

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
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
    enabled_face_loads = len(face_loads)
    face_loads.clear()
    disabled = asyncio.run(run_once(naming_agreement_enabled=False))
    disabled_face_loads = len(face_loads)
    assert enabled_face_loads == 1, f"expected one load_confirmed_faces per bulk item, got {enabled_face_loads}"
    assert disabled_face_loads == 0
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

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
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


def test_item_envelope_times_out_naming_lookup_and_persists_generic_draft(monkeypatch):
    """PERF-10 traded for DATA-19 (WBUX-6 S9-F1): serial envelope is the sum.

    A 0.05s naming budget whose lookup sleeps 5s must still finish inside
    NAMING_BUDGET_SECONDS + describe timeout + 0.5s slack, and persist the
    generic draft (naming-timeout path). Removing wait_for around the bulk
    naming lookup makes this assertion go red.
    """
    import scene.application.describe_run_worker as wmod

    async def fake_load(**kwargs):
        await asyncio.sleep(5)
        return [], object()

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT, caption="cap 1")

    monkeypatch.setattr(wmod, "NAMING_BUDGET_SECONDS", 0.05, raising=True)
    monkeypatch.setattr(wmod, "load_fusion_naming_inputs", fake_load, raising=True)

    describe_timeout = 1.0

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True)
        run_id = await _seed_run(sf)
        started = time.monotonic()
        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=describe_timeout,
        )
        elapsed = time.monotonic() - started
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return items, elapsed

    items, elapsed = asyncio.run(body())
    envelope = wmod.item_envelope_seconds(describe_timeout)
    assert envelope == pytest.approx(0.05 + describe_timeout)
    assert elapsed < envelope + 0.5
    assert items[0].status == DescribeItemStatus.COMPLETED
    assert items[0].alt_text_draft == GENERIC_DRAFT
    assert items[0].caption == "cap 1"
    assert wmod.item_envelope_seconds.__doc__ is not None
    assert "PERF-10 traded for DATA-19 (WBUX-6 S9-F1)" in wmod.item_envelope_seconds.__doc__


def _run_item_with_lookup_and_preview(*, monkeypatch, lookup_sleep: float, preview_sleep: float):
    """NAMING_BUDGET=1.0, describe timeout=0.1, lookup then Stage-3 preview."""
    import scene.application.describe_run_worker as wmod

    async def fake_load(**kwargs):
        await asyncio.sleep(lookup_sleep)
        return [], object()

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT, caption="cap 1")

    async def fake_naming_preview(**kwargs):
        if preview_sleep:
            await asyncio.sleep(preview_sleep)
        return FUSED_DRAFT, object()

    monkeypatch.setattr(wmod, "NAMING_BUDGET_SECONDS", 1.0, raising=True)
    monkeypatch.setattr(wmod, "load_fusion_naming_inputs", fake_load, raising=True)
    monkeypatch.setattr(wmod, "naming_preview", fake_naming_preview, raising=True)

    describe_timeout = 0.1
    envelope = wmod.item_envelope_seconds(describe_timeout)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True)
        run_id = await _seed_run(sf)
        started = time.monotonic()
        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=describe_timeout,
        )
        elapsed = time.monotonic() - started
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return items, elapsed, envelope

    return asyncio.run(body())


def test_hung_naming_preview_is_bounded_by_remaining_item_envelope(monkeypatch):
    """S9R2-F1: hung Stage-3 preview cannot spend a second full naming budget.

    NAMING_BUDGET=1.0, describe timeout=0.1 (envelope=1.1), lookup sleeps 0.5s,
    preview sleeps 5s. Remaining after lookup is ~0.6s, so the item must finish
    in < 1.1 + 0.5s and persist the generic draft (lookup-timeout path; sr-007).
    Mutant M1 (preview wait_for uses full NAMING_BUDGET_SECONDS) goes red here.
    """
    items, elapsed, envelope = _run_item_with_lookup_and_preview(
        monkeypatch=monkeypatch, lookup_sleep=0.5, preview_sleep=5.0
    )
    assert envelope == pytest.approx(1.1)
    # Spec ceiling is envelope+0.5=1.6; pin below 1.45 so M1 (full NAMING_BUDGET
    # preview after 0.5s lookup, ~1.5s+) cannot hide in slack.
    assert elapsed < 1.1 + 0.5
    assert elapsed < 1.45
    assert items[0].status == DescribeItemStatus.COMPLETED
    assert items[0].alt_text_draft == GENERIC_DRAFT
    assert items[0].caption == "cap 1"


def test_fast_naming_preview_applies_names_inside_remaining_item_envelope(monkeypatch):
    """S9R2-F1: a fast preview still fuses names when remaining envelope is enough.

    Same budgets as the hung-preview case; lookup sleeps 0.5s, preview is immediate.
    Mutant M2 (sleep NAMING_BUDGET-0.01 at the start of _apply_naming_preview)
    exceeds the remaining ~0.6s and goes red here (generic draft, names missing).
    """
    items, elapsed, envelope = _run_item_with_lookup_and_preview(
        monkeypatch=monkeypatch, lookup_sleep=0.5, preview_sleep=0.0
    )
    assert envelope == pytest.approx(1.1)
    assert elapsed < 1.6
    assert items[0].status == DescribeItemStatus.COMPLETED
    assert items[0].alt_text_draft == FUSED_DRAFT
    assert items[0].caption == "cap 1"


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


def test_stage2_dropped_identity_is_not_named_on_bulk_path():
    png = _png_bytes()
    dropped: dict[str, object] = {}

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        assert image_bytes == png
        return DescribeItemOutcome(
            alt_text_draft=GENERIC_DRAFT,
            caption=GENERIC_DRAFT,
            attachments=(
                Attachment(
                    fact_id=f"identity:cluster:{dropped['bob_cluster_id']}",
                    fact_source=FactSource.IDENTITY,
                    fact_label="Bob",
                    decision=AttachmentDecision.DROPPED,
                    altitude=AttachmentAltitude.NONE,
                    review_reason="face_not_detected",
                ),
            ),
        )

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True, with_identities=True)
        async with sf() as s:
            dropped["bob_cluster_id"] = await _seed_confirmed_face(
                s, label="Bob", media_id=1, bbox=(60, 10, 20, 20), roster_id=uuid.uuid4()
            )
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

    item = asyncio.run(body())
    assert item.status == DescribeItemStatus.COMPLETED
    assert item.caption == GENERIC_DRAFT
    assert item.alt_text_draft == FUSED_DRAFT
    assert "Bob" not in (item.alt_text_draft or "")
    assert [n["name"] for n in (item.provenance or {}).get("naming", {}).get("injected_names", [])] == ["Ada"]


def test_unstubbed_naming_replaces_grounded_span_with_ada():
    png = _png_bytes()

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        assert image_bytes == png
        return DescribeItemOutcome(
            alt_text_draft=GENERIC_DRAFT,
            caption=GENERIC_DRAFT,
            phrase_boxes=GROUNDED_BOXES,
        )

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True, with_identities=True)
        async with sf() as s:
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

    item = asyncio.run(body())
    assert item.status == DescribeItemStatus.COMPLETED
    assert item.caption == GENERIC_DRAFT
    assert item.alt_text_draft == "Ada stands by the window."
    assert item.alt_text_draft.startswith("Ada")
    assert "Pictured from left" not in (item.alt_text_draft or "")
    assert "Bob" not in (item.alt_text_draft or "")
    assert (item.provenance or {}).get("naming", {}).get("mode") == "grounded"
    assert [n["name"] for n in (item.provenance or {}).get("naming", {}).get("injected_names", [])] == ["Ada"]


def test_recognition_disabled_skips_fusion_despite_naming_agreement(monkeypatch):
    """HARM-F1: acx_recognition_enabled=off must reach the bulk effector.

    A tenant with naming_agreement_enabled=True still must not load fusion
    naming inputs or write naming.injected_names when the run's
    recognition_enabled flag is false.
    """
    import scene.application.describe_run_worker as wmod

    loads: list[dict] = []
    original = wmod.load_fusion_naming_inputs

    async def spy_load(**kwargs):
        loads.append(kwargs)
        return await original(**kwargs)

    monkeypatch.setattr(wmod, "load_fusion_naming_inputs", spy_load, raising=True)
    png = _png_bytes()

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        assert image_bytes == png
        return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT, caption=GENERIC_DRAFT)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True, with_identities=True)
        async with sf() as s:
            await _seed_confirmed_face(s, label="Ada", media_id=1, bbox=(10, 10, 20, 20), roster_id=uuid.uuid4())
            await s.commit()
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_run(
                tenant_id=TENANT_ID,
                media_ids=[1],
                images={1: (png, "image/png")},
                recognition_enabled=False,
            )
            await s.commit()
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=1.0
        )
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return items[0]

    item = asyncio.run(body())
    assert loads == []
    assert item.status == DescribeItemStatus.COMPLETED
    assert item.alt_text_draft == GENERIC_DRAFT
    assert (item.provenance or {}).get("naming", {}).get("injected_names", []) == []


def _fake_visual_facts_service(captured_faces: list):
    class _FakeFacts:
        caption = GENERIC_DRAFT

    class _FakeResponse:
        adapter = "seeded"
        model_id = "m"
        model_version = "v"
        prompt_or_task_version = "p"
        image_hash = "h"
        context_hash = "c"
        cached = False
        duration_ms = 1
        alt_text_draft = GENERIC_DRAFT
        visual_facts = _FakeFacts()
        # Seeded/CPU adapter: mirrors VisualFactsService's non-GPU tier.
        tier = DescriptionResultTier.PROVISIONAL_CPU

    class _FakeService:
        last_phrase_boxes = ()
        last_attachments = ()

        def __init__(self, **kwargs):
            pass

        async def describe(self, **kwargs):
            captured_faces.append(list(kwargs.get("confirmed_faces") or []))
            return _FakeResponse()

    return _FakeService


def test_bulk_item_loads_fusion_naming_inputs_once_and_shares_confirmed_faces(monkeypatch):
    """HARM-F3: Stage-2 fusion and Stage-3 preview share one naming snapshot.

    load_fusion_naming_inputs is called once per bulk item; a second load
    (router fallback or preview reload) would make this assertion go red.
    """
    from types import SimpleNamespace

    import scene.application.describe_run_worker as wmod
    import scene.interface_adapters.http.routers.describe_run as rmod

    loads: list[tuple[str, ...]] = []
    fusion_faces: list[list[str]] = []
    preview_faces: list[list[str]] = []
    policy = object()

    async def mutating_load(**kwargs):
        snapshot = ("Ada",) if not loads else ("Bob",)
        loads.append(snapshot)
        return list(snapshot), policy

    async def fake_naming_preview(**kwargs):
        preview_faces.append(list(kwargs.get("confirmed_faces") or []))
        return FUSED_DRAFT, object()

    monkeypatch.setattr(wmod, "load_fusion_naming_inputs", mutating_load, raising=True)
    monkeypatch.setattr(rmod, "load_fusion_naming_inputs", mutating_load, raising=False)
    monkeypatch.setattr(rmod, "VisualFactsService", _fake_visual_facts_service(fusion_faces))
    monkeypatch.setattr(wmod, "naming_preview", fake_naming_preview, raising=True)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True)
        run_id = await _seed_run(sf)
        describe_one = rmod._build_describe_one(
            session_factory=sf,
            tenant_id=TENANT_ID,
            adapter=SimpleNamespace(kind="seeded"),
            recognition_enabled=True,
        )
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=1.0
        )
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return items[0]

    item = asyncio.run(body())
    assert len(loads) == 1, f"expected one fusion naming load per bulk item, got {loads!r}"
    assert fusion_faces == [["Ada"]]
    assert preview_faces == [["Ada"]]
    assert fusion_faces == preview_faces
    assert item.status == DescribeItemStatus.COMPLETED
    assert item.alt_text_draft == FUSED_DRAFT


def test_disabled_naming_does_not_load_fusion_inputs_on_bulk_path(monkeypatch):
    """HARM-F3: recognition-off bulk items must not load fusion naming inputs."""
    from types import SimpleNamespace

    import scene.application.describe_run_worker as wmod
    import scene.interface_adapters.http.routers.describe_run as rmod

    loads: list[str] = []
    fusion_faces: list[list[str]] = []

    async def spy_load(**kwargs):
        loads.append("load")
        return ["Ada"], object()

    monkeypatch.setattr(wmod, "load_fusion_naming_inputs", spy_load, raising=True)
    monkeypatch.setattr(rmod, "load_fusion_naming_inputs", spy_load, raising=False)
    monkeypatch.setattr(rmod, "VisualFactsService", _fake_visual_facts_service(fusion_faces))

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True)
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_run(
                tenant_id=TENANT_ID,
                media_ids=[1],
                images={1: (b"rawbytes", "image/png")},
                recognition_enabled=False,
            )
            await s.commit()
        describe_one = rmod._build_describe_one(
            session_factory=sf,
            tenant_id=TENANT_ID,
            adapter=SimpleNamespace(kind="seeded"),
            recognition_enabled=False,
        )
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=1.0
        )
        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return items[0]

    item = asyncio.run(body())
    assert loads == []
    assert fusion_faces == [[]]
    assert item.status == DescribeItemStatus.COMPLETED
    assert item.alt_text_draft == GENERIC_DRAFT


def test_omitted_recognition_enabled_defaults_true_and_still_fuses():
    """HARM-F1: omitting recognition_enabled keeps today's naming-on behaviour."""
    png = _png_bytes()

    async def describe_one(media_id, image_bytes, content_type, *, naming_inputs=None):
        return DescribeItemOutcome(alt_text_draft=GENERIC_DRAFT, caption=GENERIC_DRAFT)

    async def body():
        path, engine, sf = await _make_db(naming_agreement_enabled=True, with_identities=True)
        async with sf() as s:
            await _seed_confirmed_face(s, label="Ada", media_id=1, bbox=(10, 10, 20, 20), roster_id=uuid.uuid4())
            await s.commit()
        run_id = await _seed_run(sf, image_bytes=png)
        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=1.0
        )
        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        await engine.dispose()
        os.unlink(path)
        return run, items[0]

    run, item = asyncio.run(body())
    assert run is not None
    assert run.recognition_enabled is True
    assert item.alt_text_draft == FUSED_DRAFT
    assert [n["name"] for n in (item.provenance or {}).get("naming", {}).get("injected_names", [])] == ["Ada"]
