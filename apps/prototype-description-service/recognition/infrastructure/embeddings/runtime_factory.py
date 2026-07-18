"""Shared embedding-runtime factory for the three construction sites (FIR-4 S3).

Selects stub / insightface / face_pipeline once so scan_worker, inline tasks,
and HTTP deps stay symmetric ([SERVE-01]). Fail-closed on any profile load error
([RLSE-05]). Production default remains insightface ([SERVE-03], [RLSE-07]).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from recognition.application.embedding.detector import (
    FaceDetectorProtocol,
    InsightFaceFaceDetector,
    StubFaceDetector,
    UnavailableFaceDetector,
)
from recognition.application.embedding.generator import (
    EmbeddingGeneratorProtocol,
    InsightFaceEmbeddingGenerator,
    StubEmbeddingGenerator,
    UnavailableEmbeddingGenerator,
)
from recognition.config.settings import RecognitionSettings
from recognition.infrastructure.embeddings import get_shared_insightface_adapter

logger = logging.getLogger(__name__)

AdapterProvider = Callable[[], Awaitable[Any]]


async def build_embedding_runtime(
    *,
    settings: RecognitionSettings,
    http_client: httpx.AsyncClient | None = None,
    adapter_provider: AdapterProvider | None = None,
    metrics: Any | None = None,
) -> tuple[FaceDetectorProtocol, EmbeddingGeneratorProtocol]:
    """Build (detector, generator) for the active runtime mode + face_pipeline profile.

    - ``runtime_mode == "test"`` → stubs (orthogonal to profile).
    - ``profile == "insightface"`` (default) → shared InsightFace adapter path;
      ``adapter_provider`` overrides the shared singleton when provided.
    - ``profile == "face_pipeline"`` → shared face_pipeline runtime; generator slot
      is ``UnavailableEmbeddingGenerator`` (embeds happen in detect). ``adapter_provider``
      is ignored. Any load/verify failure yields Unavailable* for **both** slots.
    - ``metrics`` is a process-local observer forwarded into
      ``FacePipelineFaceDetector`` (FINALB-06); shared runtime singleton does not
      own process-specific collectors. Other profiles ignore it.
    """
    if settings.runtime_mode == "test":
        return StubFaceDetector(), StubEmbeddingGenerator()

    profile = settings.face_pipeline.profile
    if profile == "face_pipeline":
        # Lazy import: keep the insightface dark default free of the face_pipeline
        # (ORT/cv2) import graph until the profile is actually selected (S3CR-01).
        from recognition.infrastructure.embeddings.face_pipeline_adapter import (
            FacePipelineFaceDetector,
            face_pipeline_unavailable_generator,
            get_shared_face_pipeline_detect_breaker,
            get_shared_face_pipeline_runtime,
        )

        try:
            runtime = get_shared_face_pipeline_runtime(
                profile=profile,
                models_dir=settings.face_pipeline.resolved_models_dir,
                score_threshold=settings.face_pipeline.score_threshold,
                nms_threshold=settings.face_pipeline.nms_threshold,
                top_k=settings.face_pipeline.top_k,
            )
            detector: FaceDetectorProtocol = FacePipelineFaceDetector(
                runtime,
                metrics=metrics,
                client=http_client,
                timeout=float(settings.face_pipeline.timeout_s),
                breaker=get_shared_face_pipeline_detect_breaker(),
            )
            generator: EmbeddingGeneratorProtocol = face_pipeline_unavailable_generator()
            return detector, generator
        except Exception as exc:
            logger.exception("face_pipeline runtime unavailable; scan paths will fail closed until it recovers.")
            reason = str(exc) or exc.__class__.__name__
            return UnavailableFaceDetector(reason), UnavailableEmbeddingGenerator(reason)

    # Incumbent insightface path (production dark default).
    try:
        if adapter_provider is not None:
            adapter = await adapter_provider()
        else:
            adapter = await get_shared_insightface_adapter()
        return (
            InsightFaceFaceDetector(adapter, client=http_client),
            InsightFaceEmbeddingGenerator(adapter),
        )
    except Exception as exc:
        logger.exception(
            "InsightFace runtime unavailable; scan paths will fail closed. "
            "Install with: pip install 'prototype-description-service[bench]' "
            "(or: uv sync --extra bench). Required for the incumbent dark-default profile; "
            "face_pipeline uses core deps + scripts/fetch_face_pipeline_models.py.",
        )
        reason = str(exc) or exc.__class__.__name__
        return UnavailableFaceDetector(reason), UnavailableEmbeddingGenerator(reason)


__all__ = [
    "AdapterProvider",
    "build_embedding_runtime",
]
