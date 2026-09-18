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
from scene.application.identity_merge import NamingPolicy, NamingStatus, NormalizedBox, PhraseBox
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.application.visual_facts_service import VisualFactsService
from scene.domain.description import DescriptionAdapterKind
from scene.tests.identity_merge_helpers import make_face

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
            assert r2.attempt_timing.processing_ms == 0
            assert r2.attempt_timing.entered_adapter is False
            assert len(metrics.adapter_durations) == 1
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


def test_processing_measures_dispatch_only_and_records_failed_retries(monkeypatch):
    import pytest
    from scene.application import visual_facts_service as module

    clock = [0.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: clock[0])
    metrics = FakeMetrics()

    class Adapter(HostedAdapter):
        def describe(self, **kwargs):
            clock[0] += 2
            if len(metrics.adapter_durations) == 0:
                raise RuntimeError("retry")
            return super().describe(**kwargs)

    async def body():
        svc = VisualFactsService(adapter=Adapter(), metrics=metrics)

        async def readiness():
            clock[0] += 30

        async def fusion(**kwargs):
            clock[0] += 10
            return None

        monkeypatch.setattr(svc, "_run_fusion_stage", fusion)
        for attempt in range(2):
            if attempt == 0:
                with pytest.raises(RuntimeError, match="retry") as failed:
                    await svc.describe(
                        tenant_id=uuid.uuid4(), media_id=1, image_bytes=IMG, context=None, before_compute=readiness
                    )
            else:
                clock[0] += 60  # Retry backoff is outside adapter processing.
                response = await svc.describe(
                    tenant_id=uuid.uuid4(), media_id=1, image_bytes=IMG, context=None, before_compute=readiness
                )
                assert response.attempt_timing.processing_ms == 2000
                assert response.duration_ms == 42000
            assert failed.value.attempt_timing.processing_ms == 2000
        assert metrics.adapter_durations == [("hosted_provider", 2.0)] * 2

        async def unavailable():
            raise RuntimeError("not ready")

        with pytest.raises(RuntimeError, match="not ready") as unavailable_error:
            await svc.describe(
                tenant_id=uuid.uuid4(), media_id=1, image_bytes=IMG, context=None, before_compute=unavailable
            )
        assert unavailable_error.value.attempt_timing.processing_ms is None
        assert unavailable_error.value.attempt_timing.entered_adapter is False
        assert len(metrics.adapter_durations) == 2

    asyncio.run(body())


def test_cancelled_dispatch_is_measured_once(monkeypatch):
    import threading
    import pytest
    from scene.application import visual_facts_service as module

    clock = [0.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: clock[0])
    release = threading.Event()
    metrics = FakeMetrics()

    async def body():
        started = asyncio.Event()
        loop = asyncio.get_running_loop()

        class Adapter(HostedAdapter):
            def describe(self, **kwargs):
                loop.call_soon_threadsafe(started.set)
                release.wait(timeout=5)
                return super().describe(**kwargs)

        svc = VisualFactsService(adapter=Adapter(), metrics=metrics)
        task = asyncio.create_task(
            svc.describe(
                tenant_id=uuid.uuid4(),
                media_id=1,
                image_bytes=IMG,
                context=None,
            )
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            clock[0] = 3
            task.cancel()
            with pytest.raises(asyncio.CancelledError) as cancelled:
                await task
            assert cancelled.value.attempt_timing.entered_adapter is True
            assert cancelled.value.attempt_timing.processing_ms is None
            return cancelled.value.attempt_timing
        finally:
            release.set()

    timing = asyncio.run(body())  # Also joins the executor's remaining work.
    assert timing.processing_ms == 3000
    assert metrics.adapter_durations == [("hosted_provider", 3.0)]


def test_cancel_before_worker_start_marker_still_publishes_once(monkeypatch):
    import threading
    import pytest
    from scene.application import visual_facts_service as module

    gated = threading.Event()
    release = threading.Event()
    metrics = FakeMetrics()
    main_thread = threading.get_ident()
    clock = [0.0]

    def perf_counter():
        if threading.get_ident() != main_thread and not gated.is_set():
            gated.set()
            assert release.wait(timeout=5)
        return clock[0]

    monkeypatch.setattr(module.time, "perf_counter", perf_counter)

    class Adapter(HostedAdapter):
        def describe(self, **kwargs):
            clock[0] += 2
            return super().describe(**kwargs)

    async def body():
        svc = VisualFactsService(adapter=Adapter(), metrics=metrics)
        task = asyncio.create_task(
            svc.describe(
                tenant_id=uuid.uuid4(),
                media_id=1,
                image_bytes=IMG,
                context=None,
            )
        )
        try:
            async with asyncio.timeout(2):
                while not gated.is_set():
                    await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError) as cancelled:
                await task
            timing = cancelled.value.attempt_timing
            assert timing.entered_adapter is False
            assert timing.processing_ms is None
            assert metrics.adapter_durations == []
            return timing
        finally:
            release.set()

    timing = asyncio.run(body())
    assert timing.entered_adapter is True
    assert timing.processing_ms == 2000
    assert metrics.adapter_durations == [("hosted_provider", 2.0)]


REREALIZE_CAPTION = "A man stands by the window."
REREALIZE_NAMED = "Daniel stands by the window."
REREALIZE_PERSON = PhraseBox(
    phrase="A man",
    span_start=0,
    span_end=5,
    box=NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7),
)
REREALIZE_FACE = make_face(
    "Daniel",
    box=NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08),
    roster_id="roster-daniel",
)


class _GroundedCaptionAdapter:
    """Fixed caption + phrase boxes so cache-hit naming can re-merge without a VLM."""

    kind = DescriptionAdapterKind.SEEDED
    model_id = "rerealize-test"
    model_version = "1"
    prompt_or_task_version = "1"

    def __init__(self, *, caption: str = REREALIZE_CAPTION, phrase_boxes=()):
        self._caption = caption
        self._phrase_boxes = tuple(phrase_boxes)
        self.calls = 0

    def describe(self, *, image_bytes, context):
        self.calls += 1
        return AdapterResult(
            caption=self._caption,
            objects=("person",),
            ocr_text=None,
            alt_text_draft=self._caption,
            context_sources=(),
            context_applied=False,
            phrase_boxes=self._phrase_boxes,
        )


class _MemoryRepo:
    """In-memory cache-key repo matching VisualFactsService lookup/insert."""

    def __init__(self):
        self._rows: dict = {}

    def _key(self, *, tenant_id, image_hash, adapter, model_id, model_version, prompt_or_task_version, context_hash):
        return (
            str(tenant_id),
            image_hash,
            adapter,
            model_id,
            model_version,
            prompt_or_task_version,
            context_hash,
        )

    async def get_by_cache_key(self, **kwargs):
        return self._rows.get(self._key(**kwargs))

    async def insert_or_get_existing(self, record):
        key = self._key(
            tenant_id=record.tenant_id,
            image_hash=record.image_hash,
            adapter=record.adapter,
            model_id=record.model_id,
            model_version=record.model_version,
            prompt_or_task_version=record.prompt_or_task_version,
            context_hash=record.context_hash,
        )
        if key in self._rows:
            return self._rows[key], False
        self._rows[key] = record
        return record, True


def test_cache_hit_rerealizes_names_from_current_confirmed_faces():
    """TRIAGE0918-M-02: naming a face after the draft was cached reaches alt text."""
    tenant = uuid.uuid4()
    adapter = _GroundedCaptionAdapter(phrase_boxes=(REREALIZE_PERSON,))
    repo = _MemoryRepo()
    policy = NamingPolicy(agreement_enabled=True)

    async def body():
        svc = VisualFactsService(adapter=adapter, repository=repo)
        first = await svc.describe(tenant_id=tenant, media_id=7, image_bytes=IMG, context=CTX, naming_policy=policy)
        svc2 = VisualFactsService(adapter=adapter, repository=repo)
        second = await svc2.describe(
            tenant_id=tenant,
            media_id=8,
            image_bytes=IMG,
            context=CTX,
            confirmed_faces=[REREALIZE_FACE],
            naming_policy=policy,
        )
        return first, second

    first, second = asyncio.run(body())
    assert first.cached is False
    assert first.alt_text_draft == REREALIZE_CAPTION
    assert second.cached is True
    assert adapter.calls == 1
    assert second.alt_text_draft == REREALIZE_NAMED
    assert second.named_draft == REREALIZE_NAMED
    assert second.generic_draft == REREALIZE_CAPTION
    assert second.naming_provenance is not None
    assert second.naming_provenance.status is NamingStatus.APPLIED
    assert "Daniel" in second.naming_provenance.names_applied


def test_cache_hit_does_not_insert_name_when_policy_rejects():
    tenant = uuid.uuid4()
    adapter = _GroundedCaptionAdapter(phrase_boxes=(REREALIZE_PERSON,))
    repo = _MemoryRepo()

    async def body():
        svc = VisualFactsService(adapter=adapter, repository=repo)
        await svc.describe(tenant_id=tenant, media_id=7, image_bytes=IMG, context=CTX)
        svc2 = VisualFactsService(adapter=adapter, repository=repo)
        return await svc2.describe(
            tenant_id=tenant,
            media_id=8,
            image_bytes=IMG,
            context=CTX,
            confirmed_faces=[REREALIZE_FACE],
            naming_policy=NamingPolicy(agreement_enabled=False),
        )

    second = asyncio.run(body())
    assert second.cached is True
    assert adapter.calls == 1
    assert second.alt_text_draft == REREALIZE_CAPTION
    assert "Daniel" not in second.alt_text_draft
    assert second.named_draft == REREALIZE_CAPTION


def test_cache_hit_rerealizes_from_stored_caption_when_draft_already_named():
    tenant = uuid.uuid4()
    adapter = _GroundedCaptionAdapter(phrase_boxes=(REREALIZE_PERSON,))
    repo = _MemoryRepo()
    policy = NamingPolicy(agreement_enabled=True)

    async def body():
        svc = VisualFactsService(adapter=adapter, repository=repo)
        first = await svc.describe(tenant_id=tenant, media_id=7, image_bytes=IMG, context=CTX)
        stored = next(iter(repo._rows.values()))
        stored.alt_text_draft = "Someone stands by the window."
        svc2 = VisualFactsService(adapter=adapter, repository=repo)
        second = await svc2.describe(
            tenant_id=tenant,
            media_id=8,
            image_bytes=IMG,
            context=CTX,
            confirmed_faces=[REREALIZE_FACE],
            naming_policy=policy,
        )
        return first, second

    first, second = asyncio.run(body())
    assert first.alt_text_draft == REREALIZE_CAPTION
    assert second.cached is True
    assert adapter.calls == 1
    assert second.alt_text_draft == REREALIZE_NAMED
    assert second.generic_draft == REREALIZE_CAPTION


def test_cache_hit_without_base_caption_keeps_cached_draft_and_naming_status():
    tenant = uuid.uuid4()
    adapter = _GroundedCaptionAdapter(phrase_boxes=(REREALIZE_PERSON,))
    repo = _MemoryRepo()
    named_only = "Alex stands by the window."

    async def body():
        svc = VisualFactsService(adapter=adapter, repository=repo)
        await svc.describe(tenant_id=tenant, media_id=7, image_bytes=IMG, context=CTX)
        stored = next(iter(repo._rows.values()))
        stored.alt_text_draft = named_only
        stored.visual_facts = {**dict(stored.visual_facts or {}), "caption": ""}
        svc2 = VisualFactsService(adapter=adapter, repository=repo)
        return await svc2.describe(
            tenant_id=tenant,
            media_id=8,
            image_bytes=IMG,
            context=CTX,
            confirmed_faces=[REREALIZE_FACE],
            naming_policy=NamingPolicy(agreement_enabled=True),
        )

    second = asyncio.run(body())
    assert second.cached is True
    assert adapter.calls == 1
    assert second.alt_text_draft == named_only
    assert second.named_draft is None
    assert second.naming_provenance is None
