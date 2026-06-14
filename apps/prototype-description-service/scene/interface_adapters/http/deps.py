"""DI providers for the scene describe route (E19-1 S5)."""

from __future__ import annotations

from scene.application.description_adapter import DescriptionAdapter
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.config.settings import DescriptionSettings


def get_description_adapter() -> DescriptionAdapter:
    """Return the configured description adapter.

    Phase 1 ships only the seeded adapter; S9 adds ``local_cpu`` selection by
    ``DescriptionSettings.adapter_mode`` behind the same protocol. The route
    depends on this provider so that swap is a one-line change here.
    """
    settings = DescriptionSettings()
    return SeededDescriptionAdapter(prompt_or_task_version=settings.prompt_or_task_version)
