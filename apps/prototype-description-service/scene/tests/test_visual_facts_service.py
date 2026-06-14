"""S4: VisualFactsService — cache→generate→persist→audit, DB-optional degrade."""

import asyncio
import uuid

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
        await conn.run_sync(Base.metadata.create_all, tables=[ImageDescription.__table__])
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_first_call_generates_persists_audits_then_cache_hit_skips_adapter():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.uuid4()
        adapter = CountingAdapter(SeededDescriptionAdapter())
        audit = FakeAudit()
        async with sf() as s:
            svc = VisualFactsService(adapter=adapter, repository=ImageDescriptionRepository(s), audit_sink=audit)
            r1 = await svc.describe(tenant_id=tenant, media_id=7, image_bytes=IMG, context=CTX)
            await s.commit()
        assert r1.cached is False
        assert adapter.calls == 1
        assert len(audit.events) == 1 and audit.events[0][0] == "description.generated"

        async with sf() as s:
            row = await ImageDescriptionRepository(s).get_by_cache_key(
                tenant_id=tenant,
                image_hash=r1.image_hash,
                adapter="seeded",
                model_version=r1.model_version,
                prompt_or_task_version=r1.prompt_or_task_version,
                context_hash=r1.context_hash,
            )
            assert row is not None  # persisted
            svc2 = VisualFactsService(adapter=adapter, repository=ImageDescriptionRepository(s), audit_sink=audit)
            r2 = await svc2.describe(tenant_id=tenant, media_id=8, image_bytes=IMG, context=CTX)
            assert r2.cached is True
            assert r2.media_id == 8
            assert adapter.calls == 1  # NOT called again on cache hit
            assert len(audit.events) == 1  # no audit on cache hit
            assert r2.alt_text_draft == r1.alt_text_draft
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
        assert len(dumped) == 15
        assert dumped["provider_disclosure"]["provider"] == "none"
        assert dumped["context_used"] == {"sources": [], "applied": False}
        assert dumped["retention_class"] == "retain_all"

    asyncio.run(body())


def test_hosted_provider_disclosure_marks_service_boundary_left():
    async def body():
        svc = VisualFactsService(adapter=HostedAdapter())
        r = await svc.describe(tenant_id=uuid.uuid4(), media_id=1, image_bytes=b"x", context=None)
        assert r.provider_disclosure.provider.value == "hosted"
        assert r.provider_disclosure.left_service_boundary is True

    asyncio.run(body())
