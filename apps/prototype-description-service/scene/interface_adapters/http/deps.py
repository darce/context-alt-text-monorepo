"""DI providers for the scene describe route (E19-1 S5)."""

from __future__ import annotations

from scene.application.description_adapter import DescriptionAdapter
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.config.settings import DescriptionSettings
from scene.domain.description import DescriptionAdapterKind


def get_description_adapter() -> DescriptionAdapter:
    """Return the configured description adapter behind the shared protocol.

    ``ACX_DESCRIPTION_ADAPTER=local_cpu`` selects the Florence-2 local-CPU adapter
    (process-wide singleton, lazy model load); a missing ``[vlm]`` extra degrades
    to a fail-closed UnavailableDescriptionAdapter rather than a 500 at import.
    Default is the seeded adapter. NOTE: local_cpu inference is slow (~30-60s) and
    runs inline here — acceptable for the eval/POC path, not the production
    request path (the async worker branch is future work).
    """
    settings = DescriptionSettings()
    if settings.adapter_mode is DescriptionAdapterKind.LOCAL_CPU:
        try:
            from scene.infrastructure.vlm import get_shared_local_cpu_adapter

            return get_shared_local_cpu_adapter()
        except Exception as exc:  # noqa: BLE001 - degrade uniformly on any import/setup failure
            from scene.infrastructure.vlm.unavailable_adapter import UnavailableDescriptionAdapter

            return UnavailableDescriptionAdapter(str(exc))
    return SeededDescriptionAdapter(prompt_or_task_version=settings.prompt_or_task_version)
