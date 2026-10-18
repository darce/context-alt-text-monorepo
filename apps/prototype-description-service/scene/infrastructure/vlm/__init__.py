"""Local-CPU VLM (Florence-2) infrastructure for image description (E19-1 S9).

Imports here must stay light: torch/transformers live behind the ``[vlm]`` extra
and are imported lazily inside the adapter so the default recognition-only
runtime never pulls them.
"""

from __future__ import annotations

from scene.infrastructure.vlm.florence_local_adapter import (
    LocalCpuDescriptionAdapter,
    LocalVlmUnavailableError,
)
from scene.infrastructure.vlm.unavailable_adapter import (
    DescriptionAdapterUnavailableError,
    UnavailableDescriptionAdapter,
)

_SHARED: dict[tuple, LocalCpuDescriptionAdapter] = {}


def get_shared_local_cpu_adapter(**kwargs) -> LocalCpuDescriptionAdapter:
    """Per-model process-wide cache so each distinct model loads at most once.

    Keyed by the build identity (model id/revision/version + decode caps), NOT a
    single global slot: two LOCAL_CPU profiles (e.g. florence_small vs
    florence_large) must never alias to one adapter. Aliasing would mis-key the
    description cache (``model_version`` is a cache-key input) and mislabel
    provenance — E19-1-REV-A-1.
    """
    key = (
        kwargs.get("model_id"),
        kwargs.get("model_revision"),
        kwargs.get("model_version"),
        kwargs.get("num_beams"),
        kwargs.get("max_new_tokens"),
        kwargs.get("max_image_edge_px"),
    )
    adapter = _SHARED.get(key)
    if adapter is None:
        adapter = LocalCpuDescriptionAdapter(**kwargs)
        _SHARED[key] = adapter
    return adapter


def reset_shared_local_cpu_adapter_for_tests() -> None:
    _SHARED.clear()


__all__ = [
    "DescriptionAdapterUnavailableError",
    "LocalCpuDescriptionAdapter",
    "LocalVlmUnavailableError",
    "UnavailableDescriptionAdapter",
    "get_shared_local_cpu_adapter",
    "reset_shared_local_cpu_adapter_for_tests",
]
