"""DI providers for the scene describe route (E19-1 S5, profile switch S11)."""

from __future__ import annotations

from scene.application.description_adapter import DescriptionAdapter
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.config.profiles import DescriptionProfile, get_profile_spec
from scene.config.settings import DescriptionSettings
from scene.infrastructure.vlm.unavailable_adapter import UnavailableDescriptionAdapter


def get_description_adapter() -> DescriptionAdapter:
    """Resolve the configured ``ACX_DESCRIPTION_ADAPTER`` profile to an adapter.

    - ``seeded`` (default): deterministic, instant, model-free.
    - ``florence_small``: Florence-2-base-ft local-CPU adapter (process-wide
      singleton, lazy model load). A missing ``[vlm]`` extra degrades to a
      fail-closed UnavailableDescriptionAdapter rather than a 500 at import.
    - ``florence_large`` / ``gpu_phi4``: deferred stubs — fail-closed adapters
      naming why and where the enablement notes live.

    NOTE: ``florence_small`` runs off the event loop (``asyncio.to_thread`` in
    VisualFactsService) but still inline within the request; the DB-backed async
    worker is deferred (see the profile registry impl-notes pointer).
    """
    spec = get_profile_spec(DescriptionSettings().profile)

    if spec.profile is DescriptionProfile.SEEDED:
        settings = DescriptionSettings()
        return SeededDescriptionAdapter(
            model_version=settings.model_version,
            prompt_or_task_version=settings.prompt_or_task_version,
        )

    if not spec.available:
        return UnavailableDescriptionAdapter(
            spec.unavailable_reason or f"profile '{spec.profile.value}' is not available",
            kind=spec.adapter_kind,
            model_id=spec.model_id or "unavailable",
            model_version=spec.model_version,
        )

    # Available local-CPU Florence profile (florence_small).
    try:
        from scene.application.settings.vlm import VlmSettings
        from scene.infrastructure.vlm import get_shared_local_cpu_adapter

        vlm = VlmSettings()
        return get_shared_local_cpu_adapter(
            model_id=spec.model_id,
            model_revision=spec.model_revision,
            model_version=spec.model_version,
            max_image_edge_px=vlm.max_image_edge_px,
            num_beams=spec.num_beams or 3,
            max_new_tokens=spec.max_new_tokens or 512,
        )
    except Exception as exc:  # noqa: BLE001 - degrade uniformly on any import/setup failure
        return UnavailableDescriptionAdapter(
            str(exc),
            kind=spec.adapter_kind,
            model_id=spec.model_id or "unavailable",
            model_version=spec.model_version,
        )
