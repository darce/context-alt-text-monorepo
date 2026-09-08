"""S4: VisualFactsService — cache→generate→persist→audit, DB-optional degrade."""

import asyncio
import uuid
from typing import cast

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import ImageDescription
from scene.application.description_adapter import AdapterResult
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.application.visual_facts_service import VisualFactsService
from scene.domain.description import DescriptionAdapterKind

IMG = b"\x89PNG service test bytes"
CTX = {"title": "Cat", "caption": "x"}


class CountingAdapter:
    """Delegates to a real adapter but counts describe() calls."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = 0

    @property
    def kind(self):
        return self._inner.kind

    @property
    def model_id(self):
        return self._inner.model_id

    @property
    def model_version(self):
        return self._inner.model_version

    @property
    def prompt_or_task_version(self):
        return self._inner.prompt_or_task_version

    def describe(self, *, image_bytes, context):
        self.calls += 1
        return self._inner.describe(image_bytes=image_bytes, context=context)


class FakeAudit:
    def __init__(self):
        self.events = []

    async def record(self, *, tenant_id, event_type, payload):
        self.events.append((event_type, payload))


class FakeMetrics:
    def __init__(self):
        self.requests = []
        self.cache_hits = []
        self.adapter_durations = []

    def record_request(self, *, adapter, result):
        self.requests.append((adapter, result))

    def record_cache_hit(self, *, adapter):
        self.cache_hits.append(adapter)

    def observe_adapter_duration(self, *, adapter, duration_seconds):
        self.adapter_durations.append((adapter, duration_seconds))


class HostedAdapter:
    kind = DescriptionAdapterKind.HOSTED_PROVIDER
    model_id = "hosted-test"
    model_version = "1"
    prompt_or_task_version = "1"

    def describe(self, *, image_bytes, context):
        return AdapterResult(
            caption="Hosted caption.",
            objects=("object",),
            ocr_text=None,
            alt_text_draft="Hosted caption.",
            context_sources=(),
            context_applied=False,
        )


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=cast(list[Table], [ImageDescription.__table__]))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_first_call_generates_persists_audits_then_cache_hit_skips_adapter():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        adapter = CountingAdapter(SeededDescriptionAdapter())
        audit = FakeAudit()
        metrics = FakeMetrics()
        async with sf() as s:
            svc = VisualFactsService(
                adapter=adapter,
                repository=ImageDescriptionRepository(s),
                audit_sink=audit,
                metrics=metrics,
            )
            r1 = await svc.describe(tenant_id=tenant, media_id=7, image_bytes=IMG, context=CTX)
            await s.commit()
        assert r1.cached is False
        assert adapter.calls == 1
        assert len(audit.events) == 1 and audit.events[0][0] == "description.generated"
        assert metrics.requests == [("seeded", "generated")]
        assert len(metrics.adapter_durations) == 1

        async with sf() as s:
            row = await ImageDescriptionRepository(s).get_by_cache_key(
                tenant_id=tenant,
                image_hash=r1.image_hash,
                adapter="seeded",
                model_id=r1.model_id,
                model_version=r1.model_version,
                prompt_or_task_version=r1.prompt_or_task_version,
                context_hash=r1.context_hash,
            )
            assert row is not None  # persisted
            svc2 = VisualFactsService(
                adapter=adapter,
                repository=ImageDescriptionRepository(s),
                audit_sink=audit,
                metrics=metrics,
            )
            r2 = await svc2.describe(tenant_id=tenant, media_id=8, image_bytes=IMG, context=CTX)
            assert r2.cached is True
            assert r2.media_id == 8
            assert adapter.calls == 1  # NOT called again on cache hit
            assert len(audit.events) == 2
            assert audit.events[1][0] == "description.cache_hit"
            assert metrics.cache_hits == ["seeded"]
            assert metrics.requests[-1] == ("seeded", "cache_hit")
            assert r2.alt_text_draft == r1.alt_text_draft
        await engine.dispose()

    asyncio.run(body())


class PinRevisionAdapter:
    """Two instances that differ only in model_id (hub pin / model_revision)."""

    kind = DescriptionAdapterKind.GPU
    model_version = "Q4_K_M"
    prompt_or_task_version = "3"

    def __init__(self, *, model_id: str, caption: str) -> None:
        self.model_id = model_id
        self._caption = caption
        self.calls = 0

    def describe(self, *, image_bytes, context):
        self.calls += 1
        return AdapterResult(
            caption=self._caption,
            objects=(),
            ocr_text=None,
            alt_text_draft=self._caption,
            context_sources=(),
            context_applied=False,
        )


def test_model_revision_pin_bump_misses_cache():
    """W3-E-04: adapters that differ only in hub pin must not share a cache row."""

    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        pin_a = "unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@" + ("a" * 40)
        pin_b = "unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@" + ("b" * 40)
        adapter_a = PinRevisionAdapter(model_id=pin_a, caption="caption A")
        adapter_b = PinRevisionAdapter(model_id=pin_b, caption="caption B")
        async with sf() as s:
            r1 = await VisualFactsService(
                adapter=adapter_a,
                repository=ImageDescriptionRepository(s),
            ).describe(tenant_id=tenant, media_id=7, image_bytes=IMG, context=CTX)
            await s.commit()
        async with sf() as s:
            r2 = await VisualFactsService(
                adapter=adapter_b,
                repository=ImageDescriptionRepository(s),
            ).describe(tenant_id=tenant, media_id=8, image_bytes=IMG, context=CTX)
            await s.commit()
        assert r1.cached is False
        assert r2.cached is False, "pin bump must miss-cache, not reuse the prior caption"
        assert adapter_a.calls == 1
        assert adapter_b.calls == 1
        assert r1.model_id == pin_a
        assert r2.model_id == pin_b
        assert r1.alt_text_draft == "caption A"
        assert r2.alt_text_draft == "caption B"
        await engine.dispose()

    asyncio.run(body())


def test_db_down_degrades_to_adapter_only():
    async def body():
        adapter = CountingAdapter(SeededDescriptionAdapter())
        svc = VisualFactsService(adapter=adapter, repository=None, audit_sink=None)
        r = await svc.describe(tenant_id=uuid.uuid4(), media_id=1, image_bytes=b"x", context=None)
        assert r.cached is False
        assert adapter.calls == 1
        assert r.duration_ms >= 0
        assert r.adapter.value == "seeded"

    asyncio.run(body())


def test_response_is_full_15_field_contract():
    async def body():
        svc = VisualFactsService(adapter=SeededDescriptionAdapter())
        r = await svc.describe(tenant_id=uuid.uuid4(), media_id=1, image_bytes=b"x", context={"a": 1})
        dumped = r.model_dump()
        # 17 core + 3 E19-4a preview + 1 E20-FUSION attachment_provenance
        # + 1 ALTQ-1 alt_text_long
        assert len(dumped) == 22
        assert dumped["generic_draft"] is None and dumped["named_draft"] is None
        assert dumped["provider_disclosure"]["provider"] == "none"
        assert dumped["context_used"] == {"sources": [], "applied": False}
        assert dumped["retention_class"] == "retain_all"

    asyncio.run(body())


class DualLengthAdapter:
    """ALTQ-1: an adapter that produces both the short draft and a long surface."""

    kind = DescriptionAdapterKind.SEEDED
    model_id = "dual-length-test"
    model_version = "1"
    prompt_or_task_version = "1"

    LONG = "A tabby cat lounging on a woven mat in warm afternoon light near a window."

    def describe(self, *, image_bytes, context):
        return AdapterResult(
            caption="A cat on a mat.",
            objects=("cat", "mat"),
            ocr_text=None,
            alt_text_draft="A cat on a mat.",
            context_sources=(),
            context_applied=False,
            alt_text_long=self.LONG,
        )


def test_alt_text_long_flows_from_adapter_to_response():
    async def body():
        svc = VisualFactsService(adapter=DualLengthAdapter())
        r = await svc.describe(tenant_id=uuid.uuid4(), media_id=1, image_bytes=b"x", context=None)
        assert r.alt_text_long == DualLengthAdapter.LONG
        assert r.model_dump()["alt_text_long"] == DualLengthAdapter.LONG

    asyncio.run(body())


def test_alt_text_long_absent_defaults_to_none():
    async def body():
        # Old adapters never set alt_text_long — the wire value stays null.
        svc = VisualFactsService(adapter=SeededDescriptionAdapter())
        r = await svc.describe(tenant_id=uuid.uuid4(), media_id=1, image_bytes=b"x", context=None)
        assert r.alt_text_long is None

    asyncio.run(body())


def test_alt_text_long_persists_and_survives_cache_hit():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        adapter = CountingAdapter(DualLengthAdapter())
        async with sf() as s:
            svc = VisualFactsService(adapter=adapter, repository=ImageDescriptionRepository(s))
            r1 = await svc.describe(tenant_id=tenant, media_id=7, image_bytes=IMG, context=CTX)
            await s.commit()
        assert r1.cached is False
        assert r1.alt_text_long == DualLengthAdapter.LONG

        async with sf() as s:
            svc2 = VisualFactsService(adapter=adapter, repository=ImageDescriptionRepository(s))
            r2 = await svc2.describe(tenant_id=tenant, media_id=8, image_bytes=IMG, context=CTX)
            assert r2.cached is True
            assert adapter.calls == 1
            assert r2.alt_text_long == DualLengthAdapter.LONG
        await engine.dispose()

    asyncio.run(body())


def test_hosted_provider_disclosure_marks_service_boundary_left():
    async def body():
        svc = VisualFactsService(adapter=HostedAdapter())
        r = await svc.describe(tenant_id=uuid.uuid4(), media_id=1, image_bytes=b"x", context=None)
        assert r.provider_disclosure.provider.value == "hosted"
        assert r.provider_disclosure.left_service_boundary is True

    asyncio.run(body())
