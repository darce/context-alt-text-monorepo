"""GPU-tier naming fusion and provenance contract tests."""

from __future__ import annotations

import asyncio
import logging
import os
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
from scene.application.identity_merge import (
    ConfirmedFace,
    NamingPolicy,
    NormalizedBox,
    PhraseBox,
    merge_identities,
)
from scene.domain.describe_run import DescribeItemStatus
from scene.domain.description import DescriptionResultTier

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-00000000f701")
GENERIC_DRAFT = "Two people stand by the window."


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (100, 50), color=(120, 120, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


def _embedding() -> list[float]:
    return [1.0] + [0.0] * (_DB_SETTINGS.pgvector_dimension - 1)


async def _make_db(*, naming_enabled: bool, with_identities: bool = False):
    path = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"gpu_tier_naming_{uuid.uuid4().hex}.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    tables: list[Table] = [Tenant.__table__, DescribeRun.__table__, DescribeRunItem.__table__]
    if with_identities:
        tables.extend(
            [MediaIdentity.__table__, IdentityCluster.__table__, IdentityMember.__table__, IdentityNameSuppression.__table__]
        )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=cast(list[Table], tables))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            Tenant(
                id=TENANT_ID,
                site_url="http://gpu-naming.test",
                naming_agreement_enabled=naming_enabled,
            )
        )
        await session.commit()
    return path, engine, session_factory


async def _seed_run(session_factory, *, recognition_enabled: bool = True):
    async with session_factory() as session:
        run_id = await DescribeRunRepository(session).create_run(
            tenant_id=TENANT_ID,
            media_ids=[1],
            images={1: (_png_bytes(), "image/png")},
            recognition_enabled=recognition_enabled,
        )
        await session.commit()
    return run_id


async def _seed_face(session, *, label: str, x: int, cluster_id=None, roster_id=None):
    cluster = None
    if cluster_id is None:
        cluster = IdentityCluster(
            tenant_id=TENANT_ID,
            label=label,
            user_confirmed=True,
            roster_id=roster_id or uuid.uuid4(),
        )
        session.add(cluster)
        await session.flush()
        cluster_id = cluster.id
    identity = MediaIdentity(
        tenant_id=TENANT_ID,
        media_id=1,
        media_url=f"http://gpu-naming.test/{x}.png",
        bbox_x=x,
        bbox_y=10,
        bbox_width=20,
        bbox_height=20,
        confidence=0.97,
        embedding=_embedding(),
        embedding_model="buffalo_l@insightface",
    )
    session.add(identity)
    await session.flush()
    session.add(IdentityMember(tenant_id=TENANT_ID, cluster_id=cluster_id, identity_id=identity.id, similarity=0.9))
    return cluster_id


class FakeGpuAdapter:
    """A final-GPU adapter result with no phrase grounding boxes."""

    async def __call__(self, media_id, image_bytes, content_type, *, naming_inputs=None):
        return DescribeItemOutcome(
            alt_text_draft=GENERIC_DRAFT,
            caption=GENERIC_DRAFT,
            phrase_boxes=(),
            tier=DescriptionResultTier.FINAL_GPU,
        )


async def _run_fake_gpu(*, naming_enabled: bool, seed_faces: bool = True, recognition_enabled: bool = True):
    path, engine, session_factory = await _make_db(naming_enabled=naming_enabled, with_identities=seed_faces)
    if seed_faces:
        async with session_factory() as session:
            await _seed_face(session, label="Bob", x=60)
            await _seed_face(session, label="Ada", x=10)
            await session.commit()
    run_id = await _seed_run(session_factory, recognition_enabled=recognition_enabled)
    await run_describe_job(
        tenant_id=TENANT_ID,
        run_id=run_id,
        session_factory=session_factory,
        describe_one=FakeGpuAdapter(),
        timeout_seconds=1.0,
    )
    async with session_factory() as session:
        item = (await DescribeRunRepository(session).list_run_items(tenant_id=TENANT_ID, run_id=run_id))[0]
    await engine.dispose()
    os.unlink(path)
    return item


def test_fake_final_gpu_adapter_fuses_positional_names_and_disabled_run_does_not():
    enabled = asyncio.run(_run_fake_gpu(naming_enabled=True))
    disabled = asyncio.run(_run_fake_gpu(naming_enabled=False))

    assert enabled.status == DescribeItemStatus.COMPLETED
    assert enabled.tier == DescriptionResultTier.FINAL_GPU
    assert enabled.alt_text_draft == f"{GENERIC_DRAFT} Pictured from left: Ada and Bob."
    enabled_naming = (enabled.provenance or {})["naming"]
    assert enabled_naming["status"] == "applied"
    assert enabled_naming["realizer"] == "positional_fallback"
    assert enabled_naming["names_applied"] == ["Ada", "Bob"]

    assert disabled.status == DescribeItemStatus.COMPLETED
    assert disabled.tier == DescriptionResultTier.FINAL_GPU
    assert disabled.alt_text_draft == GENERIC_DRAFT
    disabled_naming = (disabled.provenance or {})["naming"]
    assert disabled_naming == {
        "status": "disabled",
        "realizer": None,
        "names_applied": [],
    }


def test_no_faces_provenance_is_explicit():
    item = asyncio.run(_run_fake_gpu(naming_enabled=True, seed_faces=False))

    assert item.status == DescribeItemStatus.COMPLETED
    assert item.alt_text_draft == GENERIC_DRAFT
    assert (item.provenance or {})["naming"] == {
        "status": "no_faces",
        "realizer": None,
        "names_applied": [],
    }


def test_slow_naming_preview_skips_budget_without_failing_item(monkeypatch, caplog):
    import scene.application.describe_run_worker as worker

    async def slow_preview(**kwargs):
        await asyncio.sleep(1)
        raise AssertionError("the preview should be cancelled by the naming budget")

    monkeypatch.setattr(worker, "NAMING_BUDGET_SECONDS", 0.01)
    monkeypatch.setattr(worker, "naming_preview", slow_preview)
    with caplog.at_level(logging.WARNING):
        item = asyncio.run(_run_fake_gpu(naming_enabled=True))

    assert item.status == DescribeItemStatus.COMPLETED
    assert item.alt_text_draft == GENERIC_DRAFT
    assert (item.provenance or {})["naming"] == {
        "status": "skipped_budget",
        "realizer": None,
        "names_applied": [],
    }
    assert "naming budget" in caplog.text.lower()


def _face(label: str, *, cluster_id: str, x: float) -> ConfirmedFace:
    return ConfirmedFace(
        identity_id=f"identity-{cluster_id}-{x}",
        cluster_id=cluster_id,
        roster_id=f"roster-{cluster_id}",
        label=label,
        detection_confidence=0.97,
        box=NormalizedBox(x=x, y=0.2, width=0.05, height=0.08),
    )


def test_positional_names_keep_distinct_people_with_shared_label_and_dedupe_one_person():
    policy = NamingPolicy(agreement_enabled=True)
    distinct_people = merge_identities(
        caption=GENERIC_DRAFT,
        phrase_boxes=[],
        confirmed_faces=[_face("Alex", cluster_id="person-a", x=0.1), _face("Alex", cluster_id="person-b", x=0.6)],
        policy=policy,
    )
    one_person = merge_identities(
        caption=GENERIC_DRAFT,
        phrase_boxes=[],
        confirmed_faces=[_face("Ada", cluster_id="person-a", x=0.1), _face("Ada", cluster_id="person-a", x=0.6)],
        policy=policy,
    )

    assert distinct_people.named_draft.endswith("Pictured from left: Alex and Alex.")
    assert [name.name for name in distinct_people.provenance.injected_names] == ["Alex", "Alex"]
    assert one_person.named_draft.endswith("Pictured from left: Ada.")
    assert [name.name for name in one_person.provenance.injected_names] == ["Ada"]


def test_grounded_names_keep_distinct_people_with_shared_label():
    caption = "A person waves and a person smiles."
    second_start = caption.index("a person")
    result = merge_identities(
        caption=caption,
        phrase_boxes=[
            PhraseBox(
                phrase="A person",
                span_start=0,
                span_end=len("A person"),
                box=NormalizedBox(x=0.1, y=0.1, width=0.2, height=0.7),
            ),
            PhraseBox(
                phrase="a person",
                span_start=second_start,
                span_end=second_start + len("a person"),
                box=NormalizedBox(x=0.6, y=0.1, width=0.2, height=0.7),
            ),
        ],
        confirmed_faces=[_face("Alex", cluster_id="person-a", x=0.15), _face("Alex", cluster_id="person-b", x=0.65)],
        policy=NamingPolicy(agreement_enabled=True),
    )

    assert result.named_draft == "Alex waves and Alex smiles."
    assert [name.name for name in result.provenance.injected_names] == ["Alex", "Alex"]
    assert list(result.provenance.names_applied) == ["Alex", "Alex"]
    assert result.provenance.realizer.value == "grounded"


def test_invalid_phrase_spans_are_not_used_for_gpu_provenance():
    caption = "A person stands."
    policy = NamingPolicy(agreement_enabled=True)
    invalid = PhraseBox(
        phrase="A person",
        span_start=-1,
        span_end=-1,
        box=NormalizedBox(x=0.1, y=0.1, width=0.1, height=0.2),
    )
    result = merge_identities(
        caption=caption,
        phrase_boxes=[invalid],
        confirmed_faces=[_face("Ada", cluster_id="person-a", x=0.1)],
        policy=policy,
    )

    assert result.named_draft == caption
    assert result.provenance.injected_names == ()
