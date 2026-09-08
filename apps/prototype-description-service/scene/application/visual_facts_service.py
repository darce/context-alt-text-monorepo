"""VisualFactsService (E19-1 S4): the synchronous describe use case.

validate → hash → cache-read → adapter → (E20-FUSION stage) → persist → audit →
duration. DB-optional: with ``repository=None`` (DB down) it degrades to
adapter-only (``cached=False``, no persist, no audit), mirroring recognition's
optional-session degradation.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from pydantic import ValidationError

from db.models.scene import ImageDescription
from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.fusion.reconcile import Attachment, reconcile_context_facts
from scene.application.hashing import compute_context_hash, compute_image_hash
from scene.application.identity_merge.merge import ConfirmedFace, NormalizedBox, PhraseBox
from scene.application.identity_merge.policy import NamingPolicy
from scene.application.visual_facts_pass import (
    VisualFactsPass,
    VisualFactsPrior,
    VisualFactsPriorSource,
)
from scene.config.profiles import DescriptionProfile
from scene.domain.description import DescriptionAdapterKind, DescriptionResultTier, ProviderMode, RetentionClass
from scene.interface_adapters.http.schemas.requests import ContextPack
from scene.interface_adapters.http.schemas.responses import (
    AttachmentFactProvenance,
    AttachmentProvenance,
    ContextUsed,
    ProviderDisclosure,
    VisualFacts,
    VisualFactsResponse,
)

_logger = logging.getLogger(__name__)

_PROVIDER_FOR_ADAPTER = {
    DescriptionAdapterKind.SEEDED: ProviderMode.NONE,
    DescriptionAdapterKind.LOCAL_CPU: ProviderMode.LOCAL,
    # GPU (e.g. Phi-4) runs on our own host — bytes stay inside the boundary.
    DescriptionAdapterKind.GPU: ProviderMode.LOCAL,
    DescriptionAdapterKind.HOSTED_PROVIDER: ProviderMode.HOSTED,
}


class AuditSink(Protocol):
    async def record(self, *, tenant_id: uuid.UUID, event_type: str, payload: dict[str, Any]) -> None: ...


class DescriptionMetrics(Protocol):
    def record_request(self, *, adapter: str, result: str) -> None: ...

    def record_cache_hit(self, *, adapter: str) -> None: ...

    def observe_adapter_duration(self, *, adapter: str, duration_seconds: float) -> None: ...


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def build_visual_facts_envelope(
    *,
    result: AdapterResult,
    adapter: DescriptionAdapter,
    tenant_id: uuid.UUID,
    media_id: int,
    image_bytes: bytes,
    context: Mapping[str, Any] | None,
    tier: DescriptionResultTier,
    result_generation: int,
    duration_ms: int,
    retention_class: RetentionClass = RetentionClass.RETAIN_ALL,
) -> dict[str, Any]:
    """Build the 17-field VisualFactsResponse envelope from an adapter result."""
    image_hash = compute_image_hash(image_bytes)
    context_hash = compute_context_hash(context)
    provider = _PROVIDER_FOR_ADAPTER[adapter.kind]
    response = VisualFactsResponse(
        tenant_id=str(tenant_id),
        media_id=media_id,
        image_hash=image_hash,
        context_hash=context_hash,
        adapter=adapter.kind,
        model_id=adapter.model_id,
        model_version=adapter.model_version,
        prompt_or_task_version=adapter.prompt_or_task_version,
        visual_facts=VisualFacts(
            caption=result.caption,
            objects=list(result.objects),
            ocr_text=result.ocr_text,
        ),
        alt_text_draft=result.alt_text_draft,
        alt_text_long=result.alt_text_long,
        context_used=ContextUsed(sources=list(result.context_sources), applied=result.context_applied),
        provider_disclosure=ProviderDisclosure(
            provider=provider,
            left_service_boundary=provider is ProviderMode.HOSTED,
        ),
        cached=False,
        duration_ms=duration_ms,
        retention_class=retention_class,
        tier=tier,
        result_generation=result_generation,
    )
    return response.model_dump(mode="json")


def phrase_boxes_to_json(phrase_boxes) -> list[dict[str, Any]] | None:
    if not phrase_boxes:
        return None
    return [
        {
            "phrase": pb.phrase,
            "span": [pb.span_start, pb.span_end],
            "box": [pb.box.x, pb.box.y, pb.box.width, pb.box.height],
        }
        for pb in phrase_boxes
    ]


def _phrase_boxes_from_json(payload) -> tuple[PhraseBox, ...]:
    if not payload:
        return ()
    boxes: list[PhraseBox] = []
    for item in payload:
        try:
            x, y, w, h = (float(v) for v in item["box"])
            start, end = (int(v) for v in item["span"])
            boxes.append(
                PhraseBox(
                    phrase=str(item["phrase"]),
                    span_start=start,
                    span_end=end,
                    box=NormalizedBox(x=x, y=y, width=w, height=h),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # malformed persisted row: skip, naming degrades safely
    return tuple(boxes)


class VisualFactsService:
    def __init__(
        self,
        *,
        adapter: DescriptionAdapter,
        repository: ImageDescriptionRepository | None = None,
        audit_sink: AuditSink | None = None,
        metrics: DescriptionMetrics | None = None,
        retention_class: RetentionClass = RetentionClass.RETAIN_ALL,
        generation_timeout_seconds: float | None = None,
        profile: DescriptionProfile | None = None,
    ) -> None:
        self._adapter = adapter
        self._repo = repository
        self._audit = audit_sink
        self._metrics = metrics
        self._retention = retention_class
        self._timeout = generation_timeout_seconds
        self._profile = profile if profile is not None else DescriptionProfile.SEEDED
        # E19-4a S4: the freshly generated AdapterResult (None on cache hits).
        # The service is constructed per request, so this is request-scoped.
        self.last_adapter_result: AdapterResult | None = None
        # Phrase-grounding boxes for the naming preview — from the adapter on
        # generation, restored from the cached row on cache hits so both paths
        # produce the same named draft (E19-4A-S4-BR-03).
        self.last_phrase_boxes: tuple[PhraseBox, ...] = ()
        # E20-FUSION: last Stage-2 attachment list (empty on cache hits).
        self.last_attachments: tuple[Attachment, ...] = ()

    async def describe(
        self,
        *,
        tenant_id: uuid.UUID,
        media_id: int,
        image_bytes: bytes,
        context: Mapping[str, Any] | None,
        confirmed_faces: Sequence[ConfirmedFace] = (),
        naming_policy: NamingPolicy | None = None,
        before_compute: Callable[[], Awaitable[None]] | None = None,
    ) -> VisualFactsResponse:
        start = time.perf_counter()
        image_hash = compute_image_hash(image_bytes)
        context_hash = compute_context_hash(context)

        if self._repo is not None:
            row = await self._repo.get_by_cache_key(
                tenant_id=tenant_id,
                image_hash=image_hash,
                adapter=self._adapter.kind.value,
                model_id=self._adapter.model_id,
                model_version=self._adapter.model_version,
                prompt_or_task_version=self._adapter.prompt_or_task_version,
                context_hash=context_hash,
            )
            if row is not None:
                response = self._cache_hit_response(
                    row,
                    start=start,
                    media_id=media_id,
                    context=context,
                    confirmed_faces=confirmed_faces,
                    naming_policy=naming_policy,
                )
                await self._record_cache_hit(tenant_id=tenant_id, media_id=media_id, image_hash=image_hash)
                return response

        # Charge / side-effects only when real adapter compute is about to run
        # (cache hits and decorative short-circuits never reach here).
        if before_compute is not None:
            await before_compute()

        # Offload to a thread so a slow adapter (local_cpu Florence ~30-60s) never
        # blocks the event loop — otherwise asyncpg drops the open DB connection
        # mid-request and the persist fails. Seeded is instant, so the overhead is
        # negligible. (A dedicated worker/queue is the heavier production option.)
        adapter_start = time.perf_counter()
        call = asyncio.to_thread(self._adapter.describe, image_bytes=image_bytes, context=context)
        result = await (asyncio.wait_for(call, self._timeout) if self._timeout else call)
        self.last_adapter_result = result
        self.last_phrase_boxes = tuple(result.phrase_boxes)
        self._observe_adapter_duration(time.perf_counter() - adapter_start)

        # E20-FUSION Stage-2 reconcile between adapter and response mapping.
        attachment_provenance = await self._run_fusion_stage(
            context=context,
            adapter_result=result,
            confirmed_faces=confirmed_faces,
            naming_policy=naming_policy,
        )

        response = self._result_to_response(
            tenant_id=tenant_id,
            media_id=media_id,
            image_hash=image_hash,
            context_hash=context_hash,
            caption=result.caption,
            objects=list(result.objects),
            ocr_text=result.ocr_text,
            alt_text_draft=result.alt_text_draft,
            alt_text_long=result.alt_text_long,
            context_sources=list(result.context_sources),
            context_applied=result.context_applied,
            duration_ms=_elapsed_ms(start),
            attachment_provenance=attachment_provenance,
        )

        if self._repo is not None:
            new_row = self._response_to_row(response)
            new_row.phrase_boxes = phrase_boxes_to_json(result.phrase_boxes)
            row, inserted = await self._repo.insert_or_get_existing(new_row)
            if not inserted:
                response = self._cache_hit_response(
                    row,
                    start=start,
                    media_id=media_id,
                    context=context,
                    confirmed_faces=confirmed_faces,
                    naming_policy=naming_policy,
                )
                await self._record_cache_hit(tenant_id=tenant_id, media_id=media_id, image_hash=image_hash)
                return response
            if self._audit is not None:
                await self._audit.record(
                    tenant_id=tenant_id,
                    event_type="description.generated",
                    payload={"media_id": media_id, "image_hash": image_hash, "adapter": response.adapter.value},
                )
        self._record_request(result="generated")
        return response

    async def _run_fusion_stage(
        self,
        *,
        context: Mapping[str, Any] | None,
        adapter_result: AdapterResult,
        confirmed_faces: Sequence[ConfirmedFace],
        naming_policy: NamingPolicy | None,
    ) -> AttachmentProvenance | None:
        """Stage-2 reconcile → wire attachment provenance.

        Fail-open (S3A-02): provenance is an additive-optional enrichment, so
        any fusion failure logs and returns ``None`` instead of discarding a
        successful generation.

        The prior is derived from the main (context-applied) caption the phrase
        boxes are grounded against. A separate Stage-1 isolation inference was
        removed (EH-02): ``reconcile_context_facts`` reads only ``prior.caption``
        and that caption is always the main-pass caption, so a second pass could
        not change any decision — it was pure discarded inference on GPU tiers.
        Re-introduce an anchor pass only when its evidence actually feeds a
        reconciliation outcome (VLM-3 GPU track), proven by a falsifiable test.

        Stage-3 identity prose composition reuses the route-level
        ``merge_identities`` path (``_naming_preview``); Stage-2 already calls
        ``merge_identities`` for detector-backed identity attach decisions.
        """
        try:
            context_pack = _coerce_context_pack(context)
            if context_pack is None:
                self.last_attachments = ()
                return _attachments_to_provenance(())
            attachments = self._reconcile(
                context_pack=context_pack,
                visual_prior=VisualFactsPass.from_caption(result=adapter_result),
                adapter_result=adapter_result,
                confirmed_faces=confirmed_faces,
                naming_policy=naming_policy,
            )
            self.last_attachments = attachments
            return _attachments_to_provenance(attachments)
        except Exception:  # noqa: BLE001 - provenance must never fail the describe
            _logger.exception("fusion stage failed; describe degrades to no attachment provenance")
            self.last_attachments = ()
            return None

    def _reconcile(
        self,
        *,
        context_pack: ContextPack,
        visual_prior: VisualFactsPrior,
        adapter_result: AdapterResult,
        confirmed_faces: Sequence[ConfirmedFace],
        naming_policy: NamingPolicy | None,
    ) -> tuple[Attachment, ...]:
        """Stage-2: reconcile ContextPack facts against the main-pass caption.

        ``reconcile_context_facts`` feeds ``visual_prior.caption`` to
        ``merge_identities`` together with ``phrase_boxes`` whose spans index the
        MAIN context-applied caption, so the prior caption must be that caption.
        """
        return tuple(
            reconcile_context_facts(
                context_pack=context_pack,
                visual_prior=visual_prior,
                confirmed_faces=confirmed_faces,
                phrase_boxes=list(adapter_result.phrase_boxes),
                naming_policy=naming_policy,
            )
        )

    def _cache_hit_response(
        self,
        row: ImageDescription,
        *,
        start: float,
        media_id: int,
        context: Mapping[str, Any] | None,
        confirmed_faces: Sequence[ConfirmedFace],
        naming_policy: NamingPolicy | None,
    ) -> VisualFactsResponse:
        """Cached row → response with Stage-2 provenance recomputed (S3A-03).

        Attachments are not persisted; recomputing from the cached caption +
        restored phrase boxes is deterministic (no inference), so a cache hit
        carries the same attachment provenance as the original generation.
        Fail-open like the fresh path: a recompute failure yields ``None``.
        """
        response = self._row_to_response(row, cached=True, duration_ms=_elapsed_ms(start), media_id=media_id)
        self.last_phrase_boxes = _phrase_boxes_from_json(row.phrase_boxes)
        provenance: AttachmentProvenance | None
        try:
            context_pack = _coerce_context_pack(context)
            attachments: tuple[Attachment, ...] = ()
            if context_pack is not None:
                visual_facts = dict(row.visual_facts or {})
                context_used = dict(row.context_used or {})
                prior = VisualFactsPrior(
                    caption=str(visual_facts.get("caption", "")),
                    objects=list(visual_facts.get("objects") or []),
                    text=visual_facts.get("ocr_text"),
                    source=VisualFactsPriorSource.CAPTION_DERIVED,
                    derived_from_context_applied_caption=bool(context_used.get("applied")),
                )
                attachments = tuple(
                    reconcile_context_facts(
                        context_pack=context_pack,
                        visual_prior=prior,
                        confirmed_faces=confirmed_faces,
                        phrase_boxes=list(self.last_phrase_boxes),
                        naming_policy=naming_policy,
                    )
                )
            provenance = _attachments_to_provenance(attachments)
        except Exception:  # noqa: BLE001 - provenance must never fail the describe
            _logger.exception("fusion recompute failed on cache hit; degrading to no attachment provenance")
            attachments, provenance = (), None
        self.last_attachments = attachments
        return response.model_copy(update={"attachment_provenance": provenance})

    async def _record_cache_hit(self, *, tenant_id: uuid.UUID, media_id: int, image_hash: str) -> None:
        if self._audit is not None:
            await self._audit.record(
                tenant_id=tenant_id,
                event_type="description.cache_hit",
                payload={"media_id": media_id, "image_hash": image_hash, "adapter": self._adapter.kind.value},
            )
        if self._metrics is not None:
            self._metrics.record_cache_hit(adapter=self._adapter.kind.value)
        self._record_request(result="cache_hit")

    def _observe_adapter_duration(self, duration_seconds: float) -> None:
        if self._metrics is not None:
            self._metrics.observe_adapter_duration(adapter=self._adapter.kind.value, duration_seconds=duration_seconds)

    def _record_request(self, *, result: str) -> None:
        if self._metrics is not None:
            self._metrics.record_request(adapter=self._adapter.kind.value, result=result)

    def _result_to_response(
        self,
        *,
        tenant_id: uuid.UUID,
        media_id: int,
        image_hash: str,
        context_hash: str,
        caption: str,
        objects: list[str],
        ocr_text: str | None,
        alt_text_draft: str,
        context_sources: list[str],
        context_applied: bool,
        duration_ms: int,
        attachment_provenance: AttachmentProvenance | None = None,
        alt_text_long: str | None = None,
    ) -> VisualFactsResponse:
        provider = _PROVIDER_FOR_ADAPTER[self._adapter.kind]
        return VisualFactsResponse(
            tenant_id=str(tenant_id),
            media_id=media_id,
            image_hash=image_hash,
            context_hash=context_hash,
            adapter=self._adapter.kind,
            model_id=self._adapter.model_id,
            model_version=self._adapter.model_version,
            prompt_or_task_version=self._adapter.prompt_or_task_version,
            visual_facts=VisualFacts(caption=caption, objects=objects, ocr_text=ocr_text),
            alt_text_draft=alt_text_draft,
            alt_text_long=alt_text_long,
            context_used=ContextUsed(sources=context_sources, applied=context_applied),
            provider_disclosure=ProviderDisclosure(
                provider=provider,
                left_service_boundary=provider is ProviderMode.HOSTED,
            ),
            cached=False,
            duration_ms=duration_ms,
            retention_class=self._retention,
            attachment_provenance=attachment_provenance,
            tier=DescriptionResultTier.FINAL_GPU
            if self._adapter.kind is DescriptionAdapterKind.GPU
            else DescriptionResultTier.PROVISIONAL_CPU,
            result_generation=1,
        )

    def _row_to_response(
        self,
        row: ImageDescription,
        *,
        cached: bool,
        duration_ms: int,
        media_id: int | None = None,
    ) -> VisualFactsResponse:
        return VisualFactsResponse(
            tenant_id=str(row.tenant_id),
            media_id=row.media_id if media_id is None else media_id,
            image_hash=row.image_hash,
            context_hash=row.context_hash,
            adapter=row.adapter,  # type: ignore[arg-type]  # FIXME(MAINT-descsvc-mypy-greenup-20260621): row.adapter is a DB str; VisualFactsResponse expects DescriptionAdapterKind enum — flagged to VLM/E19 owner (see handoff finding)
            model_id=row.model_id,
            model_version=row.model_version,
            prompt_or_task_version=row.prompt_or_task_version,
            visual_facts=VisualFacts(**row.visual_facts),
            alt_text_draft=row.alt_text_draft,
            alt_text_long=row.alt_text_long,
            context_used=ContextUsed(**row.context_used),
            provider_disclosure=ProviderDisclosure(**row.provider_disclosure),
            cached=cached,
            duration_ms=duration_ms,
            retention_class=row.retention_class,  # type: ignore[arg-type]  # FIXME(MAINT-descsvc-mypy-greenup-20260621): row.retention_class is a DB str; VisualFactsResponse expects RetentionClass enum — flagged to VLM/E19 owner (see handoff finding)
            tier=DescriptionResultTier.FINAL_GPU
            if row.adapter == DescriptionAdapterKind.GPU.value
            else DescriptionResultTier.PROVISIONAL_CPU,
            result_generation=1,
        )

    def _response_to_row(self, response: VisualFactsResponse) -> ImageDescription:
        return ImageDescription(
            tenant_id=uuid.UUID(response.tenant_id),
            media_id=response.media_id,
            image_hash=response.image_hash,
            context_hash=response.context_hash,
            adapter=response.adapter.value,
            model_id=response.model_id,
            model_version=response.model_version,
            prompt_or_task_version=response.prompt_or_task_version,
            visual_facts=response.visual_facts.model_dump(),
            alt_text_draft=response.alt_text_draft,
            alt_text_long=response.alt_text_long,
            context_used=response.context_used.model_dump(),
            provider_disclosure=response.provider_disclosure.model_dump(),
            retention_class=response.retention_class.value,
            duration_ms=response.duration_ms,
        )


def _coerce_context_pack(context: Mapping[str, Any] | None) -> ContextPack | None:
    """Parse a typed ContextPack from the describe context mapping when possible."""
    if context is None:
        return None
    if isinstance(context, ContextPack):
        return context
    try:
        return ContextPack.model_validate(dict(context))
    except ValidationError:
        # Legacy free-form context (title/caption/...) is not a ContextPack.
        return None


def _attachments_to_provenance(attachments: Sequence[Attachment]) -> AttachmentProvenance:
    return AttachmentProvenance(
        facts=[
            AttachmentFactProvenance(
                fact_id=a.fact_id,
                fact_source=str(a.fact_source),
                fact_label=a.fact_label,
                decision=str(a.decision),
                altitude=str(a.altitude),
                target_evidence=a.target_evidence,
                review_reason=a.review_reason,
                visible=a.visible,
            )
            for a in attachments
        ]
    )
