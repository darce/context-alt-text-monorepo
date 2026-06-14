"""VisualFactsService (E19-1 S4): the synchronous describe use case.

validate → hash → cache-read → adapter → persist → audit → duration. DB-optional:
with ``repository=None`` (DB down) it degrades to adapter-only (``cached=False``,
no persist, no audit), mirroring recognition's optional-session degradation.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

from db.models.scene import ImageDescription
from scene.application.description_adapter import DescriptionAdapter
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.hashing import compute_context_hash, compute_image_hash
from scene.domain.description import DescriptionAdapterKind, ProviderMode, RetentionClass
from scene.interface_adapters.http.schemas.responses import (
    ContextUsed,
    ProviderDisclosure,
    VisualFacts,
    VisualFactsResponse,
)

_PROVIDER_FOR_ADAPTER = {
    DescriptionAdapterKind.SEEDED: ProviderMode.NONE,
    DescriptionAdapterKind.LOCAL_CPU: ProviderMode.LOCAL,
    DescriptionAdapterKind.HOSTED_PROVIDER: ProviderMode.HOSTED,
}


class AuditSink(Protocol):
    async def record(self, *, tenant_id: uuid.UUID, event_type: str, payload: dict[str, Any]) -> None: ...


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


class VisualFactsService:
    def __init__(
        self,
        *,
        adapter: DescriptionAdapter,
        repository: ImageDescriptionRepository | None = None,
        audit_sink: AuditSink | None = None,
        retention_class: RetentionClass = RetentionClass.RETAIN_ALL,
        generation_timeout_seconds: float | None = None,
    ) -> None:
        self._adapter = adapter
        self._repo = repository
        self._audit = audit_sink
        self._retention = retention_class
        self._timeout = generation_timeout_seconds

    async def describe(
        self,
        *,
        tenant_id: uuid.UUID,
        media_id: int,
        image_bytes: bytes,
        context: Mapping[str, Any] | None,
    ) -> VisualFactsResponse:
        start = time.perf_counter()
        image_hash = compute_image_hash(image_bytes)
        context_hash = compute_context_hash(context)

        if self._repo is not None:
            row = await self._repo.get_by_cache_key(
                tenant_id=tenant_id,
                image_hash=image_hash,
                adapter=self._adapter.kind.value,
                model_version=self._adapter.model_version,
                prompt_or_task_version=self._adapter.prompt_or_task_version,
                context_hash=context_hash,
            )
            if row is not None:
                return self._row_to_response(row, cached=True, duration_ms=_elapsed_ms(start), media_id=media_id)

        # Offload to a thread so a slow adapter (local_cpu Florence ~30-60s) never
        # blocks the event loop — otherwise asyncpg drops the open DB connection
        # mid-request and the persist fails. Seeded is instant, so the overhead is
        # negligible. (A dedicated worker/queue is the heavier production option.)
        call = asyncio.to_thread(self._adapter.describe, image_bytes=image_bytes, context=context)
        result = await (asyncio.wait_for(call, self._timeout) if self._timeout else call)
        response = self._result_to_response(
            tenant_id=tenant_id,
            media_id=media_id,
            image_hash=image_hash,
            context_hash=context_hash,
            caption=result.caption,
            objects=list(result.objects),
            ocr_text=result.ocr_text,
            alt_text_draft=result.alt_text_draft,
            context_sources=list(result.context_sources),
            context_applied=result.context_applied,
            duration_ms=_elapsed_ms(start),
        )

        if self._repo is not None:
            row, inserted = await self._repo.insert_or_get_existing(self._response_to_row(response))
            if not inserted:
                return self._row_to_response(row, cached=True, duration_ms=_elapsed_ms(start), media_id=media_id)
            if self._audit is not None:
                await self._audit.record(
                    tenant_id=tenant_id,
                    event_type="description.generated",
                    payload={"media_id": media_id, "image_hash": image_hash, "adapter": response.adapter.value},
                )
        return response

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
            context_used=ContextUsed(sources=context_sources, applied=context_applied),
            provider_disclosure=ProviderDisclosure(
                provider=provider,
                left_service_boundary=provider is ProviderMode.HOSTED,
            ),
            cached=False,
            duration_ms=duration_ms,
            retention_class=self._retention,
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
            adapter=row.adapter,
            model_id=row.model_id,
            model_version=row.model_version,
            prompt_or_task_version=row.prompt_or_task_version,
            visual_facts=VisualFacts(**row.visual_facts),
            alt_text_draft=row.alt_text_draft,
            context_used=ContextUsed(**row.context_used),
            provider_disclosure=ProviderDisclosure(**row.provider_disclosure),
            cached=cached,
            duration_ms=duration_ms,
            retention_class=row.retention_class,
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
            context_used=response.context_used.model_dump(),
            provider_disclosure=response.provider_disclosure.model_dump(),
            retention_class=response.retention_class.value,
            duration_ms=response.duration_ms,
        )
